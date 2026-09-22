"""Tests for polisher.judge — using answer stubs, no API calls."""

from __future__ import annotations

from polisher.judge import (
    claim_lines,
    split_claims,
)
from polisher.rules import Rule, RuleBook
from tests.conftest import FakeChoice, FakeNoul, FakeScore, FakeTypeSafeClient, make_review_answers

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


# ── The live lint's question set ──────────────────────────────────────────────


def test_audit_lines_asks_only_about_the_lines_that_changed() -> None:
    """An edit to one bullet must not pay again for scores, guardrails, or the gap Choice."""
    from polisher.judge import DIMENSIONS, GUARDRAILS, audit_lines

    asked: list[set[str]] = []

    class RecordingClient(FakeTypeSafeClient):
        def system_one(self, *, state, questions, **kwargs):  # type: ignore[override]
            asked.append(set(questions))
            return super().system_one(state=state, questions=questions, **kwargs)

    client = RecordingClient(make_review_answers(0))
    audited = audit_lines(client, original_resume=ORIGINAL, draft=DRAFT)

    assert len(asked) == 1, "one request per edit, not one per line"
    keys = asked[0]
    assert keys, "the edit still has lines to ground"
    assert not keys & set(DIMENSIONS)
    assert not keys & set(GUARDRAILS)
    assert "biggest_gap" not in keys
    assert all(key.startswith(("line_", "claim_")) for key in keys)
    assert len(audited) == len(claim_lines(DRAFT))


def test_audit_lines_keeps_the_verdict_of_an_unchanged_line() -> None:
    from polisher.judge import audit_lines

    line = claim_lines(DRAFT)[0]
    client = FakeTypeSafeClient(make_review_answers(1))
    audited = audit_lines(client, original_resume=ORIGINAL, draft=DRAFT, carried={line: 0.31})
    assert audited[0].support == 0.31
    assert audited[0].claims == ()


def test_a_fabricated_claim_inside_a_true_bullet_weakens_the_line() -> None:
    """The line verdict is its weakest claim: one invented clause is not a true bullet."""
    from polisher.judge import audit_lines

    line = "Led the platform team at Acme Corp and cut incidents by 90%"
    answers = make_review_answers(0)
    answers["line_00"] = FakeNoul(0.95)  # the line as a whole looks fine
    answers["claim_00_00"] = FakeNoul(0.95)  # "Led the platform team at Acme Corp"
    answers["claim_00_01"] = FakeNoul(0.10)  # "and cut incidents by 90%"
    client = FakeTypeSafeClient(answers)

    audited = audit_lines(client, original_resume=ORIGINAL, draft=line)
    assert len(claim_lines(line)) == 1
    assert audited[0].support == 0.10
    assert audited[0].failing_claim is not None
    assert "90%" in audited[0].failing_claim


# ── Unanswered requirements reach the writer ──────────────────────────────────

JD = "We need a backend engineer with distributed systems experience."


def test_feedback_names_the_requirements_the_draft_does_not_answer() -> None:
    """The coverage verdict is only useful if the next round is told about it."""
    from polisher.judge import review

    client = FakeTypeSafeClient(make_review_answers(len(claim_lines(DRAFT))))
    r = review(client, original_resume=ORIGINAL, job_description=JD, draft=DRAFT)

    assert r.coverage == {JD: None}, "the stub answers every coverage question with 'none'"
    feedback = r.feedback()
    assert "REQUIREMENTS WITH NO EVIDENCE IN THIS DRAFT" in feedback
    assert JD in feedback
    assert "do not invent" in feedback


def test_feedback_stays_quiet_when_every_requirement_is_answered() -> None:
    from polisher.judge import review

    answers = make_review_answers(len(claim_lines(DRAFT)))
    answers["cov_00"] = FakeChoice(choice="0")
    client = FakeTypeSafeClient(answers)
    r = review(client, original_resume=ORIGINAL, job_description=JD, draft=DRAFT)

    assert "REQUIREMENTS WITH NO EVIDENCE" not in r.feedback()


def test_jev_rules_are_batched_into_the_same_review_request() -> None:
    from polisher.judge import review

    asked: list[set[str]] = []

    class RecordingClient(FakeTypeSafeClient):
        def system_one(self, *, state, questions, **kwargs):  # type: ignore[override]
            asked.append(set(questions))
            return super().system_one(state=state, questions=questions, **kwargs)

    rules = RuleBook(
        rules=(
            Rule(
                id="taste-one",
                kind="prefer",
                text="Lead with the migration work.",
                source="user",
                check="jev",
                severity="advisory",
            ),
            Rule(
                id="taste-two",
                kind="prefer",
                text="Do not sound boastful.",
                source="user",
                check="jev",
                severity="advisory",
            ),
            Rule(
                id="taste-three",
                kind="must",
                text="Headline matches the posting's seniority label.",
                source="job",
                check="jev",
                severity="blocking",
            ),
        )
    )
    client = RecordingClient(make_review_answers(len(claim_lines(DRAFT))))
    review(
        client,
        original_resume=ORIGINAL,
        job_description="JD",
        draft=DRAFT,
        rulebook=rules,
    )

    assert len(asked) == 1
    assert {"rule_taste-one", "rule_taste-two", "rule_taste-three"} <= asked[0]


def test_jev_rule_results_reach_the_review() -> None:
    from polisher.judge import review

    rules = RuleBook(
        rules=(
            Rule(
                id="no-summary",
                kind="must_not",
                text="Do not add a summary section.",
                source="user",
                check="jev",
                severity="blocking",
            ),
        )
    )
    answers = make_review_answers(len(claim_lines(DRAFT)))
    answers["rule_no-summary"] = FakeNoul(0.9)
    client = FakeTypeSafeClient(answers)

    r = review(client, original_resume=ORIGINAL, job_description="JD", draft=DRAFT, rulebook=rules)

    assert len(r.rules) == 1
    assert r.blocking_violations[0].rule_id == "no-summary"
    assert "BLOCKING RULE VIOLATIONS" in r.feedback()


def test_split_requirements_skips_about_us_boilerplate() -> None:
    from polisher.judge import split_requirements

    jd = """
ABOUT US
We are a fast-growing company building logistics tools for the future.

RESPONSIBILITIES
- Build backend services in Python.
- Improve distributed systems reliability.
""".strip()

    reqs = split_requirements(jd)

    assert all("fast-growing company" not in req for req in reqs)
    assert "Build backend services in Python." in reqs
