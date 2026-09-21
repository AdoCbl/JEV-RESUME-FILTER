"""Run persistence: save each round to disk and resume from the last complete one.

Every run gets a ``runs/<run-id>/`` directory. Each finished round is written as
``round-<n>.json`` immediately after it completes, so killing the process mid-run
loses at most one in-flight round. ``--resume runs/<id>`` reloads those files and
resumes from where the run left off.

Failure taxonomy
----------------
All provider errors are wrapped in :class:`ProviderError` or one of its subclasses so
the CLI and tests can distinguish them without pattern-matching on message strings.
"""

from __future__ import annotations

import datetime
import json
import uuid
from enum import StrEnum
from pathlib import Path
from typing import Any

RUNS_DIR = Path("runs")


# ── Failure taxonomy ──────────────────────────────────────────────────────────


class FailureKind(StrEnum):
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    MALFORMED = "malformed"
    SERVER_ERROR = "server_error"
    UNKNOWN = "unknown"


class ProviderError(RuntimeError):
    """A provider failure that the loop knows how to report."""

    kind: FailureKind

    def __init__(self, kind: FailureKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind

    @classmethod
    def from_openai(cls, exc: Exception) -> ProviderError:
        """Map an openai exception to the closest FailureKind."""
        from openai import (
            APIConnectionError,
            APIStatusError,
            APITimeoutError,
            AuthenticationError,
            RateLimitError,
        )

        if isinstance(exc, AuthenticationError):
            return cls(FailureKind.AUTH, f"auth: {exc}")
        if isinstance(exc, RateLimitError):
            return cls(FailureKind.RATE_LIMIT, f"rate limit: {exc}")
        if isinstance(exc, APITimeoutError):
            return cls(FailureKind.TIMEOUT, f"timeout: {exc}")
        if isinstance(exc, APIStatusError) and exc.status_code >= 500:
            return cls(FailureKind.SERVER_ERROR, f"server error {exc.status_code}: {exc}")
        if isinstance(exc, APIConnectionError):
            return cls(FailureKind.TIMEOUT, f"connection error: {exc}")
        return cls(FailureKind.UNKNOWN, str(exc))

    @classmethod
    def from_typesafe(cls, exc: Exception) -> ProviderError:
        from typesafe_sdk import TypeSafeAPIError

        if isinstance(exc, TypeSafeAPIError):
            if exc.status in (401, 403):
                return cls(FailureKind.AUTH, f"TypeSafe auth {exc.status}: {exc}")
            if exc.status == 429:
                return cls(FailureKind.RATE_LIMIT, f"TypeSafe rate limit: {exc}")
            if exc.status >= 500:
                return cls(FailureKind.SERVER_ERROR, f"TypeSafe server error {exc.status}: {exc}")
        return cls(FailureKind.UNKNOWN, str(exc))


# ── Run IDs ───────────────────────────────────────────────────────────────────


def new_run_id() -> str:
    """A sortable, unique run ID: ``YYYYMMDD-HHMMSS-<short-uuid>``."""
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{ts}-{uuid.uuid4().hex[:8]}"


def run_dir(run_id: str, base: Path | None = None) -> Path:
    """The directory for one run. ``base`` defaults to :data:`RUNS_DIR` at call time."""
    return (RUNS_DIR if base is None else base) / run_id


# ── Round serialization ───────────────────────────────────────────────────────


def _round_to_dict(round_: Any) -> dict[str, Any]:
    """Serialise one Round dataclass to a plain dict for JSON."""

    r = round_
    return {
        "number": r.number,
        "reviewed": r.reviewed,
        "improvement": r.improvement,
        "draft": {
            "text": r.draft.text,
            "metrics": r.draft.metrics.to_dict(),
        },
        "review": {
            "scores": r.review.scores,
            "confidences": r.review.confidences,
            "levels": r.review.levels,
            "quality": r.review.quality,
            "guardrails": r.review.guardrails,
            "lines": [
                {
                    "text": line.text,
                    "support": line.support,
                    "failing_claim": line.failing_claim,
                    "claims": [[t, s] for t, s in line.claims],
                }
                for line in r.review.lines
            ],
            "reused_lines": r.review.reused_lines,
            "biggest_gap": r.review.biggest_gap,
            "biggest_gap_confidence": r.review.biggest_gap_confidence,
            "gap_distribution": r.review.gap_distribution,
            "evidence": r.review.evidence,
            "coverage": r.review.coverage,
            "metrics": r.review.metrics.to_dict(),
        },
    }


def _round_from_dict(data: dict[str, Any]) -> Any:
    """Reconstruct a Round from its saved JSON dict (no API calls needed)."""
    from .judge import AuditedLine, Review
    from .loop import Round
    from .metrics import LLMCallMetrics, RequestMetrics
    from .writer import Draft

    dm = data["draft"]["metrics"]
    draft = Draft(
        text=data["draft"]["text"],
        metrics=LLMCallMetrics(
            latency_ms=dm["latency_ms"],
            model=dm["model"],
            prompt_tokens=dm.get("prompt_tokens"),
            completion_tokens=dm.get("completion_tokens"),
            total_tokens=dm.get("total_tokens"),
        ),
    )
    rm = data["review"]["metrics"]
    metrics = RequestMetrics(
        latency_ms=rm["latency_ms"],
        model=rm["model"],
        request_id=rm.get("request_id", ""),
        input_tokens=rm.get("input_tokens"),
        output_tokens=rm.get("output_tokens"),
    )
    review = Review(
        scores=data["review"]["scores"],
        confidences=data["review"]["confidences"],
        levels=data["review"]["levels"],
        quality=data["review"]["quality"],
        guardrails=data["review"]["guardrails"],
        lines=tuple(
            AuditedLine(
                text=line["text"],
                support=line["support"],
                failing_claim=line.get("failing_claim"),
                claims=tuple((t, s) for t, s in line.get("claims", [])),
            )
            for line in data["review"]["lines"]
        ),
        reused_lines=data["review"]["reused_lines"],
        biggest_gap=data["review"]["biggest_gap"],
        biggest_gap_confidence=data["review"]["biggest_gap_confidence"],
        gap_distribution=data["review"]["gap_distribution"],
        evidence=data["review"].get("evidence", {}),
        coverage=data["review"].get("coverage", {}),
        metrics=metrics,
    )
    return Round(
        number=data["number"],
        draft=draft,
        review=review,
        improvement=data["improvement"],
        reviewed=data["reviewed"],
    )


def save_round(round_: Any, directory: Path) -> None:
    """Write one round to ``directory/round-<n>.json``."""
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"round-{round_.number:02d}.json"
    path.write_text(json.dumps(_round_to_dict(round_), indent=2))


def load_rounds(directory: Path) -> list[Any]:
    """Reload all saved rounds from a run directory, sorted by number."""
    files = sorted(directory.glob("round-*.json"), key=lambda p: p.name)
    if not files:
        raise SystemExit(f"no saved rounds found in {directory}")
    return [_round_from_dict(json.loads(f.read_text())) for f in files]


def write_manifest(directory: Path, data: dict[str, Any]) -> None:
    """Write (or overwrite) ``manifest.json`` in the run directory."""
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(json.dumps(data, indent=2))
