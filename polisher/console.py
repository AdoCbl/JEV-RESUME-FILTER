"""The terminal view of a run: the header, one line per round, and the result.

The page is where a run is read and steered — scores, the ledger, the coverage matrix, the
approve/reject decisions. So while the page is being served the terminal stays a progress
log: one line per round, and a short result that points at the page. With ``--no-serve``
there is no page, and the terminal falls back to the full breakdown, because it is then the
only view of the run there is.
"""

from pathlib import Path
from typing import Any

from . import judge
from .config import Settings
from .loop import Round

WIDTH = 68
_RULE = "─"


def _bar(value: float, width: int = 14) -> str:
    filled = round(value * width)
    return "█" * filled + "░" * (width - filled)


def print_header(
    *,
    settings: Settings,
    resume_path: Path,
    job_path: Path,
    resume: str,
    job_description: str,
) -> None:
    cap = settings.max_iterations
    print(f"{'═' * WIDTH}")
    print("  Resume polisher — DeepSeek writes, JEV reviews, scores, and guards")
    print(f"{'═' * WIDTH}")
    print(f"  Resume:    {resume_path} ({len(resume):,} chars)")
    print(f"  Job:       {job_path} ({len(job_description):,} chars)")
    print(f"  Writer:    {settings.writer_label}")
    print(f"  Reviewer:  {settings.reviewer_label}")
    print(
        f"  Loop:      up to {cap} round{'' if cap == 1 else 's'}, stops below"
        f" +{settings.min_improvement:.2f} improvement for {settings.patience} rounds,"
        f" target {settings.target_score:.2f}"
    )


def print_server(url: str) -> None:
    print(f"  Report:    {url}  (live, Ctrl-C to stop)")


def print_server_unavailable(port: int, reason: str) -> None:
    """Say why the page is not coming up, and how to get it, without losing the run."""
    print(
        f"  Report:    unavailable on port {port} ({reason}) — another run may still be"
        " serving it; rerun with --port N, or --no-serve to silence this"
    )


def print_round(
    current: Round,
    settings: Settings,
    saved_path: Path | None = None,
    *,
    verbose: bool = True,
) -> None:
    """One round as it finishes: a line when the page will show it, a block when nothing will."""
    if not verbose:
        print(_round_line(current, settings, saved_path))
        return
    review = current.review
    delta = "first draft" if current.improvement is None else f"{current.improvement:+.2f} vs best"
    print(f"\n  ── Round {current.number} of {settings.max_iterations} " + _RULE * 36)
    print(
        f"     overall {review.overall:.2f} ({delta})    quality {review.quality:.2f}"
        f"    grounded {review.groundedness:.2f}"
    )
    if not current.reviewed:
        print(
            "     the writer returned the draft unchanged — no review this round"
            " (scores carry over from the draft it started from)"
        )
    else:
        writer_tokens = current.draft.metrics.spend_tokens
        reviewer_tokens = review.metrics.total_tokens or 0
        print(
            f"     writer {len(current.draft.text):,} chars in"
            f" {current.draft.metrics.latency_ms / 1000:.1f}s ({writer_tokens:,} tok)   |"
            f"   reviewer {review.metrics.latency_ms / 1000:.1f}s ({reviewer_tokens:,} tok),"
            f" {len(review.lines)} lines audited"
            + (f" ({review.reused_lines} carried over)" if review.reused_lines else "")
        )
    for name, score in review.scores.items():
        confidence = review.confidences[name]
        flag = "  ⚠ unsure" if confidence < judge.CONFIDENCE_FLOOR else ""
        print(
            f"       {name:<19} {_bar(score / judge.TOP_LEVEL)} {score:.2f}/4"
            f"  conf {confidence:.2f}{flag}"
        )
    print(
        "       fabrication        "
        + "  ".join(f"{name}={value:.2f}" for name, value in review.guardrails.items())
    )
    weakest = review.weakest_line
    print(
        f"       line grounding     mean {review.line_grounding:.2f}"
        + (f", weakest {weakest.support:.2f}" if weakest is not None else "")
    )
    if review.blocked:
        print("       ⚠ BLOCKED — the reviewer judges this draft to have unsupported claims")
    for line in review.lines_to_review(limit=3):
        verdict = "NOT SUPPORTED" if line.unsupported else "tighten"
        print(f"       ⚠ [{line.support:.2f} {verdict}] {line.text[:76]}")
    if not review.gap_is_split:
        gap = f"{review.biggest_gap} (conf {review.biggest_gap_confidence:.2f})"
    else:
        top = sorted(review.gap_distribution.items(), key=lambda item: -item[1])[:2]
        gap = "reviewer split between " + ", ".join(f"{name} {value:.2f}" for name, value in top)
    print(f"       biggest gap        {gap}")
    if saved_path is not None:
        print(f"       saved              {saved_path} (new best draft)")


