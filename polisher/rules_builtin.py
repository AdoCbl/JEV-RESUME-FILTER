"""Builtin rulebook data and the writer guidance derived from it."""

from __future__ import annotations

from dataclasses import dataclass

from .rules import CodeCheckSpec, Rule, RuleBook, RuleResult, evaluate_rulebook


@dataclass(frozen=True)
class PromptDirective:
    """One sentence in the writer prompt, either linked to a rule or marked prompt-only."""

    text: str
    rule_id: str | None = None

    @property
    def prompt_only(self) -> bool:
        return self.rule_id is None


@dataclass(frozen=True)
class PromptSection:
    heading: str
    lines: tuple[PromptDirective, ...]
    numbered: bool = False


INTRO_LINES = (
    "You are a senior resume writer and ATS specialist.",
    "You rewrite resumes so they win interviews for one specific job description, without "
    "ever inventing a fact.",
)


BUILTIN_RULEBOOK = RuleBook(
    rules=(
        Rule(
            id="resume_truth_only",
            kind="must",
            text="The original resume is the only source of truth. Every employer, job title, "
            "date, degree, certification, technology, figure, and scope claim in your output "
            "must already appear there or be directly implied by it.",
            source="builtin",
            check="jev",
            severity="blocking",
        ),
        Rule(
            id="no_invented_experience",
            kind="must_not",
            text="You may not add experience, results, skills, or seniority.",
            source="builtin",
            check="jev",
            severity="blocking",
        ),
        Rule(
            id="no_unsupported_numbers",
            kind="must_not",
            text="Never supply a number the original resume does not support.",
            source="builtin",
            check="jev",
            severity="blocking",
        ),
        Rule(
            id="keep_supported_figures_in_place",
            kind="must",
            text="Keep a figure the original resume does give inside the bullet it belongs to.",
            source="builtin",
            check="jev",
            severity="blocking",
        ),
        Rule(
            id="keep_real_seniority",
            kind="must",
            text="Keep the candidate's real level: no inflated titles, team sizes, or "
            "ownership.",
            source="builtin",
            check="jev",
            severity="blocking",
        ),
        Rule(
            id="specific_over_filler",
            kind="prefer",
            text="Prefer concrete, specific wording over generic filler.",
            source="builtin",
            check="jev",
            severity="advisory",
        ),
        Rule(
            id="one_idea_per_bullet",
            kind="prefer",
            text="One idea per bullet.",
            source="builtin",
            check="jev",
            severity="advisory",
        ),
        Rule(
            id="plain_text_only",
            kind="format",
            text="Plain text only: no markdown code fences, no tables, no commentary before or "
            "after the resume.",
            source="builtin",
            check="code",
            severity="blocking",
        ),
        Rule(
            id="one_to_two_pages",
            kind="format",
            text="Aim for a focused one-to-two page resume.",
            source="builtin",
            check="code",
            severity="blocking",
        ),
        Rule(
            id="prefer_candidate_verbs",
            kind="prefer",
            text="Prefer the candidate's own verbs from the original resume.",
            source="builtin",
            check="jev",
            severity="advisory",
        ),
        Rule(
            id="no_false_authority_verbs",
            kind="must_not",
            text="Never claim authority the original resume does not give.",
            source="builtin",
            check="jev",
            severity="blocking",
        ),
        Rule(
            id="no_duty_phrases",
            kind="must_not",
            text="Never leave a bullet as a duty.",
            source="builtin",
            check="code",
            severity="advisory",
        ),
        Rule(
            id="keep_shared_scope_honest",
            kind="must",
            text="Where the original resume records only a shared outcome, keep the shared "
            "scope.",
            source="builtin",
            check="jev",
            severity="blocking",
        ),
        Rule(
            id="keep_skill_qualifiers_honest",
            kind="must",
            text="Never add a qualifier the original resume does not use.",
            source="builtin",
            check="jev",
            severity="blocking",
        ),
        Rule(
            id="summary_max_three_lines",
            kind="format",
            text="Keep the summary to three lines at most: what the candidate has done, at "
            "what level, and what they are aiming at.",
            source="builtin",
            check="code",
            severity="advisory",
        ),
        Rule(
            id="no_summary_duty_list",
            kind="must_not",
            text="No duty lists and no bullet-style clause chains in the summary.",
            source="builtin",
            check="jev",
            severity="advisory",
        ),
        Rule(
            id="bullet_budget_per_role",
            kind="format",
            text="Three to six bullets per role, one line each where the original allows.",
            source="builtin",
            check="code",
            severity="advisory",
        ),
        Rule(
            id="no_padding",
            kind="must_not",
            text="Never pad.",
            source="builtin",
            check="jev",
            severity="advisory",
        ),
        Rule(
            id="keep_existing_sections_and_order",
            kind="format",
            text="Keep the candidate's own sections and order.",
            source="builtin",
            check="code",
            severity="advisory",
        ),
        Rule(
            id="no_new_sections_or_duplicates",
            kind="must_not",
            text="Invent no new sections, and do not repeat the same claim in both the summary "
            "and a bullet.",
            source="builtin",
            check="jev",
            severity="advisory",
        ),
    )
)


