"""Tests for polisher.runs — persistence, failure taxonomy, manifest."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from polisher.runs import (
    FailureKind,
    ProviderError,
    load_rounds,
    new_run_id,
    run_dir,
    save_round,
    write_manifest,
)


def test_new_run_id_format() -> None:
    rid = new_run_id()
    parts = rid.split("-")
    # YYYYMMDD-HHMMSS-<hex>
    assert len(parts) == 3
    assert len(parts[0]) == 8  # date
    assert len(parts[1]) == 6  # time
    assert len(parts[2]) == 8  # short uuid


def test_run_dir_under_base(tmp_path: Path) -> None:
    d = run_dir("20260101-120000-abcd1234", base=tmp_path)
    assert d.parent == tmp_path


def test_save_and_load_round(tmp_path: Path) -> None:

    from polisher.config import Settings
    from polisher.loop import polish

    settings = Settings(
        typesafe_api_key="fake",
        typesafe_model=None,
        writer_api_key="fake",
        writer_model="fake",
        writer_base_url="https://fake.example.com",
        max_iterations=1,
        min_improvement=0.02,
        target_score=0.95,
        patience=2,
    )
    from tests.conftest import FakeOpenAIClient, FakeTypeSafeClient

    with (
        patch("polisher.loop.TypeSafeClient", return_value=FakeTypeSafeClient()),
        patch("polisher.loop.OpenAI", return_value=FakeOpenAIClient()),
    ):
        run = polish(settings, "resume text", "jd text")

    directory = tmp_path / "test-run"
    save_round(run.rounds[0], directory)
    assert (directory / "round-01.json").exists()

    loaded = load_rounds(directory)
    assert len(loaded) == 1
    assert loaded[0].number == 1
    assert loaded[0].draft.text == run.rounds[0].draft.text


def test_load_rounds_fails_on_empty_dir(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SystemExit):
        load_rounds(empty)


def test_write_manifest(tmp_path: Path) -> None:
    write_manifest(tmp_path, {"run_id": "test", "rubric_hash": "abc"})
    data = json.loads((tmp_path / "manifest.json").read_text())
    assert data["run_id"] == "test"


def test_provider_error_from_openai_auth() -> None:
    from unittest.mock import MagicMock

    from openai import AuthenticationError

    mock_resp = MagicMock()
    mock_resp.request = MagicMock()
    exc = AuthenticationError("bad key", response=mock_resp, body=None)
    err = ProviderError.from_openai(exc)
    assert err.kind == FailureKind.AUTH


def test_provider_error_from_openai_timeout() -> None:
    from unittest.mock import MagicMock

    from openai import APITimeoutError

    exc = APITimeoutError(request=MagicMock())
    err = ProviderError.from_openai(exc)
    assert err.kind == FailureKind.TIMEOUT


def test_provider_error_from_openai_rate_limit() -> None:
    from unittest.mock import MagicMock

    from openai import RateLimitError

    mock_resp = MagicMock()
    mock_resp.request = MagicMock()
    exc = RateLimitError("rate limit", response=mock_resp, body=None)
    err = ProviderError.from_openai(exc)
    assert err.kind == FailureKind.RATE_LIMIT
