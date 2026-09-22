"""JEV — the reviewer, scorer, and grounding guardrail for the polish loop.

Everything JEV knows about a draft arrives in one request per round:

* five ``Score`` questions    rate the draft on independent quality dimensions
* three ``Noul`` questions    flag fabrication the draft may have introduced
* one ``Choice`` question     names the dimension with the most room to improve
* one ``Noul`` per draft line asks whether the original resume supports that line

JEV returns judgments. This module turns them into one composite score, a grounding
gate, and the written feedback the writer receives on the next round. Nothing here
decides what to do about the score; that belongs to :mod:`polisher.loop`.

Two details keep the loop honest and cheap:

* A line that survived a revision keeps the verdict it already had (``carried``), so the
  score moves only when the draft does, and a 25-line resume is not re-audited in full
  every round.
* Each dimension's score is reported with the rubric level it sits closest to and the
  level above it, which is the instruction the number was standing in for.
"""

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from math import fsum
from statistics import fmean
from typing import Any

from typesafe_sdk import Choice, Noul, NoulCriteria, Score, TypeSafeClient

from .metrics import RequestMetrics, timed_call
from .rules import RuleBook, RuleResult, evaluate_rulebook
from .rules_builtin import BUILTIN_RULEBOOK, code_checks_for_rulebook

# ── Thresholds ────────────────────────────────────────────────────────────────

TOP_LEVEL = 4  # every dimension below has five levels, numbered 0-4
CONFIDENCE_FLOOR = 0.6  # below this JEV is unsure of its own answer, so flag it
LINE_SUPPORT_FLOOR = 0.5  # a line below this counts as unsupported by the original
LINE_REVIEW_FLOOR = 0.8  # below this a line is worth naming for the writer to tighten
MAX_REPORTED_LINES = 5  # most lines to quote back in one round's feedback
GAP_MARGIN = 0.15  # a leading gap below this margin is reported as a split, not a focus
FABRICATION_BLOCK = 0.5  # at or above this the draft must be fixed before anything else
MIN_CLAIM_CHARS = 12  # shorter lines are headings or contact details, not claims
MAX_AUDIT_LINES = 60  # cap on the per-line grounding questions in one round
MAX_REQUIREMENTS = 20  # cap on JD requirements extracted for the coverage matrix
MAX_UNCOVERED_IN_FEEDBACK = 8  # cap on unanswered requirements quoted back to the writer
RULE_VIOLATION_FLOOR = 0.5  # at or above this a JEV rule counts as violated

_POSTING_HEADINGS = {
    "requirements": "requirements",
    "qualification": "requirements",
    "qualifications": "requirements",
    "what we're looking for": "requirements",
    "what we are looking for": "requirements",
    "must have": "requirements",
    "preferred": "requirements",
    "nice to have": "requirements",
    "responsibilities": "responsibilities",
    "what you'll do": "responsibilities",
    "what you will do": "responsibilities",
    "about us": "boilerplate",
    "about the company": "boilerplate",
    "benefits": "boilerplate",
    "who we are": "boilerplate",
    "why join": "boilerplate",
    "compensation": "boilerplate",
    "equal opportunity": "boilerplate",
}
_POSTING_BOILERPLATE_PREFIXES = (
    "we are",
    "our company",
    "we offer",
    "benefits include",
    "equal opportunity",
)
_POSTING_STOPWORDS = frozenset({
    "and", "the", "for", "with", "that", "this", "your", "you", "our", "will",
    "are", "have", "has", "into", "from", "than", "their", "them", "about",
    "years", "year", "using", "able", "ability", "experience", "preferred",
    "required", "minimum", "must", "strong", "plus", "bonus", "team",
})

# ── Quality dimensions ────────────────────────────────────────────────────────
# One Score question per dimension, each measuring one thing. The weights are code,
# not prompt, so the balance can be retuned without rerunning inference.

