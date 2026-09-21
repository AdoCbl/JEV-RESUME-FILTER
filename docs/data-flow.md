# Data flow and privacy

## What leaves the machine

### TypeSafe (JEV reviewer)

The following fields are sent to the TypeSafe API on every review round:

| Field | Sent? | Notes |
|---|---|---|
| `original_resume` | Yes | The source-of-truth text for grounding checks |
| `job_description` | Yes | The target role |
| `candidate_resume` | Yes | The draft being reviewed |
| Candidate source lines | Yes | Up to 12 original-resume lines per draft line, chosen in code by word overlap, as the options of one `Choice` |
| Job requirements | Yes | Up to 20 requirements, split from the job description in code, one `Choice` each |
| Per-line text (up to 60 lines) | Yes | Each audited line, as an individual Noul question |
| Per-claim text | Yes | The clauses of a multi-clause line, one Noul each |

Everything above travels in **one request per round**. TypeSafe's subprocessor list and
data retention policy are at https://typesafe.ai/privacy.

### TypeSafe (live check, only when you edit)

Editing a draft on the page sends that draft to the same endpoint, with one difference:
only the lines that changed are asked about. Unchanged lines keep the verdict they already
had and are sent as context only. No request is made unless you edit, and no writer call is
made at all.

| Field | Sent? | Notes |
|---|---|---|
| `original_resume` | Yes | The grounding source |
| `candidate_resume` | Yes | The edited draft |
| Per-line and per-claim text | Changed lines only | The questions in `judge.line_questions` |

### Writer LLM (any OpenAI-compatible provider)

The following fields are sent to the configured writer provider:

| Field | Sent? | Notes |
|---|---|---|
| `original_resume` | Yes | Included in every writer prompt as the source of truth |
| `job_description` | Yes | The target role |
| `base_draft` | Yes | The current best draft (from round 2 onwards) |
| Reviewer feedback | Yes | The scored feedback from JEV |

The default provider is DeepSeek (`https://api.deepseek.com`). Any OpenAI-compatible
endpoint can be used by setting `base_url` in the `[writer]` section of `secrets.toml`.

## `--redact` mode

When `--redact` is passed, the following patterns are stripped from both inputs before
any text is sent to an API:

- Email addresses → `[EMAIL]`
- Phone numbers (US format) → `[PHONE]`
- HTTP/HTTPS URLs → `[URL]`
- LinkedIn handles → `[LINKEDIN]`
- GitHub handles → `[GITHUB]`
- Street addresses (US format) → `[ADDRESS]`

The writer can still produce sensible structure because the placeholders are stable.
The original, unredacted text is never sent to any API when `--redact` is active.

## `--no-store` mode

When `--no-store` is passed:

- No round files are written to `runs/`
- No `polished_resume.txt` is written by the loop; the page can still be asked to save a
  version, and that is the only thing that writes the output file
- No `UNRESOLVED.md` is written
- No audit log is written, so a decision lives only in the running page
- `--report-json` is ignored, and `--batch` writes no per-pair payload

All processing otherwise happens in memory only.

## Retention

Run artefacts are stored in `runs/<run-id>/`:

- `manifest.json` — version fingerprint (no resume text)
- `round-N.json` — each round's draft, review scores, and metrics
- `audit.jsonl` — human sign-off decisions

To delete a run's data: `resume-polisher --purge runs/<run-id>`

`--batch` additionally writes `<out>_report.json` per pair — the payload its index page
links to — and `<pairs>.index.html`.

No data is sent to any third party other than the two APIs listed above.

## Subprocessors

| Service | Purpose | Data sent |
|---|---|---|
| TypeSafe | JEV reviewer | resume text, job description, draft lines |
| Writer LLM provider | Draft generation | resume text, job description, feedback |

Configure the writer provider in `secrets.toml` under `[writer]`.
