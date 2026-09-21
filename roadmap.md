# Roadmap: from a tool that works to one a person can watch and steer

## Where it stands

The loop works end to end and is honest about what it knows. An LLM writes, JEV scores five
dimensions, guards three fabrication checks, and audits the draft line by line — and now
claim by claim inside each line. Code keeps the best draft and stops when a round stops
paying. Round files, resumability, budgets, a versioned manifest, a live report page with
per-round diffs, a human sign-off gate with an append-only audit log, privacy flags, and
batch mode are all in place, with `ruff` clean and 132 tests passing on a checkout with no
API keys (88% coverage on `polisher/`, including thirteen Playwright tests that load the
page in a browser and click it).

## What this pass changed

The page stopped being a rendering of a payload and started answering the two questions a
reviewer actually has, using judgments the run had already paid for:

- **The claim ledger is on the page.** Every audited line with its grounding probability and
  the atomic claims inside it, with the uncertain band (0.5–0.8) as a state of its own and a
  filter for it. The data has existed since the claim split landed, and was collapsed to a
  mean; the payload now carries it (`review.ledger`, `review.trust`) and the page renders it.
- **The coverage matrix is on the page.** Each job requirement against the draft line that
  answers it, with the unanswered ones left visibly empty and labelled *leave it out rather
  than invent it*. `Review.coverage` was computed every round and never shown.
- **Cost, budget, and trust are on the page.** Tokens and seconds by writer and reviewer,
  the reviewer's share of the bill, a budget meter driven by `--max-tokens`/`--max-seconds`,
  cost per round, and the carried/uncertain/needs-review counts for the winning draft. No new
  inference: all of it is arithmetic over the round records.
- **A draft can be edited and re-checked.** `audit_lines` in `judge.py` asks the line and
  claim questions and nothing else — no scores, no guardrails, no gap or coverage `Choice` —
  and the page sends it only the lines that changed, carrying the rest. **Save edited draft**
  is refused until that check comes back clean, so a hand-edit that invents a figure meets the
  same gate the loop's drafts do. The `/api/check` route that shipped unconnected is now what
  the page calls.
- **A person's rejection reaches the writer.** Already wired, now proven: the loop hands human
  rejections to `rejected_phrasings` on every round, they lead the block, and a line rejected
  by both a person and JEV is listed once.
- **A batch row's link points at a real file.** The index linked to `<out>_report.json`,
  which batch mode never wrote. Each pair now writes the payload it links to, and the index
  says to open it with `--serve-report` instead of implying a live page.
- **Dead state and duplicated logic are gone.** `ReportState.job_description` was set and
  never read; the per-line question building and settling in `judge.py` were written twice
  and are now one implementation shared by a round and the live lint.

## What this review changed

Small defects in the interaction the product is made of:

- **The sign-off gate broke on real resume text.** A flagged line was interpolated into an
  `onclick` attribute, so any line containing a double quote truncated the handler to
  `sendReview(` — the approve/reject buttons did nothing, and the rest of the line leaked
  into the markup as junk attributes. Reproduced in a browser, then fixed by addressing the
  line by position and reading its text back from the payload.
- **A decision vanished when a round landed.** The server applied approve/reject verdicts to
  the payload it held at the time; the next round replaced that payload, so a live run
  silently dropped the badges. Verdicts are now re-applied to every arriving payload.
- **`--log-json` did not log the run.** The formatter read `record.extra`, which never
  exists, so `run_id`, `round`, and `overall` were dropped from every line — traceability
  was claimed and absent. Now verified in the output.
- **A batch aborted on the first unexpected error**, because only `SystemExit` was caught.
  One broken pair no longer stops the rest, and the exit code is the number of failures.
- **`runs/` was tracked in git.** Round files hold a real resume; the directory is now
  git-ignored and the committed test residue is untracked.
- **The README documented six flags** while the tool had sixteen. The table, exit codes,
  run artifacts, batch mode, and privacy are now documented.