DIMENSIONS: dict[str, Score] = {
    "jd_alignment": Score(
        instructions=(
            "How well does `candidate_resume` make the case for this role? Judge the resume's "
            "effectiveness as an application, not whether the candidate should be hired."
        ),
        criteria=[
            "Ignores `job_description`: a general resume with nothing aimed at this role",
            "Leads with work the job description does not ask for, in the candidate's own words",
            "Addresses some of what the job description asks for, but the most relevant work "
            "is buried or described in vocabulary the job description does not use",
            "Clearly aimed at this role: the most relevant work leads, and each requirement the "
            "candidate has evidence for is addressed",
            "Every requirement the candidate has evidence for is addressed head-on in the job "
            "description's language, the strongest evidence comes first, and requirements "
            "without evidence are left out rather than padded",
        ],
    ),
    "evidence_quality": Score(
        instructions=(
            "How well does `candidate_resume` use the results, figures, and scope recorded in "
            "`original_resume`, rather than restating duties?"
        ),
        criteria=[
            "States duties only, with no outcome anywhere, though `original_resume` records "
            "results",
            "Claims outcomes vaguely, such as 'improved performance' or 'worked on', where "
            "`original_resume` gives a figure or a scale",
            "Surfaces some of `original_resume`'s specifics, but most bullets still state "
            "activity rather than result",
            "Surfaces `original_resume`'s results with their figure or scale in the bullet, and "
            "invents none",
            "Every bullet that can carry a result does, using `original_resume`'s own figures "
            "and scope, and the rest state a concrete change rather than a duty",
        ],
    ),
    "jd_keyword_coverage": Score(
        instructions=(
            "How closely does `candidate_resume` mirror the vocabulary of `job_description` for "
            "the skills and experience the candidate actually has?"
        ),
        criteria=[
            "Uses none of the job description's vocabulary; the resume could be for any role",
            "Names most required skills in different words, so both keyword scans and quick "
            "reads miss them",
            "Some required skills appear in the job description's wording, while others the "
            "candidate plainly has are named differently or only implied",
            "Every required skill the candidate has appears somewhere in the resume in the job "
            "description's own wording",
            "Every required skill the candidate has is named in the job description's wording in "
            "a bullet or a skills line, and the summary and skills section lead with the terms "
            "the job description leads with",
        ],
    ),
    "clarity_structure": Score(
        instructions="How easy is `candidate_resume` to scan and read quickly?",
        criteria=[
            "Disorganized: employers, titles, and dates are hard to find or missing",
            "Understandable but dense: long paragraphs and inconsistent formatting",
            "Clear sections and mostly consistent bullets, with detail buried in places",
            "Tight sections, consistent one-idea bullets, easy to skim in a few seconds",
            "Immediately scannable: sharp summary, consistent bullets, no filler or repetition",
        ],
    ),
    "impact_ownership": Score(
        instructions=(
            "How clearly does `candidate_resume` show the candidate's own actions and their "
            "effect, rather than duties they were assigned?"
        ),
        criteria=[
            "Duties only: 'responsible for', 'involved in', or a list of tools, with no sign of "
            "what the candidate did",
            "Mostly duties and collaboration, with the candidate's own actions left out even "
            "where `original_resume` states them",
            "Action verbs appear, but most bullets stop at the activity and never say what changed",
            "Most bullets open with a verb of doing and say what the candidate's work changed",
            "Every bullet pairs the candidate's own action with what changed, claiming only the "
            "scope `original_resume` supports",
        ],
    ),
}

WEIGHTS: dict[str, float] = {
    "jd_alignment": 0.30,
    "evidence_quality": 0.25,
    "jd_keyword_coverage": 0.20,
    "clarity_structure": 0.15,
    "impact_ownership": 0.10,
}

assert set(WEIGHTS) == set(DIMENSIONS), "every dimension needs a weight"
assert abs(fsum(WEIGHTS.values()) - 1.0) < 1e-9, "weights must sum to 1"

# ── Fabrication guardrails ────────────────────────────────────────────────────
# Judged over the whole draft. Each is phrased so that a high value means "the writer
# added something the original resume does not support".

GUARDRAILS: dict[str, Noul] = {
    "invents_metrics": Noul(
        instructions=(
            "Does `candidate_resume` state any number, percentage, scale, or duration that "
            "`original_resume` does not support?"
        ),
        criteria=NoulCriteria(
            true="It uses a figure or a scale that the original resume never states or implies.",
            false="Every figure in it is stated in the original resume, or it adds no figures.",
        ),
    ),
    "invents_facts": Noul(
        instructions=(
            "Does `candidate_resume` name any employer, job title, date, degree, certification, "
            "or technology that `original_resume` does not mention?"
        ),
        criteria=NoulCriteria(
            true="At least one factual item is new, and the original resume does not imply it.",
            false=(
                "Every employer, title, date, degree, certification, and technology is either in "
                "the original resume or directly implied by it."
            ),
        ),
    ),
    "inflates_scope": Noul(
        instructions=(
            "Does `candidate_resume` claim more seniority, scope, team size, or leadership than "
            "`original_resume` supports?"
        ),
        criteria=NoulCriteria(
            true="It upgrades the candidate's level, ownership, or scale beyond the original.",
            false="Its claims about level, ownership, and scale match the original resume.",
        ),
    ),
}

# ── Actionable direction for the writer ───────────────────────────────────────

BIGGEST_GAP = Choice(
    instructions=(
        "Which single dimension of `candidate_resume` has the most room to improve as an "
        "application for `job_description`?"
    ),
    criteria={
        "jd_alignment": "The resume is not aimed at this role: the relevant work is buried, "
        "unlabelled, or told in the candidate's own vocabulary.",
        "evidence_quality": "Bullets state activity or duties where the original resume offers "
        "figures, results, or scope.",
        "jd_keyword_coverage": "Required skills the candidate has are named in other words, so "
        "they are easy to miss.",
        "clarity_structure": "Layout, ordering, or bullet style makes the resume hard to scan.",
        "impact_ownership": "Bullets do not make the candidate's own action and its effect clear.",
    },
)

