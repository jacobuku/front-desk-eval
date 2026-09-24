"""Record shapes shared by the runner, the store and (later) the judges."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class Persona:
    id: str
    type: str
    first_message: str
    checks: dict[str, Any]
    llm_check: str


@dataclass(frozen=True)
class Scenario:
    id: str
    description: str
    prompt_file: str
    faq_file: str
    model: str
    max_tokens: int
    thinking: str | None
    system: str = field(repr=False, default="")


@dataclass(frozen=True)
class Unit:
    """One independent piece of work: persona x scenario x repeat."""
    unit_id: str
    persona: Persona
    scenario: Scenario
    repeat_idx: int


@dataclass
class SutResult:
    ok: bool
    text: str | None = None
    stop_reason: str | None = None
    truncated: bool = False
    usage: dict[str, int] = field(default_factory=dict)
    request_id: str | None = None
    latency_ms: int = 0
    attempts: int = 0
    model: str = ""
    error: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FatalRunError(RuntimeError):
    """Config/credential problem. Abort the whole run instead of burning units."""
