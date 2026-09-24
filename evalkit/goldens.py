"""Golden set - measure the judges before the judges measure the SUT.

Hand-labelled transcripts with planted failures. Recall is how many planted
failures the judges confirm; the false-positive rate is how many correct replies
they condemn. Below either bar in config, Layer 3 does not get to score the SUT -
the rubric gets fixed first.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import anthropic

from . import config as C
from .judge import judge_transcript
from .rubric import Dimension
from .schema import Persona


def resolve_dimension(
    ref: str,
    personas: dict[str, Persona],
    deferrals: dict[str, dict[str, Any]],
    shared: dict[str, Dimension],
) -> Dimension | None:
    if ref.startswith("deferred:"):
        pid, _, check = ref[len("deferred:"):].partition(".")
        entry = deferrals.get(pid, {}).get(check)
        if entry is None:
            return None
        return Dimension(id=ref, tier="deferred", model_key="sonnet", question=entry["intent"])
    if ref.startswith("persona:"):
        persona = personas.get(ref[len("persona:"):])
        if persona is None or not persona.llm_check:
            return None
        return Dimension(id=ref, tier="persona", model_key="sonnet", question=persona.llm_check)
    return shared.get(ref)


def load_cases(
    personas: dict[str, Persona],
    deferrals: dict[str, dict[str, Any]],
    shared: dict[str, Dimension],
    problems: list[str],
) -> list[dict[str, Any]]:
    path = C.GOLDENS_DIR / "cases.json"
    if not path.exists():
        problems.append("goldens/cases.json: missing")
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        problems.append(f"goldens/cases.json: invalid JSON ({e})")
        return []

    cases, seen = [], set()
    for i, case in enumerate(raw.get("cases", [])):
        cid = case.get("id")
        if not isinstance(cid, str) or cid in seen:
            problems.append(f"goldens/cases.json: cases[{i}] missing or duplicate 'id'")
            continue
        seen.add(cid)
        turns = case.get("transcript")
        if not isinstance(turns, list) or not any(t.get("role") == "assistant" for t in turns):
            problems.append(f"golden {cid}: transcript needs an assistant turn")
            continue
        expect = case.get("expect")
        if not isinstance(expect, dict) or not expect:
            problems.append(f"golden {cid}: 'expect' must be a non-empty object")
            continue
        for ref, want in expect.items():
            if want not in (C.PASS, C.FAIL, C.NO_EVIDENCE):
                problems.append(f"golden {cid}: {ref} expects unknown verdict {want!r}")
            if resolve_dimension(ref, personas, deferrals, shared) is None:
                problems.append(f"golden {cid}: dimension {ref!r} does not resolve (stale)")
        cases.append(case)
    return cases


async def run(
    cases: list[dict[str, Any]],
    personas: dict[str, Persona],
    deferrals: dict[str, dict[str, Any]],
    shared: dict[str, Dimension],
    faq: str,
    *,
    roles: tuple[str, ...],
    concurrency: int,
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(concurrency)

    async with anthropic.AsyncAnthropic(timeout=C.REQUEST_TIMEOUT_S) as client:
        async def one(case: dict[str, Any]) -> dict[str, Any]:
            dims = [resolve_dimension(ref, personas, deferrals, shared) for ref in case["expect"]]
            results = await judge_transcript(
                client, case["transcript"], [d for d in dims if d], faq,
                roles=roles, semaphore=semaphore,
            )
            return {"case_id": case["id"], "note": case.get("note", ""),
                    "expect": case["expect"], "dimensions": results}

        return list(await asyncio.gather(*(one(c) for c in cases)))


def score(results: list[dict[str, Any]]) -> dict[str, Any]:
    rows, tokens = [], {"input": 0, "output": 0, "cache_read": 0}
    caught = missed = soft_caught = 0
    false_pos = soft_false_pos = clean_ok = 0
    abstain_ok = abstain_wrong = 0

    for case in results:
        for dim in case["dimensions"]:
            want = case["expect"].get(dim["dimension_id"])
            got = dim["verdict"]
            for vote in dim["votes"]:
                usage = vote.get("usage") or {}
                tokens["input"] += usage.get("input_tokens", 0)
                tokens["output"] += usage.get("output_tokens", 0)
                tokens["cache_read"] += usage.get("cache_read_input_tokens", 0)

            if want == C.FAIL:
                if got == C.FAIL:
                    caught += 1
                elif got == C.DISPUTED:
                    soft_caught += 1
                else:
                    missed += 1
            elif want == C.PASS:
                if got == C.FAIL:
                    false_pos += 1
                elif got == C.DISPUTED:
                    soft_false_pos += 1
                else:
                    clean_ok += 1
            elif want == C.NO_EVIDENCE:
                abstain_ok += 1 if got == C.NO_EVIDENCE else 0
                abstain_wrong += 0 if got == C.NO_EVIDENCE else 1

            rows.append({
                "case_id": case["case_id"], "dimension_id": dim["dimension_id"],
                "expected": want, "got": got, "rule": dim["rule"],
                "ok": got == want,
                "invalid_votes": len(dim["votes_invalid"]),
            })

    planted = caught + soft_caught + missed
    clean = clean_ok + false_pos + soft_false_pos
    recall = caught / planted if planted else 0.0
    fp_rate = false_pos / clean if clean else 0.0

    return {
        "planted_failures": planted,
        "caught": caught,
        "caught_as_disputed": soft_caught,
        "missed": missed,
        "recall": round(recall, 3),
        "clean_dimensions": clean,
        "false_positives": false_pos,
        "false_positives_as_disputed": soft_false_pos,
        "false_positive_rate": round(fp_rate, 3),
        "abstain_expected": abstain_ok + abstain_wrong,
        "abstain_correct": abstain_ok,
        "invalid_votes": sum(r["invalid_votes"] for r in rows),
        "gate": {
            "min_recall": C.MIN_RECALL,
            "max_false_positive_rate": C.MAX_FALSE_POSITIVE_RATE,
            "recall_ok": recall >= C.MIN_RECALL,
            "false_positive_ok": fp_rate <= C.MAX_FALSE_POSITIVE_RATE,
            "passed": recall >= C.MIN_RECALL and fp_rate <= C.MAX_FALSE_POSITIVE_RATE,
        },
        "tokens": tokens,
        "rows": rows,
    }