- **Tests wrote into the repo** (`runs/test-run-store/`), and a dead `audit_log` parameter on
  `_run_one` implied an audit trail that was not written there. Both are gone.

## Still open from the previous ten

Kept visible rather than quietly dropped, since each one is a promise the README makes:

| Previous item | Open piece |
|---|---|
| 1. Checks in the repo | No browser smoke test — substring assertions cannot see a page error, and one just shipped. Carried into item 1. |
| 2. Labeled eval set | `evals/samples/` is still empty, so `evals/report.md` has no numbers and `judge.py`'s thresholds are still guesses. Items 8 needs its jitter measurement. |
| 3. Ground claims | Implemented, but the planted-clause acceptance test needs the eval samples from item 2. |
| 4. Resumable runs | The exit code is one value, not one per failure class; retry/backoff is delegated to the SDK's `RetryPolicy` rather than configured. |
| 5. Human sign-off | Rejections are logged but never fed back, so the writer can walk back into a phrase a person rejected. Carried into item 4. |
| 6. Cost and latency | The `biggest_gap` Choice is asked every round even when the dimension scores already name the gap; no prompt caching; batch uses threads, not `AsyncTypeSafeClient`. Item 10 puts the cost on screen. |
| 7. Batch mode | No index page over the batch's reports. Carried into item 9. |
| 8. Privacy | Keys still come only from `secrets.toml`, though the SDK documents `TYPESAFE_API_KEY`; retention is documented but not enforced. |
| 9. Versioned runs | No writer-prompt hash, no seed, and no significance band. Carried into item 8. |
| 10. Ship it | No container, no auth when bound off localhost, no file lock on the output, no shutdown that flushes the audit log on `SIGTERM`. |

## The theme of the next ten

The loop is now good at producing a draft. What it is not yet good at is **showing a person
what it knows and letting that person act on it**. The report page renders a payload; it does
not answer the two questions a reviewer actually has — *why does the tool believe this line?*
and *what should I do about it?* — and it cannot be steered.

That is where JEV's cost profile changes the design. Reviewing one round costs a few thousand
reviewer tokens against the writer's tens of thousands, and a review request answers every
question in parallel. A judgment is therefore cheap enough to spend on **interaction**: one
question per hovered line, one per debounced edit, one per flagged item in a triage queue, a
whole evidence search per line in a single request. None of that is affordable with the
writer, so none of it exists yet. Items 2, 5, 6 and 7 are only possible because JEV is cheap;
items 3, 4 and 10 are free, because they rebuild the view from scores the run already paid
for.

Two rules hold the theme together:

- **Keep inference out of the view.** Weight sliders, filters, re-ranking, and triage order
  are code over stored judgments. Changing how a score is *displayed* must never re-run a
  round. The skill's guidance is explicit: score once, then let controls change the view.
- **Keep uncertain judgments visible.** A Noul has no confidence, a Score and a Choice do.
  An interactive view must show the distribution it is summarising, not just a thresholded
  verdict, so a reader can see when the tool is unsure rather than being told.

---

## 1. A browser smoke test, and a page that survives hostile content

**Status: done.** Thirteen Playwright tests serve real payloads, fail on any `pageerror` or
console error, and click approve/reject; the fixtures include double and single quotes,
`</script>`, HTML tags, emoji, an RTL line, and a 400-character bullet. The hostile text now
flows through the ledger and coverage renderers too.

*Why:* a test asserted the page contains `<!doctype html>` and passed while the approve
button was dead for any resume line with a quote in it. Substring assertions cannot see a
broken page; a browser can, and the page is now the part of the product a human touches.

- Add `pytest-playwright` to the dev group and one test that serves a real payload, loads it,
  fails on any `pageerror` or console error, clicks approve and reject, and asserts the badge
  and the audit entry appear.
