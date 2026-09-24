"""Layer 4 - deterministic adjudication.

No model ever sees another model's vote, and no model produces the final
verdict. Votes come in, a rule decides:

    >= 2 fail votes      -> fail       (confirmed)
       1 fail vote       -> disputed   (delivered, dissent attached)
       0 fail, any pass  -> pass
       no valid votes    -> no_evidence (dropped)

A vote is only counted if it is *valid*: a pass or fail must cite a turn that
exists and quote words that actually appear in it. An unsupported vote is not a
weak vote, it is not a vote.
"""
from __future__ import annotations

import re
from typing import Any

from .config import PASS, FAIL, NO_EVIDENCE, DISPUTED


# Judges retype quotes with different apostrophes and dash styles than the model
# produced. Normalize those away before matching - otherwise a correct quote gets
# thrown out as fabricated.
_NOISE = re.compile(r"[\s\"'`\u2018\u2019\u201c\u201d\u2010-\u2015\u2212-]+")


def _normalize(text: str) -> str:
    return _NOISE.sub(" ", text.lower()).strip()


def validate_vote(vote: dict[str, Any], transcript: list[dict[str, Any]]) -> dict[str, Any]:
    """Mechanical evidence gate. Returns the vote with 'valid' and 'invalid_reason'."""
    verdict = vote.get("verdict")
    if verdict not in (PASS, FAIL, NO_EVIDENCE):
        return {**vote, "valid": False, "invalid_reason": f"unknown verdict {verdict!r}"}

    if verdict == NO_EVIDENCE:
        return {**vote, "valid": True, "invalid_reason": None}

    turns = {t["turn"]: t["content"] for t in transcript}
    cited = vote.get("evidence_turns") or []
    if not cited:
        return {**vote, "valid": False, "invalid_reason": "no turn cited"}
    unknown = [t for t in cited if t not in turns]
    if unknown:
        return {**vote, "valid": False, "invalid_reason": f"cited turns not in transcript: {unknown}"}

    quote = (vote.get("quote") or "").strip()
    if not quote:
        return {**vote, "valid": False, "invalid_reason": "no quote"}
    haystack = _normalize(" ".join(turns[t] for t in cited))
    if _normalize(quote) not in haystack:
        return {**vote, "valid": False, "invalid_reason": "quote not found in the cited turn(s)"}

    return {**vote, "valid": True, "invalid_reason": None}


def adjudicate(votes: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [v for v in votes if v.get("valid")]
    fails = [v for v in valid if v["verdict"] == FAIL]
    passes = [v for v in valid if v["verdict"] == PASS]

    if not valid:
        verdict, rule = NO_EVIDENCE, "no valid votes - dropped"
    elif len(fails) >= 2:
        verdict, rule = FAIL, f"{len(fails)} fail votes - confirmed"
    elif len(fails) == 1:
        verdict, rule = DISPUTED, "1 fail vote against a dissent - delivered with dissent"
    elif passes:
        verdict, rule = PASS, f"{len(passes)} pass vote(s), no fail vote"
    else:
        verdict, rule = NO_EVIDENCE, "all valid votes were no_evidence"

    dissent = None
    if verdict == DISPUTED:
        dissent = {
            "fail": {"role": fails[0].get("role"), "quote": fails[0].get("quote"),
                     "reasoning": fails[0].get("reasoning")},
            "others": [{"role": v.get("role"), "verdict": v["verdict"],
                        "reasoning": v.get("reasoning")} for v in valid if v is not fails[0]],
        }

    return {
        "verdict": verdict,
        "rule": rule,
        "votes_total": len(votes),
        "votes_valid": len(valid),
        "votes_invalid": [{"role": v.get("role"), "reason": v.get("invalid_reason")}
                          for v in votes if not v.get("valid")],
        "dissent": dissent,
    }
