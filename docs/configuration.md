# Configuration

`two keys and a file` · everything else is optional

## secrets.toml

Create `secrets.toml` in the working directory (git-ignored). The keys are the only required
settings:

```toml
[typesafe]
api_key = "YOUR_TYPESAFE_KEY"
# model = "jev-latest"            # optional; defaults to the account default

[writer]                          # any OpenAI-compatible provider
api_key = "YOUR_DEEPSEEK_KEY"
# model = "deepseek-chat"         # optional
# base_url = "https://api.deepseek.com"

[polish]                          # all optional
# max_iterations = 10
# min_improvement = 0.02
# target_score = 0.90
# patience = 2
# request_timeout = 120.0
# max_retries = 2
```

`[deepseek]` is still accepted as an alias for `[writer]`. `--secrets PATH` reads a different
file.

## the loop's knobs

| Setting | Default | Does |
|---|---|---|
| `max_iterations` | `10` | the round ceiling |
| `min_improvement` | `0.02` | gain a round needs to count as progress |
| `target_score` | `0.90` | stop early once reached, if grounding allows |
| `patience` | `2` | flat rounds tolerated before stopping |
| `request_timeout` | `120.0` | seconds to wait on one model call |
| `max_retries` | `2` | retries per call on a provider error or timeout |

## flags

Every flag works as `uv run main.py …` and as the installed `resume-polisher …`.

| Flag | What it does |
|---|---|
| `--out PATH` | where to write the winning draft (default `example/polished_resume.txt`) |
| `--port N` | report page port (default `8765`; steps to the next free one if busy) |
| `--host H` | bind address (default `127.0.0.1`) |
| `--no-serve` | skip the page and just run the loop |
| `--no-open` | serve the page but do not open a browser at it |
| `--report-json PATH` | write the run payload for later, or for another tool |
| `--serve-report PATH` | skip the run and serve a payload written earlier |
| `--max-iterations N` | override the round ceiling |
| `--max-tokens N` | stop the loop once the run has spent N tokens |
| `--max-seconds N` | stop the loop after N seconds |
| `--secrets PATH` | a different secrets file |
| `--rules RULES_TOML` | merge customer-specific rules with the built-in general rulebook |
| `--resume RUN_DIR` | continue an interrupted run, adding to that run's own directory |
| `--batch PAIRS_CSV` | run many pairs concurrently |
| `--redact` | strip contact details before anything is sent to an API |
| `--no-store` | keep everything in memory and write nothing to disk |
| `--purge RUN_DIR` | delete a run directory and everything in it |
| `--diff-runs A B` | compare two run payloads dimension by dimension |
| `--log-json` | structured JSON logs, one object per line |

## tuning

The judgment is code, not prompts, so it can be retuned without re-running inference.

| Knob | Where | Notes |
|---|---|---|
| `WEIGHTS` | `polisher/judge.py` | per-dimension weights; asserted to sum to 1 |
| `DIMENSIONS`, `GUARDRAILS` | `polisher/judge.py` | the rubrics. Every level describes the resume's treatment of the candidate's real evidence, so a better rewrite can always move the score; a level no honest rewrite can reach would freeze the loop |
| `TOP_LEVEL` | `polisher/judge.py` | `4` — every dimension has five levels, numbered 0–4 |
| `LINE_SUPPORT_FLOOR` | `polisher/judge.py` | `0.5` — below this a line counts as unsupported |
| `LINE_REVIEW_FLOOR` | `polisher/judge.py` | `0.8` — below this a line is worth naming for the writer to tighten |
| `CONFIDENCE_FLOOR` | `polisher/judge.py` | `0.6` — below this JEV is unsure of its own answer, so the dimension is flagged |
| `FABRICATION_BLOCK` | `polisher/judge.py` | `0.5` — at or above this the draft is blocked until the invented thing is removed |
| `MAX_REPORTED_LINES`, `GAP_MARGIN` | `polisher/judge.py` | `5` lines quoted back per round; a leading gap under `0.15` is reported as a split, not a focus |
| `SYSTEM_PROMPT` | `polisher/writer.py` | the writer's rules: never claim authority the original does not give (`own`, `led`, `drove`), never leave a bullet as a duty (`responsible for`, `involved in`, `helped with`), and never reword a line the reviewer already accepted |
| `TEMPERATURE` | `polisher/writer.py` | `0.4` |
| `DEFAULT_MODEL`, `DEFAULT_BASE_URL` | `polisher/writer.py` | `deepseek-chat` at `https://api.deepseek.com` |