- Give the fixtures hostile input: double and single quotes, `</script>`, `<b>`, emoji, an
  RTL line, a 400-character bullet, and a resume with no scorable line at all.
- Keep the Python-side payload tests, and run the browser test in CI against the installed
  wheel so packaging problems surface too.

**Done when:** deleting the fix in `page.py` makes the browser test fail, and the test passes
on a clean checkout in CI.

## 2. Show the evidence: the original line behind every claim

**Status: done.** One `Choice` per changed line over code-selected candidates, carried for
unchanged lines, rendered under the diff — and an unsupported line shows that nothing was
found, which is the point.

*Why:* "is this supported?" is the question the whole product rests on, and the page answers
it with a number. A reviewer who cannot see *what* supports a line cannot approve it in
reasonable time, and will approve it without looking.

- For each draft line, have code collect candidate source lines from the original resume,
  then ask JEV to select the supporting span — one `Choice` over line ids per draft line, with
  a `Noul` for "no line supports this". This is the pre-parsed value extraction / line-by-line
  search shape: find candidates in code, let the judgment pick, copy the verbatim text.
- Render it under the diff: click a line, see the original it came from, highlighted. A
  flagged line shows *nothing*, which is the point — the absence is the evidence.
- Carry the selection like the support verdicts are carried today, so an untouched line is
  not re-asked and the view stays cheap to refresh.

**Done when:** every audited line in the page links to the source line JEV selected (or states
plainly that none was found), and a round's cost rises only by the tokens of one extra
question per changed line.

## 3. Rubric controls in the page: re-weight and re-rank without an inference call

**Status: done.** Sliders over the stored per-dimension scores, labelled *re-weighted view —
scores unchanged*, with the values copyable; the loop's own best draft keeps its star.

*Why:* `WEIGHTS` and the thresholds are code, tuned by reading a report. A reviewer with an
opinion about what matters for this role — "structure matters less than impact here" — has no
way to express it and no way to see the consequence.

- Add weight sliders and threshold controls to the page. Every version already carries
  per-dimension scores, levels, and distributions, so recomputing `overall`, re-ranking the
  rounds, and re-deciding "best" is arithmetic in the browser.
- Make the state honest: a view is labelled "re-weighted view, scores unchanged", the
  original weights stay one click away, and the chosen weights are exportable so a run can be
  reproduced under them.
- Only the *view* moves: no request is sent, and the loop's own choice of best draft is left
  alone and still shown.

**Done when:** moving a slider re-ranks the versions and changes which one is highlighted,
with the network panel showing zero requests and the loop's own best draft still identified.

## 4. Let a person steer the next round

**Status: partly done.** A rejection is permanent for the run, is fed to the writer every
round, and lands in `audit.jsonl` with a reviewer and a timestamp — now covered by a test
that fails if the wording is dropped from the instruction block. **Still open:** the
keyboard-driven `j`/`k`, `a`/`r` triage queue, and the "another round, targeting these"
action.

*Why:* a rejection is recorded and then ignored. The writer is explicitly told not to reuse
"phrasings the reviewer rejected in earlier attempts" — but only phrasings JEV rejected, never
ones a human did. That is the difference between a report and a tool.

- Feed human rejections into `rejected_phrasings` for every subsequent round, permanently for
  the run, so a rejected sentence cannot come back.
- Add an approve/reject triage that queues the flagged lines with the evidence from item 2,
  keyboard-driven (`j`/`k`, `a`/`r`), and a "another round, targeting these" action that hands
  the writer the decisions instead of the rubric.
- Attribute each decision to a reviewer and keep them in the append-only log, so a run can be
  replayed: what the model proposed, what a person refused, and what replaced it.

**Done when:** rejecting a line during a live run produces a next round in which that wording
does not appear, and the audit log alone reconstructs who refused what and when.

## 5. A claim ledger that shows uncertainty instead of hiding it

