"""One payload for every view: the terminal, the JSON dump, and the web page.

:func:`build_report` is the single source of truth for what a run produced. The console
and the local server both read this payload, so the terminal and the browser cannot
disagree about a score, a diff, or a total. It is also what ``--report-json`` writes.
"""

import hashlib
import subprocess
from typing import Any

from . import judge
from .config import Settings
from .diff import Diff, line_diff
from .judge import Review
from .loop import Round
from .writer import SYSTEM_PROMPT

ORIGINAL = "original"
ROUND = "round"


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return None


def _rubric_hash() -> str:
    """Stable SHA-256 of every rubric criterion so changes are detectable."""
    parts = []
    for name, score in sorted(judge.DIMENSIONS.items()):
        parts.append(name)
        parts.extend(score.criteria)
    for name, noul in sorted(judge.GUARDRAILS.items()):
        parts.append(name)
        c = noul.criteria
        if isinstance(c, dict):
            parts.append(str(c.get("true", "")))
            parts.append(str(c.get("false", "")))
        else:
            parts.append(str(getattr(c, "true", "")))
            parts.append(str(getattr(c, "false", "")))
    digest = hashlib.sha256("\n".join(parts).encode()).hexdigest()
    return digest[:16]


def _writer_prompt_hash() -> str:
    """Short hash of the writer system prompt so prompt changes are detectable in comparisons."""
    return hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:16]


def build_manifest(settings: Settings, run_id: str | None = None) -> dict[str, Any]:
    """Version fingerprint embedded in every payload for reproducibility checks."""
    return {
        "run_id": run_id,
        "git_commit": _git_commit(),
        "rubric_hash": _rubric_hash(),
        "writer_prompt_hash": _writer_prompt_hash(),
        "writer_model": settings.writer_model,
        "writer_base_url": settings.writer_base_url,
        "reviewer_model": settings.reviewer_label,
        "weights": dict(judge.WEIGHTS),
        "thresholds": {
            "line_support_floor": judge.LINE_SUPPORT_FLOOR,
            "fabrication_block": judge.FABRICATION_BLOCK,
            "confidence_floor": judge.CONFIDENCE_FLOOR,
            "gap_margin": judge.GAP_MARGIN,
        },
    }


def _review_payload(review: Review, *, improvement: float | None, is_best: bool) -> dict[str, Any]:
    """JEV's judgments, in the shape the views read."""
    weakest = review.weakest_line
    return {
        "overall": round(review.overall, 4),
        "quality": round(review.quality, 4),
        "groundedness": round(review.groundedness, 4),
        "fabrication_risk": round(review.fabrication_risk, 4),
        "line_grounding": round(review.line_grounding, 4),
        "weakest_line": (
            None
            if weakest is None
            else {"text": weakest.text, "support": round(weakest.support, 3)}
        ),
        "audited_lines": len(review.lines),
        "blocked": review.blocked,
        "improvement": None if improvement is None else round(improvement, 4),
        "is_best": is_best,
        "weakest_dimension": review.weakest,
        "agenda": list(review.agenda()),
        "reused_lines": review.reused_lines,
        "scores": {
            name: {
                "score": round(review.scores[name], 3),
                "confidence": round(review.confidences[name], 3),
                "level": review.levels.get(name, 0),
                "level_text": str(judge.DIMENSIONS[name].criteria[review.levels.get(name, 0)]),
                "normalized": round(review.scores[name] / judge.TOP_LEVEL, 3),
                "weight": judge.WEIGHTS[name],
            }
            for name in judge.DIMENSIONS
        },
        "guardrails": {name: round(value, 3) for name, value in review.guardrails.items()},
        "biggest_gap": review.biggest_gap,
        "biggest_gap_confidence": round(review.biggest_gap_confidence, 3),
        "gap_distribution": {
            name: round(value, 3) for name, value in review.gap_distribution.items()
        },
        "gap_is_split": review.gap_is_split,
        "flagged_lines": list(review.flagged_lines),
        "lines_to_review": [
            {
                "text": line.text,
                "support": round(line.support, 3),
                "unsupported": line.unsupported,
                "failing_claim": line.failing_claim,
                "claims": [{"text": t, "support": round(s, 3)} for t, s in line.claims],
            }
            for line in review.lines_to_review()
        ],
        # Every audited line with its claims, not just the weakest handful: the page
        # shows the distribution it is summarising, so a reader can see the run is unsure
        # rather than being told a verdict.
        "ledger": [
            {
                "text": line.text,
                "support": round(line.support, 3),
                "unsupported": line.unsupported,
                "uncertain": judge.LINE_SUPPORT_FLOOR <= line.support < judge.LINE_REVIEW_FLOOR,
                "failing_claim": line.failing_claim,
                "claims": [{"text": t, "support": round(s, 3)} for t, s in line.claims],
            }
            for line in review.lines
        ],
        "trust": {
            "audited": len(review.lines),
            "carried": review.reused_lines,
            "uncertain": sum(
                1
                for line in review.lines
                if judge.LINE_SUPPORT_FLOOR <= line.support < judge.LINE_REVIEW_FLOOR
            ),
            "unsupported": len(review.flagged_lines),
            "low_confidence": len(review.low_confidence),
        },
        "low_confidence": list(review.low_confidence),
        "evidence": review.evidence,
        "coverage": [
            {"requirement": req, "draft_line": line}
            for req, line in review.coverage.items()
        ],
        "reviewer": review.metrics.to_dict(),
    }


