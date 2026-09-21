# Architecture

`one loop, many observers` · the page is the interface

## modules

```
main.py             `uv run main.py` — a two-line entry point
example/            sample inputs and a sample output; replace them with your own
polisher/
  cli.py            argument parsing, and the wiring between everything else
  config.py         secrets.toml, the loop's knobs, the input files
  writer.py         the writer LLM: system prompt, prompt assembly, draft cleanup
  judge.py          JEV: dimensions, weights, guardrails, per-line and per-claim audit,
                    source-line and requirement choices, composite score, live edit audit
  loop.py           writer -> judge -> keep the best -> repeat; the stop rules
  runs.py           run directories, round files, resume, purge
  audit.py          append-only log of human approve/reject decisions
  redact.py         strips contact details before text leaves the machine
  metrics.py        per-call latency and token records
  diff.py           line diffs between versions
  report.py         the single run payload every view reads
  console.py        the terminal view: a progress log while the page is up, the full
                    breakdown when --no-serve leaves the terminal as the only view
  page.py           the HTML view: scores, ledger, coverage, diffs, the edit surface
  server.py         the local server: the page, the payload, decisions, saving, live checks
```

## the loop is pure orchestration

`loop.polish` makes the two calls per round and hands each finished round to an observer.
Printing, file writing, and the page are observers. That is why the loop can be tested with no
API keys, and why the terminal and the browser cannot drift apart: both render
`report.build_report`, the single payload a run produces.

## boundaries worth keeping

- **One payload per run** — `report.build_report` feeds the console, `--report-json`, the page,
  and `--diff-runs`. A new view should read that payload, not re-derive numbers.
- **Nothing in the page is interpolated into HTML** — review buttons carry a line's position,
  never its text, so a resume containing markup cannot escape into the document.
- **Verdicts are carried, not recomputed** — an unchanged line keeps its earned verdict, which
  is what keeps a round's cost proportional to what actually changed.
- **`run_dir()` resolves `RUNS_DIR` at call time** so tests can point runs at a temporary
  directory instead of the repository.

## tests

```bash
uv run ruff check .
uv run pytest                      # no API keys: the fakes are in tests/conftest.py
uv run pytest --cov=polisher --cov-report=term-missing
```

The suite includes browser tests that serve a real payload, load the page in headless Chromium,
and fail on any JavaScript error, dead button, or sideways overflow. Install the browser once;
without it those tests skip locally, and in CI they are required:

```bash
uv run playwright install chromium
```

## packaging

The project is packaged (`uv_build`, `module-root = ""`, `module-name = "polisher"`). Dropping
the build system makes the project "virtual": uv then skips `[project.scripts]`, so
`resume-polisher` stops existing with only a warning. Verify packaging with `uv build --wheel`
and an install into an empty venv, not just `uv run`.