**Status: done for the view.** The ledger renders every audited line with its claims and
probabilities, the 0.5–0.8 band is a distinct state, and *needs attention* / *uncertain* /
*supported* / *unsupported* are one click apart. **Still open:** nothing routes the band
differently from the writer — `lines_to_review` still hands uncertain lines to JEV's
"tighten" instruction.

*Why:* the run already asks one `Noul` per atomic claim and takes the weakest claim in a line
as the line's verdict, but the page collapses all of it to a mean and one weakest line. The
information a reviewer needs — *which* claim in this bullet is the weak one, and how close to
the floor the others are — is computed and thrown away.

- Render every audited claim with its probability, grouped under its line and its dimension,
  as a third state between supported and unsupported: an uncertain band (say 0.5–0.8) that is
  neither a pass nor a fabrication.
- Route the uncertain band to review rather than to the writer, and keep the raw probabilities
  visible next to the band — the self-consistency pattern is exactly this, and it is honest
  about a Noul having no confidence of its own.
- Filter and sort by band, so "show me only what nobody is sure about" is one interaction.

**Done when:** a planted fabricated clause inside an otherwise true bullet is visibly the
weak claim that fails, and a reviewer can filter a run down to its uncertain claims.

## 6. A coverage matrix for the job description

**Status: done for the matrix.** Requirements are split in code, one `Choice` per
requirement runs in the same round request, and the page shows the verdict, the draft line
that answers it, and an empty cell that reads as *leave it out rather than invent it*.
**Still open:** ranking the uncovered requirements by how central they look.

*Why:* `jd_keyword_coverage` is one number for the whole resume, and
`jd_alignment` is one number for the whole application. Neither tells a person which
requirement is unanswered — the one thing they could actually fix.

- Split the job description into its requirements in code (bullets, sentences, "must have"
  lines), then ask one question per requirement: does the draft evidence it, and which lines
  do that? A `Choice` over line ids plus a `Noul` for "no evidence", in one request — the
  same shape as the line-by-line search cookbook, which scores 218 ids against a query at
  once.
