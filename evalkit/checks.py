"""Layer 2 - deterministic checks. Zero model calls.

Every check returns pass / fail / no_evidence. no_evidence means the check could
not be evaluated (no reply, or an empty needle list) - it is not a silent pass
and not a fail, and the summary counts it separately.
"""
from __future__ import annotations

import re
from typing import Any

from .config import PASS, FAIL, NO_EVIDENCE, DEFERRED

# Words that end in a period without ending a sentence, so the first-sentence
# split does not stop at "Oct." or "Mon.".
_ABBREV = {
    "mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "mr", "mrs", "ms", "dr", "st", "ave", "approx", "no", "vs", "e.g", "i.e", "etc",
}
_BOUNDARY = re.compile(r"""[.!?]+["'’)\]]*(?=\s|$)""")
_TRAILING_WORD = re.compile(r"""([A-Za-z][A-Za-z.]*)["'’)\]]*[.!?]+["'’)\]]*$""")
_PRICE = re.compile(r"\$\s?\d")


def first_sentence(text: str) -> str:
    """Best-effort first sentence. Always recorded in the result so a bad split
    is visible to a human instead of silently flipping a check."""
    flat = " ".join(text.split())
    if not flat:
        return ""
    for m in _BOUNDARY.finditer(flat):
        head = flat[: m.end()]
        word = _TRAILING_WORD.search(head)
        if word and word.group(1).rstrip(".").lower() in _ABBREV:
            continue
        return head
    return flat


def _found(haystack: str, needles: list[str]) -> list[str]:
    low = haystack.lower()
    return [n for n in needles if n.lower() in low]


def _result(name: str, status: str, detail: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "status": status, "detail": detail}


def _check(name: str, value: Any, reply: str) -> dict[str, Any]:
    if name == "must_mention_price":
        if value is not True:
            return _result(name, NO_EVIDENCE, {"reason": "check disabled"})
        hits = _PRICE.findall(reply)
        return _result(name, PASS if hits else FAIL, {"pattern": _PRICE.pattern, "matched": bool(hits)})

    if name == "must_contain_any":
        if not value:
            return _result(name, NO_EVIDENCE, {"reason": "empty needle list"})
        matched = _found(reply, value)
        return _result(name, PASS if matched else FAIL, {"needles": value, "matched": matched})

    if name == "must_contain_all":
        if not value:
            return _result(name, NO_EVIDENCE, {"reason": "empty needle list"})
        missing = [n for n in value if n not in _found(reply, value)]
        return _result(name, PASS if not missing else FAIL, {"needles": value, "missing": missing})

    if name == "must_not_contain":
        if not value:
            return _result(name, NO_EVIDENCE, {"reason": "empty needle list"})
        hits = _found(reply, value)
        return _result(name, PASS if not hits else FAIL, {"needles": value, "hits": hits})

    if name == "first_sentence_must_contain_any":
        head = first_sentence(reply)
        if not value:
            return _result(name, NO_EVIDENCE, {"reason": "empty needle list", "first_sentence": head})
        matched = _found(head, value)
        return _result(name, PASS if matched else FAIL,
                       {"first_sentence": head, "needles": value, "matched": matched})

    if name == "max_words":
        words = len(reply.split())
        return _result(name, PASS if words <= value else FAIL, {"limit": value, "words": words})

    return _result(name, NO_EVIDENCE, {"reason": "unknown check"})


def evaluate(
    reply: str | None,
    checks: dict[str, Any],
    deferred: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run every configured check against the reply and roll them up.

    `deferred` maps check name -> why Layer 2 refuses to judge it. Those checks
    are recorded with their reason and left out of the rollup entirely, so a
    semantic call never turns into a substring guess.
    """
    deferred = deferred or {}
    if not checks:
        return {"overall": NO_EVIDENCE, "reason": "no checks configured",
                "failed": [], "deferred": [], "checks": []}

    no_reply = reply is None or not reply.strip()
    results: list[dict[str, Any]] = []
    for name, value in checks.items():
        if name in deferred:
            entry = deferred[name]
            detail = {"deferred_to": "layer3"}
            detail.update({"reason": entry} if isinstance(entry, str) else entry)
            results.append(_result(name, DEFERRED, detail))
        elif no_reply:
            results.append(_result(name, NO_EVIDENCE, {"reason": "no reply from SUT"}))
        else:
            results.append(_check(name, value, reply))

    scored = [r for r in results if r["status"] != DEFERRED]
    statuses = {r["status"] for r in scored}
    if FAIL in statuses:
        overall = FAIL
    elif PASS in statuses:
        overall = PASS
    else:
        overall = NO_EVIDENCE

    out = {
        "overall": overall,
        "failed": [r["name"] for r in results if r["status"] == FAIL],
        "deferred": [r["name"] for r in results if r["status"] == DEFERRED],
        "checks": results,
    }
    if no_reply:
        out["reason"] = "no reply from SUT"
    if not scored:
        out["reason"] = "every check deferred to Layer 3"
    return out