LINE_QUESTION = "Is every factual claim in `candidate_line` supported by `original_resume`?"
LINE_CRITERIA = NoulCriteria(
    true=(
        "`candidate_line` restates something `original_resume` says or directly implies, or it "
        "makes no factual claim at all (a heading, section label, or contact detail)."
    ),
    false=(
        "`candidate_line` asserts a fact, figure, title, date, employer, degree, or technology "
        "that `original_resume` does not state or imply."
    ),
)

CLAIM_QUESTION = "Is this specific claim supported by `original_resume`?"
CLAIM_CRITERIA = NoulCriteria(
    true="The claim is stated or directly implied by the original resume.",
    false="The claim asserts something the original resume does not state or imply.",
)

# ── Source-line evidence ───────────────────────────────────────────────────────
# For each draft line, one Choice identifies which original line is its source.
# Code finds candidates by word overlap; the judgment picks, copies verbatim text.

_SKIP_WORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "was", "are", "have",
    "been", "their", "its", "will", "can", "also", "more", "into", "than", "has",
})


def source_question_id(index: int) -> str:
    """Answer id for the source-line evidence question about draft line ``index``."""
    return f"src_{index:02d}"


def _candidate_sources(
    draft_line: str, original_lines: tuple[str, ...], max_n: int = 12
) -> tuple[str, ...]:
    """Return at most max_n original lines ranked by significant-word overlap with draft_line."""
    def sig_words(text: str) -> frozenset[str]:
        return frozenset(
            w.lower().rstrip(".,;:!?'\"")
            for w in text.split()
            if len(w) >= 4 and w.lower() not in _SKIP_WORDS
        )

    draft_words = sig_words(draft_line)
    if not draft_words:
        return original_lines[:max_n]
    ranked = sorted(original_lines, key=lambda ln: -len(draft_words & sig_words(ln)))
    with_overlap = tuple(ln for ln in ranked if draft_words & sig_words(ln))
    return with_overlap[:max_n] if with_overlap else original_lines[:max_n]

# Conjunctions that often separate independent factual claims within a bullet.
_CLAIM_SPLIT_RE: re.Pattern[str] | None = None


def _get_split_re() -> re.Pattern[str]:
    global _CLAIM_SPLIT_RE
    if _CLAIM_SPLIT_RE is None:
        _CLAIM_SPLIT_RE = re.compile(
            r"\s*(?:;\s*|\s+and\s+|\s+while\s+|\s+which\s+|\s*,\s+(?=[A-Z][a-z]))\s*"
        )
    return _CLAIM_SPLIT_RE


def split_claims(line: str) -> tuple[str, ...]:
    """Split one resume line into atomic claims for fine-grained grounding.

    Short lines and headings are returned as-is.  Longer lines are split on
    ``; and while which , <Capital>`` boundaries so each factual clause can be
    verified independently.
    """
    if len(line) < MIN_CLAIM_CHARS * 3:
        return (line,)
    parts = _get_split_re().split(line)
    return tuple(p.strip() for p in parts if len(p.strip()) >= MIN_CLAIM_CHARS)


def claim_question_id(line_index: int, claim_index: int) -> str:
    return f"claim_{line_index:02d}_{claim_index:02d}"


def line_question_id(index: int) -> str:
    """Answer id for the grounding question about audited line ``index``."""
    return f"line_{index:02d}"


def build_questions(
    lines: tuple[str, ...] | list[str],
    original_lines: tuple[str, ...] | None = None,
    requirements: tuple[str, ...] | None = None,
    rulebook: RuleBook | None = None,
) -> dict[str, Noul | Choice | Score]:
    """All questions for one round, in a single request (they run in parallel).

    For lines with multiple atomic claims, we add a per-claim Noul in addition to the
    per-line Noul so that a fabricated clause inside an otherwise true bullet is caught.

    When ``original_lines`` is provided, a ``Choice`` question is added for each line
    to identify which original resume line is its primary source.

    When ``requirements`` is provided, a ``Noul`` question is added for each JD
    requirement to measure whether the draft addresses it.
    """
    active_rulebook = BUILTIN_RULEBOOK if rulebook is None else rulebook
    questions: dict[str, Noul | Choice | Score] = {}
    questions.update(DIMENSIONS)
    questions.update(GUARDRAILS)
    questions["biggest_gap"] = BIGGEST_GAP
    questions.update(rule_questions(active_rulebook))
    questions.update(line_questions(lines))
    for index, line in enumerate(lines):
        # Source-line evidence: which original line backs this draft line?
        if original_lines:
            candidates = _candidate_sources(line, original_lines)
            if candidates:
                criteria: dict[str, str] = {str(i): candidates[i] for i in range(len(candidates))}
                criteria["none"] = (
                    "No line in the original resume is the primary source for this claim."
                )
                questions[source_question_id(index)] = Choice(
                    instructions={
                        "draft_line": line,
                        "question": (
                            "Which line in the original resume is the primary source"
                            " for this draft line?"
                        ),
                    },
                    criteria=criteria,
                )
    # Coverage matrix: which draft line addresses each JD requirement?
    if requirements and lines:
        line_criteria: dict[str, str] = {str(i): line for i, line in enumerate(lines)}
        line_criteria["none"] = "No line in the candidate resume addresses this requirement."
        for req_idx, req in enumerate(requirements):
            questions[coverage_question_id(req_idx)] = Choice(
                instructions={
                    "requirement": req,
                    "question": (
                        "Which line in `candidate_resume` best addresses this job requirement?"
                    ),
                },
                criteria=line_criteria,
            )
    return questions


