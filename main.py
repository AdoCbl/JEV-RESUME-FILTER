import asyncio
import time
import tomllib
from pathlib import Path

from diagnostics import RequestMetrics, async_timed_call, timed_call
from typesafe_sdk import (
    AsyncTypeSafeClient,
    Choice,
    Noul,
    Score,
    TypeSafeAPIError,
    TypeSafeClient,
)


# ── API key ────────────────────────────────────────────────────────────────────

def _load_api_key() -> str:
    try:
        secrets = tomllib.loads(Path("secrets.toml").read_text())
    except FileNotFoundError:
        raise SystemExit("secrets.toml not found — copy the template and fill in your API key")
    return secrets["typesafe"]["api_key"]


# ── Candidate pool ─────────────────────────────────────────────────────────────

CANDIDATES: dict[str, str] = {
    "Alex Rivera": """
Alex Rivera – Staff Software Engineer

Experience:
- 5 years at DataFlow Inc as a Staff Engineer. Led a team of 6 engineers.
  Designed and owned the architecture of a distributed ingestion pipeline
  handling 500K events/second. Drove adoption of Python across the org.
- 2 years at StartupX as a full-stack engineer. Wore many hats: backend,
  infra, data pipelines, and some iOS. Python and Go primary languages.

Skills: Python (expert), Go, Kubernetes, distributed systems, system design.
Education: BSc Computer Science.
""",
    "Jamie Chen": """
Jamie Chen – Junior Software Developer

Experience:
- 1 year at MegaCorp as a software developer. Worked on a small internal
  tool in Python Flask. Fixed bugs in a legacy codebase. No leadership
  responsibilities.

Skills: Python (beginner), JavaScript, basic SQL.
Education: BSc Computer Science, graduated 2025.
""",
    "Morgan Taylor": """
Morgan Taylor – Engineering Manager

Experience:
- 8 years at EnterpriseCloud Inc as Engineering Manager. Managed 3 teams
  of 15 engineers total. Led org-wide developer-productivity initiatives.
  Previously a software engineer for 4 years before moving into management.
  Some Python scripting; not a primary language.
- Strong background in roadmap planning, hiring, and stakeholder management.

Skills: Engineering management, Agile, roadmaps, Python (basic), Java.
Education: MBA, BSc Computer Science.
""",
}


# ── Questions (all 3 primitive types) ─────────────────────────────────────────
# One API call answers all 7 questions simultaneously.

QUESTIONS = {
    # Score — ordered rubric, returns expected score + probability per level
    "python_depth": Score(
        instructions="How much depth of Python experience does this candidate have?",
        criteria=[
            "No Python experience mentioned",
            "Mentioned but no detail",
            "Used in projects, some specifics",
            "Primary language, multiple projects",
            "Deep expertise: architecture, performance, libraries",
        ],
    ),
    "team_leadership": Score(
        instructions="How much experience does this candidate have managing or leading engineering teams?",
        criteria=[
            "No management experience mentioned",
            "Informal mentorship or tech lead role",
            "Led a small team or project",
            "Managed a team with direct reports",
            "Managed multiple teams or an engineering org",
        ],
    ),
    "system_design": Score(
        instructions="How much experience does this candidate have designing large-scale or distributed systems?",
        criteria=[
            "No architecture work mentioned",
            "Contributed to design discussions",
            "Designed components of a larger system",
            "Owned architecture of a significant system",
            "Designed systems at scale across multiple domains",
        ],
    ),
    "generalist": Score(
        instructions="How much evidence is there that this candidate picks up unfamiliar tools, roles, or domains?",
        criteria=[
            "Only one domain or role mentioned",
            "Some variety but within a narrow field",
            "Worked across a few different areas or tech stacks",
            "Regularly moved between domains, wore many hats",
            "Track record of ramping up in unfamiliar areas and delivering",
        ],
    ),
    # Noul — yes/no probability (0 = definitely no, 1 = definitely yes)
    "has_startup_experience": Noul(
        instructions="Did this candidate work at a startup or early-stage company?"
    ),
    "is_senior_ready": Noul(
        instructions="Does this candidate show evidence of readiness for a senior or above engineering role?"
    ),
    # Choice — picks one option and returns probabilities for every option
    "seniority_level": Choice(
        instructions="What engineering seniority level best describes this candidate?",
        criteria={
            "junior":    "0-2 years, works under close supervision",
            "mid":       "2-5 years, works independently on well-defined tasks",
            "senior":    "5+ years, owns features end-to-end, mentors others",
            "staff":     "Cross-team technical leadership, sets direction",
            "principal": "Org-wide or industry-wide technical influence",
        },
    ),
}

CONFIDENCE_FLOOR = 0.6  # answers below this are flagged for human review


# ── Display helpers ────────────────────────────────────────────────────────────

def _bar(p: float, width: int = 18) -> str:
    filled = round(p * width)
    return "█" * filled + "░" * (width - filled)

def _conf_label(c: float) -> str:
    if c >= 0.85:
        return "HIGH"
    if c >= CONFIDENCE_FLOOR:
        return "MED"
    return "LOW ⚠"

def _print_score(name: str, answer) -> None:
    print(f"  {name}")
    print(f"    score={answer.score:.2f}/4  confidence={answer.confidence:.2f}  [{_conf_label(answer.confidence)}]")
    for level in sorted(answer.probabilities):
        p = answer.probabilities[level]
        desc = str(answer.legend.get(level, level))
        print(f"      {level}  {_bar(p)}  {p:4.0%}  {desc}")
    print()

def _print_noul(name: str, answer) -> None:
    p = answer.noul
    print(f"  {name}")
    print(f"    p(yes)={p:.2f}  {_bar(p)}  {'yes' if p >= 0.5 else 'no'}")
    print()

