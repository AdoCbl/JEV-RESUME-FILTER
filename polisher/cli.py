"""Command line: read the inputs, run the loop, print the report, serve the page.

This module is the only place that knows about all the others.
"""

import argparse
import csv
import json
import logging
import shutil
import sys
import threading
import webbrowser
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path

from openai import OpenAIError
from typesafe_sdk import TypeSafeAPIError

from . import config, console, server
from . import report as report_module
from .audit import AuditLog, write_unresolved
from .config import DEFAULT_HOST, DEFAULT_PORT
from .loop import Round, polish
from .redact import redact as redact_text
from .runs import ProviderError, load_rounds, new_run_id, run_dir, save_round, write_manifest

EXAMPLE = Path("example")
_log = logging.getLogger("polisher")

# The attributes ``logging`` puts on every record. Anything else on a record was attached
# by the caller through ``extra=`` and belongs in the JSON line.
_STANDARD_RECORD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)))


def _setup_logging(json_logs: bool) -> None:
    if json_logs:
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        logging.getLogger("polisher").addHandler(handler)
        logging.getLogger("polisher").setLevel(logging.INFO)
    else:
        logging.basicConfig(level=logging.WARNING)


class _JsonFormatter(logging.Formatter):
    """One JSON object per line, carrying whatever the caller attached via ``extra``.

    ``logging`` puts ``extra`` keys straight onto the record as attributes, so the fields
    that make a run traceable (``run_id``, ``round``, provider ``kind``) arrive here even
    though ``record.extra`` itself never exists.
    """

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        data.update(
            {
                key: value
                for key, value in record.__dict__.items()
                if key not in _STANDARD_RECORD_ATTRS
            }
        )
        return json.dumps(data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resume-polisher",
        description="Polish a resume against a job description, with JEV as the reviewer.",
    )
    parser.add_argument("resume", nargs="?", default=EXAMPLE / "resume.txt", type=Path)
    parser.add_argument(
        "job_description", nargs="?", default=EXAMPLE / "job_description.txt", type=Path
    )
    parser.add_argument("--out", default=EXAMPLE / "polished_resume.txt", type=Path)
    parser.add_argument("--secrets", default=Path("secrets.toml"), type=Path)
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--max-tokens", type=int, default=None, help="total token budget (writer+reviewer)")
    parser.add_argument("--max-seconds", type=float, default=None, help="wall-clock budget in seconds")
    parser.add_argument("--report-json", type=Path, default=None, help="write the run payload here")
    parser.add_argument("--serve-report", type=Path, default=None, help="serve a saved payload")
    parser.add_argument("--no-serve", dest="serve", action="store_false", help="skip the report page")
    parser.add_argument(
        "--no-open",
        dest="open_page",
        action="store_false",
        help="serve the report page but do not open a browser at it",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"report page port (default {DEFAULT_PORT}; steps to the next free one if busy)",
    )
    parser.add_argument(
        "--resume",
        dest="run_dir",
        type=Path,
        default=None,
        metavar="RUN_DIR",
        help="resume an interrupted run from its runs/<run-id> directory",
    )
    parser.add_argument("--redact", action="store_true", help="strip PII before sending to APIs")
    parser.add_argument("--no-store", action="store_true", help="keep everything in memory, write nothing to disk")
    parser.add_argument("--purge", type=Path, default=None, metavar="RUN_DIR", help="delete a run directory")
    parser.add_argument("--diff-runs", nargs=2, metavar=("A", "B"), type=Path, help="compare two run payloads")
    parser.add_argument("--batch", type=Path, default=None, metavar="PAIRS_CSV", help="run many pairs from a CSV")
    parser.add_argument("--log-json", action="store_true", help="emit structured JSON logs")
    return parser


def open_report(url: str) -> None:
    """Open the run's page in the default browser.

    Nobody reads a URL out of a terminal before the run finishes — by then the page has two
    rounds of context in it — so the run opens it. A machine with no browser (a server, a
    container, CI) simply returns False, and that is not worth failing a run over.
    """
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - a missing desktop session is not a run failure
        pass


PORT_WALK = 10  # how many ports to try when the default one is taken


def requested_port(args: argparse.Namespace) -> int:
    return DEFAULT_PORT if args.port is None else args.port