def rule_question_id(rule_id: str) -> str:
    return f"rule_{rule_id}"


def rule_questions(rulebook: RuleBook) -> dict[str, Noul]:
    questions: dict[str, Noul] = {}
    for rule in rulebook.ordered():
        if rule.check != "jev":
            continue
        questions[rule_question_id(rule.id)] = Noul(
            instructions={
                "rule": rule.text,
                "question": "Does `candidate_resume` violate this rule?",
            },
            criteria=NoulCriteria(
                true=f"`candidate_resume` violates this rule: {rule.text}",
                false=f"`candidate_resume` follows this rule: {rule.text}",
            ),
        )
    return questions


def line_questions(lines: tuple[str, ...] | list[str]) -> dict[str, Noul]:
    """One grounding ``Noul`` per line, plus one per atomic claim of a multi-claim line.

    Indexed against ``lines`` itself, not the draft, so the same ids answer for a round
    (over the lines that changed) and for the page's live lint (over the lines just edited).
    """
    questions: dict[str, Noul] = {}
    for index, line in enumerate(lines):
        questions[line_question_id(index)] = Noul(
            instructions={"candidate_line": line, "question": LINE_QUESTION},
            criteria=LINE_CRITERIA,
        )
        claims = split_claims(line)
        if len(claims) > 1:
            for claim_index, claim in enumerate(claims):
                questions[claim_question_id(index, claim_index)] = Noul(
                    instructions={"candidate_line": claim, "question": CLAIM_QUESTION},
                    criteria=CLAIM_CRITERIA,
                )
    return questions


def claim_lines(resume: str, limit: int = MAX_AUDIT_LINES) -> tuple[str, ...]:
    """The auditable lines of a resume: real content, not blank lines or short headings."""
    lines = []
    for raw in resume.splitlines():
        line = raw.strip().lstrip("-•*–—·").strip()
        if len(line) < MIN_CLAIM_CHARS or not any(character.isalpha() for character in line):
            continue
        lines.append(line)
        if len(lines) == limit:
            break
    return tuple(lines)


def split_requirements(jd: str, limit: int = MAX_REQUIREMENTS) -> tuple[str, ...]:
    """Extract individual requirements from a job description.

    Only lines classified as requirements or responsibilities are candidates for the
    coverage matrix; boilerplate such as "About us" is kept out of it.
    """
    return tuple(item["text"] for item in _posting_items(jd, limit) if item["section"] != "boilerplate")


def posting_report(
    job_description: str,
    draft: str,
    *,
    original_resume: str | None = None,
    limit: int = MAX_REQUIREMENTS,
) -> dict[str, Any]:
    items = _posting_items(job_description, limit)
    relevant = [item for item in items if item["section"] != "boilerplate"]
    salient = _salient_terms(item["text"] for item in relevant)
    draft_hits = [term for term in salient if _contains_term(draft, term)]
    supported_missing = []
    if original_resume is not None:
        supported_missing = [
            term
            for term in salient
            if _contains_term(original_resume, term) and not _contains_term(draft, term)
        ]
    return {
        "requirements": relevant,
        "sections": {
            "requirements": [item["text"] for item in items if item["section"] == "requirements"],
            "responsibilities": [item["text"] for item in items if item["section"] == "responsibilities"],
            "boilerplate": [item["text"] for item in items if item["section"] == "boilerplate"],
        },
        "keywords": {
            "salient": salient,
            "named_in_draft": draft_hits,
            "supported_missing": supported_missing,
        },
    }


