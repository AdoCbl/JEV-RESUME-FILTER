from pathlib import Path

import pytest

from polisher.rules_builtin import BUILTIN_RULEBOOK, iter_prompt_directives, render_writer_system_prompt
from polisher.rules import PRECEDENCE_ORDER, Rule, RuleBook, dump_rules_toml, format_ledger, load_rules, run_code_check
from polisher.writer import SYSTEM_PROMPT


def test_load_rules_rejects_unknown_kind(tmp_path: Path) -> None:
    rules = tmp_path / "rules.toml"
    rules.write_text(
        """
[[rules]]
id = "no-summary"
kind = "forbid"
text = "Do not include a summary section."
source = "user"
check = "code"
severity = "blocking"
""".strip()
    )

    with pytest.raises(SystemExit, match=r"kind"):
        load_rules(rules)


def test_load_rules_rejects_unknown_check(tmp_path: Path) -> None:
    rules = tmp_path / "rules.toml"
    rules.write_text(
        """
[[rules]]
id = "no-summary"
kind = "must_not"
text = "Do not include a summary section."
source = "user"
check = "lint"
severity = "blocking"
""".strip()
    )

    with pytest.raises(SystemExit, match=r"check"):
        load_rules(rules)


def test_rulebook_round_trips_through_toml(tmp_path: Path) -> None:
    rules = tmp_path / "rules.toml"
    rules.write_text(
        """
[[rules]]
id = "retain-clearance"
kind = "must"
text = "Keep the security clearance line."
source = "user"
check = "code"
severity = "blocking"

[[rules]]
id = "plain-text"
kind = "format"
text = "Use plain text only."
source = "builtin"
check = "code"
severity = "advisory"
""".strip()
        + "\n"
    )

    loaded = load_rules(rules)
    dumped = dump_rules_toml(loaded)

    assert dump_rules_toml(load_rules(_write_copy(tmp_path, dumped))) == dumped


def test_rulebook_orders_by_precedence() -> None:
    assert PRECEDENCE_ORDER == ("grounding", "user", "job", "builtin")

    ordered = RuleBook(
        rules=(
            Rule(
                id="builtin-prefer",
                kind="prefer",
                text="Prefer shorter bullets.",
                source="builtin",
                check="code",
                severity="advisory",
            ),
            Rule(
                id="job-must",
                kind="must",
                text="Match the posted title.",
                source="job",
                check="jev",
                severity="advisory",
            ),
            Rule(
                id="user-must-not",
                kind="must_not",
                text="Do not add a summary section.",
                source="user",
                check="code",
                severity="blocking",
            ),
        )
    ).ordered()

    assert [rule.id for rule in ordered] == ["user-must-not", "job-must", "builtin-prefer"]


def test_builtin_rules_account_for_system_prompt() -> None:
    directives = iter_prompt_directives()
    builtin_rule_ids = {rule.id for rule in BUILTIN_RULEBOOK}
    accounted_rule_ids = {directive.rule_id for directive in directives if directive.rule_id is not None}

    assert SYSTEM_PROMPT == render_writer_system_prompt()
    assert accounted_rule_ids == builtin_rule_ids
    assert any(directive.prompt_only for directive in directives)


def test_page_budget_check_passes_and_fails() -> None:
    passing = run_code_check("page_budget", "One short line\nAnother short line", max_words=10, max_lines=4)
    failing = run_code_check("page_budget", "alpha beta gamma\none\ntwo", max_words=2, max_lines=2)

    assert passing.passed
    assert not failing.passed
    assert any("words" in finding or "lines" in finding for finding in failing.findings)


def test_banned_phrases_check_passes_and_fails() -> None:
    passing = run_code_check("banned_phrases", "Built the shipment tracking API.")
    failing = run_code_check("banned_phrases", "Responsible for the API and helped with ops.")

    assert passing.passed
    assert not failing.passed
    assert failing.findings == ("responsible for", "helped with")


def test_first_person_check_passes_and_fails() -> None:
    passing = run_code_check("first_person", "Built the billing API for Acme.")
    failing = run_code_check("first_person", "I built the billing API with my team.")

    assert passing.passed
    assert not failing.passed
    assert "i" in failing.findings
    assert "my" in failing.findings


def test_us_spelling_check_passes_and_fails() -> None:
    passing = run_code_check("us_spelling", "Optimized the API and improved team behavior.")
    failing = run_code_check("us_spelling", "Optimised the API and improved team behaviour.")

    assert passing.passed
    assert not failing.passed
    assert "optimised -> optimized" in failing.findings
    assert "behaviour -> behavior" in failing.findings


def test_required_strings_check_passes_and_fails() -> None:
    passing = run_code_check(
        "required_strings",
        "Active Secret clearance\nPython\nGo",
        strings=("Secret clearance",),
    )
    failing = run_code_check(
        "required_strings",
        "Python\nGo",
        strings=("Secret clearance",),
    )

    assert passing.passed
    assert not failing.passed
    assert failing.findings == ("Secret clearance",)


def test_section_detection_check_passes_and_fails() -> None:
    passing = run_code_check(
        "sections",
        "EXPERIENCE\nBuilt APIs\n\nSKILLS\nPython",
        required_sections=("experience", "skills"),
        forbidden_sections=("summary",),
    )
    failing = run_code_check(
        "sections",
        "SUMMARY\nBackend engineer\n\nEXPERIENCE\nBuilt APIs",
        required_sections=("experience", "skills"),
        forbidden_sections=("summary",),
    )

    assert passing.passed
    assert not failing.passed
    assert "missing: skills" in failing.findings
    assert "forbidden: summary" in failing.findings


def test_emoji_check_passes_and_fails() -> None:
    passing = run_code_check("emoji", "Built the shipment tracking API.")
    failing = run_code_check("emoji", "Built the shipment tracking API 🚀")

    assert passing.passed
    assert not failing.passed
    assert failing.findings == ("🚀",)


def test_markdown_check_passes_and_fails() -> None:
    passing = run_code_check("markdown", "EXPERIENCE\nBuilt the shipment tracking API.")
    failing = run_code_check("markdown", "# Experience\n**Built** the shipment tracking API.")

    assert passing.passed
    assert not failing.passed
    assert "heading" in failing.findings
    assert "emphasis" in failing.findings


def test_format_ledger_captures_budget_duplicates_and_date_consistency() -> None:
    ledger = format_ledger(
        """
SUMMARY
One short summary line.

EXPERIENCE
Acme Corp — Senior Engineer
Jan 2020 - Present
- Built the payments API for checkout.
- Built the payments API for checkout.
- Built the payments platform for checkout and billing automation across every region, partner integration, migration planning, incident response, release coordination, dashboarding, service ownership, operational readiness, vendor rollout planning, compliance reviews, and customer-support escalation handling.

Beta Inc — Engineer
2020 - 2021
- Improved observability for the API estate.

SKILLS
Python, Go
""".strip()
    )

    assert ledger["words"] > 0
    assert ledger["sections"] == ["summary", "experience", "skills"]
    assert ledger["role_bullets"][0]["bullets"] == 3
    assert ledger["overlong_bullets"]
    assert ledger["duplicate_claims"]
    assert not ledger["date_consistent"]


def _write_copy(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "roundtrip.toml"
    path.write_text(text)
    return path