"""Integration tests for cli._run_one and main entry point."""

from __future__ import annotations

import json
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


def test_main_merges_customer_rules_with_the_builtin_rulebook(tmp_path: Path, monkeypatch) -> None:
    from polisher.cli import main
    from tests.conftest import FakeOpenAIClient, FakeTypeSafeClient

    monkeypatch.setattr("polisher.runs.RUNS_DIR", tmp_path / "runs")
    resume = tmp_path / "resume.txt"
    resume.write_text("Jane Smith\nBuilt the API.")
    jd = tmp_path / "jd.txt"
    jd.write_text("Backend engineer.")
    out = tmp_path / "out.txt"
    payload_path = tmp_path / "report.json"
    rules = tmp_path / "customer-rules.toml"
    rules.write_text(
        """
[[rules]]
id = "keep-clearance"
kind = "must"
text = "Keep the clearance line when the original resume has one."
source = "user"
check = "jev"
severity = "blocking"
""".strip()
        + "\n"
    )

    with (
        patch("polisher.loop.TypeSafeClient", return_value=FakeTypeSafeClient()),
        patch("polisher.cli._TSC", create=True),
        patch("polisher.loop.OpenAI", return_value=FakeOpenAIClient()),
    ):
        main([
            str(resume),
            str(jd),
            "--out",
            str(out),
            "--report-json",
            str(payload_path),
            "--rules",
            str(rules),
            "--secrets",
            str(_write_secrets(tmp_path)),
            "--no-serve",
        ])

    payload = json.loads(payload_path.read_text())
    rule_ids = {rule["id"] for rule in payload["rules"]["items"]}
    assert "keep-clearance" in rule_ids
    assert "resume_truth_only" in rule_ids
    assert payload["manifest"]["ruleset_sources"] == ["user", "builtin"]


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


# ── The default run, and resuming one ─────────────────────────────────────────


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    resume = tmp_path / "resume.txt"
    resume.write_text("Jane Smith\nBuilt the API.")
    jd = tmp_path / "jd.txt"
    jd.write_text("Backend engineer.")
    return resume, jd, tmp_path / "out.txt"


def test_a_plain_run_writes_the_output(tmp_path: Path, monkeypatch, capsys) -> None:
    """`uv run main.py` is the command in the README, and nothing tested it.

    The `--resume` flag shared a destination with the resume-file positional, so the default
    run read its input as a run directory and exited: "no saved rounds found in
    example/resume.txt".
    """
    from polisher.cli import main
    from tests.conftest import FakeOpenAIClient, FakeTypeSafeClient

    monkeypatch.setattr("polisher.runs.RUNS_DIR", tmp_path / "runs")
    resume, jd, out = _inputs(tmp_path)

    with (
        patch("polisher.loop.TypeSafeClient", return_value=FakeTypeSafeClient()),
        patch("polisher.loop.OpenAI", return_value=FakeOpenAIClient()),
    ):
        main(
            [str(resume), str(jd), "--out", str(out), "--no-serve",
             "--secrets", str(_write_secrets(tmp_path))]
        )

    assert out.exists()
    assert "Jane Smith" in out.read_text()
    assert "no saved rounds" not in capsys.readouterr().out


def test_the_resume_flag_is_not_the_resume_file() -> None:
    from polisher.cli import build_parser

    parser = build_parser()
    assert parser.parse_args([]).run_dir is None
    assert parser.parse_args([]).resume == Path("example/resume.txt")

    both = parser.parse_args(["mine.txt", "jd.txt", "--resume", "runs/abc"])
    assert both.resume == Path("mine.txt"), "the positional is still the resume file"
    assert both.run_dir == Path("runs/abc"), "and the flag is the run directory"


def test_resume_continues_in_the_same_directory(tmp_path: Path, monkeypatch, capsys) -> None:
    """A resumed run adds to the run it came from, so one directory still holds the run."""
    from polisher.cli import main
    from tests.conftest import FakeOpenAIClient, FakeTypeSafeClient

    runs = tmp_path / "runs"
    monkeypatch.setattr("polisher.runs.RUNS_DIR", runs)
    resume, jd, out = _inputs(tmp_path)
    secrets = _write_secrets(tmp_path)
    argv = [str(resume), str(jd), "--out", str(out), "--no-serve", "--secrets", str(secrets)]

    with (
        patch("polisher.loop.TypeSafeClient", return_value=FakeTypeSafeClient()),
        patch("polisher.loop.OpenAI", return_value=FakeOpenAIClient()),
    ):
        main([*argv, "--max-iterations", "1"])

    first = next(iter(runs.iterdir()))
    assert [p.name for p in sorted(first.iterdir())] == ["manifest.json", "round-01.json"]

    with (
        patch("polisher.loop.TypeSafeClient", return_value=FakeTypeSafeClient()),
        patch("polisher.loop.OpenAI", return_value=FakeOpenAIClient()),
    ):
        main([*argv, "--max-iterations", "2", "--resume", str(first)])

    assert f"Resuming {first.name} (1 completed round)" in capsys.readouterr().out
    assert sorted(p.name for p in first.iterdir()) == [
        "manifest.json", "round-01.json", "round-02.json",
    ]
    assert list(runs.iterdir()) == [first], "no second directory for the same run"