def start_report_server(
    state: server.ReportState, host: str, port: int, *, walk: bool
) -> tuple[ThreadingHTTPServer | None, OSError | None]:
    """Bind the report server, stepping to the next free port when the default is taken.

    The server outlives the run so the page stays usable for the decisions that are the
    reason to have a page at all — which means a previous run is often still holding the
    port. Refusing to serve is the wrong answer to that: the page is where a run is read.
    An explicitly requested port is honoured, and its failure reported.
    """
    last: OSError | None = None
    for candidate in range(port, port + (PORT_WALK if walk else 1)):
        try:
            return server.start(state, host=host, port=candidate), None
        except OSError as error:
            last = error
    return None, last


def serve_saved(args: argparse.Namespace) -> None:
    try:
        payload = json.loads(args.serve_report.read_text())
    except FileNotFoundError:
        raise SystemExit(f"{args.serve_report} not found")

    state = server.ReportState(output_path=args.out)
    state.set_report(payload)
    port = requested_port(args)
    httpd, error = start_report_server(state, args.host, port, walk=args.port is None)
    if httpd is None:
        raise SystemExit(f"could not serve on port {port}: {error}")

    url = server.url(httpd, args.host)
    console.print_server(url, moved_from=port if httpd.server_port != port else None)
    if args.open_page:
        open_report(url)
    server.wait()


def diff_runs(a: Path, b: Path) -> None:
    """Print a dimension-by-dimension comparison of two run payloads."""
    try:
        pa = json.loads(a.read_text())
        pb = json.loads(b.read_text())
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))

    mfa = pa.get("manifest", {})
    mfb = pb.get("manifest", {})
    if mfa.get("rubric_hash") and mfb.get("rubric_hash") and mfa["rubric_hash"] != mfb["rubric_hash"]:
        print(
            f"WARNING: rubric hashes differ ({mfa['rubric_hash']} vs {mfb['rubric_hash']})."
            " Scores are not on the same scale."
        )

    def best_review(payload: dict) -> dict | None:
        bi = payload.get("best_index")
        if bi is None:
            return None
        for v in payload.get("versions", []):
            if v.get("index") == bi:
                return v.get("review")
        return None

    ra, rb = best_review(pa), best_review(pb)
    if ra is None or rb is None:
        raise SystemExit("one or both payloads have no best version")

    print(f"\nDiff: {a.name}  vs  {b.name}")
    print(f"  {'dimension':<22} {'A':>6}  {'B':>6}  {'delta':>8}")
    print("  " + "─" * 50)
    for dim in ra.get("scores", {}):
        sa = ra["scores"][dim]["score"]
        sb = rb["scores"].get(dim, {}).get("score", 0.0)
        print(f"  {dim:<22} {sa:6.3f}  {sb:6.3f}  {sb - sa:+8.3f}")
    for key in ("overall", "quality", "groundedness"):
        va = ra.get(key, 0.0)
        vb = rb.get(key, 0.0)
        print(f"  {'[' + key + ']':<22} {va:6.3f}  {vb:6.3f}  {vb - va:+8.3f}")


def purge_run(run_dir_path: Path) -> None:
    if not run_dir_path.exists():
        raise SystemExit(f"{run_dir_path} does not exist")
    shutil.rmtree(run_dir_path)
    print(f"Deleted {run_dir_path}")


