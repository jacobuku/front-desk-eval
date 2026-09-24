"""Fan-out: persona x scenario x repeat, each unit independent and isolated.

Each unit is one SUT call plus its deterministic checks, written to its own
file. One unit failing never touches another. A config-level failure aborts the
whole run instead of producing 24 identically-broken records.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Callable, Iterable

import anthropic

from . import checks as layer2
from . import config as C
from . import loader
from .schema import FatalRunError, Persona, Scenario, SutResult, Unit
from .store import RunStore, now_iso


def build_units(personas: Iterable[Persona], scenario: Scenario, repeats: int) -> list[Unit]:
    return [
        Unit(unit_id=f"{p.id}__{scenario.id}__r{k}", persona=p, scenario=scenario, repeat_idx=k)
        for p in personas
        for k in range(repeats)
    ]


def _record(unit: Unit, run_id: str, sut: SutResult, started_at: str,
            deferrals: dict[str, dict[str, str]]) -> dict[str, Any]:
    reply = sut.text if sut.ok else None
    transcript = [{"turn": 0, "role": "user", "content": unit.persona.first_message}]
    if reply is not None:
        transcript.append({"turn": 1, "role": "assistant", "content": reply})

    return {
        "schema_version": C.SCHEMA_VERSION,
        "run_id": run_id,
        "unit_id": unit.unit_id,
        "persona_id": unit.persona.id,
        "persona_type": unit.persona.type,
        "scenario_id": unit.scenario.id,
        "repeat_idx": unit.repeat_idx,
        "status": "ok" if sut.ok else "sut_error",
        "started_at": started_at,
        "finished_at": now_iso(),
        "sut": sut.to_dict(),
        "transcript": transcript,
        "deterministic": layer2.evaluate(reply, unit.persona.checks,
                                        deferrals.get(unit.persona.id)),
        # Carried forward untouched for Layer 3. Nothing here reads it.
        "llm_check": unit.persona.llm_check,
    }


async def _run_unit(
    unit: Unit,
    client: anthropic.AsyncAnthropic,
    store: RunStore,
    semaphore: asyncio.Semaphore,
    abort: asyncio.Event,
    on_done: Callable[[dict[str, Any]], None],
    deferrals: dict[str, dict[str, str]],
) -> dict[str, Any] | None:
    if abort.is_set():
        return None
    async with semaphore:
        if abort.is_set():
            return None
        started_at = now_iso()
        try:
            sut = await sut_call(client, unit)
        except FatalRunError:
            abort.set()
            raise
        record = _record(unit, store.run_id, sut, started_at, deferrals)
        store.write_unit(record)
        on_done(record)
        return record


async def sut_call(client: anthropic.AsyncAnthropic, unit: Unit) -> SutResult:
    from .sut import call_sut  # local import keeps runner importable without a key
    return await call_sut(client, unit.scenario, unit.persona.first_message)


def _progress(record: dict[str, Any]) -> None:
    mark = {"pass": "PASS", "fail": "FAIL", "no_evidence": "NOEV"}[record["deterministic"]["overall"]]
    if record["status"] != "ok":
        mark = "ERR "
    failed = ",".join(record["deterministic"].get("failed", []))
    print(f"  {mark}  {record['unit_id']:<34} {record['sut']['latency_ms']:>6}ms  {failed}",
          file=sys.stderr, flush=True)


async def run(
    personas: list[Persona],
    scenario: Scenario,
    *,
    repeats: int,
    concurrency: int,
    store: RunStore,
    resume: bool,
    deferrals: dict[str, dict[str, str]] | None = None,
    do_preflight: bool = True,
) -> dict[str, Any]:
    deferrals = deferrals or {}
    units = build_units(personas, scenario, repeats)
    pending = [u for u in units if not (resume and store.completed(u.unit_id))]
    skipped = len(units) - len(pending)

    store.write_manifest({
        "schema_version": C.SCHEMA_VERSION,
        "run_id": store.run_id,
        "created_at": now_iso(),
        "scenario": {k: v for k, v in vars(scenario).items() if k != "system"},
        "personas": [p.id for p in personas],
        "repeats": repeats,
        "concurrency": concurrency,
        "unit_count": len(units),
        "deferrals": deferrals,
        "inputs": loader.fingerprints(scenario),
    })

    semaphore = asyncio.Semaphore(concurrency)
    abort = asyncio.Event()

    async with anthropic.AsyncAnthropic(timeout=C.REQUEST_TIMEOUT_S) as client:
        if do_preflight and pending:
            from .sut import preflight
            await preflight(client, scenario)
        tasks = [
            asyncio.create_task(
                _run_unit(u, client, store, semaphore, abort, _progress, deferrals))
            for u in pending
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    fatal = next((r for r in results if isinstance(r, FatalRunError)), None)
    crashed = [r for r in results if isinstance(r, BaseException) and not isinstance(r, FatalRunError)]
    if fatal is not None:
        raise fatal
    for exc in crashed:
        print(f"  unit crashed: {type(exc).__name__}: {exc}", file=sys.stderr)

    summary = summarize(store, skipped=skipped, crashed=len(crashed))
    store.write_summary(summary)
    return summary


def summarize(store: RunStore, *, skipped: int = 0, crashed: int = 0) -> dict[str, Any]:
    records = list(store.iter_units())
    manifest = store.read_manifest()
    model = manifest["scenario"]["model"]

    by_persona: dict[str, dict[str, Any]] = {}
    totals = {"pass": 0, "fail": 0, "no_evidence": 0, "sut_error": 0,
              "truncated": 0, "deferred_checks": 0}
    tokens = {"input": 0, "output": 0, "cache_read": 0}
    check_failures: dict[str, int] = {}

    for r in sorted(records, key=lambda r: (r["persona_id"], r["repeat_idx"])):
        overall = r["deterministic"]["overall"]
        totals[overall] += 1
        if r["status"] != "ok":
            totals["sut_error"] += 1
        if r["sut"].get("truncated"):
            totals["truncated"] += 1
        usage = r["sut"].get("usage") or {}
        tokens["input"] += usage.get("input_tokens", 0)
        tokens["output"] += usage.get("output_tokens", 0)
        tokens["cache_read"] += usage.get("cache_read_input_tokens", 0)
        for name in r["deterministic"].get("failed", []):
            check_failures[name] = check_failures.get(name, 0) + 1
        totals["deferred_checks"] += len(r["deterministic"].get("deferred", []))

        entry = by_persona.setdefault(r["persona_id"], {
            "persona_type": r["persona_type"], "results": [], "failed_checks": [],
            "deferred_checks": [], "latency_ms": [],
        })
        entry["results"].append(overall if r["status"] == "ok" else "sut_error")
        entry["failed_checks"].extend(r["deterministic"].get("failed", []))
        entry["deferred_checks"].extend(r["deterministic"].get("deferred", []))
        entry["latency_ms"].append(r["sut"].get("latency_ms", 0))

    for entry in by_persona.values():
        distinct = set(entry["results"])
        # Same persona, same prompt, different verdict across repeats: the SUT is
        # unstable here. That is a finding, not noise to average away.
        entry["stable"] = len(distinct) == 1
        entry["verdict"] = distinct.pop() if len(distinct) == 1 else "mixed"
        entry["failed_checks"] = sorted(set(entry["failed_checks"]))
        entry["deferred_checks"] = sorted(set(entry["deferred_checks"]))

    rate_in, rate_out = C.PRICING.get(model, (0.0, 0.0))
    cost = (tokens["input"] / 1e6) * rate_in + (tokens["output"] / 1e6) * rate_out

    return {
        "run_id": store.run_id,
        "scenario_id": manifest["scenario"]["id"],
        "model": model,
        "generated_at": now_iso(),
        "unit_count": len(records),
        "skipped_on_resume": skipped,
        "crashed": crashed,
        "totals": totals,
        "check_failures": dict(sorted(check_failures.items(), key=lambda kv: -kv[1])),
        "unstable_personas": sorted(p for p, e in by_persona.items() if not e["stable"]),
        "by_persona": by_persona,
        "tokens": tokens,
        "est_cost_usd": round(cost, 4),
    }


def rescore(
    store: RunStore,
    personas: list[Persona],
    deferrals: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Re-apply Layer 2 to stored transcripts. No API calls.

    This is what persisting transcripts buys: a check-rule change is re-scored
    over the transcripts that already exist, instead of paying to re-run the
    conversations and comparing against a different sample.
    """
    deferrals = deferrals or {}
    by_id = {p.id: p for p in personas}
    rescored = 0

    for record in store.iter_units():
        persona = by_id.get(record["persona_id"])
        if persona is None:
            print(f"  skipping {record['unit_id']}: persona no longer defined", file=sys.stderr)
            continue
        reply = next((t["content"] for t in record["transcript"] if t["role"] == "assistant"), None)
        before = record["deterministic"]["overall"]
        record["deterministic"] = layer2.evaluate(reply, persona.checks, deferrals.get(persona.id))
        record["rescored_at"] = now_iso()
        store.write_unit(record)
        rescored += 1
        after = record["deterministic"]["overall"]
        if before != after:
            print(f"  {record['unit_id']:<34} {before} -> {after}", file=sys.stderr)

    manifest = store.read_manifest()
    manifest["deferrals"] = deferrals
    manifest["rescored_at"] = now_iso()
    store.write_manifest(manifest)

    summary = summarize(store)
    summary["rescored_units"] = rescored
    store.write_summary(summary)
    return summary