def _posting_items(jd: str, limit: int) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    relevant_count = 0
    section = "unstructured"
    for raw in jd.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        heading = _posting_heading(stripped)
        if heading is not None:
            section = heading
            continue
        line = stripped.lstrip("-•*–—·1234567890.)").strip()
        if len(line) < 20 or not any(char.isalpha() for char in line):
            continue
        kind = _posting_section_for_line(line, section)
        priority = _posting_priority(line, kind)
        items.append({"text": line, "section": kind, "priority": priority})
        if kind != "boilerplate":
            relevant_count += 1
            if relevant_count == limit:
                break
    return items


def _posting_heading(line: str) -> str | None:
    normalized = line.strip().rstrip(":").lower()
    for marker, kind in _POSTING_HEADINGS.items():
        if marker in normalized:
            return kind
    return None


def _posting_section_for_line(line: str, current_section: str) -> str:
    lowered = line.lower()
    if current_section in ("requirements", "responsibilities", "boilerplate"):
        return current_section
    if lowered.startswith(_POSTING_BOILERPLATE_PREFIXES):
        return "boilerplate"
    if any(token in lowered for token in ("responsible for", "you will", "build", "design", "lead ")):
        return "responsibilities"
    return "requirements"


def _posting_priority(line: str, section: str) -> str:
    lowered = line.lower()
    if any(token in lowered for token in ("preferred", "nice to have", "bonus", "plus")):
        return "nice_to_have"
    if section == "responsibilities":
        return "responsibility"
    return "must_have"


def _salient_terms(lines: list[str] | tuple[str, ...] | Any, limit: int = 12) -> list[str]:
    counts: Counter[str] = Counter()
    for line in lines:
        words = [
            word.lower()
            for word in re.findall(r"[A-Za-z][A-Za-z0-9+#./-]*", line)
            if len(word) >= 3 and word.lower() not in _POSTING_STOPWORDS
        ]
        counts.update(words)
    return [term for term, _ in counts.most_common(limit)]


def _contains_term(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text, flags=re.IGNORECASE) is not None


def coverage_question_id(index: int) -> str:
    """Answer id for the coverage question about JD requirement ``index``."""
    return f"cov_{index:02d}"


# ── The review ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AuditedLine:
    """One line of the draft, and JEV's probability that the original resume supports it."""

    text: str
    support: float
    # The specific atomic claim that failed, when claim-level splitting was used
    failing_claim: str | None = None
    # All atomic claims and their individual support probabilities (empty for carried lines)
    claims: tuple[tuple[str, float], ...] = ()

    @property
    def unsupported(self) -> bool:
        return self.support < LINE_SUPPORT_FLOOR


