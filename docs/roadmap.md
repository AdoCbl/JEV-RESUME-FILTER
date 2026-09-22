# Roadmap

The next version of this project should read less like a model debug view and more like a
product that helps a person make a hiring decision quickly. The work falls into three waves:

## wave 1 — better controls, better first read

Shipped in this pass:

1. **Customer rules beside the JD**
   The run can now load an extra TOML rulebook with `--rules rules.toml`. Those rules are
   merged with the built-in general rules so the writer and reviewer both enforce customer
   constraints beside the job description rather than instead of them.
2. **A higher-signal report page**
   The page now leads with four product questions: what to do next, which rules are active,
   whether the draft can be trusted, and how well the draft answers the posting. Raw score
   tables remain available, but they are folded so the first screen is action-oriented.
3. **Tests pinned to the product contract**
   New tests cover merged rulebooks and the new page summary so the UX and quality controls do
   not regress silently.

## wave 2 — stronger resume output

1. **Rule presets for common customers**
   Ship reusable TOML presets for common constraints such as federal resumes, startup resumes,
   recruiter one-pagers, and technical IC roles.
2. **Rules generated from the posting**
   Distill a posting into job-scoped rules such as title fidelity, geography constraints,
   clearance requirements, and forbidden claims, then show them in the same rulebook window.
3. **Structured rewrite agenda**
   Turn the review into a short edit list grouped by: unsupported claims, missing evidence,
   missing requirements, and style cleanups. Feed that structure to both the page and writer.
4. **Evidence-first keyword coverage**
   Prefer terms already supported by the source resume, and explicitly separate “worth adding”
   from “would be invention”.

## wave 3 — a product people can operate daily

1. **First-run onboarding**
   Provide a guided empty state with sample inputs, what each section means, and which actions
   are safe.
2. **Named rulebook management**
   Save, diff, and reuse customer rulebooks across runs. The page should always show which
   policy set produced the output.
3. **Decision queue for batches**
   Turn the batch index into a reviewer work queue with filters for unresolved lines, blocking
   rules, and weak requirement coverage.
4. **Outcome tracking**
   Compare rulebooks, prompts, and scoring changes against evaluation sets so UI polish does not
   come at the cost of resume quality.

## product principles

1. Show one next action before showing ten measurements.
2. Keep general rules, customer rules, and JD evidence visible in one place.
3. Do not reward unsupported optimization; trust stays above polish.
4. Every number on the page should either change a decision or move behind a fold.