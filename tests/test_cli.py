"""Integration tests for cli._run_one and main entry point."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from polisher.audit import AuditLog
from polisher.config import Settings


def _settings(tmp_path: Path) -> Settings:
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


def test_run_one_writes_output(tmp_path: Path) -> None:
    from polisher.cli import _run_one
    from tests.conftest import FakeOpenAIClient, FakeTypeSafeClient

    s = _settings(tmp_path)
    out = tmp_path / "out.txt"
    audit = AuditLog(None)

    with (
        patch("polisher.loop.TypeSafeClient", return_value=FakeTypeSafeClient()),
        patch("polisher.loop.OpenAI", return_value=FakeOpenAIClient()),
    ):
        payload = _run_one(
            settings=s,
            resume="Jane Smith\nBuilt the API.",
            job_description="Backend engineer.",
            out=out,
            run_id="test-run-001",
            store=False,
            audit_log=audit,
            state=None,
            url=None,
            report_json=None,
        )

    assert payload["status"] == "done"
    assert out.exists()
    assert out.read_text().strip()


def test_run_one_no_store_skips_disk(tmp_path: Path) -> None:
    from dataclasses import replace

    from polisher.cli import _run_one
    from tests.conftest import FakeOpenAIClient, FakeTypeSafeClient

    s = replace(_settings(tmp_path), no_store=True)
    out = tmp_path / "out.txt"
    audit = AuditLog(None)

    with (
        patch("polisher.loop.TypeSafeClient", return_value=FakeTypeSafeClient()),
        patch("polisher.loop.OpenAI", return_value=FakeOpenAIClient()),
    ):
        _run_one(
            settings=s,
            resume="Jane Smith\nBuilt the API.",
            job_description="Backend engineer.",
            out=out,
            run_id="test-run-no-store",
            store=False,
            audit_log=audit,
            state=None,
            url=None,
            report_json=None,
        )

    # --no-store means nothing written
    assert not out.exists()


def test_run_one_saves_rounds_to_disk(tmp_path: Path) -> None:
    from polisher.cli import _run_one
    from tests.conftest import FakeOpenAIClient, FakeTypeSafeClient

    s = _settings(tmp_path)
    out = tmp_path / "out.txt"
    audit = AuditLog(None)
    run_id = "test-run-store"

    with (
        patch("polisher.loop.TypeSafeClient", return_value=FakeTypeSafeClient()),
        patch("polisher.loop.OpenAI", return_value=FakeOpenAIClient()),
    ):
        _run_one(
            settings=s,
            resume="Jane Smith\nBuilt the API.",
            job_description="Backend engineer.",
            out=out,
            run_id=run_id,
            store=True,
            audit_log=audit,
            state=None,
            url=None,
            report_json=None,
        )

    from polisher.runs import run_dir
    d = run_dir(run_id)
    assert (d / "round-01.json").exists()


def test_main_diff_runs(tmp_path: Path) -> None:
    import json

    from polisher.cli import main
    from polisher.config import Settings
    from polisher.report import build_manifest

    s = Settings(
        typesafe_api_key="ts", typesafe_model=None,
        writer_api_key="w", writer_model="m", writer_base_url="https://x.com",
        max_iterations=1, min_improvement=0.02, target_score=0.9, patience=2,
    )
    mf = build_manifest(s, run_id="r1")

    def _p(score: float) -> dict:
        return {
            "manifest": mf, "best_index": 1,
            "versions": [
                {"index": 0, "kind": "original"},
                {"index": 1, "kind": "round", "review": {
                    "overall": score, "quality": score, "groundedness": 1.0,
                    "scores": {k: {"score": 3.0} for k in [
                        "jd_alignment", "evidence_quality",
                        "jd_keyword_coverage", "clarity_structure", "impact_ownership",
                    ]},
                }},
            ],
        }

    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(_p(0.7)))
    b.write_text(json.dumps(_p(0.8)))

    # Should not raise
    main(["--diff-runs", str(a), str(b)])


def test_main_purge(tmp_path: Path) -> None:
    from polisher.cli import main

    d = tmp_path / "run-to-purge"
    d.mkdir()
    main(["--purge", str(d)])
    assert not d.exists()
