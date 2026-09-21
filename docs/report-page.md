# The report page

`the interface` · every run serves it, on `127.0.0.1`

The page is where a run is read and steered: scores, the claim ledger, the coverage matrix, the
approve/reject decisions, and editing a draft. The terminal is a progress log while the page is
up — one line per round. With `--no-serve` there is no page, so the terminal prints the full
per-round breakdown instead, because it is then the only view of the run there is.

## the server

Every run serves a live page at `http://127.0.0.1:8765` and opens it in your browser; rounds
appear as they finish, so a long run can be watched instead of waited for. `--no-open` serves it
without opening a browser.

The page stays up after the run so you can read it and make the decisions it asks for, which
means a previous run is often still holding the port. A run on the default port steps to the next
free one and says so; `--port N` is honoured exactly, so a busy port there is reported instead of
worked around.

The page listens on `127.0.0.1` with no login and can read the payload and write the output file,
so `--host 0.0.0.0` exposes a resume to anyone who can reach the port. Bind off localhost only
behind something that authenticates. See [data flow](data-flow.md).

Reopen a finished run with `--serve-report <payload.json>`, or `--report-json PATH` to write the
payload for another tool. `--no-store` keeps everything in memory and writes no payload at all.

## the page, in the order a decision is made

| Section | What it answers |
|---|---|
| **verdict ......** | the one number, at display size: `quality × grounded`, where `grounded = 1 − fabrication risk`. Beside it, the delta against the previous round, the biggest gap, and the verdict strip: lines audited, carried rather than re-asked, unsupported, uncertain, low-confidence dimensions, and the weakest line |
| **needs a decision** | every line the reviewer could not ground, with its probability, its failing claim, and **Approve** / **Reject**. The only band that gets the accent colour, because it is the only thing on the page that needs a person |
| **draft** | the selected version diffed against the previous one or against the original, with `source ▸` on each line opening the original line that supports it — or `⊘ no line in the original resume supports this claim` |
| **dimensions** | the five weighted dimensions with their delta and the rubric level each sits at |
| **fabrication checks** | the three guardrails as probabilities, against the block line |
| **grounding ledger** | every audited line with the probability it is grounded, the atomic claims inside it, and the claim that dragged it down. Filter to *needs attention*, *all*, *uncertain*, or *unsupported* |
| **requirement coverage** | each job requirement against the draft line that answers it, with the gaps left visibly empty. An uncovered requirement is an instruction to leave it out, not to invent it |
| **run totals** | tokens and seconds by writer and reviewer, the reviewer's share of the bill, the budget meter when `--max-tokens` or `--max-seconds` is set, and cost per round |

The page, `--report-json`, and the console all render the one payload (`polisher.report.build_report`),
so they cannot disagree.

## states

A line's grounding sits in one of three states, set by the floors in `polisher/judge.py`:

| State | Range | Meaning |
|---|---|---|
| **supported** | `≥ 0.80` | the original resume carries the claim |
| **uncertain** | `0.50 – 0.80` | shown as its own state, not rounded to either side |
| **unsupported** | `< 0.50` | the reviewer could not ground it — this is what "needs a decision" collects |

A draft whose fabrication risk reaches the block line (`0.50`) is **blocked**: it cannot be the
winner until the invented thing is removed.

## keys

| Key | Does |
|---|---|
| `←` `→` | step through the versions (the timeline chips do the same) |
| `h` | hide unchanged diff lines, keeping a marker where they were skipped |
| `c` | compare against the original instead of the previous version |
| `w` | toggle the weights panel |
| `e` | edit the selected draft |

## editing and saving

With `e`, the selected draft becomes editable. A debounced change asks JEV about the lines that
changed and nothing else, and the verdict appears in the gutter — green supported, amber
uncertain, red unsupported, with the failing claim on hover.

**Save edited draft** writes to the output file, but only once its own check came back clean. It
is the same gate the loop's drafts pass, so a hand-edit that still invents a figure cannot ship.

**Save this version** writes the selected version to the output file, which is how you keep a
round the loop did not pick. It is disabled while the run is live, because the loop owns that
file and rewrites it whenever a round becomes the new best.

## decisions

Every flagged line carries an Approve/Reject verdict. Decisions are appended to `audit.jsonl`
(one JSON object per decision, with the reviewer and timestamp) and fed back to the writer, so a
phrasing a person rejected cannot return in a later round.