def _print_choice(name: str, answer) -> None:
    print(f"  {name}")
    print(f"    choice={answer.choice}  confidence={answer.confidence:.2f}  [{_conf_label(answer.confidence)}]")
    for opt, p in sorted(answer.probabilities.items(), key=lambda kv: -kv[1]):
        marker = "◀" if opt == answer.choice else " "
        print(f"    {marker} {opt:<10} {_bar(p)}  {p:4.0%}")
    print()


# ── Shared logic ───────────────────────────────────────────────────────────────

def compute_composite(answers: dict) -> dict[str, float]:
    """Normalizes 0–4 scores to 0–1 and applies role-specific weights."""
    py   = answers["python_depth"].score / 4
    lead = answers["team_leadership"].score / 4
    arch = answers["system_design"].score / 4
    gen  = answers["generalist"].score / 4
    return {
        "Senior IC":   0.40 * py + 0.10 * lead + 0.40 * arch + 0.10 * gen,
        "Eng Manager": 0.15 * py + 0.40 * lead + 0.20 * arch + 0.25 * gen,
    }

def routing_verdict(answers: dict) -> str:
    """Confidence-gated routing: flags any answer below CONFIDENCE_FLOOR."""
    low = [k for k, a in answers.items() if hasattr(a, "confidence") and a.confidence < CONFIDENCE_FLOOR]
    if low:
        return f"⚠  REVIEW — low confidence on: {', '.join(low)}"
    return f"✓  AUTO — all answers exceed confidence floor ({CONFIDENCE_FLOOR})"


# ── Demo 1: one candidate, all 3 primitives, full breakdown ───────────────────

def demo_single_candidate(api_key: str) -> None:
    name = "Alex Rivera"
    print(f"\n{'═' * 64}")
    print(f"  Demo 1 · Single candidate — {name}")
    print(f"  All 3 primitives (Score + Noul + Choice) in one API call")
    print(f"{'═' * 64}\n")

    client = TypeSafeClient(api_key=api_key)
    response, metrics = timed_call(client, state=CANDIDATES[name], questions=QUESTIONS)
    answers = response.answers

    print("── Score answers (expected score + probability per rubric level) ─")
    for q in ("python_depth", "team_leadership", "system_design", "generalist"):
        _print_score(q, answers[q])

    print("── Noul answers (probability that the statement is true) ─────────")
    for q in ("has_startup_experience", "is_senior_ready"):
        _print_noul(q, answers[q])

    print("── Choice answers (selected option + probability per option) ─────")
    _print_choice("seniority_level", answers["seniority_level"])

    print("── Composite scores (weighted combination of normalized scores) ───")
    composites = compute_composite(answers)
    for role, s in composites.items():
        tag = " ← SHORTLIST" if s >= 0.70 else ""
        print(f"  {role:<15} {_bar(s)}  {s:.2f}{tag}")
    print(f"\n  Best fit role: {max(composites, key=composites.__getitem__)}")
    print()

    print("── Confidence-gated routing ──────────────────────────────────────")
    print(f"  {routing_verdict(answers)}\n")

    metrics.report()


# ── Demo 2: async batch ranking of all candidates concurrently ────────────────

async def _evaluate(
    client: AsyncTypeSafeClient, name: str, resume: str
) -> tuple[str, dict[str, float], str, RequestMetrics, str]:
    response, metrics = await async_timed_call(client, state=resume, questions=QUESTIONS)
    answers = response.answers
    return (
        name,
        compute_composite(answers),
        response.choices["seniority_level"].choice,
        metrics,
        routing_verdict(answers),
    )


async def demo_batch_ranking(api_key: str) -> None:
    n = len(CANDIDATES)
    print(f"\n{'═' * 64}")
    print(f"  Demo 2 · Async batch ranking — {n} candidates (concurrent)")
    print(f"  Uses AsyncTypeSafeClient + asyncio.gather for parallelism")
    print(f"{'═' * 64}\n")

    async with AsyncTypeSafeClient(api_key=api_key) as client:
        tasks = [_evaluate(client, nm, res) for nm, res in CANDIDATES.items()]
        t0 = time.perf_counter()
        results = await asyncio.gather(*tasks)
        wall_ms = (time.perf_counter() - t0) * 1000

    ranked = sorted(results, key=lambda r: -r[1]["Senior IC"])

    hdr = f"  {'#':<3}  {'Candidate':<15}  {'Senior IC':>9}  {'Eng Mgr':>7}  {'Seniority':<10}  {'Latency':>8}  Routing"
    print(hdr)
    print(f"  {'─' * (len(hdr) - 2)}")
    for i, (name, composites, seniority, metrics, routing) in enumerate(ranked, 1):
        icon = "✓" if routing.startswith("✓") else "⚠"
        print(
            f"  {i:<3}  {name:<15}  {composites['Senior IC']:>9.2f}"
            f"  {composites['Eng Manager']:>7.2f}  {seniority:<10}"
            f"  {metrics.latency_ms:>7.0f}ms  {icon}"
        )

    total_in  = sum(r[3].input_tokens  or 0 for r in results)
    total_out = sum(r[3].output_tokens or 0 for r in results)
    print(
        f"\n  Batch totals — tokens: {total_in + total_out:,}"
        f" ({total_in:,} in / {total_out:,} out)"
        f"  |  wall-clock: {wall_ms:.0f} ms (concurrent, not summed)"
    )


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    try:
        api_key = _load_api_key()
        demo_single_candidate(api_key)
        asyncio.run(demo_batch_ranking(api_key))
    except TypeSafeAPIError as e:
        print(f"\n✗  API error {e.status}: {e}")


if __name__ == "__main__":
    main()

