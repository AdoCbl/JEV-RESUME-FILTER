"""The writer: any OpenAI-compatible LLM that drafts and revises the resume.

The writer owns wording, ordering, and emphasis. It does not own truth: the original
resume is the only source of facts, and JEV checks that every round.
"""

import time
from dataclasses import dataclass

from openai import OpenAI

from .metrics import LLMCallMetrics

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com"
TEMPERATURE = 0.4

SYSTEM_PROMPT = """You are a senior resume writer and ATS specialist. \
You rewrite resumes so they win interviews for one specific job description, \
without ever inventing a fact.

Absolute rules:
1. The original resume is the only source of truth. Every employer, job title, date, \
degree, certification, technology, figure, and scope claim in your output must already \
appear there or be directly implied by it.
2. You may rephrase, reorder, merge, split, shorten, and delete. You may not add \
experience, results, skills, or seniority.
3. Never supply a number the original resume does not support. Keep a figure the \
original resume does give inside the bullet it belongs to.
4. Keep the candidate's real level: no inflated titles, team sizes, or ownership.
5. Prefer concrete, specific wording over generic filler. One idea per bullet.
6. Plain text only: no markdown code fences, no tables, no commentary before or after \
the resume.
7. Aim for a focused one-to-two page resume.

Choosing verbs — this is where resumes either lose their strength or tell a lie:
- Prefer the candidate's own verbs from the original resume. They are already grounded \
and already specific: built, wrote, moved, migrated, maintained, ran, fixed, set up, \
reviewed, mentored, reduced.
- Never claim authority the original resume does not give. No own, owned, led, drove, \
spearheaded, architected, directed, managed, or founded unless it says exactly that.
- Never leave a bullet as a duty. "Responsible for X", "Involved in X", "Participated \
in X", and "Helped with X" are the weakest way to describe work. Say what the candidate \
did to X with a verb of doing the original resume supports: "Responsible for the shipment \
tracking API" becomes "Maintained the shipment tracking API", and where the original \
resume also records the work — "Wrote the Python client library", "my part was moving the \
rate-calculation endpoints" — say that instead.
- Where the original resume records only a shared outcome, keep the shared scope: \
"Contributed to a team effort that reduced p95 latency" is honest, claiming the reduction \
alone is not.
- Strength comes from naming what was done, to what, with what result — never from a \
bigger-sounding verb or a longer sentence.
- Never add a qualifier the original resume does not use. No "primary", "expert", or \
"advanced" beside a skill, and keep the qualifiers it does use, such as \
"Kubernetes (basic)".

Shape:
- Keep the summary to three lines at most: what the candidate has done, at what level, and \
what they are aiming at. No duty lists, no bullet-style clause chains.
- Three to six bullets per role, one line each where the original allows. Never pad.
- Keep the candidate's own sections and order. Invent no new sections, and do not repeat \
the same claim in both the summary and a bullet."""


@dataclass(frozen=True)
class Draft:
    """One writer attempt, with what it cost."""

    text: str
    metrics: LLMCallMetrics


def _user_prompt(
    *,
    original_resume: str,
    job_description: str,
    base_draft: str | None,
    feedback: str | None,
    history: str | None,
    rejected: str | None,
) -> str:
    parts = [
        "## ORIGINAL RESUME (the only source of truth)\n" + original_resume.strip(),
        "## JOB DESCRIPTION (the target)\n" + job_description.strip(),
    ]
    if base_draft is None:
        parts.append(
            "## CURRENT BEST DRAFT\nNone yet. Write the first polished draft from the "
            "original resume."
        )
    else:
        parts.append(
            "## CURRENT BEST DRAFT (improve this one and keep what already works)\n"
            + base_draft.strip()
        )
    if feedback:
        parts.append("## REVIEWER FEEDBACK ON THE CURRENT BEST DRAFT\n" + feedback.strip())
    if history:
        parts.append(history)
    if rejected:
        parts.append(rejected)
    parts.append(
        "## TASK\n"
        "Rewrite the resume so it targets the job description as directly as possible while "
        "obeying every rule.\n"
        "Work through the reviewer feedback in order: first remove or ground anything flagged as "
        "unsupported, then fix the biggest gap.\n"
        "Every line you keep must survive a fact check against the original resume.\n\n"
        "## CHANGE DISCIPLINE\n"
        "Spend the round on the biggest gap and on the lines the reviewer named.\n"
        "Leave every bullet the reviewer did not name exactly as it is in the current best "
        "draft, word for word. Do not swap a verb, reorder clauses, or shorten a line for the "
        "sake of editing: a rewrite that changes no fact and no emphasis is a wasted round.\n"
        "If the biggest gap is already addressed as far as the original resume allows, return "
        "the draft unchanged rather than rewording it.\n"
        "Return the complete resume text only."
    )
    return "\n\n".join(parts)


def _clean(text: str) -> str:
    """Drop stray code fences and surrounding whitespace from a model reply."""
    lines = text.strip().splitlines()
    while lines and lines[0].startswith("```"):
        lines.pop(0)
    while lines and lines[-1].strip().startswith("```"):
        lines.pop()
    return "\n".join(lines).strip()


def write_draft(
    client: OpenAI,
    *,
    model: str = DEFAULT_MODEL,
    original_resume: str,
    job_description: str,
    base_draft: str | None = None,
    feedback: str | None = None,
    history: str | None = None,
    rejected: str | None = None,
) -> Draft:
    """Ask the writer for one full draft, optionally revising an earlier one."""
    prompt = _user_prompt(
        original_resume=original_resume,
        job_description=job_description,
        base_draft=base_draft,
        feedback=feedback,
        history=history,
        rejected=rejected,
    )
    started = time.perf_counter()
    completion = client.chat.completions.create(
        model=model,
        temperature=TEMPERATURE,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    latency_ms = (time.perf_counter() - started) * 1000

    text = _clean(completion.choices[0].message.content or "")
    if not text:
        raise RuntimeError("the writer returned an empty draft")

    usage = completion.usage
    return Draft(
        text=text,
        metrics=LLMCallMetrics(
            latency_ms=latency_ms,
            model=completion.model or model,
            prompt_tokens=None if usage is None else usage.prompt_tokens,
            completion_tokens=None if usage is None else usage.completion_tokens,
            total_tokens=None if usage is None else usage.total_tokens,
        ),
    )