def _round_line(current: Round, settings: Settings, saved_path: Path | None) -> str:
    """The one line a round gets when the page is the place it will be read."""
    review = current.review
    delta = "first draft" if current.improvement is None else f"{current.improvement:+.2f}"
    flagged = len(review.flagged_lines)
    parts = [
        f"  round {current.number}/{settings.max_iterations}",
        f"overall {review.overall:.2f} ({delta})",
        f"quality {review.quality:.2f}",
        f"grounded {review.groundedness:.2f}",
        "nothing flagged" if not flagged else f"{flagged} flagged",
    ]
    if not current.reviewed:
        parts.append("writer unchanged")
    if saved_path is not None:
        parts.append("new best")
    return "   ".join(parts)


def print_result(report: dict[str, Any], url: str | None = None, *, verbose: bool = True) -> None:
    """The end-of-run summary, read from the same payload the page renders."""
    versions = report["versions"]
    best = None if report["best_index"] is None else versions[report["best_index"]]
    totals = report["totals"]

    if not verbose:
        print()
        if best is not None:
            review = best["review"]
            print(
                f"  Done — {best['label']} is the best draft: overall {review['overall']:.2f}"
                f" (quality {review['quality']:.2f}, grounded {review['groundedness']:.2f})"
            )
            print(f"  Stopped:     {report['stop_reason']}")
            print(
                f"  {len(versions) - 1} rounds · {totals['total_tokens']:,} tokens ·"
                f" {totals['seconds']:,.0f}s · wrote {report['paths']['out']}"
            )
            if review["flagged_lines"]:
                print(
                    f"  ⚠  {len(review['flagged_lines'])} unsupported line(s) in the winning"
                    " draft — decide them on the page before using this resume."
                )
        if url:
            print(f"  Report:      {url}  (still serving; Ctrl-C to stop)")
        return

    print(f"\n{'═' * WIDTH}")
    print("  Result")
    print(f"{'═' * WIDTH}")
    print(f"  Rounds run:  {len(versions) - 1}")
    print(f"  Stopped:     {report['stop_reason']}")
    if best is not None:
        review = best["review"]
        print(
            f"  Best draft:  {best['label']} — overall {review['overall']:.2f}"
            f" (quality {review['quality']:.2f}, grounded {review['groundedness']:.2f},"
            f" fabrication risk {review['fabrication_risk']:.2f})"
        )
        if review["flagged_lines"]:
            print(
                f"  ⚠  {len(review['flagged_lines'])} line(s) of the winning draft are still"
                " unsupported by the original resume — check them before sending it."
            )
        print(f"  Output:      {report['paths']['out']} ({best['chars']:,} chars)")
    if url:
        print(f"  Report:      {url}  (Ctrl-C to stop)")
    print("\n── Run totals ─────────────────────────────────────────────────")
    print(f"  Writer calls:   {totals['writer_calls']}  ({totals['writer_tokens']:,} tokens)")
    print(f"  Reviewer calls: {totals['reviewer_calls']}  ({totals['reviewer_tokens']:,} tokens)")
    print(f"  Total tokens:   {totals['total_tokens']:,}")
    print(f"  Total latency:  {totals['seconds']:,.1f} s")