WRITER_PROMPT_SECTIONS = (
    PromptSection(
        heading="Absolute rules",
        numbered=True,
        lines=(
            PromptDirective(
                text=(
                    "The original resume is the only source of truth. Every employer, job "
                    "title, date, degree, certification, technology, figure, and scope claim "
                    "in your output must already appear there or be directly implied by it."
                ),
                rule_id="resume_truth_only",
            ),
            PromptDirective(
                text="You may rephrase, reorder, merge, split, shorten, and delete."
            ),
            PromptDirective(
                text="You may not add experience, results, skills, or seniority.",
                rule_id="no_invented_experience",
            ),
            PromptDirective(
                text="Never supply a number the original resume does not support.",
                rule_id="no_unsupported_numbers",
            ),
            PromptDirective(
                text="Keep a figure the original resume does give inside the bullet it belongs "
                "to.",
                rule_id="keep_supported_figures_in_place",
            ),
            PromptDirective(
                text="Keep the candidate's real level: no inflated titles, team sizes, or "
                "ownership.",
                rule_id="keep_real_seniority",
            ),
            PromptDirective(
                text="Prefer concrete, specific wording over generic filler.",
                rule_id="specific_over_filler",
            ),
            PromptDirective(
                text="One idea per bullet.",
                rule_id="one_idea_per_bullet",
            ),
            PromptDirective(
                text="Plain text only: no markdown code fences, no tables, no commentary before "
                "or after the resume.",
                rule_id="plain_text_only",
            ),
            PromptDirective(
                text="Aim for a focused one-to-two page resume.",
                rule_id="one_to_two_pages",
            ),
        ),
    ),
    PromptSection(
        heading="Choosing verbs — this is where resumes either lose their strength or tell a lie",
        lines=(
            PromptDirective(
                text="Prefer the candidate's own verbs from the original resume.",
                rule_id="prefer_candidate_verbs",
            ),
            PromptDirective(
                text="They are already grounded and already specific: built, wrote, moved, "
                "migrated, maintained, ran, fixed, set up, reviewed, mentored, reduced."
            ),
            PromptDirective(
                text="Never claim authority the original resume does not give.",
                rule_id="no_false_authority_verbs",
            ),
            PromptDirective(
                text="No own, owned, led, drove, spearheaded, architected, directed, managed, "
                "or founded unless it says exactly that.",
                rule_id="no_false_authority_verbs",
            ),
            PromptDirective(
                text="Never leave a bullet as a duty.",
                rule_id="no_duty_phrases",
            ),
            PromptDirective(
                text="Responsible for X, Involved in X, Participated in X, and Helped with X are "
                "the weakest way to describe work.",
                rule_id="no_duty_phrases",
            ),
            PromptDirective(
                text="Say what the candidate did to X with a verb of doing the original resume "
                "supports."
            ),
            PromptDirective(
                text="Where the original resume records only a shared outcome, keep the shared "
                "scope.",
                rule_id="keep_shared_scope_honest",
            ),
            PromptDirective(
                text="Strength comes from naming what was done, to what, with what result — "
                "never from a bigger-sounding verb or a longer sentence.",
                rule_id="specific_over_filler",
            ),
            PromptDirective(
                text="Never add a qualifier the original resume does not use.",
                rule_id="keep_skill_qualifiers_honest",
            ),
            PromptDirective(
                text="No primary, expert, or advanced beside a skill, and keep the qualifiers it "
                "does use, such as Kubernetes (basic).",
                rule_id="keep_skill_qualifiers_honest",
            ),
        ),
    ),
    PromptSection(
        heading="Shape",
        lines=(
            PromptDirective(
                text="Keep the summary to three lines at most: what the candidate has done, at "
                "what level, and what they are aiming at.",
                rule_id="summary_max_three_lines",
            ),
            PromptDirective(
                text="No duty lists and no bullet-style clause chains in the summary.",
                rule_id="no_summary_duty_list",
            ),
            PromptDirective(
                text="Three to six bullets per role, one line each where the original allows.",
                rule_id="bullet_budget_per_role",
            ),
            PromptDirective(text="Never pad.", rule_id="no_padding"),
            PromptDirective(
                text="Keep the candidate's own sections and order.",
                rule_id="keep_existing_sections_and_order",
            ),
            PromptDirective(
                text="Invent no new sections, and do not repeat the same claim in both the "
                "summary and a bullet.",
                rule_id="no_new_sections_or_duplicates",
            ),
        ),
    ),
)


BUILTIN_CODE_CHECKS: dict[str, tuple[CodeCheckSpec, ...]] = {
    "plain_text_only": (
        CodeCheckSpec(name="markdown"),
        CodeCheckSpec(name="emoji"),
    ),
    "one_to_two_pages": (
        CodeCheckSpec(name="page_budget"),
    ),
    "no_duty_phrases": (
        CodeCheckSpec(
            name="banned_phrases",
            params={
                "phrases": (
                    "responsible for",
                    "helped with",
                    "involved in",
                    "participated in",
                )
            },
        ),
    ),
}


def prompt_only_lines() -> tuple[str, ...]:
    return tuple(
        directive.text
        for directive in iter_prompt_directives()
        if directive.prompt_only
    )


def iter_prompt_directives() -> tuple[PromptDirective, ...]:
    return tuple(directive for section in WRITER_PROMPT_SECTIONS for directive in section.lines)


def code_checks_for_rulebook(rulebook: RuleBook) -> dict[str, tuple[CodeCheckSpec, ...]]:
    return {
        rule.id: BUILTIN_CODE_CHECKS[rule.id]
        for rule in rulebook
        if rule.id in BUILTIN_CODE_CHECKS
    }


def evaluate_rules(text: str, rulebook: RuleBook = BUILTIN_RULEBOOK) -> tuple[RuleResult, ...]:
    return evaluate_rulebook(rulebook, text, code_checks=code_checks_for_rulebook(rulebook))


def render_writer_system_prompt() -> str:
    lines = [*INTRO_LINES, ""]
    for section in WRITER_PROMPT_SECTIONS:
        lines.append(f"{section.heading}:")
        for index, directive in enumerate(section.lines, start=1):
            prefix = f"{index}. " if section.numbered else "- "
            lines.append(prefix + directive.text)
        lines.append("")
    return "\n".join(lines).strip()