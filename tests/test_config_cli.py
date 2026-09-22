"""Tests for polisher.config and polisher.cli (non-network parts)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from polisher.config import Settings, load_settings, read_input
from polisher.rules import Rule, RuleBook

# ── config tests ──────────────────────────────────────────────────────────────


def test_load_settings_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        load_settings(tmp_path / "nonexistent.toml")


def test_load_settings_missing_typesafe_key(tmp_path: Path) -> None:
    cfg = tmp_path / "s.toml"
    cfg.write_text("[typesafe]\napi_key = ''\n[writer]\napi_key = 'x'\n")
    with pytest.raises(SystemExit):
        load_settings(cfg)


def test_load_settings_missing_writer_section(tmp_path: Path) -> None:
    cfg = tmp_path / "s.toml"
    cfg.write_text("[typesafe]\napi_key = 'x'\n")
    with pytest.raises(SystemExit):
        load_settings(cfg)


def test_load_settings_backward_compat_deepseek(tmp_path: Path) -> None:
    cfg = tmp_path / "s.toml"
    cfg.write_text("[typesafe]\napi_key = 'ts'\n[deepseek]\napi_key = 'ds'\n")
    s = load_settings(cfg)
    assert s.writer_api_key == "ds"


def test_load_settings_writer_section(tmp_path: Path) -> None:
    cfg = tmp_path / "s.toml"
    cfg.write_text(
        "[typesafe]\napi_key = 'ts'\n"
        "[writer]\napi_key = 'wk'\nmodel = 'gpt-4o'\nbase_url = 'https://api.openai.com/v1'\n"
    )
    s = load_settings(cfg)
    assert s.writer_api_key == "wk"
    assert s.writer_model == "gpt-4o"
    assert s.writer_base_url == "https://api.openai.com/v1"


def test_load_settings_polish_overrides(tmp_path: Path) -> None:
    cfg = tmp_path / "s.toml"
    cfg.write_text(
        "[typesafe]\napi_key = 'ts'\n[writer]\napi_key = 'wk'\n"
        "[polish]\nmax_iterations = 3\ntarget_score = 0.85\n"
    )
    s = load_settings(cfg)
    assert s.max_iterations == 3
    assert s.target_score == 0.85


def test_read_input_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        read_input(tmp_path / "missing.txt")


def test_read_input_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.txt"
    p.write_text("   \n")
    with pytest.raises(SystemExit):
        read_input(p)


def test_read_input_returns_stripped(tmp_path: Path) -> None:
    p = tmp_path / "resume.txt"
    p.write_text("  hello world  \n")
    assert read_input(p) == "hello world"


def test_settings_typesafe_client_kwargs() -> None:
    s = Settings(
        typesafe_api_key="ts-key",
        typesafe_model="jev-latest",
        writer_api_key="w",
        writer_model="m",
        writer_base_url="https://x.com",
        max_iterations=5,
        min_improvement=0.02,
        target_score=0.9,
        patience=2,
    )
    kwargs = s.typesafe_client_kwargs()
    assert kwargs["api_key"] == "ts-key"
    assert kwargs["model"] == "jev-latest"


def test_settings_typesafe_kwargs_no_model() -> None:
    s = Settings(
        typesafe_api_key="ts",
        typesafe_model=None,
        writer_api_key="w",
        writer_model="m",
        writer_base_url="https://x.com",
        max_iterations=5,
        min_improvement=0.02,
        target_score=0.9,
        patience=2,
    )
    kwargs = s.typesafe_client_kwargs()
    assert "model" not in kwargs


# ── cli tests (non-network parts) ────────────────────────────────────────────


def test_build_parser_defaults() -> None:
    from polisher.cli import build_parser

    parser = build_parser()
    args = parser.parse_args([])
    assert args.max_iterations is None
    assert args.serve is True
    assert args.redact is False
    assert args.no_store is False


def test_build_parser_flags() -> None:
    from polisher.cli import build_parser

    parser = build_parser()
    args = parser.parse_args([
        "--max-iterations", "3",
        "--max-tokens", "50000",
        "--max-seconds", "120",
        "--redact",
        "--no-store",
        "--no-serve",
        "--log-json",
    ])
    assert args.max_iterations == 3
    assert args.max_tokens == 50000
    assert args.max_seconds == 120.0
    assert args.redact is True
    assert args.no_store is True
    assert args.serve is False
    assert args.log_json is True


def test_diff_runs_matching_rubrics(tmp_path: Path) -> None:
    import io

    from polisher.cli import diff_runs
    from polisher.config import Settings
    from polisher.report import build_manifest

    s = Settings(
        typesafe_api_key="ts", typesafe_model=None,
        writer_api_key="w", writer_model="m", writer_base_url="https://x.com",
        max_iterations=1, min_improvement=0.02, target_score=0.9, patience=2,
    )
    mf = build_manifest(s, run_id="r1")

    def _make_payload(overall: float, name: str) -> dict:
        return {
            "manifest": mf,
            "best_index": 1,
            "versions": [
                {"index": 0, "kind": "original"},
                {
                    "index": 1,
                    "kind": "round",
                    "review": {
                        "overall": overall,
                        "quality": overall,
                        "groundedness": 1.0,
                        "scores": {
                            "jd_alignment": {"score": 3.0},
                            "evidence_quality": {"score": 3.0},
                            "jd_keyword_coverage": {"score": 3.0},
                            "clarity_structure": {"score": 3.0},
                            "impact_ownership": {"score": 3.0},
                        },
                    },
                },
            ],
        }

    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(_make_payload(0.75, "a")))
    b.write_text(json.dumps(_make_payload(0.85, "b")))

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        diff_runs(a, b)
    assert "overall" in buf.getvalue().lower() or "Diff" in buf.getvalue()


def test_diff_runs_warns_on_ruleset_change(tmp_path: Path) -> None:
    import io

    from polisher.cli import diff_runs
    from polisher.report import build_manifest

    s = Settings(
        typesafe_api_key="ts", typesafe_model=None,
        writer_api_key="w", writer_model="m", writer_base_url="https://x.com",
        max_iterations=1, min_improvement=0.02, target_score=0.9, patience=2,
    )
    rulebook_a = RuleBook(
        rules=(
            Rule(
                id="keep-clearance",
                kind="must",
                text="Keep the clearance line.",
                source="user",
                check="code",
                severity="blocking",
            ),
        )
    )
    rulebook_b = RuleBook(
        rules=(
            Rule(
                id="no-summary",
                kind="must_not",
                text="Do not add a summary section.",
                source="user",
                check="code",
                severity="blocking",
            ),
        )
    )

    def _make_payload(manifest: dict) -> dict:
        return {
            "manifest": manifest,
            "best_index": 1,
            "versions": [
                {"index": 0, "kind": "original"},
                {
                    "index": 1,
                    "kind": "round",
                    "review": {
                        "overall": 0.75,
                        "quality": 0.75,
                        "groundedness": 1.0,
                        "scores": {
                            "jd_alignment": {"score": 3.0},
                            "evidence_quality": {"score": 3.0},
                            "jd_keyword_coverage": {"score": 3.0},
                            "clarity_structure": {"score": 3.0},
                            "impact_ownership": {"score": 3.0},
                        },
                    },
                },
            ],
        }

    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(_make_payload(build_manifest(s, rulebook=rulebook_a))))
    b.write_text(json.dumps(_make_payload(build_manifest(s, rulebook=rulebook_b))))

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        diff_runs(a, b)

    assert "ruleset hashes differ" in buf.getvalue().lower()


def test_purge_run_deletes_directory(tmp_path: Path) -> None:
    from polisher.cli import purge_run

    d = tmp_path / "test-run"
    d.mkdir()
    (d / "round-01.json").write_text("{}")
    purge_run(d)
    assert not d.exists()


def test_purge_run_missing_directory(tmp_path: Path) -> None:
    from polisher.cli import purge_run

    with pytest.raises(SystemExit):
        purge_run(tmp_path / "nonexistent")
