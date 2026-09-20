"""Append-only audit log for human sign-off decisions (Item 5).

Every approve/reject decision is recorded as a JSONL entry so that a reviewer can
later replay who approved what and when. The audit log is never overwritten, only
appended to.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuditLog:
    """Thread-safe append-only JSONL audit log."""

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._lock = threading.Lock()

    def record(
        self,
        *,
        run_id: str,
        line: str,
        verdict: str,  # "approved" or "rejected"
        reviewer: str = "human",
    ) -> None:
        if self._path is None:
            return
        entry = {
            "ts": datetime.now(tz=UTC).isoformat(),
            "run_id": run_id,
            "line": line,
            "verdict": verdict,
            "reviewer": reviewer,
        }
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a") as fh:
                fh.write(json.dumps(entry) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if self._path is None or not self._path.exists():
            return []
        entries = []
        for raw in self._path.read_text().splitlines():
            raw = raw.strip()
            if raw:
                entries.append(json.loads(raw))
        return entries


def write_unresolved(output_path: Path, flagged: list[str]) -> Path:
    """Write UNRESOLVED.md beside the output file listing lines that still need review."""
    path = output_path.with_name("UNRESOLVED.md")
    lines = [
        "# Unresolved lines",
        "",
        "These lines in the saved draft were flagged as potentially unsupported by the",
        "original resume and have not been approved by a reviewer. Do not send this resume",
        "without resolving each one.",
        "",
    ]
    for text in flagged:
        lines.append(f"- {text}")
    path.write_text("\n".join(lines) + "\n")
    return path
