"""Tests for polisher.loop — using answer and writer stubs, no API calls."""

from __future__ import annotations

from unittest.mock import patch

from polisher.config import Settings
from polisher.loop import PolisherRun, attempt_history, polish, rejected_phrasings
from tests.conftest import FakeOpenAIClient, FakeTypeSafeClient

RESUME = "Jane Smith\nSoftware Engineer\n\nBuilt the billing service at Acme."
JD = "We need a backend engineer with billing system experience."


def _settings(**overrides) -> Settings:
    base = dict(
        typesafe_api_key="fake",
        typesafe_model=None,
        writer_api_key="fake",
        writer_model="fake-model",
        writer_base_url="https://fake.example.com",
        max_iterations=2,
        min_improvement=0.02,
        target_score=0.95,
        patience=2,
    )
    base.update(overrides)
    return Settings(**base)


def _run(settings=None, draft_text: str = RESUME) -> PolisherRun:
    s = settings or _settings()
    fake_reviewer = FakeTypeSafeClient()
    fake_writer = FakeOpenAIClient(text=draft_text)
    with (
        patch("polisher.loop.TypeSafeClient", return_value=fake_reviewer),
        patch("polisher.loop.OpenAI", return_value=fake_writer),
    ):
        return polish(s, RESUME, JD)


def test_loop_runs_at_least_one_round() -> None:
    result = _run()
    assert len(result.rounds) >= 1
    assert result.best is not None


def test_loop_respects_max_iterations() -> None:
    result = _run(_settings(max_iterations=1))
    assert len(result.rounds) == 1


def test_stop_reason_is_set() -> None:
    result = _run()
    assert result.stop_reason


def test_on_round_callback_called() -> None:
    calls: list[int] = []

    def cb(current, best, rounds):
        calls.append(current.number)

    s = _settings(max_iterations=2)
    fake_reviewer = FakeTypeSafeClient()
    fake_writer = FakeOpenAIClient()
    with (
        patch("polisher.loop.TypeSafeClient", return_value=fake_reviewer),
        patch("polisher.loop.OpenAI", return_value=fake_writer),
    ):
        polish(s, RESUME, JD, on_round=cb)

    assert len(calls) == 2


def test_unchanged_draft_not_re_reviewed() -> None:
    result = _run()
    # If the writer returns the same text every round, reviewed=False after round 1
    for r in result.rounds[1:]:
        assert not r.reviewed


def test_attempt_history_none_on_empty() -> None:
    assert attempt_history([]) is None


def test_attempt_history_contains_scores() -> None:
    result = _run()
    hist = attempt_history(result.rounds)
    assert hist is not None
    assert "round 1" in hist


def test_rejected_phrasings_none_when_best_wins_all() -> None:
    result = _run()
    # All rounds are the same draft, so best == every round
    assert rejected_phrasings(result.rounds, result.best) is None


def test_budget_seconds_stops_loop() -> None:
    s = _settings(max_iterations=10, max_seconds=0.0001)
    fake_reviewer = FakeTypeSafeClient()
    fake_writer = FakeOpenAIClient()
    with (
        patch("polisher.loop.TypeSafeClient", return_value=fake_reviewer),
        patch("polisher.loop.OpenAI", return_value=fake_writer),
    ):
        result = polish(s, RESUME, JD)
    # With near-zero budget only 1 round can complete before the check fires
    assert len(result.rounds) <= 2


def test_resume_from_prior_rounds() -> None:
    first = _run(_settings(max_iterations=1))
    s = _settings(max_iterations=2)
    fake_reviewer = FakeTypeSafeClient()
    fake_writer = FakeOpenAIClient()
    with (
        patch("polisher.loop.TypeSafeClient", return_value=fake_reviewer),
        patch("polisher.loop.OpenAI", return_value=fake_writer),
    ):
        result = polish(s, RESUME, JD, prior_rounds=list(first.rounds))
    assert result.rounds[0].number == 1
    assert len(result.rounds) <= 2


# ── Steering: a person's rejection reaches the writer ────────────────────────

REJECTED = "Architected a platform serving 10M users"


def test_a_human_rejection_is_handed_to_the_writer_every_round() -> None:
    """A phrasing a person refused must not be able to come back in a later round."""
    import polisher.loop as loop

    seen: list[str | None] = []
    real_write = loop.write_draft

    def spy(writer, **kwargs):
        seen.append(kwargs.get("rejected"))
        return real_write(writer, **kwargs)

    s = _settings(max_iterations=3)
    with (
        patch.object(loop, "write_draft", spy),
        patch("polisher.loop.TypeSafeClient", return_value=FakeTypeSafeClient()),
        patch("polisher.loop.OpenAI", return_value=FakeOpenAIClient()),
    ):
        loop.polish(
            s,
            RESUME,
            JD,
            human_rejections=lambda: [REJECTED],
            reviewer=FakeTypeSafeClient(),
        )

    assert len(seen) >= 2, "the loop must have written more than one round"
    for block in seen:
        assert block is not None
        assert REJECTED in block
        assert "rejected by a human" in block


def test_human_rejections_lead_the_rejected_phrasings_block() -> None:
    """A person's refusal outranks JEV's, and a line rejected by both is listed once."""

    class _Line:
        def __init__(self, text: str) -> None:
            self.text = text

    class _Review:
        def __init__(self, lines, overall: float = 0.1) -> None:
            self._lines = lines
            self.overall = overall

        def lines_to_review(self):
            return tuple(self._lines)

    class _Round:
        def __init__(self, number: int, review) -> None:
            self.number = number
            self.review = review

    losing = _Round(1, _Review([_Line("JEV flagged this"), _Line(REJECTED)]))
    best = _Round(2, _Review([], overall=0.9))

    block = rejected_phrasings([losing, best], best, extra=[REJECTED])
    assert block is not None
    bullets = [line.strip() for line in block.splitlines() if line.strip().startswith("- ")]
    assert bullets[0] == f"- {REJECTED}", "the human rejection leads"
    assert bullets.count(f"- {REJECTED}") == 1, "and is not repeated as a JEV line"
    assert "- JEV flagged this" in bullets
    assert "rejected by a human" in block
