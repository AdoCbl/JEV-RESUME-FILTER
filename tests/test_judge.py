"""Tests for polisher.judge — using answer stubs, no API calls."""

from __future__ import annotations

from polisher.judge import (
    claim_lines,
    split_claims,
)
from tests.conftest import FakeNoul, FakeScore, FakeTypeSafeClient, make_review_answers

ORIGINAL = "Led the platform team at Acme Corp for three years. Cut p95 latency by 40%."
DRAFT = "Led the platform team at Acme Corp. Reduced p95 latency by 40% through caching."


def _make_client(n_lines: int = 3, high_guardrail: bool = False) -> FakeTypeSafeClient:
    answers = make_review_answers(n_lines)
    if high_guardrail:
        from polisher.judge import GUARDRAILS
        for name in GUARDRAILS:
            answers[name] = FakeNoul(0.8)
    return FakeTypeSafeClient(answers, n_lines=n_lines)


def _do_review(draft: str, original: str = ORIGINAL, **kwargs):
    from polisher.judge import review
    client = _make_client(n_lines=len(claim_lines(draft)), **kwargs)
    return review(client, original_resume=original, job_description="some JD", draft=draft)


def test_review_returns_review_object() -> None:
    r = _do_review(DRAFT)
    assert 0.0 <= r.overall <= 1.0
    assert 0.0 <= r.quality <= 1.0


def test_overall_is_quality_times_groundedness() -> None:
    r = _do_review(DRAFT)
    assert abs(r.overall - r.quality * r.groundedness) < 1e-9


def test_blocked_when_guardrail_high() -> None:
    r = _do_review(DRAFT, high_guardrail=True)
    assert r.blocked


def test_not_blocked_by_default() -> None:
    r = _do_review(DRAFT)
    assert not r.blocked


def test_carried_lines_are_not_re_audited() -> None:
    from polisher.judge import review
    lines = claim_lines(DRAFT)
    carried = {lines[0]: 0.95}
    client = _make_client(n_lines=len(lines))
    r = review(client, original_resume=ORIGINAL, job_description="JD", draft=DRAFT, carried=carried)
    assert r.reused_lines == 1
    assert r.lines[0].support == 0.95


def test_flagged_lines_below_floor() -> None:
    from polisher.judge import review

    lines = claim_lines(DRAFT)
    answers = make_review_answers(len(lines))
    answers["line_00"] = FakeNoul(0.2)  # below floor
    client = FakeTypeSafeClient(answers)
    r = review(client, original_resume=ORIGINAL, job_description="JD", draft=DRAFT)
    assert any(line.unsupported for line in r.lines)


def test_claim_lines_filters_short() -> None:
    text = "Name\nEmail\nLed a team that built the recommendation engine and improved CTR by 15 percent."
    lines = claim_lines(text)
    assert all(len(line_text) >= 12 for line_text in lines)


def test_split_claims_single_clause() -> None:
    assert split_claims("Short line") == ("Short line",)


def test_split_claims_multiple_clauses() -> None:
    line = "Built the recommendation engine and reduced latency by 40% while cutting costs."
    claims = split_claims(line)
    assert len(claims) >= 2


def test_low_confidence_returns_dimension_names() -> None:
    from polisher.judge import DIMENSIONS, review

    lines = claim_lines(DRAFT)
    answers = make_review_answers(len(lines))
    # Set very low confidence on first dimension
    dim = next(iter(DIMENSIONS))
    answers[dim] = FakeScore(score=2.0, confidence=0.3)
    client = FakeTypeSafeClient(answers)
    r = review(client, original_resume=ORIGINAL, job_description="JD", draft=DRAFT)
    assert dim in r.low_confidence


def test_agenda_includes_biggest_gap_first() -> None:
    r = _do_review(DRAFT)
    agenda = r.agenda()
    assert len(agenda) >= 1
    assert r.biggest_gap == agenda[0]
