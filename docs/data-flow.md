# Data flow and privacy

## What leaves the machine

### TypeSafe (JEV reviewer)

The following fields are sent to the TypeSafe API on every review round:

| Field | Sent? | Notes |
|---|---|---|
| `original_resume` | Yes | The source-of-truth text for grounding checks |
| `job_description` | Yes | The target role |
| `candidate_resume` | Yes | The draft being reviewed |
| Per-line text (up to 60 lines) | Yes | Each audited line, as individual Noul questions |

TypeSafe's subprocessor list and data retention policy are at https://typesafe.ai/privacy.

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
- No `polished_resume.txt` is written
- No `UNRESOLVED.md` is written
- No audit log is written
- `--report-json` is silently ignored

All processing happens in memory only.

## Retention

Run artefacts are stored in `runs/<run-id>/`:

- `manifest.json` — version fingerprint (no resume text)
- `round-N.json` — each round's draft, review scores, and metrics
- `audit.jsonl` — human sign-off decisions

To delete a run's data: `resume-polisher --purge runs/<run-id>`

No data is sent to any third party other than the two APIs listed above.

## Subprocessors

| Service | Purpose | Data sent |
|---|---|---|
| TypeSafe | JEV reviewer | resume text, job description, draft lines |
| Writer LLM provider | Draft generation | resume text, job description, feedback |

Configure the writer provider in `secrets.toml` under `[writer]`.
