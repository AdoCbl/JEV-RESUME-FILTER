"""Tests for polisher.server — no network, no API keys."""

from __future__ import annotations

import json
from http.client import HTTPConnection
from pathlib import Path

import pytest

from polisher.server import ReportState, start, url

SAMPLE_REPORT = {
    "status": "done",
    "best_index": 1,
    "versions": [
        {"index": 0, "kind": "original", "text": "Original"},
        {"index": 1, "kind": "round", "text": "Polished\nresume", "review": {"flagged_lines": []}},
    ],
    "totals": {},
    "config": {},
    "manifest": {},
}


@pytest.fixture
def state(tmp_path: Path) -> ReportState:
    out = tmp_path / "out.txt"
    s = ReportState(output_path=out)
    s.set_report(SAMPLE_REPORT)
    return s


@pytest.fixture
def running_server(state: ReportState):
    httpd = start(state, host="127.0.0.1", port=0)
    yield httpd, state
    httpd.shutdown()


def _get(httpd, path: str) -> tuple[int, bytes]:
    conn = HTTPConnection("127.0.0.1", httpd.server_port)
    conn.request("GET", path)
    resp = conn.getresponse()
    return resp.status, resp.read()


def _post(httpd, path: str, body: dict, csrf: str = "") -> tuple[int, dict]:
    data = json.dumps(body).encode()
    conn = HTTPConnection("127.0.0.1", httpd.server_port)
    conn.request("POST", path, data, {"content-type": "application/json", "X-Csrf-Token": csrf})
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read())


def test_get_root_returns_html(running_server) -> None:
    httpd, _ = running_server
    status, body = _get(httpd, "/")
    assert status == 200
    assert b"<!doctype html>" in body.lower()


def test_get_api_report(running_server) -> None:
    httpd, _ = running_server
    status, body = _get(httpd, "/api/report")
    assert status == 200
    data = json.loads(body)
    assert data["status"] == "done"


def test_get_healthz(running_server) -> None:
    httpd, _ = running_server
    status, body = _get(httpd, "/healthz")
    assert status == 200
    assert json.loads(body)["status"] == "ok"


def test_get_unknown_route_404(running_server) -> None:
    httpd, _ = running_server
    status, _ = _get(httpd, "/nope")
    assert status == 404


def test_post_save_requires_csrf(running_server) -> None:
    httpd, _ = running_server
    status, body = _post(httpd, "/api/save", {"index": 1})
    assert status == 403


def test_post_save_with_valid_csrf(running_server) -> None:
    httpd, state = running_server
    status, body = _post(httpd, "/api/save", {"index": 1}, csrf=state.csrf_token)
    assert status == 200
    assert state.saved_index == 1


def test_post_save_original_rejected(running_server) -> None:
    httpd, state = running_server
    status, body = _post(httpd, "/api/save", {"index": 0}, csrf=state.csrf_token)
    assert status == 400


def test_post_review_approve(running_server) -> None:
    httpd, state = running_server
    status, body = _post(
        httpd, "/api/review",
        {"line": "Polished resume", "verdict": "approved"},
        csrf=state.csrf_token,
    )
    assert status == 200
    assert state.decisions()["Polished resume"] == "approved"


def test_post_review_reject(running_server) -> None:
    httpd, state = running_server
    status, body = _post(
        httpd, "/api/review",
        {"line": "Invented claim", "verdict": "rejected"},
        csrf=state.csrf_token,
    )
    assert status == 200
    assert state.decisions()["Invented claim"] == "rejected"


def test_post_review_invalid_verdict(running_server) -> None:
    httpd, state = running_server
    status, body = _post(
        httpd, "/api/review",
        {"line": "x", "verdict": "maybe"},
        csrf=state.csrf_token,
    )
    assert status == 400


def test_url_helper_resolves_wildcard() -> None:
    class FakeHTTPD:
        server_port = 9999

    assert "127.0.0.1:9999" in url(FakeHTTPD(), "0.0.0.0")


def test_save_version_writes_file(state: ReportState, tmp_path: Path) -> None:
    state.save_version(1)
    assert state.output_path.read_text().strip() == "Polished\nresume"


# ── Human sign-off state ─────────────────────────────────────────────────────

FLAGGED = "Architected a platform serving 10M users"


