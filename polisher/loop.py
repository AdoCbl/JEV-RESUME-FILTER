"""The polish loop: write, review, keep the best, repeat — and know when to stop.

The loop owns orchestration and nothing else. It makes the two API calls per round,
keeps the highest-scoring draft, and hands each finished round to an observer. Printing,
writing files, and updating the web report are observers' business (see
:mod:`polisher.cli`), so the loop can be driven from a test with no API keys at all.
"""

from collections.abc import Callable
from dataclasses import dataclass

from openai import OpenAI
from typesafe_sdk import TypeSafeClient

from . import judge
from .config import Settings
from .judge import Review
from .rules import RuleBook
from .writer import Draft, write_draft


@dataclass(frozen=True)
class Round:
    """One writer attempt and the review it earned."""

    number: int
    draft: Draft
    review: Review
    improvement: float | None  # versus the best draft before this round; None on round 1
    reviewed: bool = True  # False when the writer returned the draft unchanged

    @property
    def beat_best(self) -> bool:
        """True when this round's draft is the new best."""
        return self.improvement is None or self.improvement > 0


@dataclass(frozen=True)
class PolisherRun:
    """What a whole run produced."""

    rounds: tuple[Round, ...]
    best: Round
    stop_reason: str


RoundObserver = Callable[[Round, Round, tuple[Round, ...]], None]


def attempt_history(rounds: list[Round] | tuple[Round, ...]) -> str | None:
    """The scores so far, so the writer does not walk back into a worse attempt."""
    if not rounds:
        return None
    rows = [
        f"  round {r.number}: overall {r.review.overall:.2f}"
        f" (quality {r.review.quality:.2f}, grounded {r.review.groundedness:.2f})"
        for r in rounds
    ]
    return (
        "## ATTEMPT HISTORY\n"
        "Do not repeat an attempt that scored below the current best draft.\n" + "\n".join(rows)
    )


def rejected_phrasings(
    rounds: list[Round] | tuple[Round, ...],
    best: Round | None,
    extra: list[str] | None = None,
    limit: int = 6,
) -> str | None:
    """Phrasings JEV or a human reviewer rejected, so the writer does not repeat them.

    ``extra`` holds lines a human explicitly rejected during a live run; those are
    permanent for the run and prepended so they lead the writer's instruction.
    """
    human = list(extra or [])
    jev: list[str] = []
    for round_ in reversed(tuple(rounds)):
        if round_ is best:
            continue
        for line in round_.review.lines_to_review():
            if line.text not in human and line.text not in jev:
                jev.append(line.text)
            if len(jev) == limit:
                break
        if len(jev) == limit:
            break
    seen = human + jev
    if not seen:
        return None
    attribution = []
    if human:
        attribution.append(f"{len(human)} rejected by a human")
    if jev:
        attribution.append(f"{len(jev)} by JEV in prior rounds")
    lines = [f"  - {t}" for t in seen]
    return (
        "## PHRASINGS THE REVIEWER REJECTED IN EARLIER ATTEMPTS\n"
        "Do not reuse these wordings. Rewrite each from the original resume or drop the claim."
        f" ({', '.join(attribution)})\n" + "\n".join(lines)
    )


def stop_reason(current: Round, settings: Settings, misses: int) -> str | None:
    """Two ways out: the draft is good enough, or another round is not paying off.

    A single bad round is not evidence of a plateau — the writer is stochastic — so the
    loop tolerates ``settings.patience`` non-improving rounds before it stops.
    """
    review = current.review
    if (
        review.overall >= settings.target_score
        and not review.blocked
        and not review.blocking_violations
    ):
        return f"target reached (overall {review.overall:.2f} >= {settings.target_score:.2f})"
    if misses >= settings.patience:
        last = current.improvement
        detail = "no round beat the best draft" if last is None else f"last {last:+.2f}"
        return (
            f"no meaningful improvement in {settings.patience} rounds ({detail},"
            f" needs +{settings.min_improvement:.2f})"
        )
    return None


