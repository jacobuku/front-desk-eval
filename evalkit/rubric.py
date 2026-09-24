"""Layer 3 rubric assembly.

Three kinds of dimension, in priority order:

  deferred: - backfills a Layer 2 check that substring matching cannot judge.
              This is Layer 3's first job.
  persona:  - the persona's own llm_check question.
  safety/quality - cross-persona dimensions from rubric.json.

A judge receives the question, the transcript and the FAQ. It never receives the
persona type, the needle lists, or the reason a check was deferred - those would
tell it what the guest is testing for.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from . import config as C
from .schema import Persona


@dataclass(frozen=True)
class Dimension:
    id: str
    tier: str          # deferred | persona | safety | quality
    model_key: str     # sonnet | opus
    question: str


def load_rubric(problems: list[str]) -> list[Dimension]:
    if not C.RUBRIC_FILE.exists():
        problems.append("rubric.json: missing")
        return []
    try:
        raw = json.loads(C.RUBRIC_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        problems.append(f"rubric.json: invalid JSON ({e})")
        return []

    dims: list[Dimension] = []
    seen: set[str] = set()
    for i, item in enumerate(raw.get("dimensions", [])):
        did = item.get("id")
        if not isinstance(did, str) or not did.strip():
            problems.append(f"rubric.json: dimensions[{i}] missing 'id'")
            continue
        if did in seen:
            problems.append(f"rubric.json: duplicate dimension id {did!r}")
            continue
        seen.add(did)
        if item.get("model") not in C.JUDGE_MODELS:
            problems.append(f"rubric.json: {did} has unknown model "
                            f"{item.get('model')!r} (known: {', '.join(C.JUDGE_MODELS)})")
            continue
        if not isinstance(item.get("question"), str) or not item["question"].strip():
            problems.append(f"rubric.json: {did} needs a non-empty 'question'")
            continue
        dims.append(Dimension(id=did, tier=item.get("tier", "quality"),
                              model_key=item["model"], question=item["question"]))
    return dims


def dimensions_for(
    persona: Persona,
    deferrals: dict[str, dict[str, Any]],
    shared: list[Dimension],
    tiers: set[str] | None = None,
) -> list[Dimension]:
    dims: list[Dimension] = []

    for check_name, entry in sorted(deferrals.get(persona.id, {}).items()):
        dims.append(Dimension(
            id=f"deferred:{persona.id}.{check_name}",
            tier="deferred",
            model_key="sonnet",
            question=entry["intent"],   # 'reason' is for humans and stays out
        ))

    if persona.llm_check:
        dims.append(Dimension(id=f"persona:{persona.id}", tier="persona",
                              model_key="sonnet", question=persona.llm_check))

    dims.extend(shared)
    if tiers is not None:
        dims = [d for d in dims if d.tier in tiers]
    return dims
