# Resume Polisher — DeepSeek writes, JEV judges

An iterative resume polisher built on the [TypeSafe AI](https://typesafe.ai) System One API.
An LLM writes; **JEV reviews, scores, and fact-checks** every draft against the original
resume; ordinary code owns the loop, the scoring, and the stop decision.

```
resume.txt + job_description.txt  ->  polished_resume.txt
```

![The report page: the winning round diffed against the original, with the source-line
evidence open, the five dimension scores, the claim ledger, the job-description coverage
matrix, and the run's cost and trust strip](docs/report-page.png)

*Every run serves this page. Here the diff links a bullet to the original line that supports
it, and says plainly when nothing does — which is the reason to believe the score.*

## How a round works

```mermaid
flowchart LR
    W["<b>writer</b> — DeepSeek<br/>drafts or revises the resume"] --> D["draft"]
    D --> R
    subgraph R["reviewer — JEV, one request"]
        direction TB
        S["<b>5 Score</b> — quality dimensions"]
        N["<b>3 Noul</b> — fabrication guardrails"]
        C["<b>1 Choice</b> — biggest remaining gap"]
        L["<b>N Noul</b> — one per draft line:<br/>is it supported by the original?"]
        E["<b>N Choice</b> — which original line<br/>is this draft line's source?"]
        V["<b>M Choice</b> — which draft line<br/>answers each job requirement?"]
        S ~~~ N ~~~ C ~~~ L ~~~ E ~~~ V
    end
    R --> K{"code: keep the best draft,<br/>score it, decide"}
    K -- "still improving" --> W
    K -- "stop" --> O["polished_resume.txt"]
```

Everything JEV knows about a draft arrives in **one request per round** — questions are
evaluated in parallel, so the line-by-line audit costs question tokens and almost no
extra latency.

## JEV's job

| Role | Primitive | What it returns |
|---|---|---|
| **Scorer** | 5 × `Score` (0–4 rubrics) | `jd_alignment`, `evidence_quality`, `jd_keyword_coverage`, `clarity_structure`, `impact_ownership` |
| **Guardrail** | 3 × `Noul` | `invents_metrics`, `invents_facts`, `inflates_scope` — probability the draft added something the original resume does not support |
| **Guardrail** | 1 × `Noul` per draft line, and 1 per clause of a multi-clause line | probability that line, or that clause, is grounded in the original resume |
| **Reviewer** | 1 × `Choice` | `biggest_gap` — which dimension to fix next |
| **Evidence** | 1 × `Choice` per draft line | which of the original's lines (chosen in code by word overlap) is the source, or none |
| **Coverage** | 1 × `Choice` per job requirement | which draft line answers it, or none |

Code turns those judgments into two numbers:

```
quality          = Σ weight × score / 4                       # weights live in judge.py
fabrication_risk = max(worst guardrail, 1 − mean line grounding, weakest unsupported line)
overall          = quality × (1 − fabrication_risk)           # grounding is a gate, not a nudge
```

A draft that is polished but invented scores low, so the loop never settles on one. The
weakest line counts at full strength once it drops below the support floor, because a
mean over twenty lines would let one invented claim hide among nineteen grounded ones.

## The loop

1. The writer drafts (round 1) or revises the **best draft so far**, given JEV's feedback:
   per-dimension scores with the rubric level each one sits at and what the level above
   asks for, the lines whose grounding is weakest (quoted, with probabilities), the biggest
   gap, the requirements the draft does not answer (named so they are left out, not invented),
   the attempt history, and the phrasings JEV and any human reviewer rejected — so it does not
   walk back into a worse draft or reuse wording that failed.
2. JEV scores the draft, runs the fabrication checks across it, and audits its lines.
   A line that survived the revision unchanged keeps the verdict it already earned: it is
   not asked again, which saves input tokens and keeps its verdict from jittering, so score
   movement comes from what actually changed.
3. Code keeps the highest `overall` draft and goes again. A round whose draft comes back
   unchanged is not reviewed at all — the score cannot move — so it is recorded as a flat
   round and counted towards the stop rule.

It stops when either happens:

- **no meaningful improvement** — no round beat the best draft by `min_improvement`
  (default `0.02`) for `patience` consecutive rounds (default `2`), because the writer is
  stochastic and one bad round is not a plateau;
- **max iterations** — 10 rounds by default;
- or earlier, when the draft reaches `target_score` (default `0.90`) without being blocked
  on grounding.

`polished_resume.txt` is always the best draft from the rounds that ran, never the last one.

## Requirements

- Python 3.14+ and [uv](https://docs.astral.sh/uv/)
- A [TypeSafe API key](https://console.typesafe.ai/keys) — JEV, the reviewer
- A [DeepSeek API key](https://platform.deepseek.com/) — the writer

## Setup

```bash
uv sync
```

Create `secrets.toml` (git-ignored):

```toml
[typesafe]
api_key = "YOUR_TYPESAFE_KEY"
# model = "jev-latest"          # optional

[writer]                        # any OpenAI-compatible provider
api_key = "YOUR_DEEPSEEK_KEY"
# model = "deepseek-chat"       # optional
# base_url = "https://api.deepseek.com"

[polish]                        # all optional
# max_iterations = 10
# min_improvement = 0.02
# target_score = 0.90
# patience = 2
# request_timeout = 120.0        # seconds to wait on one model call
# max_retries = 2                # retries per call on a provider error or timeout
```

`[deepseek]` is still accepted as an alias for `[writer]`.

## Run

```bash
uv run main.py
uv run main.py path/to/resume.txt path/to/job_description.txt --out polished_resume.txt
```

The same entry point is installed as `resume-polisher`, so every flag below works as
`uv run resume-polisher …`; `uv tool install .` puts it on your PATH.

The defaults are the files in `example/` (``resume.txt``, ``job_description.txt``,
``polished_resume.txt``); replace them with your own, or pass paths.

Each round prints its dimension scores, guardrail probabilities, the lines JEV could not
support, and the biggest gap. The run ends with the winning round and a token/latency total.

| Flag | What it does |
|---|---|
| `--out PATH` | where to write the winning draft (default `example/polished_resume.txt`) |
| `--port N` | port for the report page (default `8765`) |
| `--host H` | bind address (default `127.0.0.1`) |
| `--no-serve` | skip the page and just run the loop |
| `--report-json PATH` | write the run payload for later, or for another tool |
| `--serve-report PATH` | skip the run and serve a payload written earlier |
| `--max-iterations N` | override the round ceiling |
| `--max-tokens N` | stop the loop once the run has spent N tokens |
| `--max-seconds N` | stop the loop after N seconds |
| `--secrets PATH` | a different secrets file |
| `--resume RUN_DIR` | continue from the last complete round in `runs/<id>/` |
| `--batch PAIRS_CSV` | run many pairs concurrently (see below) |
| `--redact` | strip contact details before anything is sent to an API |
| `--no-store` | keep everything in memory and write nothing to disk |
| `--purge RUN_DIR` | delete a run directory and everything in it |
| `--diff-runs A B` | compare two run payloads dimension by dimension |
| `--log-json` | structured JSON logs, one object per line |

### Run artifacts

Every run writes `runs/<run-id>/`, so a crash or a `Ctrl-C` costs at most the round in
flight:

| File | What it holds |
|---|---|
| `manifest.json` | the version fingerprint: git commit, rubric hash, models, weights, thresholds |
| `round-<n>.json` | that round's draft, the reviewer's verdicts, and the per-call costs |
| `audit.jsonl` | append-only log of every human approve/reject, with the reviewer and timestamp |

`runs/` is git-ignored on purpose: a round file contains a real resume. Continue an
interrupted run with `--resume runs/<run-id>`, and delete one with `--purge runs/<run-id>`.

### What a run leaves you

- `polished_resume.txt` — the best draft of the rounds that ran, never the last one.
- `UNRESOLVED.md` — written instead of a clean artifact whenever the winning draft still has
  lines the reviewer could not ground. Each one needs an approve/reject decision on the page
  before the resume is sent anywhere.

### Batch mode

`--batch pairs.csv` takes one row per application:

```csv
resume,job_description,out
resumes/jane.txt,jobs/backend.txt,out/jane-backend.txt
```

Pairs run concurrently (four at a time) and each gets its own `runs/<id>/`. One broken pair
is reported and skipped rather than aborting the batch, and the exit code is the number of
pairs that failed.

Each pair also writes its payload next to its output (`<out>_report.json`) — open one with
`--serve-report` — and the batch writes `<pairs>.index.html`, a decision queue sorted so
pairs with unresolved flagged lines or fabrication risk come first. With `--no-store`
neither is written.

### Privacy

A resume is personal data and it is sent to two third parties. `docs/data-flow.md` lists
exactly what leaves the machine and to whom. `--redact` strips email, phone, address, and
links before any request; `--no-store` writes nothing to disk at all.

The page listens on `127.0.0.1` and has no login: it can read the run's payload and write
the output file. `--host 0.0.0.0` therefore exposes a resume and its output to anyone who
can reach the port. Bind off localhost only behind something that authenticates.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | the run finished (the loop stopping early is normal, not a failure) |
| 1 | a provider failure — the message names the class (auth, rate limit, timeout, …) |
| N | `--batch`: N pairs failed |

`example/resume.txt` and `example/job_description.txt` are **sample inputs**, and
`example/polished_resume.txt` is a sample of what a run produces; replace them with your
own.

## Report page

Every run serves a live page at `http://127.0.0.1:8765`. Rounds appear as they finish,
so a long run can be watched instead of scrolled.

- **Versions** — the original plus every round, each with its overall score.
- **Undo / Next** — step through the versions, with `←` and `→`; the timeline chips do
the same. The page follows the newest round until you navigate.
- **Diff** — the selected version against the previous one, or against the original
(`c` toggles). `h` hides unchanged lines and keeps the markers where they were skipped.
- **JEV scores** — the five dimensions with the delta against the previous version, the
reviewer's confidence, the three fabrication checks, line grounding, the weakest line, the
biggest gap, and any lines the reviewer could not support.
- **Grounding ledger** — every audited line with the probability it is grounded, the atomic
claims inside it, and the uncertain band (0.5–0.8) shown as its own state between supported
and unsupported. Filter to *needs attention*, *uncertain*, or *unsupported*; the claims
behind a line are the reason a verdict exists, so they are shown rather than summarised.
- **Requirements answered** — the job description's requirements against the draft lines
that answer them, with the gaps left visibly empty. An uncovered requirement is an
instruction to leave it out, not to invent it.
- **Run totals** — tokens and seconds by writer and reviewer, the reviewer's share of the
bill, the budget meter when `--max-tokens` or `--max-seconds` is set, cost per round, and
what to trust in the winning draft: how many lines were carried rather than re-asked, how
many sit in the uncertain band, and how many need a person.
- **Edit** — edit the selected draft in place (`e`). A debounced change asks JEV about the
lines that changed and nothing else, and the verdict appears in the gutter: green grounded,
amber uncertain, red unsupported, with the failing claim on hover. **Save edited draft**
writes the edit to the output file, but only once its own check came back clean — the same
gate the loop's drafts pass, so a hand-edit that still invents a figure cannot ship.
- **Approve / reject** — every flagged line carries a verdict that is appended to
`audit.jsonl` and fed back to the writer, so a phrasing a person rejected cannot return.
- **Save this version** — writes the selected version to the output file, which is how you
keep a round the loop did not pick. The button is disabled while the run is live, because
the loop owns that file and rewrites it whenever a round becomes the new best.

The page is a view over one payload (`build_report`), which is also what `--report-json`
writes and what the console prints, so the terminal and the browser cannot disagree.

## Project structure

```
main.py             `uv run main.py` — a two-line entry point
example/            sample inputs and a sample output; replace with your own
polisher/
  config.py         secrets.toml, the loop's knobs, the input files
  writer.py         DeepSeek: the system prompt, prompt assembly, draft cleanup
  judge.py          JEV: dimensions, weights, guardrails, per-line and per-claim audit,
                    source-line and requirement choices, composite score, live edit audit
  loop.py           writer -> judge -> keep the best -> repeat; the stop rules
  metrics.py        per-call latency and token records
  diff.py           line diffs between versions, for both views
  report.py         the single run payload every view reads
  console.py        the terminal view
  page.py           the HTML view: scores, ledger, coverage, diffs, and the edit surface
  server.py         the local server: the page, the payload, decisions, saving, live checks
  cli.py            argument parsing and the wiring between all of the above
```

The loop is pure orchestration: it makes the two calls per round and hands each finished
round to an observer. Printing, file writing, and the page are observers, which is why the
loop can be tested with no API keys.

## Tuning

- **Weights** — `WEIGHTS` in `judge.py`. Code, not prompts: retune without rerunning inference.
- **Rubrics** — `DIMENSIONS` and `GUARDRAILS` in `judge.py`. Every level describes the
  resume's treatment of the candidate's real evidence, so a better rewrite can always move
  the score; a level no honest rewrite can reach would freeze the loop.
- **Strictness** — `LINE_SUPPORT_FLOOR`, `LINE_REVIEW_FLOOR`, `FABRICATION_BLOCK`, and
  `CONFIDENCE_FLOOR` in `judge.py`.
- **Patience and timeouts** — `[polish]` in `secrets.toml`. `patience` decides how many
  flat rounds are tolerated before stopping, and `request_timeout` / `max_retries` bound
  one model call so a stalled provider cannot hang the loop.
- **Writer policy** — `SYSTEM_PROMPT` in `writer.py`. It carries the rules that matter
  most in practice: never claim authority the original resume does not give (`own`, `led`,
  `drove`), never leave a bullet as a duty (`responsible for`, `involved in`, `helped
  with`) — say what the candidate did instead — and never reword a line the reviewer has
  already accepted, so a round is not spent on cosmetic edits.
- **Writer behavior** — `TEMPERATURE` in `writer.py`.

## Checks

```bash
uv run ruff check .
uv run pytest                      # no API keys needed: the fakes are in tests/conftest.py
uv run pytest --cov=polisher --cov-report=term-missing
```

The suite includes browser tests that serve a real payload, load the page in headless
Chromium, and fail on any JavaScript error, dead button, or sideways overflow. Install the
browser once; without it those tests skip, and in CI they are required:

```bash
uv run playwright install chromium
```