def polish(
    settings: Settings,
    resume: str,
    job_description: str,
    on_round: RoundObserver | None = None,
    prior_rounds: list[Round] | None = None,
    human_rejections: Callable[[], list[str]] | None = None,
    reviewer: TypeSafeClient | None = None,
    rulebook: RuleBook | None = None,
) -> PolisherRun:
    """Write, review, keep the best, feed the review back, and stop when it stops paying.

    Pass ``prior_rounds`` to resume from a previously interrupted run.
    Pass ``human_rejections`` to include lines a person rejected during a live run in the
    writer's instruction block every round; those rejections are permanent for the run.
    """
    import time as _time

    rounds: list[Round] = list(prior_rounds or [])
    best: Round | None = max(rounds, key=lambda r: r.review.overall) if rounds else None
    misses = 0
    reason = f"hit the {settings.max_iterations}-round ceiling"
    run_start = _time.monotonic()
    total_tokens = sum(
        (r.draft.metrics.spend_tokens or 0) + (r.review.metrics.total_tokens or 0)
        for r in rounds
    )

    reviewer = reviewer or TypeSafeClient(**settings.typesafe_client_kwargs())

    with OpenAI(
        api_key=settings.writer_api_key,
        base_url=settings.writer_base_url,
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,
    ) as writer:
        start_number = (rounds[-1].number + 1) if rounds else 1
        for number in range(start_number, settings.max_iterations + 1):
            # Budget: seconds
            if settings.max_seconds is not None:
                elapsed = _time.monotonic() - run_start
                if elapsed >= settings.max_seconds:
                    reason = f"budget exhausted: {elapsed:.0f}s >= {settings.max_seconds:.0f}s"
                    break
            # Budget: tokens
            if settings.max_tokens is not None and total_tokens >= settings.max_tokens:
                reason = f"budget exhausted: {total_tokens:,} tokens >= {settings.max_tokens:,}"
                break

            base = best
            # Lines the writer did not touch keep the verdict they already earned.
            carried = (
                None if base is None else {line.text: line.support for line in base.review.lines}
            )
            # Evidence (source line mappings) is also carried for unchanged lines.
            carried_evidence = None if base is None else base.review.evidence
            extra_rejected = human_rejections() if human_rejections is not None else []
            draft = write_draft(
                writer,
                model=settings.writer_model,
                original_resume=resume,
                job_description=job_description,
                base_draft=None if base is None else base.draft.text,
                feedback=None if base is None else base.review.feedback(),
                history=attempt_history(rounds),
                rejected=rejected_phrasings(rounds, base, extra=extra_rejected),
            )

            if base is not None and draft.text == base.draft.text:
                # The writer changed nothing: count as flat, skip re-review.
                review, reviewed, improvement = base.review, False, 0.0
            else:
                review = judge.review(
                    reviewer,
                    original_resume=resume,
                    job_description=job_description,
                    draft=draft.text,
                    carried=carried,
                    carried_evidence=carried_evidence,
                    rulebook=rulebook,
                )
                reviewed = True
                improvement = None if best is None else review.overall - best.review.overall

            total_tokens += (draft.metrics.spend_tokens or 0) + (
                review.metrics.total_tokens or 0 if reviewed else 0
            )

            current = Round(
                number=number,
                draft=draft,
                review=review,
                improvement=improvement,
                reviewed=reviewed,
            )
            rounds.append(current)
            if best is None or review.overall > best.review.overall:
                best = current

            if on_round is not None:
                on_round(current, best, tuple(rounds))

            if current.improvement is not None and current.improvement < settings.min_improvement:
                misses += 1
            else:
                misses = 0
            found = stop_reason(current, settings, misses)
            if found is not None:
                reason = found
                break

    assert best is not None, "the loop always runs at least one round"
    return PolisherRun(rounds=tuple(rounds), best=best, stop_reason=reason)