def _report_with_a_flagged_line() -> dict:
    return {
        "status": "done",
        "best_index": 1,
        "versions": [
            {"index": 0, "kind": "original", "text": "Original"},
            {
                "index": 1,
                "kind": "round",
                "text": "Polished",
                "review": {
                    "flagged_lines": [FLAGGED],
                    "lines_to_review": [
                        {"text": FLAGGED, "support": 0.2, "unsupported": True}
                    ],
                },
            },
        ],
        "totals": {},
        "config": {},
        "manifest": {},
    }


def test_a_flagged_line_is_unresolved_until_a_decision_is_recorded(tmp_path: Path) -> None:
    state = ReportState(output_path=tmp_path / "out.txt")
    state.set_report(_report_with_a_flagged_line())
    assert state.unresolved_flagged() == [FLAGGED]

    state.record_decision(FLAGGED, "rejected")
    assert state.unresolved_flagged() == []


def test_a_decision_survives_a_new_round_arriving(tmp_path: Path) -> None:
    """A live run replaces the payload each round; the verdict must not vanish from the page."""
    state = ReportState(output_path=tmp_path / "out.txt")
    state.record_decision(FLAGGED, "approved")
    state.set_report(_report_with_a_flagged_line())

    entry = state.get_report()["versions"][1]["review"]["lines_to_review"][0]
    assert entry["decision"] == "approved"


# ── Live lint and the gate on a hand-edited draft ─────────────────────────────

ORIGINAL = "Led the platform team at Acme Corp. Cut p95 latency by 40%."
GOOD_LINE = "Led the platform team at Acme Corp."
BAD_LINE = "Architected a multi-region platform serving 10M users"


def _state_with_reviewer(tmp_path: Path, support: float) -> ReportState:
    from tests.conftest import FakeNoul, FakeTypeSafeClient

    state = ReportState(output_path=tmp_path / "out.txt")
    state.set_report(SAMPLE_REPORT)
    state.original_resume = ORIGINAL
    state.reviewer = FakeTypeSafeClient({"line_00": FakeNoul(support)})
    return state


def test_check_grounds_the_submitted_draft(tmp_path: Path) -> None:
    state = _state_with_reviewer(tmp_path, support=0.2)
    httpd = start(state, host="127.0.0.1", port=0)
    try:
        status, body = _post(
            httpd, "/api/check", {"text": BAD_LINE}, csrf=state.csrf_token
        )
    finally:
        httpd.shutdown()
    assert status == 200
    assert body["lines"][0]["text"] == BAD_LINE
    assert body["unsupported"] == [BAD_LINE]


def test_check_without_a_reviewer_is_unavailable(tmp_path: Path) -> None:
    """`--serve-report` has no client, so the page must say so rather than pretend."""
    state = ReportState(output_path=tmp_path / "out.txt")
    state.set_report(SAMPLE_REPORT)
    httpd = start(state, host="127.0.0.1", port=0)
    try:
        status, body = _post(httpd, "/api/check", {"text": BAD_LINE}, csrf=state.csrf_token)
    finally:
        httpd.shutdown()
    assert status == 503


def test_save_edit_requires_the_check_to_have_run(tmp_path: Path) -> None:
    state = _state_with_reviewer(tmp_path, support=0.95)
    with pytest.raises(ValueError, match="check this edit"):
        state.save_edit(GOOD_LINE)
    assert not state.output_path.exists()


def test_save_edit_refuses_a_line_that_cannot_be_grounded(tmp_path: Path) -> None:
    state = _state_with_reviewer(tmp_path, support=0.2)
    state.record_check(BAD_LINE, [BAD_LINE])
    with pytest.raises(ValueError, match="cannot be grounded"):
        state.save_edit(BAD_LINE)
    assert not state.output_path.exists()


def test_save_edit_writes_once_the_check_is_clean(tmp_path: Path) -> None:
    state = _state_with_reviewer(tmp_path, support=0.95)
    state.record_check(BAD_LINE, [])
    state.save_edit(BAD_LINE)
    assert state.output_path.read_text().strip() == BAD_LINE


def test_a_newer_check_replaces_the_verdict_that_gates_saving(tmp_path: Path) -> None:
    """The gate follows the newest check, so an old failure cannot block a clean edit."""
    state = _state_with_reviewer(tmp_path, support=0.95)
    state.record_check(BAD_LINE, [BAD_LINE])
    state.record_check(GOOD_LINE, [])
    state.save_edit(GOOD_LINE)
    assert state.output_path.read_text().strip() == GOOD_LINE
