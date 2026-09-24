"""Layer 0 - input validation.

Nothing downstream runs until personas, scenarios and prompt/FAQ files are
proven well-formed. A bad input is a stop, not a warning.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import config as C
from .schema import Persona, Scenario


class InputError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__(f"{len(problems)} input problem(s)")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _read_json(path: Path, problems: list[str]) -> Any:
    if not path.exists():
        problems.append(f"{path.name}: missing")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        problems.append(f"{path.name}: invalid JSON ({e})")
        return None


def _validate_checks(pid: str, checks: Any, problems: list[str]) -> None:
    if not isinstance(checks, dict):
        problems.append(f"persona {pid}: 'checks' must be an object")
        return
    if not checks:
        problems.append(f"persona {pid}: 'checks' is empty - nothing for Layer 2 to assert")
    for name, value in checks.items():
        expected = C.KNOWN_CHECKS.get(name)
        if expected is None:
            known = ", ".join(sorted(C.KNOWN_CHECKS))
            problems.append(f"persona {pid}: unknown check '{name}' (known: {known})")
            continue
        if expected is bool and not isinstance(value, bool):
            problems.append(f"persona {pid}: check '{name}' must be a boolean")
        elif expected is int and not isinstance(value, int):
            problems.append(f"persona {pid}: check '{name}' must be an integer")
        elif expected is list:
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                problems.append(f"persona {pid}: check '{name}' must be a list of strings")


def load_personas(problems: list[str]) -> list[Persona]:
    raw = _read_json(C.PERSONAS_FILE, problems)
    if raw is None:
        return []
    if not isinstance(raw, list) or not raw:
        problems.append("personas.json: expected a non-empty array")
        return []

    personas: list[Persona] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            problems.append(f"personas[{i}]: expected an object")
            continue
        pid = item.get("id")
        if not isinstance(pid, str) or not pid.strip():
            problems.append(f"personas[{i}]: missing 'id'")
            continue
        if pid in seen:
            problems.append(f"persona {pid}: duplicate id")
            continue
        seen.add(pid)

        msg = item.get("first_message")
        if not isinstance(msg, str) or not msg.strip():
            problems.append(f"persona {pid}: missing or empty 'first_message'")
            msg = ""
        llm_check = item.get("llm_check")
        if not isinstance(llm_check, str) or not llm_check.strip():
            # Layer 3 input. Not needed to produce transcripts, but a missing one
            # means this persona silently drops out of judging later.
            problems.append(f"persona {pid}: missing 'llm_check' (Layer 3 would skip it)")
            llm_check = ""
        _validate_checks(pid, item.get("checks"), problems)

        personas.append(Persona(
            id=pid,
            type=item.get("type", "unspecified"),
            first_message=msg,
            checks=item.get("checks") if isinstance(item.get("checks"), dict) else {},
            llm_check=llm_check,
        ))
    return personas


def load_scenarios(problems: list[str]) -> tuple[dict[str, Scenario], str | None]:
    raw = _read_json(C.SCENARIOS_FILE, problems)
    if raw is None:
        return {}, None
    entries = raw.get("scenarios") if isinstance(raw, dict) else None
    if not isinstance(entries, list) or not entries:
        problems.append("scenarios.json: expected a non-empty 'scenarios' array")
        return {}, None

    scenarios: dict[str, Scenario] = {}
    for i, item in enumerate(entries):
        sid = item.get("id") if isinstance(item, dict) else None
        if not isinstance(sid, str) or not sid.strip():
            problems.append(f"scenarios[{i}]: missing 'id'")
            continue
        if sid in scenarios:
            problems.append(f"scenario {sid}: duplicate id")
            continue

        system = ""
        for key in ("prompt_file", "faq_file"):
            rel = item.get(key)
            if not isinstance(rel, str) or not (C.ROOT / rel).exists():
                problems.append(f"scenario {sid}: '{key}' -> {rel!r} not found")
        prompt_rel, faq_rel = item.get("prompt_file", ""), item.get("faq_file", "")
        if (C.ROOT / str(prompt_rel)).exists() and (C.ROOT / str(faq_rel)).exists():
            # The prompts end with "...that is not in the FAQ below", so the FAQ
            # is appended to the system prompt, not sent as a user turn.
            system = (
                (C.ROOT / str(prompt_rel)).read_text(encoding="utf-8").rstrip()
                + "\n\n---\n\n"
                + (C.ROOT / str(faq_rel)).read_text(encoding="utf-8").strip()
            )

        model = item.get("model")
        if not isinstance(model, str) or not model.strip():
            problems.append(f"scenario {sid}: missing 'model'")
            model = ""
        max_tokens = item.get("max_tokens", 1024)
        if not isinstance(max_tokens, int) or max_tokens < 64:
            problems.append(f"scenario {sid}: 'max_tokens' must be an int >= 64")
            max_tokens = 1024
        thinking = item.get("thinking", "disabled")
        if thinking not in ("disabled", "adaptive", None):
            problems.append(f"scenario {sid}: 'thinking' must be 'disabled', 'adaptive' or null")
            thinking = "disabled"

        scenarios[sid] = Scenario(
            id=sid,
            description=item.get("description", ""),
            prompt_file=str(prompt_rel),
            faq_file=str(faq_rel),
            model=model,
            max_tokens=max_tokens,
            thinking=thinking,
            system=system,
        )

    default = raw.get("default_scenario") if isinstance(raw, dict) else None
    if default is not None and default not in scenarios:
        problems.append(f"scenarios.json: default_scenario {default!r} is not defined")
        default = None
    return scenarios, default


def load_deferrals(personas: list[Persona], problems: list[str]) -> dict[str, dict[str, str]]:
    """Checks handed to Layer 3, kept out of personas.json so the input data
    stays exactly as authored. A deferral naming a check that no longer exists
    is stale and must be caught here, not silently ignored."""
    if not C.DEFERRALS_FILE.exists():
        return {}
    raw = _read_json(C.DEFERRALS_FILE, problems)
    if raw is None:
        return {}
    entries = raw.get("deferrals") if isinstance(raw, dict) else None
    if entries is None:
        return {}
    if not isinstance(entries, dict):
        problems.append("deferrals.json: 'deferrals' must be an object")
        return {}

    by_id = {p.id: p for p in personas}
    out: dict[str, dict[str, str]] = {}
    for pid, checks in entries.items():
        persona = by_id.get(pid)
        if persona is None:
            problems.append(f"deferrals.json: unknown persona {pid!r}")
            continue
        if not isinstance(checks, dict):
            problems.append(f"deferrals.json: {pid} must map check name -> reason")
            continue
        kept = {}
        for name, entry in checks.items():
            if name not in persona.checks:
                problems.append(f"deferrals.json: {pid} has no check {name!r} to defer (stale)")
                continue
            if not isinstance(entry, dict):
                problems.append(f"deferrals.json: {pid}.{name} must be an object with 'reason' and 'intent'")
                continue
            for field in ("reason", "intent"):
                if not isinstance(entry.get(field), str) or not entry[field].strip():
                    problems.append(f"deferrals.json: {pid}.{name} needs a non-empty '{field}'")
                    break
            else:
                kept[name] = entry
        out[pid] = kept
    return out


def load_all() -> tuple[list[Persona], dict[str, Scenario], str | None,
                        dict[str, dict[str, str]], list[str]]:
    problems: list[str] = []
    personas = load_personas(problems)
    scenarios, default = load_scenarios(problems)
    deferrals = load_deferrals(personas, problems)
    return personas, scenarios, default, deferrals, problems


def fingerprints(scenario: Scenario) -> dict[str, str]:
    """What produced these transcripts. Changes here invalidate comparisons."""
    out = {"personas.json": sha(C.PERSONAS_FILE), "scenarios.json": sha(C.SCENARIOS_FILE)}
    if C.DEFERRALS_FILE.exists():
        out["deferrals.json"] = sha(C.DEFERRALS_FILE)
    for rel in (scenario.prompt_file, scenario.faq_file):
        path = C.ROOT / rel
        if path.exists():
            out[rel] = sha(path)
    return out