@dataclass(frozen=True)
class Review:
    """What JEV said about one draft, in the terms the loop acts on."""

    scores: dict[str, float]
    confidences: dict[str, float]
    levels: dict[str, int]
    quality: float
    guardrails: dict[str, float]
    lines: tuple[AuditedLine, ...]
    reused_lines: int
    biggest_gap: str
    biggest_gap_confidence: float
    gap_distribution: dict[str, float]
    metrics: RequestMetrics
    rulebook: RuleBook
    rules: tuple[RuleResult, ...]
    # draft_line_text → original_line_text (None when no original line supports it)
    evidence: dict[str, str | None] = field(default_factory=dict)
    # requirement_text → draft_line_text that addresses it (None when uncovered)
    coverage: dict[str, str | None] = field(default_factory=dict)

    @property
    def line_grounding(self) -> float:
        """Mean support across the audited lines."""
        return fmean(line.support for line in self.lines) if self.lines else 1.0

    @property
    def weakest_line(self) -> AuditedLine | None:
        """The line JEV is least sure the original resume supports."""
        return min(self.lines, key=lambda line: line.support, default=None)

    @property
    def flagged_lines(self) -> tuple[str, ...]:
        """The claims that must be rewritten or deleted before this draft can ship."""
        return tuple(line.text for line in self.lines if line.unsupported)

    @property
    def fabrication_risk(self) -> float:
        """The loudest signal: the worst guardrail, the spread of bad lines, or the worst line.

        A mean over the lines would let one invented claim hide among twenty grounded
        ones, so the weakest line counts at full strength as soon as it falls below the
        support floor.
        """
        weakest = self.weakest_line
        worst_line_risk = 0.0
        if weakest is not None and weakest.unsupported:
            worst_line_risk = 1 - weakest.support
        return max(max(self.guardrails.values()), 1 - self.line_grounding, worst_line_risk)

    @property
    def groundedness(self) -> float:
        """How much of the quality score survives the fabrication gate."""
        return 1 - self.fabrication_risk

    @property
    def overall(self) -> float:
        """Quality, gated by grounding: a draft that invents things cannot score well."""
        return self.quality * self.groundedness

    @property
    def blocked(self) -> bool:
        """True when the draft must fix its grounding before anything else."""
        return self.fabrication_risk >= FABRICATION_BLOCK

    @property
    def low_confidence(self) -> tuple[str, ...]:
        """Dimensions JEV answered without much confidence, so the draft is under-specified."""
        return tuple(name for name, c in self.confidences.items() if c < CONFIDENCE_FLOOR)

    @property
    def violations(self) -> tuple[RuleResult, ...]:
        return tuple(result for result in self.rules if result.state == "violated")

    @property
    def blocking_violations(self) -> tuple[RuleResult, ...]:
        by_id = {rule.id: rule for rule in self.rulebook}
        return tuple(
            result
            for result in self.violations
            if by_id[result.rule_id].severity == "blocking"
        )

    @property
    def advisory_violations(self) -> tuple[RuleResult, ...]:
        by_id = {rule.id: rule for rule in self.rulebook}
        return tuple(
            result
            for result in self.violations
            if by_id[result.rule_id].severity == "advisory"
        )

    @property
    def weakest(self) -> str:
        """The lowest-scoring dimension, relative to its top level."""
        return min(self.scores, key=lambda name: self.scores[name] / TOP_LEVEL)

    def lines_to_review(self, limit: int = MAX_REPORTED_LINES) -> tuple[AuditedLine, ...]:
        """The lines whose support is low enough to be worth quoting back to the writer."""
        weak = sorted(
            (line for line in self.lines if line.support < LINE_REVIEW_FLOOR),
            key=lambda line: line.support,
        )
        return tuple(weak[:limit])

    def agenda(self, limit: int = 3) -> tuple[str, ...]:
        """The dimensions worth working on next: the named gap first, then the lowest ones."""
        ranked = sorted(self.scores, key=lambda name: self.scores[name] / TOP_LEVEL)
        picked: list[str] = []
        for name in (self.biggest_gap, *ranked):
            if name in DIMENSIONS and name not in picked:
                picked.append(name)
            if len(picked) == limit:
                break
        return tuple(picked)

    def rubric_note(self, name: str) -> str:
        """Where this dimension stands in its own rubric, and what the next level asks for.

        A score on its own tells the writer nothing it can act on. The level description it
        sits closest to, and the one above it, is the instruction the score was standing in
        for.
        """
        levels = list(DIMENSIONS[name].criteria)
        level = self.levels.get(name, 0)
        lines = [
            f'  {name} {self.scores[name]:.2f}/4 — level {level} of {TOP_LEVEL}: "{levels[level]}"'
        ]
        if level < TOP_LEVEL:
            lines.append(f'    level {level + 1} asks for: "{levels[level + 1]}"')
        else:
            lines.append("    already at the top level of this rubric")
        return "\n".join(lines)

    @property
    def gap_is_split(self) -> bool:
        """True only when the reviewer is genuinely torn, not when one gap dominates.

        A low ``confidence`` on the Choice is normal when one option leads but the
        alternatives are all plausible, so the margin decides, not the confidence.
        """
        ranked = sorted(self.gap_distribution.values(), reverse=True)
        return len(ranked) > 1 and ranked[0] - ranked[1] < GAP_MARGIN

    def feedback(self) -> str:
        """The review written as the writer's next instruction block."""
        by_id = {rule.id: rule for rule in self.rulebook}
        lines = ["SCORES (0-4, with the weight each carries in the overall number)"]
        for name, weight in WEIGHTS.items():
            lines.append(
                f"  {name}: {self.scores[name]:.2f}/4  weight {weight:.0%}"
                f"  reviewer confidence {self.confidences[name]:.2f}"
            )
        lines.append(
            f"  overall: quality {self.quality:.2f} x groundedness {self.groundedness:.2f}"
            f" = {self.overall:.2f}"
        )
        if self.blocking_violations:
            lines.append("BLOCKING RULE VIOLATIONS (fix these before anything else)")
            for result in self.blocking_violations:
                rule = by_id[result.rule_id]
                probability = ""
                if result.probability is not None:
                    probability = f" [{result.probability:.2f}]"
                lines.append(f"  -{probability} {rule.text}")
                if result.findings:
                    lines.append(f"    evidence: {'; '.join(result.findings)}")
        if self.advisory_violations:
            lines.append("ADVISORY RULE VIOLATIONS")
            for result in self.advisory_violations:
                rule = by_id[result.rule_id]
                lines.append(f"  - {rule.text}")
                if result.findings:
                    lines.append(f"    evidence: {'; '.join(result.findings)}")
        if self.blocked:
            lines.append(
                "BLOCKING: the reviewer judges this draft to contain claims the original resume "
                "does not support. Fix grounding before improving anything else."
            )
        lines.append("FABRICATION CHECKS (probability the check is true; lower is better)")
        for name, probability in sorted(self.guardrails.items(), key=lambda item: -item[1]):
            lines.append(f"  {name}: {probability:.2f}")
        weakest = self.weakest_line
        reused = f" ({self.reused_lines} unchanged from the current best draft)"
        lines.append(
            f"LINE-BY-LINE GROUNDING: {self.line_grounding:.0%} of {len(self.lines)} lines are "
            "supported by the original resume"
            + (f", weakest line {weakest.support:.2f}" if weakest is not None else "")
            + (reused if self.reused_lines else "")
        )
        reported = self.lines_to_review()
        if reported:
            lines.append(
                "  Lines the reviewer is least sure the original resume supports. Rewrite each "
                "so that every claim in it is backed by the original resume, or delete it:"
            )
            for line in reported:
                verdict = "NOT SUPPORTED" if line.unsupported else "tighten"
                lines.append(f"    - [{line.support:.2f} {verdict}] {line.text}")
                if line.failing_claim and line.failing_claim != line.text:
                    lines.append(f"      failing claim: \"{line.failing_claim}\"")
        if self.low_confidence:
            lines.append(
                "  The reviewer was unsure about: "
                + ", ".join(self.low_confidence)
                + ". Make the resume explicit enough for these to be easy to judge."
            )
        # A requirement the draft does not answer is a fact about the candidate, not a gap in
        # the writing: the instruction is to leave it out, because the alternative the writer
        # has is to invent the evidence.
        uncovered = [req for req, line in self.coverage.items() if line is None]
        if uncovered:
            lines.append(
                "REQUIREMENTS WITH NO EVIDENCE IN THIS DRAFT (leave these out; do not invent "
                "support for them)"
            )
            lines.extend(f"    - {req}" for req in uncovered[:MAX_UNCOVERED_IN_FEEDBACK])
        ranked = sorted(self.gap_distribution.items(), key=lambda item: -item[1])
        lines.append("BIGGEST GAP")
        if not self.gap_is_split:
            lines.append(f"  {self.biggest_gap} — address this first.")
        else:
            lines.append(
                "  The reviewer is split between "
                + " and ".join(f"{name} ({probability:.2f})" for name, probability in ranked[:2])
                + " — improve both."
            )
        lines.append("WHERE THESE DIMENSIONS STAND ON THE RUBRIC")
        lines.extend(self.rubric_note(name) for name in self.agenda())
        return "\n".join(lines)