- Render a matrix: requirement, verdict, the draft lines that answer it, and an empty cell
  where the candidate simply has no evidence (which must read as "leave it out", not
  "fabricate it" — the writer's rules already say so).
- Rank the uncovered requirements by how central they look, using JEV's probabilities, so the
  page suggests where a round is worth spending.

**Done when:** every requirement in the job description is either linked to the draft lines
that answer it or marked uncovered, and the uncovered list can be handed to the next round.

## 7. Lint the draft as it is edited, at JEV speed

**Status: done.** `✎ Edit` on a reviewed round makes it editable; a 700 ms debounce sends
one request for the lines that changed, with the rest carried, and the verdict lands in the
gutter with the failing claim on hover. Saving is refused while the last check found an
ungrounded line, and the gate is enforced server-side against the checked text.

*Why:* the page is read-only. The moment a person wants to fix one line themselves — usually
the flagged ones — they leave the tool, and the run's judgments stop applying to the text.

- Make the winning version editable in the page, and on a debounced change ask JEV about only
  the lines that changed, carrying the verdicts for everything else exactly as the loop does.
  One request per pause, not per keystroke, and it reuses the carried-verdict machinery that
  already exists.
- Show marginalia in place: unsupported claim, inflated scope, duty-flavoured verb, keyword
  the job description uses and this bullet does not — the semantic linting shape, at a
  fraction of the writer's cost.
- Saving an edit runs the same human sign-off gate as the loop's own drafts: a hand-edited
  line that JEV cannot ground still needs an explicit approval, and still lands in the log.

**Done when:** typing a fabricated figure into the editable draft raises a marginal warning
within about a second, with no writer call, and a hand-edit cannot reach the final artifact
while a flagged line is unresolved.

## 8. Compare two runs, with a band instead of eyeballed numbers

**Status: open.** `--diff-runs` still prints deltas with no band. It needs the labeled eval
set to state the jitter, and inventing a number would be worse than showing none.

*Why:* a score you cannot reproduce is a score you cannot defend. `--diff-runs` prints deltas
from a terminal, and two runs two points apart look different even when the difference is
jitter — which nobody has measured (previous item 2).

- Finish the eval set enough to state the round-to-round jitter per dimension, then use it as
  the significance band in a page view of `--diff-runs`: dimension by dimension, with deltas
  inside the band marked as noise and deltas outside it marked as movement.
- Refuse to compare payloads with different rubric hashes, in the page as well as the CLI, and
  say which criterion changed.
- Add the writer-prompt hash and a seed to the manifest so a comparison covers the writer too,
  and show the two manifests side by side.

**Done when:** two runs of the same inputs are shown as unchanged within the band, a rubric
edit is refused a comparison, and the numbers behind the band are in `evals/report.md`.

## 9. One page for a batch, with a decision queue

**Status: partly done.** The index sorts by what needs a decision (flagged lines, then
fabrication risk), and each row now writes and links the payload it names. **Still open:**
recording decisions from the index — that needs a batch server, and the single-run page
already carries the gate and the log.

*Why:* batch mode runs twenty pairs and prints twenty lines to a terminal. Each pair has its
own report page and nothing links them, which is the same as having no report.

- Add an index page over the batch: one row per pair with its best overall, its weakest
  dimension, its flagged-line count, its cost, and a link to that pair's report.
- Sort it as a *decision queue*, not a leaderboard: pairs with unresolved flagged lines or a
  high fabrication risk first, because those are the ones that need a person.
- Let the index carry the decisions: approve/reject from the list, with the same gate and the
  same audit log, so a reviewer can clear a batch without opening twenty tabs.

**Done when:** 20 pairs produce one page that sorts by what needs a decision, its links open
the right report, and a decision recorded there appears in that run's audit log.

## 10. Put cost, budget, and trust on the screen

**Status: done.** Writer and reviewer tokens by round, the reviewer's share of the run, a
budget meter for `--max-tokens`/`--max-seconds`, and a trust strip counting carried,
uncertain, low-confidence, and needs-a-person — all from the run's own records, no extra
inference call.

*Why:* the product's central claim is that JEV is cheap and the writer is not, and the page
shows one token total. Nothing tells a person how close a run is to its budget, what the
reviewing actually costs, or how much of the score they are supposed to believe.

- Add a budget meter driven by `--max-tokens` and `--max-seconds`: how much is spent, how much
  is left, and what the loop will do when it runs out (stop and keep the best draft, saying so
  in the stop reason).
- Break the cost down per round and per call — writer tokens against reviewer tokens, per
  question — so the reviewer's share of the bill is visible rather than asserted.
- Add a trust strip per version: how many lines were carried (not re-asked), how many
  questions were asked, how many answers came back with low confidence, and how many needed a
  human. A run with many low-confidence answers should look different from one with none.

**Done when:** the page reports cost per round, the reviewer's share of tokens, remaining
budget, and the carried/uncertain/needs-review counts from the run's own metadata, all without
an extra inference call.

---

## Sequencing

1 first: every item after it changes the page, and the page needs a test that can fail before
those changes are safe to make.

2 and 3 next, in that order: 2 is the biggest single gain in trust and needs JEV; 3 is free,
visible, and settles the page's interaction model. 4 then turns both into something a person
can act on, and it closes the promise the previous roadmap left open.

5, 6 and 7 are the JEV-heavy half, and each one gets cheaper once 2's line-id selection and
4's carried verdicts exist — 6 and 7 are the same question shape over different state.

8 needs the eval set, so start the labeling in parallel and let it land when it lands; it
turns every other item from "looks better" into "measured better".

9 and 10 are the ones a team notices. They are cheap, they need no new inference, and they
should follow the interaction model set by 2–4 rather than inventing a second one.
