"""Tests for polisher.report."""

from __future__ import annotations

from unittest.mock import patch

from polisher.config import Settings
from polisher.loop import polish
from polisher.report import build_manifest, build_report
from tests.conftest import FakeOpenAIClient, FakeTypeSafeClient

RESUME = "Jane Smith\nBuilt the API."
JD = "Backend engineer role."


def _settings() -> Settings:
    return Settings(
        typesafe_api_key="fake",
        typesafe_model=None,
        writer_api_key="fake",
        writer_model="fake-model",
        writer_base_url="https://fake.example.com",
        max_iterations=1,
        min_improvement=0.02,
        target_score=0.95,
        patience=2,
    )


def _one_round_run():
    s = _settings()
    with (
        patch("polisher.loop.TypeSafeClient", return_value=FakeTypeSafeClient()),
        patch("polisher.loop.OpenAI", return_value=FakeOpenAIClient()),
    ):
        return polish(s, RESUME, JD), s


def test_build_report_has_required_keys() -> None:
    run, s = _one_round_run()
    payload = build_report(
        settings=s,
        resume=RESUME,
        job_description=JD,
        paths={"resume": "r.txt", "job_description": "jd.txt", "out": "out.txt"},
        rounds=run.rounds,
        best=run.best,
        stop_reason=run.stop_reason,
        status="done",
    )
    for key in ("status", "stop_reason", "versions", "totals", "config", "manifest"):
        assert key in payload, f"missing key: {key}"


def test_first_version_is_original() -> None:
    run, s = _one_round_run()
    payload = build_report(
        settings=s, resume=RESUME, job_description=JD,
        paths={}, rounds=run.rounds, best=run.best,
        stop_reason=run.stop_reason, status="done",
    )
    assert payload["versions"][0]["kind"] == "original"
    assert payload["versions"][0]["text"] == RESUME


def test_round_versions_have_review() -> None:
    run, s = _one_round_run()
    payload = build_report(
        settings=s, resume=RESUME, job_description=JD,
        paths={}, rounds=run.rounds, best=run.best,
        stop_reason=run.stop_reason, status="done",
    )
    for v in payload["versions"][1:]:
        assert v["review"] is not None


def test_totals_match_rounds() -> None:
    run, s = _one_round_run()
    payload = build_report(
        settings=s, resume=RESUME, job_description=JD,
        paths={}, rounds=run.rounds, best=run.best,
        stop_reason=run.stop_reason, status="done",
    )
    assert payload["totals"]["writer_calls"] == len(run.rounds)


def test_manifest_contains_rubric_hash() -> None:
    s = _settings()
    manifest = build_manifest(s, run_id="test-run-001")
    assert "rubric_hash" in manifest
    assert len(manifest["rubric_hash"]) == 16
    assert manifest["run_id"] == "test-run-001"


def test_manifest_rubric_hash_is_stable() -> None:
    s = _settings()
    h1 = build_manifest(s)["rubric_hash"]
    h2 = build_manifest(s)["rubric_hash"]
    assert h1 == h2


def test_run_id_in_payload() -> None:
    run, s = _one_round_run()
    payload = build_report(
        settings=s, resume=RESUME, job_description=JD,
        paths={}, rounds=run.rounds, best=run.best,
        stop_reason=run.stop_reason, status="done",
        run_id="my-run-123",
    )
    assert payload["manifest"]["run_id"] == "my-run-123"


def test_ledger_and_trust_come_from_the_same_audit() -> None:
    """The page shows the distribution the run paid for, so the numbers must agree."""
    from polisher import judge

    run, s = _one_round_run()
    payload = build_report(
        settings=s, resume=RESUME, job_description=JD,
        paths={}, rounds=run.rounds, best=run.best,
        stop_reason=run.stop_reason, status="done",
    )
    review = payload["versions"][1]["review"]
    assert review["ledger"], "the ledger is what the page shows instead of a lone mean"
    assert review["trust"]["audited"] == len(review["ledger"])
    assert review["trust"]["unsupported"] == len(review["flagged_lines"])
    assert payload["config"]["line_review_floor"] == judge.LINE_REVIEW_FLOOR


def test_every_ledger_line_carries_its_claims() -> None:
    run, s = _one_round_run()
    payload = build_report(
        settings=s, resume=RESUME, job_description=JD,
        paths={}, rounds=run.rounds, best=run.best,
        stop_reason=run.stop_reason, status="done",
    )
    for entry in payload["versions"][1]["review"]["ledger"]:
        assert entry["claims"], "a line with no claim breakdown hides where the risk is"
        assert all(0.0 <= claim["support"] <= 1.0 for claim in entry["claims"])
