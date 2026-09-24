"""Persistence. One directory per run, one file per unit.

Transcripts are the artifact everything downstream reads: Layer 3 judging runs
off these files, never off a live re-run. A crashed unit costs one file.
"""
from __future__ import annotations

import json
import os
import random
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import config as C


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"{stamp}-{suffix}"


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class RunStore:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.dir = C.RUNS_DIR / run_id
        self.units_dir = self.dir / "units"
        self.judgments_dir = self.dir / "judgments"
        self.units_dir.mkdir(parents=True, exist_ok=True)

    @property
    def manifest_path(self) -> Path:
        return self.dir / "manifest.json"

    @property
    def summary_path(self) -> Path:
        return self.dir / "summary.json"

    def unit_path(self, unit_id: str) -> Path:
        return self.units_dir / f"{unit_id}.json"

    def completed(self, unit_id: str) -> bool:
        """A unit counts as done only if it produced a usable record - a
        sut_error is retried on resume."""
        path = self.unit_path(unit_id)
        if not path.exists():
            return False
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("status") == "ok"
        except (json.JSONDecodeError, OSError):
            return False

    def write_manifest(self, payload: dict[str, Any]) -> None:
        _write_atomic(self.manifest_path, payload)

    def read_manifest(self) -> dict[str, Any]:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def write_unit(self, record: dict[str, Any]) -> None:
        _write_atomic(self.unit_path(record["unit_id"]), record)

    def write_summary(self, payload: dict[str, Any]) -> None:
        _write_atomic(self.summary_path, payload)

    def judgment_path(self, unit_id: str) -> Path:
        return self.judgments_dir / f"{unit_id}.json"

    def judged(self, unit_id: str) -> bool:
        return self.judgment_path(unit_id).exists()

    def write_judgment(self, record: dict[str, Any]) -> None:
        self.judgments_dir.mkdir(parents=True, exist_ok=True)
        _write_atomic(self.judgment_path(record["unit_id"]), record)

    def iter_judgments(self) -> Iterator[dict[str, Any]]:
        if not self.judgments_dir.exists():
            return
        for path in sorted(self.judgments_dir.glob("*.json")):
            yield json.loads(path.read_text(encoding="utf-8"))

    def iter_units(self) -> Iterator[dict[str, Any]]:
        for path in sorted(self.units_dir.glob("*.json")):
            yield json.loads(path.read_text(encoding="utf-8"))


def latest_run_id() -> str | None:
    if not C.RUNS_DIR.exists():
        return None
    runs = sorted(p.name for p in C.RUNS_DIR.iterdir() if (p / "manifest.json").exists())
    return runs[-1] if runs else None