def test_resume_without_saved_rounds_says_which_directory(tmp_path: Path, monkeypatch) -> None:
    import pytest as _pytest

    from polisher.cli import main
    from tests.conftest import FakeOpenAIClient, FakeTypeSafeClient

    monkeypatch.setattr("polisher.runs.RUNS_DIR", tmp_path / "runs")
    resume, jd, out = _inputs(tmp_path)
    empty = tmp_path / "empty-run"
    empty.mkdir()

    with (
        patch("polisher.loop.TypeSafeClient", return_value=FakeTypeSafeClient()),
        patch("polisher.loop.OpenAI", return_value=FakeOpenAIClient()),
        _pytest.raises(SystemExit, match="no saved rounds"),
    ):
        main(
            [str(resume), str(jd), "--out", str(out), "--no-serve",
             "--secrets", str(_write_secrets(tmp_path)), "--resume", str(empty)]
        )


# ── The page opens by itself ──────────────────────────────────────────────────


def _serve_run(
    tmp_path: Path,
    monkeypatch,
    extra: list[str],
    opened: list[str],
    *,
    port: str | None = "0",
) -> Path:
    """Run the tool with the page served, without opening a real browser and without blocking.

    ``port="0"`` binds a free port; ``port=None`` leaves the flag off, which is the path an
    ordinary `uv run main.py` takes and the only one that steps past a busy port.
    """
    from polisher.cli import main
    from tests.conftest import FakeOpenAIClient, FakeTypeSafeClient

    monkeypatch.setattr("polisher.runs.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("polisher.server.wait", lambda: None)
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    resume, jd, out = _inputs(tmp_path)
    argv = [str(resume), str(jd), "--out", str(out), "--secrets", str(_write_secrets(tmp_path))]
    if port is not None:
        argv += ["--port", port]
    with (
        patch("polisher.loop.TypeSafeClient", return_value=FakeTypeSafeClient()),
        patch("typesafe_sdk.TypeSafeClient", return_value=FakeTypeSafeClient()),
        patch("polisher.loop.OpenAI", return_value=FakeOpenAIClient()),
    ):
        main([*argv, *extra])
    return out


def test_the_run_opens_the_report_page(tmp_path: Path, monkeypatch) -> None:
    """Nobody reads a URL out of a terminal before the run ends; the run opens the page."""
    opened: list[str] = []
    _serve_run(tmp_path, monkeypatch, [], opened)

    assert opened, "the run did not open its page"
    assert opened[0].startswith("http://127.0.0.1:")


def _busy_port() -> int:
    """A real listening socket: the only thing that makes a port genuinely unavailable."""
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    _OPEN_SOCKETS.append(sock)  # held for the life of the process
    return sock.getsockname()[1]


_OPEN_SOCKETS: list = []


def test_a_busy_default_port_steps_to_the_next_one(tmp_path: Path, monkeypatch) -> None:
    """A previous run holds the port, because the server outlives the run.

    Refusing to serve is the wrong answer to that: the page is where a run is read.
    """
    import urllib.request

    opened: list[str] = []
    busy = _busy_port()
    monkeypatch.setattr("polisher.cli.DEFAULT_PORT", busy)
    _serve_run(tmp_path, monkeypatch, [], opened, port=None)

    assert opened, "no page came up because the default port was busy"
    served = int(opened[0].rsplit(":", 1)[1])
    assert busy < served <= busy + 10, "it should step forward, not wander"
    with urllib.request.urlopen(f"{opened[0]}/healthz", timeout=5) as response:
        assert response.status == 200


def test_an_explicit_busy_port_is_reported_and_the_run_carries_on(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """An explicitly requested port is honoured, so its failure is the run's to report."""
    opened: list[str] = []
    busy = _busy_port()
    out = _serve_run(tmp_path, monkeypatch, [], opened, port=str(busy))

    printed = capsys.readouterr().out
    assert f"unavailable on port {busy}" in printed
    assert opened == [], "there is no page to open"
    assert out.exists(), "the run still happened"


def test_no_open_serves_without_a_browser(tmp_path: Path, monkeypatch) -> None:
    opened: list[str] = []
    _serve_run(tmp_path, monkeypatch, ["--no-open"], opened)

    assert opened == []


def test_serve_report_opens_the_saved_page(tmp_path: Path, monkeypatch) -> None:
    from polisher.cli import main

    opened: list[str] = []
    monkeypatch.setattr("polisher.server.wait", lambda: None)
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)

    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps({"status": "done", "versions": [], "totals": {}}))

    main(["--serve-report", str(payload), "--port", "0"])
    assert opened and opened[0].startswith("http://127.0.0.1:")

    opened.clear()
    main(["--serve-report", str(payload), "--port", "0", "--no-open"])
    assert opened == []


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
