"""Resume polisher: any OpenAI-compatible LLM writes, JEV reviews, scores, and guards.

    resume.txt + job_description.txt  ->  polished_resume.txt

The loop is small and the responsibilities are split by role:

``config``    what a run needs: both API keys, the loop's knobs, the input files
``writer``    any OpenAI-compatible LLM: drafts and revises the resume
``judge``     JEV: scores five dimensions, guards three fabrication checks, audits
              every line (and every claim within a line) against the original resume
``loop``      writer -> judge -> keep the best -> repeat, with budget caps and resume
``diff``      line-level diffs between versions
``report``    one payload for every view, built from the run (includes manifest)
``console``   the terminal view
``page``      the HTML view
``server``    a local server for that page, sign-off, and saving a chosen version
``cli``       argument parsing and the wiring between all of the above
``runs``      run persistence, failure taxonomy, and resumption
``audit``     append-only JSONL audit log for human sign-off decisions
``redact``    PII redaction before sending text to external APIs

Typical use::

    from polisher import Settings, load_settings, polish

    settings = load_settings()
    run = polish(settings, resume, job_description)
    print(run.best.review.overall)
"""

from .config import Settings, load_settings, read_input
from .judge import Review, review
from .loop import PolisherRun, Round, polish
from .metrics import LLMCallMetrics, RequestMetrics
from .report import build_manifest, build_report
from .writer import Draft, write_draft

__all__ = [
    "Draft",
    "LLMCallMetrics",
    "PolisherRun",
    "RequestMetrics",
    "Review",
    "Round",
    "Settings",
    "build_manifest",
    "build_report",
    "load_settings",
    "polish",
    "read_input",
    "review",
    "write_draft",
]
