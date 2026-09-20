#!/usr/bin/env python3
"""Evaluate JEV's scoring against human-labeled samples.

Usage:
    uv run python evals/run_eval.py [--secrets secrets.toml] [--out evals/report.md]

Each sample in ``evals/samples/`` is a JSON file with:
  original_resume   str
  job_description   str
  draft             str
  human_scores      dict[str, float]  (0–4 per dimension)
  planted_fabrication  str | null      (a specific fabricated clause, if any)

This script reports:
  - Per-dimension mean absolute error and Spearman rank correlation vs human scores
  - Guardrail precision/recall at FABRICATION_BLOCK for planted fabrications
  - Line-level precision/recall at LINE_SUPPORT_FLOOR for planted fabricated lines
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from statistics import mean
from typing import Any

# Add project root to sys.path so we can import polisher without installing.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from typesafe_sdk import TypeSafeClient

from polisher.config import load_settings
from polisher.judge import (
    DIMENSIONS,
    FABRICATION_BLOCK,
    LINE_SUPPORT_FLOOR,
    TOP_LEVEL,
    review,
)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rank correlation (returns None if fewer than 2 samples)."""
    n = len(xs)
    if n < 2:
        return None

    def rank(seq: list[float]) -> list[float]:
        sorted_vals = sorted(enumerate(seq), key=lambda t: t[1])
        ranks = [0.0] * n
        for rank_val, (idx, _) in enumerate(sorted_vals):
            ranks[idx] = float(rank_val + 1)
        return ranks

    rx, ry = rank(xs), rank(ys)
    mx, my = mean(rx), mean(ry)
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    den = math.sqrt(
        sum((v - mx) ** 2 for v in rx) * sum((v - my) ** 2 for v in ry)
    )
    return num / den if den > 0 else 0.0


def load_samples(samples_dir: Path) -> list[dict[str, Any]]:
    samples = []
    for path in sorted(samples_dir.glob("*.json")):
        samples.append(json.loads(path.read_text()))
    return samples


def run_eval(secrets_path: Path, samples_dir: Path, out_path: Path) -> None:
    settings = load_settings(secrets_path)
    client = TypeSafeClient(**settings.typesafe_client_kwargs())

    samples = load_samples(samples_dir)
    if not samples:
        print(f"No samples found in {samples_dir}. Add JSON files to run the eval.")
        return

    # Per-dimension accumulators
    dim_human: dict[str, list[float]] = {dim: [] for dim in DIMENSIONS}
    dim_jev: dict[str, list[float]] = {dim: [] for dim in DIMENSIONS}
    # Fabrication detection accumulators
    fab_tp = fab_fp = fab_fn = fab_tn = 0
    line_tp = line_fp = line_fn = line_tn = 0

    for i, sample in enumerate(samples):
        print(f"  Sample {i + 1}/{len(samples)} … ", end="", flush=True)
        r = review(
            client,
            original_resume=sample["original_resume"],
            job_description=sample["job_description"],
            draft=sample["draft"],
        )
        print(f"overall={r.overall:.2f}")

        human = sample.get("human_scores", {})
        for dim in DIMENSIONS:
            if dim in human:
                dim_human[dim].append(float(human[dim]))
                dim_jev[dim].append(r.scores[dim])

        # Guardrail eval: does JEV block when there is a planted fabrication?
        has_planted = bool(sample.get("planted_fabrication"))
        jev_blocked = r.blocked
        if has_planted:
            if jev_blocked:
                fab_tp += 1
            else:
                fab_fn += 1
        else:
            if jev_blocked:
                fab_fp += 1
            else:
                fab_tn += 1

        # Line-level eval: is the planted fabricated line flagged as unsupported?
        planted_line = sample.get("planted_fabrication_line")
        if planted_line:
            audited_texts = [entry.text for entry in r.lines]
            if planted_line in audited_texts:
                flagged_line = next(
                    (entry for entry in r.lines if entry.text == planted_line), None
                )
                if flagged_line and flagged_line.unsupported:
                    line_tp += 1
                else:
                    line_fn += 1
            else:
                line_fn += 1  # line not audited at all
        elif any(audited_line.unsupported for audited_line in r.lines):
            line_fp += 1
        else:
            line_tn += 1

    # Build report
    lines = [
        "# Eval report",
        "",
        f"Samples: {len(samples)}",
        "",
        "## Per-dimension accuracy",
        "",
        f"{'dimension':<22} {'MAE':>6}  {'Spearman':>9}  {'n':>4}",
        "─" * 50,
    ]
    for dim in DIMENSIONS:
        h, j = dim_human[dim], dim_jev[dim]
        if not h:
            lines.append(f"{dim:<22}   —      —        0")
            continue
        mae = mean(abs(hv - jv) for hv, jv in zip(h, j))
        rho = spearman(h, j)
        rho_str = f"{rho:.3f}" if rho is not None else "  —  "
        lines.append(f"{dim:<22} {mae:6.3f}  {rho_str:>9}  {len(h):>4}")

    def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
        prec = tp / (tp + fp) if (tp + fp) > 0 else float("nan")
        rec = tp / (tp + fn) if (tp + fn) > 0 else float("nan")
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else float("nan")
        return prec, rec, f1

    fab_prec, fab_rec, fab_f1 = _prf(fab_tp, fab_fp, fab_fn)
    line_prec, line_rec, line_f1 = _prf(line_tp, line_fp, line_fn)

    lines += [
        "",
        "## Fabrication guardrail (FABRICATION_BLOCK detection)",
        "",
        f"  precision {fab_prec:.3f}  recall {fab_rec:.3f}  F1 {fab_f1:.3f}",
        f"  TP={fab_tp} FP={fab_fp} FN={fab_fn} TN={fab_tn}",
        "",
        "## Line-level grounding (LINE_SUPPORT_FLOOR detection of planted lines)",
        "",
        f"  precision {line_prec:.3f}  recall {line_rec:.3f}  F1 {line_f1:.3f}",
        f"  TP={line_tp} FP={line_fp} FN={line_fn} TN={line_tn}",
        "",
        "## Constants used",
        "",
        f"  FABRICATION_BLOCK = {FABRICATION_BLOCK}",
        f"  LINE_SUPPORT_FLOOR = {LINE_SUPPORT_FLOOR}",
        f"  TOP_LEVEL = {TOP_LEVEL}",
    ]

    report = "\n".join(lines) + "\n"
    out_path.write_text(report)
    print(f"\nReport written to {out_path}")
    print(report)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate JEV scoring against human labels.")
    parser.add_argument("--secrets", default=Path("secrets.toml"), type=Path)
    parser.add_argument("--samples", default=Path("evals/samples"), type=Path)
    parser.add_argument("--out", default=Path("evals/report.md"), type=Path)
    args = parser.parse_args()
    run_eval(args.secrets, args.samples, args.out)


if __name__ == "__main__":
    main()
