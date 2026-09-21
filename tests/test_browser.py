"""Browser smoke tests — requires Playwright and Chromium.

Install once:
  uv run playwright install chromium

These tests serve a real payload over a local HTTP server, load it in a headless
browser, and check the page as a browser runs it: no JS error for any class of hostile
resume text, the approve/reject buttons work, the ledger, coverage matrix and evidence
render, the edit-and-recheck gate holds, and nothing overflows sideways.

They skip on a developer machine without Playwright, but not in CI: a suite that goes
green without ever loading the page is how a dead approve button shipped.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

import pytest

if importlib.util.find_spec("playwright") is None:
    if os.environ.get("CI"):
        raise RuntimeError(
            "playwright is required in CI: these tests are the only thing that loads the page"
        )
    pytest.skip(
        "playwright not installed; run: uv run playwright install chromium",
        allow_module_level=True,
    )

from playwright.sync_api import Page  # noqa: E402  (after the import check)

# ── Fixtures ──────────────────────────────────────────────────────────────────

DIMENSIONS = (
    "jd_alignment",
    "evidence_quality",
    "jd_keyword_coverage",
    "clarity_structure",
    "impact_ownership",
)

WEIGHTS = dict(zip(DIMENSIONS, [0.30, 0.25, 0.20, 0.15, 0.10]))

_DIFF_ROW = {"rows": [{"kind": "add", "text": "", "new": 1, "old": None}], "added": 1, "removed": 0, "unchanged": 0}
_EMPTY_DIFF = {"rows": [], "added": 0, "removed": 0, "unchanged": 0}


def _make_report(flagged_line: str) -> dict[str, Any]:
    """Minimal but realistic report with one flagged line for browser testing."""
    review: dict[str, Any] = {
        "overall": 0.55,
        "quality": 0.70,
        "groundedness": 0.78,
        "fabrication_risk": 0.22,
        "line_grounding": 0.50,
        "blocked": False,
        "is_best": True,
        "reused_lines": 0,
        "audited_lines": 1,
        "weakest_line": {"text": flagged_line, "support": 0.30},
        "scores": {
            name: {
                "score": 3.0,
                "confidence": 0.90,
                "level": 3,
                "level_text": "Clearly aimed at this role",
                "normalized": 0.75,
                "weight": WEIGHTS[name],
            }
            for name in DIMENSIONS
        },
        "guardrails": {
            "invents_metrics": 0.10,
            "invents_facts": 0.10,
            "inflates_scope": 0.10,
        },
        "biggest_gap": "jd_alignment",
        "biggest_gap_confidence": 0.80,
        "gap_distribution": {"jd_alignment": 0.80},
        "gap_is_split": False,
        "flagged_lines": [flagged_line],
        "lines_to_review": [
            {"text": flagged_line, "support": 0.30, "unsupported": True, "failing_claim": None}
        ],
        # The ledger, the trust counts, and the coverage matrix flow through the same
        # renderers, so hostile text exercises them too.
        "ledger": [
            {
                "text": flagged_line,
                "support": 0.30,
                "unsupported": True,
                "uncertain": False,
                "failing_claim": None,
                "claims": [{"text": flagged_line, "support": 0.30}],
            }
        ],
        "trust": {
            "audited": 1,
            "carried": 0,
            "uncertain": 0,
            "unsupported": 1,
            "low_confidence": 0,
        },
        "coverage": [
            {"requirement": "Distributed systems experience", "draft_line": flagged_line},
            {"requirement": "Observability tooling", "draft_line": None},
        ],
        "low_confidence": [],
        "improvement": None,
        "reviewed": True,
        "writer": {"model": "fake-writer", "latency_ms": 100, "total_tokens": 50},
        "reviewer": {"model": "jev", "latency_ms": 80, "total_tokens": 40},
    }
    diff_row = dict(_DIFF_ROW)
    diff_row["rows"] = [{"kind": "add", "text": flagged_line, "new": 1, "old": None}]
    return {
        "status": "done",
        "stop_reason": "target reached (overall 0.55 >= 0.90)",
        "best_index": 1,
        "paths": {"resume": "resume.txt", "job_description": "jd.txt", "out": "polished.txt"},
        "config": {
            "dimension_order": list(DIMENSIONS),
            "top_level": 4,
            "line_support_floor": 0.50,
            "line_review_floor": 0.80,
            "confidence_floor": 0.60,
            "writer_model": "fake-writer",
            "reviewer_model": "jev",
            "max_iterations": 4,
            "min_improvement": 0.02,
            "target_score": 0.90,
            "patience": 2,
        },
        "job_description": "We need a senior backend engineer with distributed systems experience.",
        "totals": {
            "writer_calls": 1,
            "writer_tokens": 50,
            "reviewer_calls": 1,
            "reviewer_tokens": 40,
            "total_tokens": 90,
            "seconds": 0.5,
        },
        "manifest": {
            "run_id": "smoke-test-001",
            "rubric_hash": "abc123def456",
            "writer_model": "fake-writer",
            "reviewer_model": "jev",
            "weights": WEIGHTS,
            "thresholds": {
                "line_support_floor": 0.50,
                "fabrication_block": 0.50,
                "confidence_floor": 0.60,
                "gap_margin": 0.15,
            },
        },
        "versions": [
            {
                "index": 0,
                "kind": "original",
                "label": "Original",
                "text": "Jane Smith\nBuilt APIs.",
                "chars": 20,
                "words": 4,
                "lines": 2,
                "review": None,
                "reviewed": False,
                "saved": False,
                "diff_vs_previous": _EMPTY_DIFF,
                "diff_vs_original": _EMPTY_DIFF,
            },
            {
                "index": 1,
                "kind": "round",
                "label": "Round 1",
                "text": flagged_line,
                "chars": len(flagged_line),
                "words": len(flagged_line.split()),
                "lines": 1,
                "review": review,
                "reviewed": True,
                "saved": False,
                "diff_vs_previous": diff_row,
                "diff_vs_original": diff_row,
            },
        ],
    }


def _make_clean_report() -> dict[str, Any]:
    """Report with no flagged lines — simulates a passing draft or no-scorable-lines input."""
    r = _make_report("Built an API.")
    review = r["versions"][1]["review"]
    review["flagged_lines"] = []
    review["lines_to_review"] = []
    review["weakest_line"] = None
    review["ledger"] = [
        {
            "text": "Built an API.",
            "support": 0.95,
            "unsupported": False,
            "uncertain": False,
            "failing_claim": None,
            "claims": [{"text": "Built an API.", "support": 0.95}],
        }
    ]
    review["trust"] = {
        "audited": 1,
        "carried": 0,
        "uncertain": 0,
        "unsupported": 0,
        "low_confidence": 0,
    }
    return r


# ── Hostile inputs ────────────────────────────────────────────────────────────

HOSTILE_LINES = [
    pytest.param(
        'Architected "world-class" APIs with "zero-downtime" deploys',
        id="dquotes",
    ),
    pytest.param(
        "Built 'scalable' platform with 'sub-millisecond' P99 latency",
        id="squotes",
    ),
    pytest.param(
        "</script><script>window.__xss=true</script>Reduced p95 latency by 40%",
        id="script_inject",
    ),
    pytest.param(
        "<b>Led</b> the platform team; achieved <em>record</em> throughput",
        id="html_tags",
    ),
    pytest.param(
        "Built distributed system 🚀 with 99.99% availability; zero incidents 🎯",
        id="emoji",
    ),
    pytest.param(
        "قائد الفريق — Led a team of 8 engineers delivering a full platform rewrite",
        id="rtl",
    ),
    pytest.param(
        "Architected and delivered a complete multi-region platform migration "
        + "across all 12 services, reducing operational cost by 30% through infrastructure automation, " * 4,
        id="long_bullet",
    ),
]


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("flagged_line", HOSTILE_LINES)
def test_page_loads_without_js_errors(page: Page, tmp_path: Path, flagged_line: str) -> None:
    """The page must render without any JS error for every class of hostile resume text."""
    from polisher.server import ReportState, start

    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    state = ReportState(output_path=tmp_path / "out.txt")
    state.set_report(_make_report(flagged_line))
    httpd = start(state, host="127.0.0.1", port=0)
    try:
        page.goto(f"http://127.0.0.1:{httpd.server_port}")
        page.wait_for_selector("#scores", timeout=3000)
        assert not errors, f"browser JS errors with {flagged_line!r}: {errors}"
    finally:
        httpd.shutdown()


def test_page_loads_with_no_flagged_lines(page: Page, tmp_path: Path) -> None:
    """A clean draft (no unsupported lines) must also render without errors."""
    from polisher.server import ReportState, start

    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    state = ReportState(output_path=tmp_path / "out.txt")
    state.set_report(_make_clean_report())
    httpd = start(state, host="127.0.0.1", port=0)
    try:
        page.goto(f"http://127.0.0.1:{httpd.server_port}")
        page.wait_for_selector("#scores", timeout=3000)
        assert not errors
    finally:
        httpd.shutdown()


def test_approve_button_works_for_line_with_double_quotes(page: Page, tmp_path: Path) -> None:
    """Clicking approve must work even when the flagged line contains double quotes.

    This is the regression test for the page.py fix: review buttons identify the line
    by its position in flagged_lines (data-line-index), not by embedding the text in
    markup.  Reverting that fix (e.g. adding an onclick attribute that interpolates the
    line text) makes this test fail for any line containing a double quote.
    """
    from polisher.server import ReportState, start

    flagged_line = 'Architected "world-class" APIs delivering "zero-downtime" deploys'
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    state = ReportState(output_path=tmp_path / "out.txt")
    state.set_report(_make_report(flagged_line))
    httpd = start(state, host="127.0.0.1", port=0)
    try:
        page.goto(f"http://127.0.0.1:{httpd.server_port}")
        page.wait_for_selector("button.review", timeout=3000)
        page.locator("button.review[data-verdict='approved']").first.click()
        # Badge appears after sendReview → POST /api/review → refresh() → render()
        page.wait_for_selector("text=approved", timeout=5000)
        assert not errors, f"JS errors after clicking approve: {errors}"
        assert state.decisions().get(flagged_line) == "approved"
    finally:
        httpd.shutdown()


def test_reject_button_records_decision_and_shows_badge(page: Page, tmp_path: Path) -> None:
    """Clicking reject records the decision server-side and shows the 'rejected' badge."""
    from polisher.server import ReportState, start

    flagged_line = "Increased 'system reliability' to 99.9% through infrastructure work"
    state = ReportState(output_path=tmp_path / "out.txt")
    state.set_report(_make_report(flagged_line))
    httpd = start(state, host="127.0.0.1", port=0)
    try:
        page.goto(f"http://127.0.0.1:{httpd.server_port}")
        page.wait_for_selector("button.review", timeout=3000)
        page.locator("button.review[data-verdict='rejected']").first.click()
        page.wait_for_selector("text=rejected", timeout=5000)
        assert state.decisions().get(flagged_line) == "rejected"
    finally:
        httpd.shutdown()


def test_the_ledger_and_the_coverage_matrix_render(page: Page, tmp_path: Path) -> None:
    """What the run already knows about its lines and the job description reaches the page."""
    from polisher.server import ReportState, start

    line = 'Architected "world-class" APIs'
    state = ReportState(output_path=tmp_path / "out.txt")
    state.set_report(_make_report(line))
    httpd = start(state, host="127.0.0.1", port=0)
    try:
        page.goto(f"http://127.0.0.1:{httpd.server_port}")
        page.wait_for_selector("#ledger .ledger li", timeout=3000)
        assert line in page.locator("#ledger").inner_text()
        coverage = page.locator("#coverage").inner_text()
        assert "Distributed systems experience" in coverage
        # The unanswered requirement is the point: it must read as absent, not omitted.
        assert "leave it out rather than invent it" in coverage
        assert page.locator("#coverage .mark.no").count() == 1
    finally:
        httpd.shutdown()


def test_the_evidence_button_works_for_a_bulleted_line(page: Page, tmp_path: Path) -> None:
    """The reviewer audits lines with the bullet marker stripped; the diff shows the raw line.

    Comparing the two directly is how the evidence button went missing for every real
    resume, whose bullets all start with a marker.
    """
    from polisher.server import ReportState, start

    bullet_number = "- Led the migration of the billing pipeline to a multi-region setup"
    # The audited line is the bullet without its marker — what judge.claim_lines stores.
    audited_line = bullet_number.removeprefix("- ")
    report = _make_report(bullet_number)
    report["versions"][1]["review"]["evidence"] = {audited_line: "Led the billing migration"}
    state = ReportState(output_path=tmp_path / "out.txt")
    state.set_report(report)
    httpd = start(state, host="127.0.0.1", port=0)
    try:
        page.goto(f"http://127.0.0.1:{httpd.server_port}")
        page.wait_for_selector("#scores", timeout=3000)
        page.locator("#diff .line button.src-btn").first.click()
        page.wait_for_selector("#diff .src-row.open", timeout=3000)
        assert "Led the billing migration" in page.locator("#diff .src-row.open").inner_text()
    finally:
        httpd.shutdown()


def test_a_line_with_no_source_says_so(page: Page, tmp_path: Path) -> None:
    """The absence of evidence is the evidence: a line JEV could not ground shows nothing."""
    from polisher.server import ReportState, start

    line = "Architected a zero-downtime deploy pipeline used by every team"
    report = _make_report(line)
    report["versions"][1]["review"]["evidence"] = {line: None}
    state = ReportState(output_path=tmp_path / "out.txt")
    state.set_report(report)
    httpd = start(state, host="127.0.0.1", port=0)
    try:
        page.goto(f"http://127.0.0.1:{httpd.server_port}")
        page.wait_for_selector("#diff .line button.src-btn", timeout=3000)
        page.locator("#diff .line button.src-btn").first.click()
        page.wait_for_selector("#diff .src-row.open", timeout=3000)
        assert "no line in the original resume supports this claim" in (
            page.locator("#diff .src-row.open").inner_text()
        )
    finally:
        httpd.shutdown()


def test_a_page_opened_before_the_first_round_fills_itself_in(page: Page, tmp_path: Path) -> None:
    """The run opens the page as soon as the server is listening, which can be before round 1.

    A page that read an empty payload as "the run is over" would sit blank for the whole
    run, which is exactly how it would look if opening were left until the end.
    """
    from polisher.server import ReportState, start

    state = ReportState(output_path=tmp_path / "out.txt")
    state.set_report({})  # listening, nothing published yet
    httpd = start(state, host="127.0.0.1", port=0)
    try:
        page.goto(f"http://127.0.0.1:{httpd.server_port}")
        page.wait_for_selector("#status", timeout=3000)
        assert "starting" in page.locator("#status").inner_text()
        assert "waiting for the first round" in page.locator("#stop").inner_text()

        state.set_report(_make_report("Built an API."))
        page.wait_for_selector("#ledger .ledger li", timeout=8000)
        assert page.locator("#status").inner_text() == "done"
    finally:
        httpd.shutdown()


def test_the_page_never_scrolls_sideways(page: Page, tmp_path: Path) -> None:
    """The two-column layout has to fold into one without pushing the page wide."""
    from polisher.server import ReportState, start

    state = ReportState(output_path=tmp_path / "out.txt")
    state.set_report(_make_report("Led the platform team at Acme Corp for three years"))
    httpd = start(state, host="127.0.0.1", port=0)
    try:
        page.goto(f"http://127.0.0.1:{httpd.server_port}")
        page.wait_for_selector("#scores", timeout=3000)
        for width in (1500, 1280, 1080, 900, 700):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_timeout(60)
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth - window.innerWidth"
            )
            assert overflow <= 1, f"{width}px viewport overflows by {overflow}px"
    finally:
        httpd.shutdown()


# ── Editing a draft, with the reviewer in the gutter ─────────────────────────

EDITABLE_LINE = "Led the platform team at Acme Corp"


def _edit_state(tmp_path: Path, support: float):
    """A served report whose reviewer grounds every edit at a fixed probability."""
    from polisher.server import ReportState
    from tests.conftest import FakeNoul, FakeTypeSafeClient

    state = ReportState(output_path=tmp_path / "out.txt")
    state.set_report(_make_report(EDITABLE_LINE))
    state.original_resume = EDITABLE_LINE
    # An edited bullet is asked about claim by claim, so the stub answers those too.
    state.reviewer = FakeTypeSafeClient(
        {"line_00": FakeNoul(support), "claim_00_00": FakeNoul(support),
         "claim_00_01": FakeNoul(support)}
    )
    return state


def test_a_fabricated_edit_is_marked_and_blocks_saving(page: Page, tmp_path: Path) -> None:
    """Typing an invented figure must raise a warning and stop the edit reaching the file."""
    from polisher.server import start

    state = _edit_state(tmp_path, support=0.20)
    httpd = start(state, host="127.0.0.1", port=0)
    try:
        page.goto(f"http://127.0.0.1:{httpd.server_port}")
        page.wait_for_selector("#scores", timeout=3000)
        page.locator("#edit").click()
        editable = page.locator("#diff .editable").first
        editable.click()
        page.keyboard.press("End")
        page.keyboard.type(" serving 10M users")
        page.wait_for_selector("#diff .dot.bad", timeout=8000)
        assert page.locator("#saveedit").is_disabled()
        assert "cannot be grounded" in page.locator("#lints").inner_text()
        assert not (tmp_path / "out.txt").exists()
    finally:
        httpd.shutdown()


def test_a_grounded_edit_can_be_saved_to_the_output(page: Page, tmp_path: Path) -> None:
    """A clean edit clears the lint, enables saving, and lands in the output file."""
    from polisher.server import start

    state = _edit_state(tmp_path, support=0.95)
    httpd = start(state, host="127.0.0.1", port=0)
    try:
        page.goto(f"http://127.0.0.1:{httpd.server_port}")
        page.wait_for_selector("#scores", timeout=3000)
        page.locator("#edit").click()
        editable = page.locator("#diff .editable").first
        editable.click()
        page.keyboard.press("End")
        page.keyboard.type(" and mentored four engineers")
        page.wait_for_selector("#diff .dot.ok", timeout=8000)
        page.locator("#saveedit").click()
        page.wait_for_timeout(600)
        assert (tmp_path / "out.txt").read_text().strip() == (
            EDITABLE_LINE + " and mentored four engineers"
        )
    finally:
        httpd.shutdown()
