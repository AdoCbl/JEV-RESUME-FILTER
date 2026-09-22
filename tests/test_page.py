"""Tests for polisher.page.

The page is one HTML string with the run payload embedded in it. Two things can break it,
and they break differently:

* the payload is embedded by Python, so ``</script>`` inside a resume line must not be able
  to close the payload block — testable here;
* the version list, the diff, and the approve/reject buttons are built by JavaScript in the
  browser, so the escaping that keeps a resume line out of an HTML attribute is a property
  of the template source, not of ``render_page``'s output — checked here as a source
  invariant, and end-to-end by the browser smoke test in CI.

The review buttons used to embed the flagged line through ``JSON.stringify`` inside an
``onclick`` attribute, which truncated the handler for any line containing a double quote.
These tests exist so that cannot come back.
"""

from __future__ import annotations

import json

from polisher.page import _TEMPLATE, render_page

DIMENSIONS = (
    "jd_alignment",
    "evidence_quality",
    "jd_keyword_coverage",
    "clarity_structure",
    "impact_ownership",
)


def _report(draft: str) -> dict:
    review = {
        "overall": 0.6,
        "quality": 0.8,
        "groundedness": 0.75,
        "blocked": False,
        "is_best": True,
        "line_grounding": 0.5,
        "reused_lines": 0,
        "audited_lines": 2,
        "weakest_line": {"text": draft, "support": 0.2},
        "scores": {
            name: {
                "score": 3.0,
                "confidence": 0.9,
                "level": 3,
                "level_text": "tight",
                "normalized": 0.75,
                "weight": 0.2,
            }
            for name in DIMENSIONS
        },
        "guardrails": {"invents_metrics": 0.1, "invents_facts": 0.1, "inflates_scope": 0.1},
        "biggest_gap": "jd_alignment",
        "biggest_gap_confidence": 0.8,
        "gap_distribution": {"jd_alignment": 0.8},
        "gap_is_split": False,
        "flagged_lines": [draft],
        "lines_to_review": [
            {"text": draft, "support": 0.2, "unsupported": True, "failing_claim": None}
        ],
        "low_confidence": [],
        "improvement": 0.1,
        "reviewed": True,
        "writer": {"model": "deepseek-chat", "latency_ms": 1000, "total_tokens": 100},
        "reviewer": {"model": "jev", "latency_ms": 1000, "total_tokens": 100},
    }
    diff = {"rows": [], "added": 0, "removed": 0, "unchanged": 2}
    return {
        "status": "done",
        "stop_reason": "target reached",
        "best_index": 1,
        "paths": {"resume": "r.txt", "job_description": "jd.txt", "out": "out.txt"},
        "config": {"dimension_order": list(DIMENSIONS), "top_level": 4, "confidence_floor": 0.6},
        "job_description": "Backend engineer.",
        "totals": {
            "writer_calls": 1,
            "writer_tokens": 10,
            "reviewer_calls": 1,
            "reviewer_tokens": 10,
            "total_tokens": 20,
            "seconds": 1.0,
        },
        "manifest": {"run_id": "test"},
        "versions": [
            {
                "index": 0,
                "kind": "original",
                "label": "Original",
                "text": "Jane Smith\nBuilt the API.",
                "chars": 20,
                "words": 5,
                "lines": 2,
                "review": None,
                "reviewed": True,
                "saved": False,
                "diff_vs_previous": diff,
                "diff_vs_original": diff,
            },
            {
                "index": 1,
                "kind": "round",
                "label": "Round 1",
                "text": draft,
                "chars": len(draft),
                "words": len(draft.split()),
                "lines": len(draft.splitlines()),
                "review": review,
                "reviewed": True,
                "saved": True,
                "diff_vs_previous": diff,
                "diff_vs_original": diff,
            },
        ],
    }


# ── The payload Python embeds ────────────────────────────────────────────────


def test_closing_script_tag_in_a_resume_line_cannot_end_the_payload_block() -> None:
    html = render_page(_report("</script><script>alert(1)</script>"))
    assert html.count("</script>") == 2  # only the two real script blocks
    assert "</script><script>alert(1)" not in html


def test_embedded_payload_round_trips_through_json() -> None:
    """Whatever Python escapes must still parse back to the same payload in the browser."""
    report = _report('Improved "time to first byte" by 40%')
    html = render_page(report)
    start = html.index('<script id="payload" type="application/json">')
    body = html[start:].split(">", 1)[1].split("</script>", 1)[0]
    assert json.loads(body) == report


def test_csrf_token_is_embedded_for_the_post_routes() -> None:
    html = render_page(_report("Invented claim"), csrf_token="token-123")
    assert '"token-123"' in html


def test_page_renders_with_no_report() -> None:
    html = render_page(None)
    assert "<!doctype html>" in html.lower()
    assert '<script id="payload" type="application/json">{}</script>' in html


def test_round_updates_are_announced_to_screen_readers() -> None:
    assert 'aria-live="polite"' in _TEMPLATE


# ── The template invariants the browser side depends on ──────────────────────


def test_template_has_no_inline_event_handlers() -> None:
    """Inline handlers force user text into an attribute; the page uses listeners instead."""
    assert "onclick=" not in _TEMPLATE
    assert "onchange=" not in _TEMPLATE


def test_review_buttons_are_addressed_by_position_not_by_line_text() -> None:
    """The line text is read back from the payload on click, never written into markup."""
    assert 'data-line-index="${i}"' in _TEMPLATE
    assert "JSON.stringify(t)" not in _TEMPLATE


def test_template_removes_recomputed_score_lines() -> None:
    assert 'leaderRow("mean line grounding"' not in _TEMPLATE
    assert 'leaderRow("fabrication risk"' not in _TEMPLATE
    assert "grounded = 1 − fabrication risk" not in _TEMPLATE


def test_template_contains_verdict_band_labels() -> None:
    assert "Ready to send" in _TEMPLATE
    assert "Needs your review" in _TEMPLATE
    assert "Not grounded" in _TEMPLATE


def test_template_contains_focus_summary_labels() -> None:
    assert "next move" in _TEMPLATE
    assert "active rules" in _TEMPLATE
    assert "proof gate" in _TEMPLATE
    assert "job fit" in _TEMPLATE