def compare(summary_a: dict[str, Any], summary_b: dict[str, Any]) -> dict[str, Any]:
    """Per-persona diff between two runs. Verdict changes only count when every
    repeat agrees - a mixed result is never reported as fixed."""
    rows = []
    for pid in sorted(set(summary_a["by_persona"]) | set(summary_b["by_persona"])):
        a = summary_a["by_persona"].get(pid, {})
        b = summary_b["by_persona"].get(pid, {})
        va, vb = a.get("verdict", "-"), b.get("verdict", "-")
        if va == vb:
            change = "same"
        elif vb == "pass" and va in ("fail", "mixed"):
            change = "FIXED" if b.get("stable") else "improved (still unstable)"
        elif va == "pass" and vb in ("fail", "mixed"):
            change = "REGRESSED"
        else:
            change = f"{va} -> {vb}"
        rows.append({
            "persona_id": pid,
            "persona_type": a.get("persona_type") or b.get("persona_type", ""),
            "a": {"results": a.get("results", []), "verdict": va, "stable": a.get("stable"),
                  "failed_checks": a.get("failed_checks", [])},
            "b": {"results": b.get("results", []), "verdict": vb, "stable": b.get("stable"),
                  "failed_checks": b.get("failed_checks", [])},
            "change": change,
        })
    return {
        "a": {"run_id": summary_a["run_id"], "scenario_id": summary_a["scenario_id"],
              "totals": summary_a["totals"], "est_cost_usd": summary_a["est_cost_usd"]},
        "b": {"run_id": summary_b["run_id"], "scenario_id": summary_b["scenario_id"],
              "totals": summary_b["totals"], "est_cost_usd": summary_b["est_cost_usd"]},
        "rows": rows,
    }
