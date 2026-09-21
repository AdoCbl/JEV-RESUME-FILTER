"""Integration tests for cli._run_one and main entry point."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

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
            state=None,
            url=None,
            report_json=None,
        )

    # --no-store means nothing written
    assert not out.exists()


def test_run_one_saves_rounds_to_disk(tmp_path: Path, monkeypatch) -> None:
    from polisher.cli import _run_one
    from tests.conftest import FakeOpenAIClient, FakeTypeSafeClient

    monkeypatch.setattr("polisher.runs.RUNS_DIR", tmp_path / "runs")
    s = _settings(tmp_path)
    out = tmp_path / "out.txt"
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


def _write_secrets(tmp_path: Path) -> Path:
    path = tmp_path / "secrets.toml"
    path.write_text('[typesafe]\napi_key = "fake"\n\n[writer]\napi_key = "fake"\n')
    return path


def test_run_batch_continues_after_a_missing_input(tmp_path: Path, monkeypatch) -> None:
    """One broken pair must not abort the batch, and the exit code counts the failures."""
    from polisher.cli import main
    from tests.conftest import FakeOpenAIClient, FakeTypeSafeClient

    monkeypatch.setattr("polisher.runs.RUNS_DIR", tmp_path / "runs")
    resume = tmp_path / "resume.txt"
    resume.write_text("Jane Smith\nBuilt the API.")
    jd = tmp_path / "jd.txt"
    jd.write_text("Backend engineer.")
    good_a, good_b, missing = tmp_path / "a.txt", tmp_path / "b.txt", tmp_path / "nope.txt"
    pairs = tmp_path / "pairs.csv"
    pairs.write_text(
        "resume,job_description,out\n"
        f"{resume},{jd},{good_a}\n"
        f"{missing},{jd},{missing.with_name('bad.txt')}\n"
        f"{resume},{jd},{good_b}\n"
    )

    with (
        patch("polisher.loop.TypeSafeClient", return_value=FakeTypeSafeClient()),
        patch("polisher.loop.OpenAI", return_value=FakeOpenAIClient()),
        pytest.raises(SystemExit) as exit_info,
    ):
        main(["--batch", str(pairs), "--secrets", str(_write_secrets(tmp_path))])

    assert exit_info.value.code == 1  # exactly one pair failed
    assert good_a.exists()
    assert good_b.exists()


def test_a_batch_pair_writes_the_payload_its_index_links_to(tmp_path: Path, monkeypatch) -> None:
    """An index of dead links is not a report, so every row must have written its payload."""
    import json

    from polisher.cli import main
    from tests.conftest import FakeOpenAIClient, FakeTypeSafeClient

    monkeypatch.setattr("polisher.runs.RUNS_DIR", tmp_path / "runs")
    resume = tmp_path / "resume.txt"
    resume.write_text("Jane Smith\nBuilt the API.")
    jd = tmp_path / "jd.txt"
    jd.write_text("Backend engineer.")
    out = tmp_path / "jane.txt"
    pairs = tmp_path / "pairs.csv"
    pairs.write_text("resume,job_description,out\n" f"{resume},{jd},{out}\n")

    with (
        patch("polisher.loop.TypeSafeClient", return_value=FakeTypeSafeClient()),
        patch("polisher.loop.OpenAI", return_value=FakeOpenAIClient()),
    ):
        main(["--batch", str(pairs), "--secrets", str(_write_secrets(tmp_path))])

    payload_path = tmp_path / "jane_report.json"
    assert payload_path.exists(), "the index links to this file"
    payload = json.loads(payload_path.read_text())
    assert payload["versions"], "a payload the page can render"

    index = (tmp_path / "pairs.index.html").read_text()
    assert str(payload_path) in index
    assert "serve-report" in index


def test_main_purge(tmp_path: Path) -> None:
    from polisher.cli import main

    d = tmp_path / "run-to-purge"
    d.mkdir()
    main(["--purge", str(d)])
    assert not d.exists()


# ── Packaging ─────────────────────────────────────────────────────────────────


def test_the_console_script_is_actually_packaged() -> None:
    """`[project.scripts]` without a build system is skipped by uv, with only a warning.

    That warning was easy to miss, and the README and the batch index both tell a person to
    run `resume-polisher`. Assert the declaration and the build configuration together, since
    the failure is the combination rather than either half.
    """
    import tomllib

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())

    assert data["project"]["scripts"]["resume-polisher"] == "polisher.cli:main"
    assert "build-system" in data, (
        "without a build system the project is virtual and uv skips the entry point"
    )
    backend = data["tool"]["uv"]["build-backend"]
    assert backend["module-name"] == "polisher", "the module is not named after the dist"
    assert backend["module-root"] == "", "the module is at the repository root, not under src/"