def review(
    client: TypeSafeClient,
    *,
    original_resume: str,
    job_description: str,
    draft: str,
    carried: Mapping[str, float] | None = None,
    carried_evidence: Mapping[str, str | None] | None = None,
    rulebook: RuleBook | None = None,
) -> Review:
    """Score one draft, check it for fabrication, audit its lines, and measure JD coverage.

    One request: every question sees the same state and is answered independently, so the
    line audit costs the question tokens and almost no extra latency.

    ``carried`` holds the support verdicts from the draft this one was revised from. Lines
    that survived unchanged keep their verdict: they are not asked again, which saves input
    tokens and, more importantly, keeps their verdicts from jittering between rounds so the
    only movement in the score comes from what actually changed.

    ``carried_evidence`` holds the source-line mappings from the previous draft.  Lines that
    survived unchanged are not re-asked, so the evidence cost rises only by one Choice per
    changed line.
    """
    active_rulebook = BUILTIN_RULEBOOK if rulebook is None else rulebook
    lines = claim_lines(draft)
    known = carried or {}
    fresh = tuple(dict.fromkeys(line for line in lines if line not in known))
    original_lines = claim_lines(original_resume)
    requirements = split_requirements(job_description)
    state = {
        "original_resume": original_resume,
        "job_description": job_description,
        "candidate_resume": draft,
    }
    response, metrics = timed_call(
        client,
        state=state,
        questions=build_questions(fresh, original_lines, requirements, active_rulebook),
    )
    answers = response.answers

    scores = {name: answers[name].score for name in DIMENSIONS}
    confidences = {name: answers[name].confidence for name in DIMENSIONS}
    levels = {
        name: int(max(answers[name].probabilities, key=answers[name].probabilities.__getitem__))
        for name in DIMENSIONS
    }
    quality = fsum(WEIGHTS[name] * scores[name] / TOP_LEVEL for name in DIMENSIONS)

    guardrails = {name: answers[name].noul for name in GUARDRAILS}

    audited = settle_lines(fresh, lines, answers, known)
    # Extract source-line evidence for fresh lines; carry forward for unchanged ones.
    known_ev: dict[str, str | None] = dict(carried_evidence or {})
    fresh_ev: dict[str, str | None] = {}
    for index, line in enumerate(fresh):
        src_id = source_question_id(index)
        try:
            chosen = answers[src_id].choice
        except (KeyError, AttributeError):
            fresh_ev[line] = None
            continue
        if chosen == "none":
            fresh_ev[line] = None
        else:
            candidates = _candidate_sources(line, original_lines)
            try:
                ci = int(chosen)
                fresh_ev[line] = candidates[ci] if 0 <= ci < len(candidates) else None
            except (ValueError, IndexError):
                fresh_ev[line] = None

    evidence: dict[str, str | None] = {
        line: known_ev[line] if line in known_ev else fresh_ev.get(line)
        for line in lines
    }

    # Coverage: which draft line addresses each JD requirement?
    coverage: dict[str, str | None] = {}
    for req_idx, req in enumerate(requirements):
        cov_id = coverage_question_id(req_idx)
        try:
            chosen = answers[cov_id].choice
        except (KeyError, AttributeError):
            coverage[req] = None
            continue
        if chosen == "none":
            coverage[req] = None
        else:
            try:
                line_idx = int(chosen)
                coverage[req] = lines[line_idx] if 0 <= line_idx < len(lines) else None
            except (ValueError, IndexError):
                coverage[req] = None

    gap = answers["biggest_gap"]
    rules = settle_rules(active_rulebook, draft, answers)
    return Review(
        scores=scores,
        confidences=confidences,
        levels=levels,
        quality=quality,
        guardrails=guardrails,
        lines=audited,
        reused_lines=sum(1 for line in lines if line in known),
        biggest_gap=gap.choice,
        biggest_gap_confidence=gap.confidence,
        gap_distribution=dict(gap.probabilities),
        metrics=metrics,
        rulebook=active_rulebook,
        rules=rules,
        evidence=evidence,
        coverage=coverage,
    )


