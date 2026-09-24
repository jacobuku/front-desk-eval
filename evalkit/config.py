"""Paths, constants and the check vocabulary. No I/O here."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PERSONAS_FILE = ROOT / "personas.json"
SCENARIOS_FILE = ROOT / "scenarios.json"
DEFERRALS_FILE = ROOT / "deferrals.json"
RUBRIC_FILE = ROOT / "rubric.json"
GOLDENS_DIR = ROOT / "goldens"
RUNS_DIR = ROOT / "runs"

SCHEMA_VERSION = 1

DEFAULT_REPEATS = 3
DEFAULT_CONCURRENCY = 8
MAX_ATTEMPTS = 3
BACKOFF_BASE_S = 2.0
REQUEST_TIMEOUT_S = 90.0

# Layer 2 check vocabulary -> expected value type. Anything outside this set is a
# typo in personas.json and must fail validation loudly rather than be skipped.
KNOWN_CHECKS: dict[str, type | tuple[type, ...]] = {
    "must_mention_price": bool,
    "must_contain_any": list,
    "must_contain_all": list,
    "must_not_contain": list,
    "first_sentence_must_contain_any": list,
    "max_words": int,
}

# USD per million tokens, for the run cost estimate only.
PRICING = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

PASS, FAIL, NO_EVIDENCE = "pass", "fail", "no_evidence"
# A check Layer 2 cannot judge without being brittle. Excluded from the
# rollup and handed to Layer 3 - not a pass, not a fail.
DEFERRED = "deferred"
# Layer 4 verdict that is neither confirmed nor dropped: one fail vote
# against a dissent. Delivered with the dissent attached.
DISPUTED = "disputed"

# Judge models. Safety and multi-step reasoning go to Opus; the rest to
# Sonnet. The rubric names a key, never a model id.
JUDGE_MODELS = {"sonnet": "claude-sonnet-5", "opus": "claude-opus-5"}
JUDGE_ROLES = ("assessor", "challenger")
JUDGE_MAX_TOKENS = 2000
DEFAULT_JUDGE_CONCURRENCY = 8

# Golden-set gate. Below either bar the judges do not get to score the SUT.
MIN_RECALL = 0.80
MAX_FALSE_POSITIVE_RATE = 0.10
