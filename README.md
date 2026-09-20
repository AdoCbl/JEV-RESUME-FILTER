# Resume Filter — TypeSafe AI Demo

Screens engineering resumes against explicit criteria using the [TypeSafe AI](https://typesafe.ai) System One API. Jev evaluates all questions in a single request; code owns the scoring, routing, and ranking logic.

## What it covers

| Concept | Description |
|---|---|
| **Score** | Ordered rubric — returns an expected score and probability per level |
| **Noul** | Yes/no probability — e.g. *"Did this candidate work at a startup?"* |
| **Choice** | Classification — picks one option and returns probabilities for all |
| **Composite scoring** | Normalises scores and combines with role-specific weights |
| **Confidence routing** | Flags low-confidence answers for human review |
| **Async batch** | Evaluates a pool of candidates concurrently with `AsyncTypeSafeClient` |
| **Request metrics** | Latency, model, request ID, and token usage via `diagnostics.py` |

## Requirements

- Python 3.14+ and [uv](https://docs.astral.sh/uv/)
- A [TypeSafe API key](https://console.typesafe.ai/keys)

## Setup

```bash
uv sync
```

Add your API key to `secrets.toml` (already git-ignored):

```toml
[typesafe]
api_key = "YOUR_API_KEY_HERE"
```

## Run

```bash
uv run main.py
```

**Demo 1** evaluates one candidate with all three primitives and prints the full probability breakdown, composite scores, and confidence routing verdict.

**Demo 2** evaluates all three candidates concurrently and prints a ranked summary table with aggregated token totals and wall-clock time.

## Project structure

```
main.py         All demos, questions, candidates, and display helpers
diagnostics.py  Reusable timed_call / async_timed_call + RequestMetrics
secrets.toml    API key — never committed
pyproject.toml  Dependencies and ruff config
```

## Linting

```bash
uv run ruff check .
uv run ruff format .
```
