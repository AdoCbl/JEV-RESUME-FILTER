"""A local view of a run: the page, the payload, and saving a chosen version.

Standard library only. The server holds the latest report payload, so the loop can
update it from its observer thread while the browser is reading it — which is what makes
the page live during a run.

Endpoints:
  GET  /           — the report page
  GET  /api/report — the run payload (JSON)
  GET  /healthz    — liveness check
  POST /api/save   — write a chosen version, or a hand-edited draft, to the output file
  POST /api/review — record a human approve/reject decision on a flagged line
  POST /api/check  — ground the lines of an edited draft, asking only what changed
"""

import json
import secrets
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .config import DEFAULT_HOST, DEFAULT_PORT
from .page import render_page

_CSRF_HEADER = "X-Csrf-Token"


@dataclass
class ReportState:
    """The latest payload, shared between the loop's thread and the server's threads."""

    output_path: Path
    saved_index: int | None = None
    csrf_token: str = field(default_factory=lambda: secrets.token_hex(32))
    # Audit log callback: (line, verdict) -> None; set by cli.py when --no-store is off
    on_review: Any = None  # Callable[[str, str], None] | None
    # Context for /api/check: set by cli.py after the loop starts
    original_resume: str | None = None
    reviewer: Any = None  # TypeSafeClient | None
    _report: dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    # Approved/rejected decisions keyed by line text
    _decisions: dict[str, str] = field(default_factory=dict)
    # The most recent live check: the edited text and the lines it could not ground
    _checked_text: str | None = None
    _checked_unsupported: list[str] = field(default_factory=list)

    def set_report(self, report: dict[str, Any]) -> None:
        with self._lock:
            self._report = report
            # A round's payload replaces the previous one, so re-apply the verdicts already
            # recorded: an approval must not disappear from the page because a round landed.
            self._apply_decisions()

    def get_report(self) -> dict[str, Any]:
        with self._lock:
            return self._report

    def _apply_decisions(self) -> None:
        """Write the recorded verdicts into the payload so the page reflects them.

        The caller holds ``_lock``.
        """
        if not self._decisions:
            return
        for version in self._report.get("versions", []):
            review = version.get("review")
            if review is None:
                continue
            for entry in review.get("lines_to_review", []):
                verdict = self._decisions.get(entry["text"])
                if verdict is not None:
                    entry["decision"] = verdict

    def record_decision(self, line: str, verdict: str) -> None:
        with self._lock:
            self._decisions[line] = verdict
            self._apply_decisions()

    def decisions(self) -> dict[str, str]:
        with self._lock:
            return dict(self._decisions)

    def unresolved_flagged(self) -> list[str]:
        """Flagged lines in the best version that have not been approved or rejected."""
        report = self.get_report()
        best_idx = report.get("best_index")
        if best_idx is None:
            return []
        versions = report.get("versions", [])
        best = next((v for v in versions if v.get("index") == best_idx), None)
        if best is None or best.get("review") is None:
            return []
        flagged = best["review"].get("flagged_lines", [])
        decisions = self.decisions()
        return [line for line in flagged if line not in decisions]

    def save_version(self, index: int) -> Path:
        versions = self.get_report().get("versions", [])
        match = next((v for v in versions if v.get("index") == index), None)
        if match is None:
            raise ValueError(f"no version {index} in this run")
        if match.get("kind") == "original":
            raise ValueError("the original resume is the input, not an output")
        self.output_path.write_text(match["text"] + "\n")
        self.saved_index = index
        with self._lock:
            for version in self._report.get("versions", []):
                version["saved"] = version.get("index") == index
        return self.output_path

    def record_check(self, text: str, unsupported: list[str]) -> None:
        with self._lock:
            self._checked_text = text
            self._checked_unsupported = list(unsupported)

    def save_edit(self, text: str) -> Path:
        """Write a hand-edited draft — but only once its own check came back clean.

        The gate is the same one the loop's drafts pass: a hand-edit that still has a line
        the reviewer cannot ground does not reach the output file. Requiring the check to
        have run also means the gate is decided by the reviewer's judgment on this exact
        text, not by the page asserting that it looks fine.
        """
        with self._lock:
            if self._checked_text != text:
                raise ValueError("check this edit before saving it")
            unsupported = list(self._checked_unsupported)
        if unsupported:
            shown = "; ".join(line[:60] for line in unsupported[:3])
            raise ValueError(
                f"{len(unsupported)} line(s) still cannot be grounded: {shown}"
            )
        self.output_path.write_text(text + "\n")
        return self.output_path


