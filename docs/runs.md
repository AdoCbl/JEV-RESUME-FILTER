# Runs, outputs, and batch

`one directory per run` · durable by default, avoidable entirely

## what a run leaves behind

Every run writes `runs/<run-id>/`, so a crash or a `Ctrl-C` costs at most the round in flight.
`runs/` is git-ignored on purpose: a round file contains a real resume.

| File | What it holds |
|---|---|
| `manifest.json` | the version fingerprint: git commit, rubric hash, models, weights, thresholds |
| `round-<n>.json` | that round's draft, the reviewer's verdicts, and the per-call costs |
| `audit.jsonl` | append-only log of every human approve/reject, with the reviewer and timestamp |

Continue an interrupted run with `--resume runs/<run-id>`: new rounds are written back into that
same directory, so one run stays in one place, and `--purge runs/<run-id>` removes all of it.

## what a run leaves you

- `polished_resume.txt` — the best draft of the rounds that ran, never the last one.
- `UNRESOLVED.md` — written instead of a clean artifact whenever the winner still has lines the
  reviewer could not ground. Each needs an approve/reject decision on the page before the resume
  is sent anywhere.

Both live wherever `--out` points. The defaults are the sample files in `example/`.

## batch mode

`--batch pairs.csv` takes one row per application (`resume,job_description,out`), runs four at a
time, and gives each pair its own run directory. A broken pair is reported and skipped rather
than aborting the batch.

```csv
resume,job_description,out
resumes/jane.txt,jobs/backend.txt,out/jane-backend.txt
```

Each pair writes its payload next to its output (`<out>_report.json`, openable with
`--serve-report`), and the batch writes `<pairs>.index.html`: a decision queue sorted so pairs
with unresolved flagged lines or fabrication risk come first. `--no-store` writes none of it.

## exit codes

| Code | Meaning |
|---|---|
| 0 | the run finished (stopping early is normal, not a failure) |
| 1 | provider failure — the message names the class (auth, rate limit, timeout, …) |
| N | `--batch`: N pairs failed |

## privacy

A resume is personal data, sent to two third parties. [Data flow](data-flow.md) lists exactly
what leaves the machine and to whom. `--redact` strips email, phone, address, and links before
any request, and `--no-store` writes nothing to disk at all.
