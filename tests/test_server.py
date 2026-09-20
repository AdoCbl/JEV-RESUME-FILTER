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