def _version(
    *,
    index: int,
    label: str,
    kind: str,
    text: str,
    review: dict[str, Any] | None,
    previous_text: str,
    original_text: str,
    saved: bool,
    reviewed: bool = True,
) -> dict[str, Any]:
    """One version of the resume, with both diffs the page can show."""
    return {
        "index": index,
        "label": label,
        "kind": kind,
        "text": text,
        "chars": len(text),
        "words": len(text.split()),
        "lines": len(text.splitlines()),
        "review": review,
        "reviewed": reviewed,
        "saved": saved,
        "diff_vs_previous": _diff_payload(line_diff(previous_text, text)),
        "diff_vs_original": _diff_payload(line_diff(original_text, text)),
    }


def _diff_payload(diff: Diff) -> dict[str, Any]:
    return diff.to_payload()


def _totals(rounds: tuple[Round, ...] | list[Round]) -> dict[str, Any]:
    """Roll up every call the run made; derived, never accumulated.

    A round whose draft came back unchanged was never reviewed, so it contributed a writer
    call and no reviewer call.
    """
    reviewed = [round_ for round_ in rounds if round_.reviewed]
    writer_tokens = sum(round_.draft.metrics.spend_tokens for round_ in rounds)
    reviewer_tokens = sum(round_.review.metrics.total_tokens or 0 for round_ in reviewed)
    latency_ms = sum(round_.draft.metrics.latency_ms for round_ in rounds) + sum(
        round_.review.metrics.latency_ms for round_ in reviewed
    )
    return {
        "writer_calls": len(rounds),
        "writer_tokens": writer_tokens,
        "reviewer_calls": len(reviewed),
        "reviewer_tokens": reviewer_tokens,
        "total_tokens": writer_tokens + reviewer_tokens,
        "latency_ms": round(latency_ms, 1),
        "seconds": round(latency_ms / 1000, 1),
    }


def build_report(
    *,
    settings: Settings,
    resume: str,
    job_description: str,
    paths: dict[str, str],
    rounds: tuple[Round, ...] | list[Round],
    best: Round | None,
    stop_reason: str | None,
    status: str,
    saved_index: int | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Assemble the payload for one run, complete or still in progress.

    ``status`` is ``"running"`` while the loop is mid-flight; the page polls while it is.
    """
    versions = [
        _version(
            index=0,
            label="Original",
            kind=ORIGINAL,
            text=resume,
            review=None,
            previous_text="",
            original_text=resume,
            saved=saved_index == 0,
        )
    ]
    previous_text = resume
    for round_ in rounds:
        review = _review_payload(
            round_.review,
            improvement=round_.improvement,
            is_best=best is not None and round_ is best,
        )
        review["writer"] = round_.draft.metrics.to_dict()
        versions.append(
            _version(
                index=round_.number,
                label=f"Round {round_.number}",
                kind=ROUND,
                text=round_.draft.text,
                review=review,
                previous_text=previous_text,
                original_text=resume,
                saved=saved_index == round_.number,
                reviewed=round_.reviewed,
            )
        )
        previous_text = round_.draft.text

    return {
        "status": status,
        "stop_reason": stop_reason,
        "best_index": None if best is None else best.number,
        "paths": paths,
        "manifest": build_manifest(settings, run_id=run_id),
        "config": {
            "writer_model": settings.writer_model,
            "reviewer_model": settings.reviewer_label,
            "max_iterations": settings.max_iterations,
            "min_improvement": settings.min_improvement,
            "target_score": settings.target_score,
            "patience": settings.patience,
            "max_tokens": settings.max_tokens,
            "max_seconds": settings.max_seconds,
            "weights": judge.WEIGHTS,
            "dimension_order": list(judge.DIMENSIONS),
            "top_level": judge.TOP_LEVEL,
            "line_support_floor": judge.LINE_SUPPORT_FLOOR,
            "line_review_floor": judge.LINE_REVIEW_FLOOR,
            "fabrication_block": judge.FABRICATION_BLOCK,
            "confidence_floor": judge.CONFIDENCE_FLOOR,
        },
        "job_description": job_description,
        "versions": versions,
        "totals": _totals(rounds),
    }