def _run_one(
    *,
    settings: config.Settings,
    resume: str,
    job_description: str,
    out: Path,
    run_id: str,
    store: bool,
    state: server.ReportState | None,
    url: str | None,
    report_json: Path | None,
    prior_rounds: list[Round] | None = None,
    human_rejections=None,  # Callable[[], list[str]] | None
    reviewer=None,  # TypeSafeClient | None — shared with server for /api/check
    store_dir: Path | None = None,  # a resumed run writes back into its own directory
) -> dict:
    """Run the polish loop for one (resume, job_description) pair and return the payload."""
    directory = (store_dir or run_dir(run_id)) if store else None
    if directory is not None:
        mf = report_module.build_manifest(settings, run_id=run_id)
        write_manifest(directory, mf)

    paths = {
        "resume": "<redacted>" if settings.redact else str(out.parent / "resume.txt"),
        "job_description": "<redacted>" if settings.redact else str(out.parent / "job_description.txt"),
        "out": str(out),
        "run_id": run_id,
    }
    saved_index: int | None = None

    def snapshot(
        rounds: tuple[Round, ...] | list[Round],
        best: Round | None,
        status: str,
        stop_reason: str | None = None,
    ) -> dict:
        return report_module.build_report(
            settings=settings,
            resume=resume,
            job_description=job_description,
            paths=paths,
            rounds=rounds,
            best=best,
            stop_reason=stop_reason,
            status=status,
            saved_index=state.saved_index if state is not None else saved_index,
            run_id=run_id,
        )

    if state is not None:
        state.set_report(snapshot(prior_rounds or (), None, status="running"))

    def on_round(current: Round, best: Round, rounds: tuple[Round, ...]) -> None:
        nonlocal saved_index
        if current is best:
            if not settings.no_store:
                out.write_text(current.draft.text + "\n")
            saved_index = current.number
            if state is not None:
                state.saved_index = saved_index
        if store and directory is not None:
            save_round(current, directory)
        # With a page up, the terminal is a progress log: the scores and the flagged lines
        # are on the page, and printing them twice does not help anyone.
        console.print_round(
            current, settings, saved_path=out if current is best else None, verbose=url is None
        )
        if state is not None:
            state.set_report(snapshot(rounds, best, status="running"))
        _log.info("round", extra={"run_id": run_id, "round": current.number,
                                   "overall": round(current.review.overall, 4)})

    try:
        run = polish(
            settings, resume, job_description,
            on_round=on_round, prior_rounds=prior_rounds,
            human_rejections=human_rejections,
            reviewer=reviewer,
        )
    except (TypeSafeAPIError, OpenAIError) as exc:
        provider_err = (
            ProviderError.from_typesafe(exc)
            if isinstance(exc, TypeSafeAPIError)
            else ProviderError.from_openai(exc)
        )
        _log.error("provider_error", extra={"run_id": run_id, "kind": provider_err.kind.value,
                                             "msg": str(provider_err)})
        raise SystemExit(f"Provider error [{provider_err.kind.value}]: {provider_err}") from exc

    payload = snapshot(run.rounds, run.best, status="done", stop_reason=run.stop_reason)
    if state is not None:
        state.set_report(payload)
    console.print_result(payload, url=url, verbose=url is None)

    if report_json is not None and not settings.no_store:
        report_json.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"\n  Payload:     {report_json}")

    # Human sign-off: write UNRESOLVED.md if the best draft has unresolved flagged lines
    best_idx = payload.get("best_index")
    if best_idx is not None:
        best_v = next((v for v in payload["versions"] if v.get("index") == best_idx), None)
        if best_v and best_v.get("review"):
            flagged = best_v["review"].get("flagged_lines", [])
            if state is not None:
                unresolved = state.unresolved_flagged()
            else:
                unresolved = flagged  # no server means no decisions were recorded
            if unresolved and not settings.no_store:
                upath = write_unresolved(out, unresolved)
                print(f"\n  ⚠  UNRESOLVED: {len(unresolved)} flagged line(s) need approval → {upath}")

    return payload


