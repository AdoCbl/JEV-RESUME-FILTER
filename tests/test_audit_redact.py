"""Tests for polisher.audit and polisher.redact."""

from __future__ import annotations

from pathlib import Path

from polisher.audit import AuditLog, write_unresolved
from polisher.redact import redact

# ── redact tests ─────────────────────────────────────────────────────────────


def test_redact_removes_email() -> None:
    assert "[EMAIL]" in redact("Contact: alice@example.com")
    assert "alice@example.com" not in redact("alice@example.com")


def test_redact_removes_phone() -> None:
    assert "[PHONE]" in redact("Call me at 555-123-4567")


def test_redact_removes_url() -> None:
    assert "[URL]" in redact("See https://github.com/user/repo for code")


def test_redact_removes_linkedin() -> None:
    result = redact("linkedin.com/in/janedoe")
    assert "janedoe" not in result


def test_redact_leaves_non_pii_intact() -> None:
    text = "Built the billing service and reduced latency by 40%."
    assert redact(text) == text


def test_redact_empty_string() -> None:
    assert redact("") == ""


def test_redact_multiple_patterns() -> None:
    text = "alice@example.com  555-123-4567  https://example.com"
    result = redact(text)
    assert "[EMAIL]" in result
    assert "[PHONE]" in result
    assert "[URL]" in result


# ── audit tests ───────────────────────────────────────────────────────────────


def test_audit_log_writes_jsonl(tmp_path: Path) -> None:

    log_path = tmp_path / "audit.jsonl"
    log = AuditLog(log_path)
    log.record(run_id="run-001", line="Led the team", verdict="approved")
    log.record(run_id="run-001", line="Invented claim", verdict="rejected")

    entries = log.read_all()
    assert len(entries) == 2
    assert entries[0]["verdict"] == "approved"
    assert entries[1]["verdict"] == "rejected"
    assert entries[0]["line"] == "Led the team"


def test_audit_log_none_path_is_noop() -> None:
    log = AuditLog(None)
    log.record(run_id="r", line="x", verdict="approved")
    assert log.read_all() == []


def test_audit_log_is_append_only(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    log = AuditLog(log_path)
    log.record(run_id="r", line="first", verdict="approved")
    log.record(run_id="r", line="second", verdict="rejected")
    entries = log.read_all()
    assert len(entries) == 2


def test_write_unresolved(tmp_path: Path) -> None:
    out = tmp_path / "resume.txt"
    path = write_unresolved(out, ["Invented claim", "Inflated scope"])
    assert path.name == "UNRESOLVED.md"
    text = path.read_text()
    assert "Invented claim" in text
    assert "Inflated scope" in text


def test_write_unresolved_empty_list(tmp_path: Path) -> None:
    out = tmp_path / "resume.txt"
    path = write_unresolved(out, [])
    assert path.exists()
