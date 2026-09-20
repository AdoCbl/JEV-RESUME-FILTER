"""Tests for polisher.console."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

from polisher.config import Settings


def _settings() -> Settings:
    return Settings(
        typesafe_api_key="fake",
        typesafe_model=None,
        writer_api_key="fake",
        writer_model="deepseek-chat",
        writer_base_url="https://api.deepseek.com",
        max_iterations=5,
        min_improvement=0.02,
        target_score=0.90,
        patience=2,
    )


def _capture(fn, *args, **kwargs) -> str:
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        fn(*args, **kwargs)
    return buf.getvalue()


def test_print_header_contains_model(tmp_path: Path) -> None:
    from polisher import console

    out = _capture(
        console.print_header,
        settings=_settings(),
        resume_path=Path("resume.txt"),
        job_path=Path("jd.txt"),
        resume="some resume text",
        job_description="some job description",
    )
    assert "deepseek-chat" in out


def test_print_server_contains_url() -> None:
    from polisher import console

    out = _capture(console.print_server, "http://127.0.0.1:8765")
    assert "http://127.0.0.1:8765" in out


def test_print_server_unavailable_mentions_port() -> None:
    from polisher import console

    out = _capture(console.print_server_unavailable, 8765, "address already in use")
    assert "8765" in out


def test_print_result_shows_rounds(tmp_path: Path) -> None:
    from unittest.mock import patch

    from polisher import console
    from polisher.loop import polish
    from tests.conftest import FakeOpenAIClient, FakeTypeSafeClient

    s = _settings()
    with (
        patch("polisher.loop.TypeSafeClient", return_value=FakeTypeSafeClient()),
        patch("polisher.loop.OpenAI", return_value=FakeOpenAIClient()),
    ):
        from polisher.report import build_report

        run = polish(s, "resume text", "jd text")
        payload = build_report(
            settings=s,
            resume="resume text",
            job_description="jd text",
            paths={"resume": "r.txt", "job_description": "jd.txt", "out": "out.txt"},
            rounds=run.rounds,
            best=run.best,
            stop_reason=run.stop_reason,
            status="done",
        )

    out = _capture(console.print_result, payload)
    assert "Rounds run:" in out
    assert "Stopped:" in out


def test_print_round_shows_round_number() -> None:
    from unittest.mock import patch

    from polisher import console
    from polisher.loop import polish
    from tests.conftest import FakeOpenAIClient, FakeTypeSafeClient

    s = _settings()
    with (
        patch("polisher.loop.TypeSafeClient", return_value=FakeTypeSafeClient()),
        patch("polisher.loop.OpenAI", return_value=FakeOpenAIClient()),
    ):
        run = polish(s, "resume text", "jd text")

    out = _capture(console.print_round, run.rounds[0], s)
    assert "Round 1" in out
