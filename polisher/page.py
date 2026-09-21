"""The HTML view: a version timeline, JEV's scores, and a diff of what changed.

One self-contained page — no CDN, no build step. The run payload is embedded for the
first paint and re-fetched from ``/api/report`` while the loop is still running.
"""

import json
from typing import Any

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Resume polisher — report</title>
<style>
:root{
  --bg:#0e1014; --panel:#161a21; --panel2:#1d222c; --border:#272d39;
  --text:#e7eaf0; --muted:#98a1b1; --accent:#c264ff; --good:#3ddc97; --bad:#ff6b6b; --warn:#ffc857;
}
*{box-sizing:border-box}
/* This is a page for a browser window, so it is laid out for one: a hard ceiling so a wide
   monitor does not stretch a diff to 2000px, and two columns from a laptop width up. */
body{margin:0 auto;max-width:1640px;background:var(--bg);color:var(--text);
  font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
header{display:flex;gap:14px;align-items:baseline;flex-wrap:wrap;
  padding:16px 22px;border-bottom:1px solid var(--border)}
h1{margin:0;font-size:15px;letter-spacing:.02em}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:12px 22px;
  border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg);z-index:5}
.sep{width:1px;height:22px;background:var(--border);margin:0 2px}
button{background:var(--panel2);color:var(--text);border:1px solid var(--border);border-radius:8px;
  padding:7px 12px;font:inherit;cursor:pointer;transition:border-color .12s}
button:hover:not(:disabled){border-color:var(--accent)}
button:disabled{opacity:.4;cursor:default}
button.primary{border-color:var(--accent);background:#26183a}
button:focus-visible,.chip:focus-visible,.toggle input:focus-visible,
input[type=range]:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
kbd{background:var(--panel2);border:1px solid var(--border);border-bottom-width:2px;
  border-radius:4px;padding:0 5px;font:inherit;font-size:11.5px}
.toggle{display:flex;gap:6px;align-items:center;color:var(--muted);cursor:pointer;user-select:none}
.timeline{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-left:auto}
/* Below a wide desktop the versions take their own row rather than breaking the row in
   the middle of the actions. */
@media (max-width:1400px){.timeline{flex-basis:100%;margin-left:0}}
.chip{display:flex;gap:7px;align-items:center;border:1px solid var(--border);border-radius:999px;
  padding:4px 10px;font-size:13px;background:var(--panel);cursor:pointer}
.chip.sel{border-color:var(--accent);background:#231535}
.chip .n{color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
/* Two columns: what the draft scored beside what the draft says. The wide column gets the
   text-shaped views (diff, ledger, coverage) because they have the longest strings. The
   sidebar gives way before the text does, and only a genuinely narrow window stacks. */
main{display:grid;grid-template-columns:clamp(300px,26%,380px) minmax(0,1fr);gap:18px;
  padding:18px 22px 34px;align-items:start}
@media (max-width:1000px){main{grid-template-columns:1fr}
  /* Narrow: one column, the draft first, because that is what the page is for. */
  .wide{order:-1}}
.side,.wide{display:flex;flex-direction:column;gap:14px;min-width:0}
.card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:16px}
.card:empty{display:none}
.card h2{margin:0 0 12px;font-size:11px;letter-spacing:.11em;text-transform:uppercase;color:var(--muted)}
.muted{color:var(--muted)}
.big{font-size:34px;font-weight:600;font-variant-numeric:tabular-nums;line-height:1.1}
.row{display:flex;gap:10px;align-items:center;margin:7px 0}
.row .label{flex:0 0 150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar{flex:1;height:7px;border-radius:4px;background:#242a35;overflow:hidden;min-width:60px}
.bar > i{display:block;height:100%;background:var(--accent)}
.bar.good > i{background:var(--good)}
.bar.bad > i{background:var(--bad)}
.num{font-variant-numeric:tabular-nums;min-width:44px;text-align:right}
.delta{font-variant-numeric:tabular-nums;font-size:12px;min-width:52px;text-align:right}
.up{color:var(--good)} .down{color:var(--bad)} .flat{color:var(--muted)}
/* One measurement: its numbers on a line, the bar underneath. A long name gets the whole
   line to itself instead of being cut off to make room for a bar beside it. */
.dim{margin:9px 0}
.dim .head{display:flex;gap:8px;align-items:baseline}
.dim .head .label{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dim .head .lv{flex:0 0 auto;color:var(--muted);font-size:11px;border:1px solid var(--border);
  border-radius:4px;padding:0 4px}
.dim .head .meta{flex:0 0 auto;color:var(--muted);font-size:12px;white-space:nowrap}
.dim > .bar{display:block;height:6px;margin-top:4px}
/* Flagged lines get their own block: the line, then the decision, so a two-line bullet
   does not push its own buttons out of the card. */
.flagged{list-style:none;margin:8px 0 0;padding:0}
.flagged li{border-top:1px solid var(--border);padding:8px 0}
.flagged .acts{display:flex;gap:6px;margin-top:6px}
.flagged .acts button{padding:3px 9px;font-size:12px}
.badge{border:1px solid var(--border);border-radius:999px;padding:2px 9px;font-size:12px;color:var(--muted)}
.badge.live{border-color:var(--accent);color:var(--accent)}
.badge.blocked{border-color:var(--bad);color:var(--bad)}
.list{margin:6px 0 0;padding-left:18px}
.list li{margin:3px 0}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px}
.diff{border:1px solid var(--border);border-radius:12px;overflow:hidden;background:var(--panel)}
.diff .head{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;
  padding:12px 16px;border-bottom:1px solid var(--border);background:var(--panel2)}
.diff .body{max-height:calc(100vh - 260px);overflow:auto}
.line{display:grid;grid-template-columns:42px 42px 1fr auto;gap:10px;padding:1px 12px;
  white-space:pre-wrap;word-break:break-word}
.line .g{color:#5d6675;text-align:right;font-variant-numeric:tabular-nums;
  font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;user-select:none}
.line .t{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px}
.line.add{background:rgba(61,220,151,.09);border-left:3px solid var(--good)}
.line.remove{background:rgba(255,107,107,.09);border-left:3px solid var(--bad);color:#d8bfc4}
.line.remove .t{text-decoration:line-through;text-decoration-color:rgba(255,107,107,.5)}
.line.skip{color:var(--muted);font-style:italic;justify-content:center;padding:5px 12px;
  border-top:1px dashed var(--border);border-bottom:1px dashed var(--border);display:block;text-align:center}
details summary{cursor:pointer;color:var(--muted)}
.src-btn{background:none;border:none;color:var(--muted);cursor:pointer;padding:0 5px;font-size:11px;border-radius:3px;line-height:1;vertical-align:middle}
.src-btn:hover{color:var(--text)}
.src-row{display:none;padding:2px 12px 6px 100px;font-size:12px;background:rgba(100,100,160,.04);border-bottom:1px solid var(--border)}
.src-row.open{display:block}
.wslider-row{display:flex;gap:6px;align-items:center;font-size:12px;white-space:nowrap}
.wslider-row input[type=range]{width:64px}
footer{padding:0 22px 30px;color:var(--muted)}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:13px}
.note{color:var(--muted);font-size:12.5px}
.star{color:var(--warn)}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0,0,0,0);white-space:nowrap;border:0}
/* Grounding ledger: the distribution behind the mean, with the uncertain band visible. */
.unc{color:var(--warn)} .bad{color:var(--bad)} .ok{color:var(--good)}
.ledger{list-style:none;margin:8px 0 0;padding:0;max-height:360px;overflow:auto}
.ledger li{border-top:1px solid var(--border);padding:7px 0}
.ledger .ln{display:flex;gap:8px;align-items:baseline}
.ledger .ln .t{flex:1;min-width:0;word-break:break-word}
.ledger .p{font-variant-numeric:tabular-nums;min-width:34px;text-align:right;flex:0 0 34px}
.claim{display:flex;gap:8px;align-items:baseline;padding:1px 0 1px 12px;font-size:12px;
  color:var(--muted)}
/* One claim per line, clipped rather than wrapped: the claim set is a distribution to
   scan, and the full text is in the line above and on hover. The text shrinks to fit so a
   marker can follow it rather than being pushed to the far edge of the row. */
.claim .t{flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.claim .fails{flex:0 0 auto;color:var(--bad);font-size:11px;text-transform:uppercase;
  letter-spacing:.06em}
.filters{display:flex;gap:6px;margin:8px 0 0;flex-wrap:wrap}
.filters button{padding:3px 9px;font-size:12px}
.filters button.on{border-color:var(--accent);background:#231535}
/* Coverage: one row per requirement, and an empty cell where the candidate has nothing. */
.cov{display:grid;grid-template-columns:18px 1fr;gap:3px 8px;margin:8px 0 0;font-size:12.5px}
.cov .mark{text-align:center}
.cov .mark.ok{color:var(--good)} .cov .mark.no{color:var(--muted)}
.cov .ans{grid-column:2;color:var(--muted);font-size:12px;margin:0 0 7px}
.meter{height:7px;border-radius:4px;background:#242a35;overflow:hidden;margin:5px 0}
.meter > i{display:block;height:100%;background:var(--accent)}
.meter.hot > i{background:var(--bad)}
/* Live lint: the winning draft, editable, with the reviewer's verdict in the gutter. */
.editrow{display:grid;grid-template-columns:22px 1fr;gap:8px;padding:1px 12px;align-items:start}
.editrow .dot{text-align:center;color:var(--muted);cursor:help;font-size:11px;line-height:1.9}
.editrow .dot.unc{color:var(--warn)} .editrow .dot.bad{color:var(--bad)} .editrow .dot.ok{color:var(--good)}
.editable{outline:none;border-radius:3px;padding:0 4px;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px;
  white-space:pre-wrap;word-break:break-word}
.editable:focus{background:#231535}
</style>
</head>
<body>
<header>
  <h1>Resume polisher</h1>
  <span id="status" class="badge"></span>
  <span id="paths" class="muted mono"></span>
  <span id="stop" class="muted" style="margin-left:auto"></span>
</header>
<!-- Rounds arrive on their own, so the newest one is announced rather than hunted for. -->
<p id="live" class="sr-only" role="status" aria-live="polite"></p>

<div class="toolbar">
  <button id="undo" title="previous version (←)">← Undo</button>
  <button id="next" title="next version (→)">Next →</button>
  <span class="sep"></span>
  <button id="save" class="primary" title="write this version to the output file">Save this version</button>
  <span id="savestatus" class="note"></span>
  <span class="sep"></span>
  <label class="toggle"><input type="checkbox" id="hide" checked /> hide unchanged (h)</label>
  <label class="toggle"><input type="checkbox" id="vsorig" /> compare original (c)</label>
  <span class="sep"></span>
  <button id="rubric-btn" title="rubric weight controls (w)">Weights ▸</button>
  <button id="edit" title="edit this draft and re-check only the lines you change (e)">✎ Edit</button>
  <button id="saveedit" class="primary" style="display:none" title="write the edited draft to the output file">Save edited draft</button>
  <div id="timeline" class="timeline"></div>
</div>
<div id="rubric-panel" style="display:none;padding:10px 22px;border-bottom:1px solid var(--border);background:var(--bg)">
  <div style="display:flex;flex-wrap:wrap;gap:14px;align-items:flex-start">
    <span class="muted" style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;margin-top:4px">Re-weight</span>
    <div id="wsliders" style="display:flex;flex-wrap:wrap;gap:10px"></div>
    <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:2px">
      <span id="wsum" class="muted note"></span>
      <button id="wreset" style="font-size:12px;padding:4px 8px">Reset</button>
      <button id="wexport" style="font-size:12px;padding:4px 8px">Copy weights</button>
      <span id="wreweight-note" class="note" style="color:var(--warn)"></span>
    </div>
  </div>
</div>

<main>
  <div class="side">
    <div class="card" id="scores"></div>
    <div class="card"><h2>Run totals</h2><div id="totals"></div></div>
  </div>
  <div class="wide">
    <div class="card" style="padding:0;background:none;border:none">
      <div class="diff">
        <div class="head" id="diffhead"></div>
        <div class="body" id="diff"></div>
      </div>
    </div>
    <div class="card" id="flagged"></div>
    <div class="card" id="ledger"></div>
    <div class="card"><h2>Job description</h2>
      <details><summary>show the target</summary>
        <p class="mono" id="jd" style="white-space:pre-wrap"></p>
      </details>
      <div id="coverage"></div>
    </div>
  </div>
</main>

<footer id="footer" class="note"></footer>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
"use strict";
const CSRF_TOKEN = "__CSRF_TOKEN__";
const state = { report:{}, index:0, vsOriginal:false, hideUnchanged:true, touched:false,
                announced:null, editing:false, editResults:null, editCheckedText:null,
                editUnsupported:[] };
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
// The reviewer audits lines with their bullet marker stripped (judge.claim_lines),
// while diff rows and editable rows are the file's raw text. One key for both, or a
// bulleted resume — every resume — would never line up with its own verdicts.
const auditKey = (text) => String(text).trim().replace(/^[-•*–—·]+/, "").trim();
const versions = () => state.report.versions || [];
const current = () => versions()[state.index] || null;
const previous = () => versions()[state.index - 1] || null;

function bar(value, cls) {
  const w = Math.max(0, Math.min(1, value)) * 100;
  return `<span class="bar ${cls}"><i style="width:${w}%"></i></span>`;
}
function delta(now, before, digits = 2) {
  if (before === undefined || before === null) return `<span class="delta flat"></span>`;
  const d = now - before;
  const cls = Math.abs(d) < 0.005 ? "flat" : d > 0 ? "up" : "down";
  const sign = d > 0 ? "+" : "";
  return `<span class="delta ${cls}">${sign}${d.toFixed(digits)}</span>`;
}
function scoreRows(v, prev) {
  const cfg = state.report.config || {};
  const order = cfg.dimension_order || Object.keys(v.review.scores);
  return order.map((name) => {
    const s = v.review.scores[name];
    const before = prev && prev.review ? prev.review.scores[name].score : null;
    const low = s.confidence < (cfg.confidence_floor ?? 0.6) ? " ⚠" : "";
    return `<div class="dim">
      <div class="head">
        <span class="label" title="${esc(name)} — level ${s.level} of ${cfg.top_level}: ${esc(s.level_text)}">${esc(name)}</span>
        <span class="lv" title="rubric level ${s.level} of ${cfg.top_level}">L${s.level}</span>
        <span class="num">${s.score.toFixed(2)}/4</span>
        ${delta(s.score, before)}
        <span class="meta" title="reviewer confidence">${s.confidence.toFixed(2)}${low}</span>
      </div>
      ${bar(s.normalized, "")}
    </div>`;
  }).join("");
}
function guardrailRows(v) {
  const g = v.review.guardrails || {};
  return Object.entries(g).sort((a, b) => b[1] - a[1]).map(([name, p]) => `<div class="dim">
    <div class="head"><span class="label">${esc(name)}</span>
      <span class="num">${p.toFixed(2)}</span></div>
    ${bar(p, "bad")}
  </div>`).join("");
}

function renderScores() {
  const v = current();
  if (!v || !v.review) {
    $("scores").innerHTML = `<h2>Original resume</h2>
      <div class="big">—</div>
      <p class="muted">The reviewer has not scored anything yet. Each round appears here
      with its five dimension scores, its fabrication checks, and its line-by-line grounding.</p>`;
    return;
  }
  const r = v.review;
  const prev = previous();
  const best = r.is_best ? ' <span class="star" title="best draft">★ best</span>' : "";
  const blocked = r.blocked ? ' <span class="badge blocked">blocked</span>' : "";
  const gap = r.gap_is_split
    ? "reviewer split between " + Object.entries(r.gap_distribution).sort((a, b) => b[1] - a[1])
        .slice(0, 2).map(([n, p]) => `${esc(n)} ${p.toFixed(2)}`).join(" and ")
    : esc(r.biggest_gap);
  const weakest = r.weakest_line
    ? `<div class="dim"><div class="head"><span class="label">weakest line</span>
       <span class="num">${r.weakest_line.support.toFixed(2)}</span></div>
       <div class="note mono" style="margin-top:2px">${esc(r.weakest_line.text)}</div></div>`
    : "";
  // Built as its own variable: an escaped quote inside a template literal is a syntax
  // error that takes the whole page down, and the browser is the only thing that catches it.
  const note = v.reviewed ? "" : "unchanged, scores carried";
  const carriedNote = note ? ` <span class='muted'>${note}</span>` : "";
  const reweighted = _isReweighted();
  const rwOverall = reweighted ? _recomputeOverall(v, _activeWeights()) : null;
  const displayOverall = rwOverall !== null ? rwOverall : r.overall;
  const rwNote = reweighted ? `<div class="note" style="color:var(--warn);margin:2px 0">re-weighted view — scores unchanged</div>` : '';
  $('scores').innerHTML = `
    <h2>${esc(v.label)}${best}${blocked}${carriedNote}</h2>
    <div class="big">${displayOverall.toFixed(2)}</div>${rwNote}
    <div class="muted">quality ${r.quality.toFixed(2)} × grounded ${r.groundedness.toFixed(2)}
      ${delta(r.overall, prev && prev.review ? prev.review.overall : null)}</div>
    <h2 style="margin-top:16px">Dimensions</h2>
    ${scoreRows(v, prev)}
    <h2 style="margin-top:16px">Fabrication checks</h2>
    ${guardrailRows(v)}
    <div class="dim"><div class="head"><span class="label">line grounding</span>
      <span class="num">${r.line_grounding.toFixed(2)}</span>
      <span class="meta" title="${r.reused_lines} lines were carried over from the previous draft instead of re-asked">${r.audited_lines} lines · ${r.reused_lines} carried</span></div>
      ${bar(r.line_grounding, "good")}</div>
    ${weakest}
    <h2 style="margin-top:16px">Biggest gap</h2>
    <p class="muted" style="margin:0">${gap}</p>
    <div class="note" style="margin-top:16px;border-top:1px solid var(--border);padding-top:10px">
      ${v.chars.toLocaleString()} chars · ${v.words} words · ${v.lines} lines ·
      ${v.saved ? "saved to " + esc(state.report.paths ? state.report.paths.out : "the output file") : "not saved"}
    </div>`;
}

// The lines the reviewer could not ground, with the decision they need. They sit under the
// diff because they are about the text: the writer's wording, then the verdict on it.
// The buttons carry the flagged line's position, never its text: a line containing a quote
// cannot break out of an HTML attribute, and the click handler reads the text back from the
// payload, so nothing user-supplied is interpolated into markup.
function renderFlagged() {
  const el = $("flagged");
  const v = current();
  const r = v && v.review;
  const lines = (r && r.flagged_lines) || [];
  if (!lines.length) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = `<h2>Unsupported lines (${lines.length})</h2>
    <p class="note" style="margin:0 0 4px">A line here is one the reviewer does not believe the
      original resume supports. Each needs an approve/reject decision before it ships, and a
      rejection goes back to the writer.</p>
    <ul class="flagged">${lines.map((text, i) => {
      const entry = (r.lines_to_review || []).find((line) => line.text === text);
      const decision = entry && entry.decision;
      const claim = entry && entry.failing_claim
        ? `<div class="note">failing claim: “${esc(entry.failing_claim)}”</div>`
        : "";
      const badge = decision
        ? ` <span class="badge" style="color:${decision === "approved" ? "var(--good)" : "var(--bad)"}">${esc(decision)}</span>`
        : "";
      const acts = decision ? ""
        : `<div class="acts">
             <button class="review" data-version="${v.index}" data-line-index="${i}" data-verdict="approved">✓ Approve</button>
             <button class="review" data-version="${v.index}" data-line-index="${i}" data-verdict="rejected" style="border-color:var(--bad)">✗ Reject</button>
           </div>`;
      return `<li><div class="mono">${esc(text)}${badge}</div>${claim}${acts}</li>`;
    }).join("")}</ul>`;
}

function diffRows(v) {
  const evidence = (v.review && v.review.evidence) ? v.review.evidence : {};
  const key = state.vsOriginal ? "diff_vs_original" : "diff_vs_previous";
  const d = v[key];
  if (!d || !d.rows.length) return `<div class="line skip">nothing to compare yet</div>`;
  return d.rows.filter((row) => !state.hideUnchanged || row.kind !== "equal")
    .map((row) => {
      if (row.kind === "skip") return `<div class="line skip">⋯ ${row.count} unchanged lines</div>`;
      const g1 = row.old ?? "", g2 = row.new ?? "";
      const lineKey = auditKey(row.text);
      const hasEvidence = Object.prototype.hasOwnProperty.call(evidence, lineKey);
      const src = evidence[lineKey];
      const srcBtn = hasEvidence
        ? `<button class="src-btn" title="show source line">▸</button>`
        : `<span></span>`;
      const srcRow = hasEvidence
        ? `<div class="src-row">${
            src !== null && src !== undefined
              ? `<span class="muted">source: </span><span class="mono">${esc(src)}</span>`
              : `<span style="color:var(--bad)">⊘ no line in the original resume supports this claim</span>`
          }</div>`
        : '';
      return `<div class="line ${row.kind}"><span class="g">${g1}</span><span class="g">${g2}</span>` +
             `<span class="t">${esc(row.text) || "&nbsp;"}</span>${srcBtn}</div>${srcRow}`;
    }).join("");
}

function renderDiff() {
  const v = current();
  if (!v || !v.review) {
    $("diffhead").innerHTML = "<strong>Original resume</strong> <span class='muted'>the input</span>";
    $("diff").innerHTML = v
      ? v.text.split("\\n").map((t) => `<div class="line"><span class="g"></span><span class="g"></span><span class="t">${esc(t)}</span></div>`).join("")
      : "";
    return;
  }
  if (state.editing) { renderEditable(v); return; }
  const key = state.vsOriginal ? "diff_vs_original" : "diff_vs_previous";
  const d = v[key];
  const from = state.vsOriginal ? "the original resume" : (previous() || {}).label || "the original resume";
  const unchanged = d.added === 0 && d.removed === 0;
  $("diffhead").innerHTML = `<strong>${esc(v.label)}</strong>
    <span class="muted">vs ${esc(from)}</span>
    ${unchanged
      ? '<span class="muted">no changes — this round kept the wording it was given</span>'
      : `<span class="up">+${d.added}</span><span class="down">−${d.removed}</span>`}
    <span class="muted">${d.unchanged} unchanged</span>
    ${v.review.improvement === null ? "" : `<span class="muted">· overall ${v.review.improvement > 0 ? "+" : ""}${v.review.improvement.toFixed(2)} vs best</span>`}`;
  $("diff").innerHTML = unchanged
    ? `<div class="line skip">identical to ${esc(from)}</div>`
    : diffRows(v);
}

// ── Grounding ledger, coverage, and cost ──────────────────────────────────────
// Everything below is arithmetic over judgments the run already paid for. The one
// exception is the debounced re-check of an edit, which asks about changed lines only.

function _band(support) {
  const cfg = state.report.config || {};
  const floor = cfg.line_support_floor ?? 0.5;
  const review = cfg.line_review_floor ?? 0.8;
  if (support < floor) return "bad";
  if (support < review) return "unc";
  return "ok";
}
function _bandWord(band) {
  return band === "bad" ? "unsupported" : band === "unc" ? "uncertain" : "supported";
}

let _ledgerFilter = "attention";

function ledgerItem(entry) {
  const band = _band(entry.support);
  const claims = entry.claims || [];
  // Show the per-claim distribution only where it says something the line score does not.
  const claimRows = claims.length > 1
    ? claims.map((claim) => {
        const b = _band(claim.support);
        // The claim that dragged the line down is the reason the line is flagged, so it is
        // marked rather than left for the reader to find by comparing numbers.
        const fails = entry.failing_claim && claim.text === entry.failing_claim
          ? ` <span class="fails">fails</span>` : "";
        return `<div class="claim"><span class="p ${b}">${claim.support.toFixed(2)}</span>` +
               `<span class="t" title="${esc(claim.text)}">${esc(claim.text)}</span>${fails}</div>`;
      }).join("")
    : "";
  const failing = entry.failing_claim && claims.length <= 1
    ? `<div class="claim"><span class="p bad">weak</span><span>${esc(entry.failing_claim)}</span></div>`
    : "";
  return `<li><div class="ln">
      <span class="p ${band}" title="${_bandWord(band)}">${entry.support.toFixed(2)}</span>
      <span class="t">${esc(entry.text)}</span></div>${failing}${claimRows}</li>`;
}

function renderLedger() {
  const el = $("ledger");
  const v = current();
  const entries = (v && v.review && v.review.ledger) || [];
  if (!entries.length) { el.innerHTML = ""; return; }
  const cfg = state.report.config || {};
  const floor = cfg.line_support_floor ?? 0.5;
  const review = cfg.line_review_floor ?? 0.8;
  const trust = v.review.trust || {};
  const withBand = entries.map((entry) => Object.assign({}, entry, { band: _band(entry.support) }));
  const attention = withBand.filter((entry) => entry.band !== "ok");
  const shown = _ledgerFilter === "all" ? withBand
    : _ledgerFilter === "attention" ? attention
    : withBand.filter((entry) => entry.band === _ledgerFilter);
  const filters = [
    ["attention", `needs attention (${attention.length})`],
    ["all", `all (${withBand.length})`],
    ["unc", `uncertain (${trust.uncertain || 0})`],
    ["bad", `unsupported (${trust.unsupported || 0})`],
  ];
  el.innerHTML = `<h2>Grounding ledger</h2>
    <div class="note">${trust.audited || 0} lines audited · ${trust.carried || 0} carried from the
      previous draft instead of re-asked · uncertain band ${floor}–${review}</div>
    <div class="filters">${filters.map(([key, label]) =>
      `<button data-filter="${key}" class="${_ledgerFilter === key ? "on" : ""}">${esc(label)}</button>`
    ).join("")}</div>
    ${shown.length ? `<ul class="ledger">${shown.map(ledgerItem).join("")}</ul>`
                   : `<p class="note">nothing in this band</p>`}`;
  el.querySelectorAll(".filters button").forEach((button) => {
    button.addEventListener("click", () => { _ledgerFilter = button.dataset.filter; renderLedger(); });
  });
}

function renderCoverage() {
  const el = $("coverage");
  const v = current();
  const cov = (v && v.review && v.review.coverage) || [];
  if (!cov.length) { el.innerHTML = ""; return; }
  const open = cov.filter((entry) => !entry.draft_line);
  el.innerHTML = `<h2 style="margin-top:14px">Requirements answered (${cov.length - open.length} of ${cov.length})</h2>
    <div class="cov">${cov.map((entry) =>
      `<span class="mark ${entry.draft_line ? "ok" : "no"}">${entry.draft_line ? "✓" : "○"}</span>
       <span>${esc(entry.requirement)}</span>
       <span class="ans">${entry.draft_line
         ? "answered by: " + esc(entry.draft_line)
         : "no line in this draft answers it — leave it out rather than invent it"}</span>`
    ).join("")}</div>`;
}

function renderTotals() {
  const r = state.report;
  const cfg = r.config || {};
  const t = r.totals || {};
  const reviewer = t.reviewer_tokens || 0;
  const total = t.total_tokens || 0;
  const share = total ? Math.round((reviewer / total) * 100) : 0;
  const budget = cfg.max_tokens ? [total, cfg.max_tokens, "token"]
    : cfg.max_seconds ? [t.seconds || 0, cfg.max_seconds, "time"] : null;
  let meter;
  if (budget) {
    const pct = Math.min(100, (budget[0] / budget[1]) * 100);
    meter = `<div class="note">${budget[2]} budget: ${budget[0].toLocaleString()} of
      ${budget[1].toLocaleString()} used (${Math.round(pct)}%)</div>
      <div class="meter ${pct >= 90 ? "hot" : ""}"><i style="width:${pct}%"></i></div>`;
  } else {
    meter = `<div class="note">no budget cap set — the loop stops on the score alone</div>`;
  }
  const perRound = versions().filter((v) => v.review).map((v) => {
    const w = (v.review.writer && v.review.writer.total_tokens) || 0;
    const rv = (v.review.reviewer && v.review.reviewer.total_tokens) || 0;
    const sum = w + rv || 1;
    return `<div class="dim"><div class="head"><span class="label">${esc(v.label)}</span>
      <span class="meta" title="writer tokens">${w.toLocaleString()}w</span>
      <span class="meta" title="reviewer tokens">${rv.toLocaleString()}r</span></div>
      <span class="bar" title="reviewer share of this round's tokens"><i style="width:${(rv / sum) * 100}%"></i></span></div>`;
  }).join("");
  const best = versions().filter((v) => v.review && v.review.is_best).pop()
    || versions().filter((v) => v.review).pop();
  const trust = best && best.review.trust;
  const trustStrip = trust ? `<h2 style="margin-top:14px">How much to trust ${esc(best.label)}</h2>
    <div class="kv">
      <span class="muted">audited</span><span>${trust.audited} lines · ${trust.carried} carried, not re-asked</span>
      <span class="muted">uncertain</span><span>${trust.uncertain} lines in the band · ${trust.low_confidence} dimension${trust.low_confidence === 1 ? "" : "s"} answered without confidence</span>
      <span class="muted">needs a person</span><span>${trust.unsupported} unsupported line${trust.unsupported === 1 ? "" : "s"}</span>
    </div>` : "";
  $("totals").innerHTML = `<div class="kv">
      <span class="muted">writer</span><span>${t.writer_calls || 0} calls · ${(t.writer_tokens || 0).toLocaleString()} tokens</span>
      <span class="muted">reviewer</span><span>${t.reviewer_calls || 0} calls · ${reviewer.toLocaleString()} tokens · ${share}% of the run</span>
      <span class="muted">total</span><span>${total.toLocaleString()} tokens · ${t.seconds || 0}s</span>
    </div>${meter}
    <h2 style="margin-top:14px">Cost per round
      <span class="muted" style="letter-spacing:0;text-transform:none">(bar = reviewer share)</span></h2>
    ${perRound || '<p class="note">no rounds yet</p>'}
    ${trustStrip}`;
}

// ── Editing a draft, with JEV in the gutter ───────────────────────────────────

let _editTimer = null;

function editText() {
  return Array.from($("diff").querySelectorAll(".editable"))
    .map((el) => el.textContent).join("\\n");
}
function _carriedMap(text) {
  const v = current();
  if (!v || !v.review) return {};
  const now = new Set(text.split("\\n").map((line) => auditKey(line)));
  const carried = {};
  (v.review.ledger || []).forEach((entry) => {
    if (now.has(entry.text)) carried[entry.text] = entry.support;
  });
  return carried;
}
function toggleEdit() {
  const v = current();
  if (!v || !v.review) { setSaved("pick a reviewed round to edit"); return; }
  state.editing = !state.editing;
  state.editResults = null;
  state.editCheckedText = null;
  state.editUnsupported = [];
  setSaved(state.editing ? "edit the draft — only the lines you change are re-checked" : "");
  render();
}
function renderEditable(v) {
  $("diffhead").innerHTML = `<strong>Editing ${esc(v.label)}</strong>
    <span class="muted">only the lines you change are re-checked</span>
    <span id="lints" class="note"></span>`;
  $("diff").innerHTML = v.text.split("\\n").map((text) =>
    `<div class="editrow"><span class="dot muted">·</span>` +
    `<div class="editable" contenteditable="plaintext-only" spellcheck="false">${esc(text)}</div></div>`
  ).join("");
  if (state.editResults) applyEditResults();
}
function applyEditResults() {
  const results = state.editResults || {};
  $("diff").querySelectorAll(".editrow").forEach((row) => {
    const text = auditKey(row.querySelector(".editable").textContent);
    const dot = row.querySelector(".dot");
    const found = results[text];
    dot.className = "dot " + (found ? found.band : "muted");
    dot.textContent = "●";
    dot.title = found
      ? `${found.support.toFixed(2)} — ${_bandWord(found.band)}` +
        (found.failing_claim ? ": " + found.failing_claim : "")
      : "not checked (no factual claim to ground)";
  });
  const unsupported = state.editUnsupported || [];
  const lints = $("lints");
  if (lints) {
    lints.textContent = unsupported.length
      ? `${unsupported.length} line(s) cannot be grounded`
      : "every line is grounded";
    lints.style.color = unsupported.length ? "var(--bad)" : "var(--good)";
  }
}
async function checkEdit() {
  if (!state.editing) return;
  const text = editText();
  try {
    const res = await fetch("/api/check", {
      method: "POST",
      headers: { "content-type": "application/json", "X-Csrf-Token": CSRF_TOKEN },
      body: JSON.stringify({ text, carried: _carriedMap(text) }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setSaved(`check unavailable: ${data.error || res.status}`); return; }
    state.editResults = {};
    (data.lines || []).forEach((line) => {
      state.editResults[line.text] = { band: _band(line.support), support: line.support,
                                       failing_claim: line.failing_claim };
    });
    state.editCheckedText = text;
    state.editUnsupported = data.unsupported || [];
    applyEditResults();
    updateEditControls();
  } catch (error) {
    setSaved(`check error: ${error}`);
  }
}
function updateEditControls() {
  $("edit").textContent = state.editing ? "✎ Done" : "✎ Edit";
  const saveEdit = $("saveedit");
  saveEdit.style.display = state.editing ? "" : "none";
  const clean = state.editing && state.editCheckedText !== null
    && state.editCheckedText === editText()
    && (state.editUnsupported || []).length === 0;
  saveEdit.disabled = !clean;
  saveEdit.title = clean
    ? "write the edited draft to the output file"
    : "re-check the edit first — a line that cannot be grounded blocks saving";
}
async function saveEdited() {
  setSaved("saving edited draft…");
  try {
    const res = await fetch("/api/save", {
      method: "POST",
      headers: { "content-type": "application/json", "X-Csrf-Token": CSRF_TOKEN },
      body: JSON.stringify({ text: editText() }),
    });
    const data = await res.json().catch(() => ({}));
    setSaved(res.ok ? `saved edited draft → ${data.saved}`
                    : `not saved: ${data.error || res.status}`);
    if (res.ok) { state.editing = false; await refresh(); }
  } catch (error) {
    setSaved(`not saved: ${error}`);
  }
}

function renderTimeline() {
  const reweighted = _isReweighted();
  const rwBestIdx = reweighted ? _reweightedBestIndex() : null;
  $('timeline').innerHTML = versions().map((v, i) => {
    const rwScore = reweighted ? _recomputeOverall(v, _activeWeights()) : null;
    const score = rwScore !== null ? rwScore.toFixed(2) : (v.review ? v.review.overall.toFixed(2) : '—');
    const isLoopBest = v.review && v.review.is_best;
    const isRwBest = reweighted && v.index === rwBestIdx && v.review;
    const star = isRwBest
      ? '<span class="star" title="re-weighted best">★</span>'
      : (isLoopBest && !reweighted
          ? '<span class="star">★</span>'
          : (isLoopBest ? '<span class="muted" title="loop best">◆</span>' : ''));
    const dot = v.saved ? '<span class="muted" title="saved to the output file">●</span>' : "";
    return `<span class="chip ${i === state.index ? "sel" : ""}" data-i="${i}">
      ${esc(v.label)} <span class="n">${score}</span>${star}${dot}</span>`;
  }).join("");
  $("timeline").querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => select(Number(chip.dataset.i)));
  });
}

function render() {
  const r = state.report;
  const cfg = r.config || {};
  // The page is opened as soon as the server is listening, which can be before the first
  // payload exists. That state is "starting", not "done" — and it has to keep polling, or
  // the browser would sit on an empty page for the whole run.
  const waiting = !r.status && !versions().length;
  const live = r.status === "running" || waiting;
  $("status").textContent = waiting ? "starting…" : live ? "running" : "done";
  $("status").className = "badge" + (live && !waiting ? " live" : "");
  $("paths").textContent = (r.paths ? `${r.paths.resume} → ${r.paths.out}` : "");
  $("stop").textContent = waiting
    ? "waiting for the first round…"
    : live
      ? `round ${versions().length} running…`
      : (r.stop_reason || "");
  $("jd").textContent = r.job_description || "";
  $("footer").innerHTML = `<div>writer ${esc(cfg.writer_model || "")} · reviewer
    ${esc(cfg.reviewer_model || "")} · stop when a round beats the best by less than
    ${cfg.min_improvement} for ${cfg.patience} rounds, or reaches ${cfg.target_score}</div>
    <div style="margin-top:8px">
      <kbd>←</kbd> <kbd>→</kbd> versions ·
      <kbd>h</kbd> hide unchanged ·
      <kbd>c</kbd> compare with the original ·
      <kbd>w</kbd> weights ·
      <kbd>e</kbd> edit and re-check
    </div>`;
  const newest = versions()[versions().length - 1];
  if (newest && newest.review && newest.index !== state.announced) {
    state.announced = newest.index;
    $("live").textContent =
      `${newest.label} finished: overall ${newest.review.overall.toFixed(2)}`;
  }
  $("undo").disabled = state.index <= 0;
  $("next").disabled = state.index >= versions().length - 1;
  // While the loop runs, it owns the output file: it rewrites it whenever a round becomes
  // the new best. Picking a version is a decision to make once the run has stopped.
  const canSave = !live && current() && current().review;
  $("save").disabled = !canSave || state.editing;
  $("save").title = live
    ? "the run is still writing this file with its best draft"
    : "write this version to the output file";
  $("edit").disabled = live || !current() || !current().review;
  $("edit").title = live
    ? "wait for the run to finish before editing"
    : "edit this draft and re-check only the lines you change (e)";
  renderTimeline();
  renderScores();
  renderFlagged();
  renderLedger();
  renderCoverage();
  renderDiff();
  renderTotals();
  updateEditControls();
}

function select(index) {
  state.touched = true;
  state.index = Math.max(0, Math.min(versions().length - 1, index));
  // Editing belongs to the version that was open; switching versions ends the edit.
  state.editing = false;
  state.editResults = null;
  state.editCheckedText = null;
  state.editUnsupported = [];
  render();
}
function step(delta) { select(state.index + delta); }
function setSaved(message) { $("savestatus").textContent = message; }

async function save() {
  const v = current();
  if (!v || !v.review) return;
  setSaved("saving…");
  try {
    const res = await fetch("/api/save", {
      method: "POST",
      headers: { "content-type": "application/json", "X-Csrf-Token": CSRF_TOKEN },
      body: JSON.stringify({ index: v.index }),
    });
    const data = await res.json();
    setSaved(res.ok ? `saved ${v.label} → ${data.saved}` : `error: ${data.error}`);
    if (res.ok) await refresh();
  } catch (error) {
    setSaved(`error: ${error}`);
  }
}

async function sendReview(line, verdict) {
  try {
    const res = await fetch("/api/review", {
      method: "POST",
      headers: { "content-type": "application/json", "X-Csrf-Token": CSRF_TOKEN },
      body: JSON.stringify({ line, verdict }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setSaved(`review error: ${data.error || res.status}`);
      return;
    }
    setSaved(`${verdict}: ${line}`);
    await refresh();
  } catch (error) {
    setSaved(`review error: ${error}`);
  }
}

async function refresh() {
  try {
    const res = await fetch("/api/report", { cache: "no-store" });
    if (res.ok) {
      const firstPaint = !versions().length;
      state.report = await res.json();
      const newest = Math.max(0, versions().length - 1);
      // Follow the newest round while the run is live, until the reader navigates. The first
      // payload after an empty page lands on the best draft: this page is opened before round
      // 1 normally, and it must not sit on the original once there is something to show.
      if (!state.touched && (state.report.status === "running" || firstPaint)) {
        state.index = state.report.status === "running"
          ? newest
          : (state.report.best_index ?? newest);
      }
      render();
      // Keep polling while the run is live, and while nothing has been published yet: the
      // page can be open before the first round lands.
      if (state.report.status === "running" || !versions().length) setTimeout(refresh, 1500);
    }
  } catch (error) { /* the server went away; keep the last paint */ }
}

// Delegated: the flagged list is rebuilt on every render, so one listener on the card
// covers every review button the page will ever contain.
$("flagged").addEventListener("click", (event) => {
  const button = event.target.closest("button.review");
  if (!button) return;
  const version = versions().find((v) => v.index === Number(button.dataset.version));
  const line = version && version.review
    ? version.review.flagged_lines[Number(button.dataset.lineIndex)]
    : undefined;
  if (line === undefined) return;
  sendReview(line, button.dataset.verdict);
});

$("undo").addEventListener("click", () => step(-1));
$("next").addEventListener("click", () => step(1));
$("save").addEventListener("click", save);
$("edit").addEventListener("click", toggleEdit);
$("saveedit").addEventListener("click", saveEdited);
// One request per pause, and only the lines that changed are asked about: the rest
// arrive as carried verdicts, exactly as they do between rounds of the loop.
$("diff").addEventListener("input", (event) => {
  if (!state.editing) return;
  const row = event.target.closest(".editrow");
  const dot = row && row.querySelector(".dot");
  if (dot) { dot.className = "dot"; dot.textContent = "…"; dot.title = "checking"; }
  clearTimeout(_editTimer);
  _editTimer = setTimeout(checkEdit, 700);
});
$("hide").addEventListener("change", (e) => { state.hideUnchanged = e.target.checked; renderDiff(); });
$("vsorig").addEventListener("change", (e) => { state.vsOriginal = e.target.checked; renderDiff(); });

// Evidence expand: delegated so it survives re-renders of #diff innerHTML.
$('diff').addEventListener('click', (event) => {
  const btn = event.target.closest('button.src-btn');
  if (!btn) return;
  const lineDiv = btn.closest('.line');
  const srcRow = lineDiv && lineDiv.nextElementSibling;
  if (srcRow && srcRow.classList.contains('src-row')) {
    const open = srcRow.classList.toggle('open');
    btn.textContent = open ? '▾' : '▸';
  }
});

// ── Weight sliders ────────────────────────────────────────────────────────────
let _customWeights = null;

function _defaultWeights() {
  return Object.assign({}, (state.report.manifest || {}).weights || {});
}
function _activeWeights() {
  return _customWeights || _defaultWeights();
}
function _isReweighted() {
  if (!_customWeights) return false;
  const def = _defaultWeights();
  return Object.keys(_customWeights).some(
    (k) => Math.abs((_customWeights[k] || 0) - (def[k] || 0)) > 0.001
  );
}
function _recomputeOverall(v, weights) {
  if (!v || !v.review) return null;
  const total = Object.values(weights).reduce((a, b) => a + b, 0) || 1;
  let q = 0;
  for (const [name, w] of Object.entries(weights)) {
    const s = v.review.scores && v.review.scores[name];
    if (s) q += (w / total) * s.normalized;
  }
  return q * v.review.groundedness;
}
function _reweightedBestIndex() {
  const weights = _activeWeights();
  let best = -1, bestScore = -1;
  for (const v of versions()) {
    const sc = _recomputeOverall(v, weights);
    if (sc !== null && sc > bestScore) { bestScore = sc; best = v.index; }
  }
  return best;
}
function _updateWeightPanel() {
  const weights = _activeWeights();
  const total = Object.values(weights).reduce((a, b) => a + b, 0);
  const sumEl = $('wsum');
  if (sumEl) sumEl.textContent = `sum ${Math.round(total * 100)}%`;
  const noteEl = $('wreweight-note');
  if (noteEl) noteEl.textContent = _isReweighted() ? 're-weighted view — scores unchanged' : '';
}
function _initWeightSliders() {
  const weights = _defaultWeights();
  if (!Object.keys(weights).length) return;
  $('wsliders').innerHTML = Object.entries(weights).map(([dim, w]) => {
    const cur = (_customWeights && _customWeights[dim] !== undefined) ? _customWeights[dim] : w;
    return `<div class="wslider-row">
      <span style="min-width:115px;overflow:hidden;text-overflow:ellipsis" title="${esc(dim)}">${esc(dim)}</span>
      <input type="range" min="0" max="50" step="1" value="${Math.round(cur * 100)}" data-dim="${esc(dim)}">
      <span data-wpct="${esc(dim)}" style="min-width:34px;text-align:right">${Math.round(cur * 100)}%</span>
    </div>`;
  }).join('');
  _updateWeightPanel();
}
$('rubric-btn').addEventListener('click', () => {
  const panel = $('rubric-panel');
  const open = panel.style.display === 'none';
  panel.style.display = open ? 'block' : 'none';
  $('rubric-btn').textContent = open ? 'Weights ▾' : 'Weights ▸';
  if (open) _initWeightSliders();
});
$('wsliders').addEventListener('input', (e) => {
  const slider = e.target.closest('input[type=range]');
  if (!slider || !slider.dataset.dim) return;
  const dim = slider.dataset.dim;
  if (!_customWeights) _customWeights = Object.assign({}, _defaultWeights());
  _customWeights[dim] = Number(slider.value) / 100;
  const pct = $('wsliders').querySelector(`[data-wpct="${CSS.escape(dim)}"]`);
  if (pct) pct.textContent = `${slider.value}%`;
  _updateWeightPanel();
  renderTimeline();
  renderScores();
});
$('wreset').addEventListener('click', () => {
  _customWeights = null;
  _initWeightSliders();
  renderTimeline();
  renderScores();
});
$('wexport').addEventListener('click', () => {
  const weights = _activeWeights();
  const total = Object.values(weights).reduce((a, b) => a + b, 0) || 1;
  const normalized = Object.fromEntries(
    Object.entries(weights).map(([k, v]) => [k, Math.round(v / total * 1000) / 1000])
  );
  if (navigator.clipboard) {
    navigator.clipboard.writeText(JSON.stringify(normalized, null, 2))
      .then(() => setSaved('weights copied to clipboard'))
      .catch(() => setSaved('copy failed — see console'));
  }
});

document.addEventListener('keydown', (event) => {
  const target = event.target;
  // Never steal a keystroke from an input or from the editable draft.
  if (target.tagName === 'INPUT' || target.isContentEditable) return;
  if (event.key === 'ArrowLeft') { event.preventDefault(); step(-1); }
  if (event.key === 'ArrowRight') { event.preventDefault(); step(1); }
  if (event.key === 'h') { $('hide').checked = !$('hide').checked; state.hideUnchanged = $('hide').checked; renderDiff(); }
  if (event.key === 'c') { $('vsorig').checked = !$('vsorig').checked; state.vsOriginal = $('vsorig').checked; renderDiff(); }
  if (event.key === 'w') { $('rubric-btn').click(); }
  if (event.key === 'e') { toggleEdit(); }
});

state.report = JSON.parse($("payload").textContent || "{}");
state.index = state.report.status === "running"
  ? Math.max(0, versions().length - 1)
  : (state.report.best_index ?? Math.max(0, versions().length - 1));
render();
refresh();
</script>
</body>
</html>
"""


def render_page(report: dict[str, Any] | None, csrf_token: str = "") -> str:
    """Render the report page, with the payload and CSRF token embedded."""
    payload = json.dumps(report or {}, separators=(",", ":")).replace("</", "<\\/")
    page = _TEMPLATE.replace("__PAYLOAD__", payload)
    page = page.replace("__CSRF_TOKEN__", csrf_token)
    return page
