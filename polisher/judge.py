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
from collections.abc import Mapping
from dataclasses import dataclass
from math import fsum
from statistics import fmean

from typesafe_sdk import Choice, Noul, NoulCriteria, Score, TypeSafeClient

from .metrics import RequestMetrics, timed_call

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


def build_questions(lines: tuple[str, ...] | list[str]) -> dict[str, Noul | Choice | Score]:
    """All questions for one round, in a single request (they run in parallel).

    For lines with multiple atomic claims, we add a per-claim Noul in addition to the
    per-line Noul so that a fabricated clause inside an otherwise true bullet is caught.
    """
    questions: dict[str, Noul | Choice | Score] = {}
    questions.update(DIMENSIONS)
    questions.update(GUARDRAILS)
    questions["biggest_gap"] = BIGGEST_GAP
    for index, line in enumerate(lines):
        questions[line_question_id(index)] = Noul(
            instructions={"candidate_line": line, "question": LINE_QUESTION},
            criteria=LINE_CRITERIA,
        )
        # Per-claim questions for multi-claim lines
        claims = split_claims(line)
        if len(claims) > 1:
            for ci, claim in enumerate(claims):
                questions[claim_question_id(index, ci)] = Noul(
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


# ── The review ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AuditedLine:
    """One line of the draft, and JEV's probability that the original resume supports it."""

    text: str
    support: float
    # The specific atomic claim that failed, when claim-level splitting was used
    failing_claim: str | None = None

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
) -> Review:
    """Score one draft, check it for fabrication, and audit its lines.

    One request: every question sees the same state and is answered independently, so the
    line audit costs the question tokens and almost no extra latency.

    ``carried`` holds the support verdicts from the draft this one was revised from. Lines
    that survived unchanged keep their verdict: they are not asked again, which saves input
    tokens and, more importantly, keeps their verdicts from jittering between rounds so the
    only movement in the score comes from what actually changed.
    """
    lines = claim_lines(draft)
    known = carried or {}
    fresh = tuple(dict.fromkeys(line for line in lines if line not in known))
    state = {
        "original_resume": original_resume,
        "job_description": job_description,
        "candidate_resume": draft,
    }
    response, metrics = timed_call(client, state=state, questions=build_questions(fresh))
    answers = response.answers

    scores = {name: answers[name].score for name in DIMENSIONS}
    confidences = {name: answers[name].confidence for name in DIMENSIONS}
    levels = {
        name: int(max(answers[name].probabilities, key=answers[name].probabilities.__getitem__))
        for name in DIMENSIONS
    }
    quality = fsum(WEIGHTS[name] * scores[name] / TOP_LEVEL for name in DIMENSIONS)

    guardrails = {name: answers[name].noul for name in GUARDRAILS}

    # Build per-line support scores, using claim-level minimum when available.
    settled: dict[str, float] = {}
    failing_claims: dict[str, str | None] = {}
    for index, line in enumerate(fresh):
        line_support = answers[line_question_id(index)].noul
        claims = split_claims(line)
        if len(claims) > 1:
            # The line passes only when every claim passes.
            claim_supports = [
                answers[claim_question_id(index, ci)].noul for ci in range(len(claims))
            ]
            weakest_ci = min(range(len(claims)), key=lambda i: claim_supports[i])
            claim_min = claim_supports[weakest_ci]
            if claim_min < line_support:
                settled[line] = claim_min
                failing_claims[line] = claims[weakest_ci] if claim_min < LINE_REVIEW_FLOOR else None
            else:
                settled[line] = line_support
                failing_claims[line] = None
        else:
            settled[line] = line_support
            failing_claims[line] = None

    audited = tuple(
        AuditedLine(
            text=line,
            support=known[line] if line in known else settled[line],
            failing_claim=None if line in known else failing_claims.get(line),
        )
        for line in lines
    )

    gap = answers["biggest_gap"]
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
    )