def _write_batch_index(results: list[dict], path: Path) -> None:
    """Write a decision-queue HTML index over a completed batch.

    Sorted so pairs with unresolved flagged lines or fabrication risk come first —
    those are the ones that need a reviewer's attention.
    """
    import html as _html

    def _priority(r: dict) -> tuple:
        payload = r.get("payload", {})
        best = next(
            (v for v in payload.get("versions", []) if v.get("index") == payload.get("best_index")),
            None,
        )
        review = best.get("review") if best else None
        flagged = len(review.get("flagged_lines", [])) if review else 0
        risk = review.get("fabrication_risk", 0) if review else 0
        overall = review.get("overall", 0) if review else 0
        return (-flagged, -risk, overall)

    sorted_results = sorted(results, key=_priority)

    rows = []
    for r in sorted_results:
        payload = r.get("payload", {})
        best = next(
            (v for v in payload.get("versions", []) if v.get("index") == payload.get("best_index")),
            None,
        )
        review = best.get("review") if best else None
        overall = f"{review['overall']:.2f}" if review else "—"
        flagged = len(review.get("flagged_lines", [])) if review else "—"
        risk = f"{review.get('fabrication_risk', 0):.2f}" if review else "—"
        weakest_dim = review.get("weakest_dimension", "—") if review else "—"
        status = r.get("status", "?")
        out = _html.escape(r.get("out", ""))
        report_link = ""
        report_json = r.get("report_json", "")
        if report_json:
            report_link = (
                f' <a href="{_html.escape(report_json)}" style="color:#c264ff">'
                f'payload →</a>'
            )
        row_color = "#ff6b6b" if status != "ok" else ("#ffc857" if isinstance(flagged, int) and flagged > 0 else "")
        rows.append(
            f'<tr style="border-bottom:1px solid #272d39">'
            f'<td style="padding:8px 12px;color:{row_color or "#e7eaf0"}">{out}</td>'
            f'<td style="padding:8px 12px;text-align:right">{overall}</td>'
            f'<td style="padding:8px 12px;text-align:right;color:{"#ff6b6b" if isinstance(flagged,int) and flagged else "#e7eaf0"}">{flagged}</td>'
            f'<td style="padding:8px 12px;text-align:right">{risk}</td>'
            f'<td style="padding:8px 12px;color:#98a1b1">{_html.escape(str(weakest_dim))}</td>'
            f'<td style="padding:8px 12px">{status}{report_link}</td>'
            f'</tr>'
        )

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Batch index — {_html.escape(path.stem)}</title>
<style>
body{{margin:0;background:#0e1014;color:#e7eaf0;font:14px/1.55 ui-sans-serif,system-ui,sans-serif}}
h1{{padding:20px;margin:0;font-size:16px}}
table{{width:100%;border-collapse:collapse}}
th{{background:#161a21;padding:8px 12px;text-align:left;font-size:11px;letter-spacing:.08em;
    text-transform:uppercase;color:#98a1b1}}
tr:hover{{background:rgba(255,255,255,.03)}}
</style></head><body>
<h1>Batch: {_html.escape(path.stem)} &nbsp;<span style="color:#98a1b1;font-weight:normal">
  sorted by unresolved flagged lines, then fabrication risk.</span></h1>
<p style="margin:0 20px 14px;color:#98a1b1;font-size:13px">
  Open a pair's page with <code style="color:#e7eaf0">uv run resume-polisher --serve-report &lt;payload&gt;</code>
  — every row wrote one.</p>
<table>
<thead><tr>
  <th>output</th><th>overall</th><th>flagged</th><th>fab risk</th>
  <th>weakest dim</th><th>status</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</body></html>
"""
    path.write_text(html)


def run_batch(args: argparse.Namespace, settings: config.Settings) -> None:
    """Process many (resume, job_description) pairs from a CSV file concurrently."""
    import concurrent.futures

    try:
        rows = list(csv.DictReader(args.batch.open()))
    except FileNotFoundError:
        raise SystemExit(f"{args.batch} not found")

    required = {"resume", "job_description", "out"}
    if rows and not required.issubset(rows[0].keys()):
        raise SystemExit(f"{args.batch} must have columns: {', '.join(sorted(required))}")

    results: list[dict] = []
    failures: list[str] = []
    lock = threading.Lock()

    def process(row: dict) -> None:
        run_id = new_run_id()
        try:
            resume_text = config.read_input(Path(row["resume"]))
            jd_text = config.read_input(Path(row["job_description"]))
            out = Path(row["out"])
            # The index links to each pair's payload, so the pair has to write one:
            # serve it with `--serve-report <file>` to open that pair's page.
            report_path = Path(row.get("report_json") or out.with_name(out.stem + "_report.json"))
            if settings.redact:
                resume_text = redact_text(resume_text)
                jd_text = redact_text(jd_text)
            payload = _run_one(
                settings=settings,
                resume=resume_text,
                job_description=jd_text,
                out=out,
                run_id=run_id,
                store=not settings.no_store,
                state=None,
                url=None,
                report_json=None if settings.no_store else report_path,
            )
        except (SystemExit, Exception) as exc:  # noqa: BLE001 - one bad pair must not kill the batch
            with lock:
                failures.append(f"{row.get('resume', '?')}: {exc}")
                results.append({
                    "run_id": run_id,
                    "out": str(row.get("out", "")),
                    "status": "failed",
                    "error": str(exc),
                })
            return
        with lock:
            results.append({
                "run_id": run_id,
                "out": str(out),
                "status": "ok",
                "best": payload.get("best_index"),
                "payload": payload,
                "report_json": "" if settings.no_store else str(report_path),
            })

    max_workers = min(4, len(rows))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(process, rows))

    print("\n── Batch summary ──────────────────────────────────────────────")
    for r in results:
        mark = "✓" if r["status"] == "ok" else "✗"
        print(f"  {mark} {r['out']}  (run {r['run_id']})")
    if failures:
        print(f"\n{len(failures)} failed:")
        for f in failures:
            print(f"  {f}")

    # Write a decision-queue index page sorted by what needs attention first
    index_path = args.batch.with_suffix(".index.html")
    _write_batch_index(results, index_path)
    print(f"\n  Batch index: {index_path}")

    if failures:
        sys.exit(min(len(failures), 125))


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    _setup_logging(args.log_json)

    if args.purge is not None:
        purge_run(args.purge)
        return

    if args.diff_runs is not None:
        diff_runs(*args.diff_runs)
        return

    if args.serve_report is not None:
        serve_saved(args)
        return

    settings = config.load_settings(args.secrets)
    if args.max_iterations is not None:
        settings = replace(settings, max_iterations=args.max_iterations)
    if args.max_tokens is not None:
        settings = replace(settings, max_tokens=args.max_tokens)
    if args.max_seconds is not None:
        settings = replace(settings, max_seconds=args.max_seconds)
    if args.redact:
        settings = replace(settings, redact=True)
    if args.no_store:
        settings = replace(settings, no_store=True)
    if args.log_json:
        settings = replace(settings, log_json=True)

    if args.batch is not None:
        run_batch(args, settings)
        return

    resume = config.read_input(args.resume)
    job_description = config.read_input(args.job_description)

    if settings.redact:
        resume = redact_text(resume)
        job_description = redact_text(job_description)

    # Resume: the flag names a run directory, which is not the resume file above. Sharing the
    # two under one name made the default run treat its input as a run directory, and made
    # --resume silently do nothing.
    prior_rounds: list[Round] | None = None
    store_dir: Path | None = None
    if args.run_dir is not None:
        prior_rounds = load_rounds(args.run_dir)
        store_dir = args.run_dir
        print(
            f"  Resuming {args.run_dir.name} "
            f"({len(prior_rounds)} completed round{'' if len(prior_rounds) == 1 else 's'})"
        )

    # A resumed run keeps the directory it came from, so the rounds stay in one place and
    # --purge <that directory> still removes the whole run.
    run_id = store_dir.name if store_dir is not None else new_run_id()

    console.print_header(
        settings=settings,
        resume_path=args.resume,
        job_path=args.job_description,
        resume=resume,
        job_description=job_description,
    )

    state: server.ReportState | None = None
    url: str | None = None
    audit_log = AuditLog(
        None if settings.no_store else run_dir(run_id) / "audit.jsonl"
    )

    if args.serve:
        state = server.ReportState(output_path=args.out)
        state.original_resume = resume
        state.on_review = lambda line, verdict: audit_log.record(
            run_id=run_id, line=line, verdict=verdict
        )
        from typesafe_sdk import TypeSafeClient as _TSC

        shared_reviewer = _TSC(**settings.typesafe_client_kwargs())
        state.reviewer = shared_reviewer
        port = requested_port(args)
        httpd, error = start_report_server(state, args.host, port, walk=args.port is None)
        if httpd is None:
            state = None
            shared_reviewer = None
            console.print_server_unavailable(port, error.strerror if error else "unknown")
        else:
            url = server.url(httpd, args.host)
            console.print_server(url, moved_from=port if httpd.server_port != port else None)
            # The page is served before the first round lands; it polls until there is
            # something to show, so opening it now is safe.
            if args.open_page:
                open_report(url)
    else:
        shared_reviewer = None

    _run_one(
        settings=settings,
        resume=resume,
        job_description=job_description,
        out=args.out,
        run_id=run_id,
        store=not settings.no_store,
        state=state,
        url=url,
        report_json=args.report_json,
        prior_rounds=prior_rounds,
        store_dir=store_dir,
        human_rejections=(
            lambda: [ln for ln, v in state.decisions().items() if v == "rejected"]
        ) if state is not None else None,
        reviewer=shared_reviewer,
    )

    if state is not None:
        server.wait()