def settle_rules(
    rulebook: RuleBook,
    draft: str,
    answers: Mapping[str, Any],
) -> tuple[RuleResult, ...]:
    configured = code_checks_for_rulebook(rulebook)
    code_results = {
        result.rule_id: result
        for result in evaluate_rulebook(rulebook, draft, code_checks=configured)
    }
    settled: list[RuleResult] = []
    for rule in rulebook.ordered():
        if rule.check == "jev":
            try:
                probability = answers[rule_question_id(rule.id)].noul
            except (KeyError, AttributeError):
                settled.append(RuleResult(rule_id=rule.id, state="not_checkable"))
                continue
            settled.append(
                RuleResult(
                    rule_id=rule.id,
                    state="violated" if probability >= RULE_VIOLATION_FLOOR else "passed",
                    probability=probability,
                )
            )
            continue
        settled.append(code_results[rule.id])
    return tuple(settled)


def settle_lines(
    fresh: tuple[str, ...],
    lines: tuple[str, ...],
    answers: Mapping[str, Any],
    known: Mapping[str, float],
) -> tuple[AuditedLine, ...]:
    """Turn the per-line and per-claim answers into the audited lines the views read.

    A line takes the probability of its weakest claim, because a bullet with one invented
    clause is not a supported bullet. ``known`` lines were never asked; they keep the
    verdict they already earned.
    """
    settled: dict[str, float] = {}
    failing_claims: dict[str, str | None] = {}
    all_claims: dict[str, tuple[tuple[str, float], ...]] = {}
    for index, line in enumerate(fresh):
        line_support = answers[line_question_id(index)].noul
        claims = split_claims(line)
        if len(claims) > 1:
            claim_supports = [
                answers[claim_question_id(index, ci)].noul for ci in range(len(claims))
            ]
            all_claims[line] = tuple(zip(claims, claim_supports, strict=True))
            weakest = min(range(len(claims)), key=lambda i: claim_supports[i])
            claim_min = claim_supports[weakest]
            if claim_min < line_support:
                settled[line] = claim_min
                failing_claims[line] = claims[weakest] if claim_min < LINE_REVIEW_FLOOR else None
            else:
                settled[line] = line_support
                failing_claims[line] = None
        else:
            all_claims[line] = ((line, line_support),)
            settled[line] = line_support
            failing_claims[line] = None
    return tuple(
        AuditedLine(
            text=line,
            support=known[line] if line in known else settled[line],
            failing_claim=None if line in known else failing_claims.get(line),
            claims=() if line in known else all_claims.get(line, ()),
        )
        for line in lines
    )


def audit_lines(
    client: TypeSafeClient,
    *,
    original_resume: str,
    draft: str,
    carried: Mapping[str, float] | None = None,
) -> tuple[AuditedLine, ...]:
    """Ground the lines of an edited draft — the questions a person's edit can move.

    The page asks this after a debounced edit. It is the same question, floor, and claim
    splitting as a round applied to the lines that changed; the five dimension scores, the
    three guardrails, the gap ``Choice``, the source ``Choice`` and the coverage matrix are
    left out because editing a bullet cannot change them, and asking would be paid for and
    thrown away.
    """
    lines = claim_lines(draft)
    known = carried or {}
    fresh = tuple(dict.fromkeys(line for line in lines if line not in known))
    if not fresh:
        return settle_lines((), lines, {}, known)
    state = {"original_resume": original_resume, "candidate_resume": draft}
    response, _ = timed_call(client, state=state, questions=line_questions(fresh))
    return settle_lines(fresh, lines, response.answers, known)