def _handler(state: ReportState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "resume-polisher"
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            self._send(status, json.dumps(payload).encode(), "application/json")

        def _check_csrf(self) -> bool:
            return self.headers.get(_CSRF_HEADER) == state.csrf_token

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/index.html"):
                page = render_page(state.get_report(), csrf_token=state.csrf_token)
                self._send(200, page.encode(), "text/html; charset=utf-8")
            elif self.path == "/api/report":
                self._json(200, state.get_report())
            elif self.path == "/healthz":
                self._json(200, {"status": "ok"})
            else:
                self._json(404, {"error": f"no route {self.path}"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._check_csrf():
                self._json(403, {"error": "invalid or missing CSRF token"})
                return
            length = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(length) or b"{}"
            try:
                body = json.loads(raw)
            except json.JSONDecodeError as exc:
                self._json(400, {"error": str(exc)})
                return

            if self.path == "/api/save":
                try:
                    if "text" in body:
                        saved = state.save_edit(str(body["text"]))
                    else:
                        saved = state.save_version(int(body["index"]))
                except (KeyError, TypeError, ValueError) as exc:
                    self._json(400, {"error": str(exc)})
                    return
                self._json(200, {"saved": str(saved), "index": body.get("index")})

            elif self.path == "/api/review":
                line = body.get("line", "")
                verdict = body.get("verdict", "")
                if not line or verdict not in ("approved", "rejected"):
                    self._json(400, {"error": "line and verdict ('approved'|'rejected') required"})
                    return
                state.record_decision(line, verdict)
                if state.on_review is not None:
                    state.on_review(line, verdict)
                self._json(200, {"line": line, "verdict": verdict})

            elif self.path == "/api/check":
                if state.reviewer is None or not state.original_resume:
                    self._json(503, {"error": "live checking not available for this run"})
                    return
                draft_text = body.get("text", "")
                if not draft_text:
                    self._json(400, {"error": "text required"})
                    return
                try:
                    from .judge import audit_lines

                    carried = body.get("carried") or None
                    audited = audit_lines(
                        state.reviewer,
                        original_resume=state.original_resume,
                        draft=draft_text,
                        carried=carried,
                    )
                except Exception as exc:  # noqa: BLE001 — report the provider message to the page
                    self._json(500, {"error": str(exc)})
                    return
                unsupported = [line.text for line in audited if line.unsupported]
                state.record_check(draft_text, unsupported)
                self._json(200, {
                    "lines": [
                        {
                            "text": line.text,
                            "support": round(line.support, 3),
                            "unsupported": line.unsupported,
                            "failing_claim": line.failing_claim,
                            "claims": [
                                {"text": t, "support": round(s, 3)} for t, s in line.claims
                            ],
                        }
                        for line in audited
                    ],
                    "unsupported": unsupported,
                })

            else:
                self._json(404, {"error": f"no route {self.path}"})

    return Handler


def start(
    state: ReportState, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), _handler(state))
    threading.Thread(target=httpd.serve_forever, name="report-server", daemon=True).start()
    return httpd


def url(httpd: ThreadingHTTPServer, host: str = DEFAULT_HOST) -> str:
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    return f"http://{shown}:{httpd.server_port}"


def wait() -> None:
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass

