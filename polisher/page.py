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
body{margin:0;background:var(--bg);color:var(--text);
  font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
header{display:flex;gap:14px;align-items:baseline;flex-wrap:wrap;
  padding:16px 22px;border-bottom:1px solid var(--border)}
h1{margin:0;font-size:15px;letter-spacing:.02em}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:12px 22px;
  border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg);z-index:5}
button{background:var(--panel2);color:var(--text);border:1px solid var(--border);border-radius:8px;
  padding:7px 12px;font:inherit;cursor:pointer;transition:border-color .12s}
button:hover:not(:disabled){border-color:var(--accent)}
button:disabled{opacity:.4;cursor:default}
button.primary{border-color:var(--accent);background:#26183a}
.toggle{display:flex;gap:6px;align-items:center;color:var(--muted);cursor:pointer;user-select:none}
.timeline{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-left:auto}
.chip{display:flex;gap:7px;align-items:center;border:1px solid var(--border);border-radius:999px;
  padding:5px 11px;background:var(--panel);cursor:pointer}
.chip.sel{border-color:var(--accent);background:#231535}
.chip .n{color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
main{display:grid;grid-template-columns:minmax(330px,390px) 1fr;gap:18px;padding:18px 22px 34px}
@media (max-width:940px){main{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:16px}
.card + .card{margin-top:14px}
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
.line{display:grid;grid-template-columns:42px 42px 1fr;gap:10px;padding:1px 12px;
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
footer{padding:0 22px 30px;color:var(--muted)}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:13px}
.note{color:var(--muted);font-size:12.5px}
.star{color:var(--warn)}
</style>
</head>
<body>
<header>
  <h1>Resume polisher</h1>
  <span id="status" class="badge"></span>
  <span id="paths" class="muted mono"></span>
  <span id="stop" class="muted" style="margin-left:auto"></span>
</header>

<div class="toolbar">
  <button id="undo" title="previous version (←)">← Undo</button>
  <button id="next" title="next version (→)">Next →</button>
  <button id="save" class="primary" title="write this version to the output file">Save this version</button>
  <span id="savestatus" class="note"></span>
  <label class="toggle"><input type="checkbox" id="hide" checked /> hide unchanged (h)</label>
  <label class="toggle"><input type="checkbox" id="vsorig" /> compare with original (c)</label>
  <div id="timeline" class="timeline"></div>
</div>

<main>
  <div>
    <div class="card" id="scores"></div>
    <div class="card" id="meta"></div>
    <div class="card"><h2>Job description</h2>
      <details><summary>show the target</summary>
        <p class="mono" id="jd" style="white-space:pre-wrap"></p>
      </details>
    </div>
  </div>
  <div class="card" style="padding:0;background:none;border:none">
    <div class="diff">
      <div class="head" id="diffhead"></div>
      <div class="body" id="diff"></div>
    </div>
    <div class="card" style="margin-top:14px"><h2>Run totals</h2><div class="kv" id="totals"></div></div>
  </div>
</main>

<footer id="footer" class="note"></footer>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
"use strict";
const CSRF_TOKEN = "__CSRF_TOKEN__";
const state = { report:{}, index:0, vsOriginal:false, hideUnchanged:true, touched:false };
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
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
    return `<div class="row">
      <span class="label" title="${esc(name)} — level ${s.level} of ${cfg.top_level}: ${esc(s.level_text)}">${esc(name)} <span class="muted">L${s.level}</span></span>
      ${bar(s.normalized, "")}
      <span class="num">${s.score.toFixed(2)}/4</span>
      ${delta(s.score, before)}
      <span class="num muted" title="reviewer confidence">${s.confidence.toFixed(2)}${low}</span>
    </div>`;
  }).join("");
}
function guardrailRows(v) {
  const g = v.review.guardrails || {};
  return Object.entries(g).sort((a, b) => b[1] - a[1]).map(([name, p]) => `<div class="row">
    <span class="label">${esc(name)}</span>
    ${bar(p, "bad")}
    <span class="num">${p.toFixed(2)}</span>
    <span class="delta flat"></span>
    <span class="num muted"></span>
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
    ? `<div class="row"><span class="label">weakest line</span>
       <span class="num">${r.weakest_line.support.toFixed(2)}</span>
       <span class="muted mono" style="flex:1;overflow:hidden;text-overflow:ellipsis">${esc(r.weakest_line.text)}</span></div>`
    : "";
  const flagged = r.flagged_lines.length
    ? `<h2 style="margin-top:14px">Unsupported lines (${r.flagged_lines.length})</h2>
       <ul class="list mono">${r.flagged_lines.map((t) => {
         const dec = (r.lines_to_review || []).find(l => l.text === t);
         const d = dec && dec.decision;
         const badge = d ? ` <span class="badge" style="color:${d==='approved'?'var(--good)':'var(--bad)'}">${d}</span>` : '';
         const btns = d ? '' : ` <button style="padding:2px 7px;font-size:11px" onclick="sendReview(${JSON.stringify(t)},'approved')">✓ Approve</button><button style="padding:2px 7px;font-size:11px;border-color:var(--bad)" onclick="sendReview(${JSON.stringify(t)},'rejected')">✗ Reject</button>`;
         return `<li>${esc(t)}${badge}${btns}</li>`;
       }).join("")}</ul>`
    : "";
  // Built as its own variable: an escaped quote inside a template literal is a syntax
  // error that takes the whole page down, and the browser is the only thing that catches it.
  const note = v.reviewed ? "" : "unchanged, scores carried";
  const carriedNote = note ? ` <span class='muted'>${note}</span>` : "";
  $("scores").innerHTML = `
    <h2>${esc(v.label)}${best}${blocked}${carriedNote}</h2>
    <div class="big">${r.overall.toFixed(2)}</div>
    <div class="muted">quality ${r.quality.toFixed(2)} × grounded ${r.groundedness.toFixed(2)}
      ${delta(r.overall, prev && prev.review ? prev.review.overall : null)}</div>
    <h2 style="margin-top:16px">Dimensions</h2>
    ${scoreRows(v, prev)}
    <h2 style="margin-top:16px">Fabrication checks</h2>
    ${guardrailRows(v)}
    <div class="row"><span class="label">line grounding</span>
      ${bar(r.line_grounding, "good")}
      <span class="num">${r.line_grounding.toFixed(2)}</span>
      <span class="delta flat" title="${r.reused_lines} lines carried over from the previous draft">${r.audited_lines} lines · ${r.reused_lines} carried</span>
      <span class="num muted"></span></div>
    ${weakest}
    <h2 style="margin-top:16px">Biggest gap</h2>
    <p class="muted" style="margin:0">${gap}</p>
    ${flagged}`;
}

function renderMeta() {
  const v = current();
  const cfg = state.report.config || {};
  const paths = state.report.paths || {};
  if (!v) { $("meta").innerHTML = ""; return; }
  const cost = v.review
    ? `<div class="kv">
        <span class="muted">writer</span><span>${esc(v.review.writer.model)}
          · ${v.review.writer.latency_ms / 1000}s
          · ${(v.review.writer.total_tokens || 0).toLocaleString()} tokens</span>
        <span class="muted">reviewer</span><span>${esc(v.review.reviewer.model)}
          · ${v.review.reviewer.latency_ms / 1000}s
          · ${(v.review.reviewer.total_tokens || 0).toLocaleString()} tokens</span>
      </div>`
    : `<div class="kv"><span class="muted">writer</span><span>${esc(cfg.writer_model || "")}</span>
        <span class="muted">reviewer</span><span>${esc(cfg.reviewer_model || "")}</span></div>`;
  $("meta").innerHTML = `<h2>${esc(v.label)}</h2>
    <div class="kv">
      <span class="muted">chars</span><span>${v.chars.toLocaleString()} · ${v.words} words · ${v.lines} lines</span>
      <span class="muted">file</span><span class="mono">${v.saved ? esc(paths.out) + " (saved)" : "—"}</span>
    </div>
    <h2 style="margin-top:14px">Cost this round</h2>${cost}`;
}

function diffRows(v) {
  const key = state.vsOriginal ? "diff_vs_original" : "diff_vs_previous";
  const d = v[key];
  if (!d || !d.rows.length) return `<div class="line skip">nothing to compare yet</div>`;
  return d.rows.filter((row) => !state.hideUnchanged || row.kind !== "equal")
    .map((row) => {
      if (row.kind === "skip") return `<div class="line skip">⋯ ${row.count} unchanged lines</div>`;
      const g1 = row.old ?? "", g2 = row.new ?? "";
      return `<div class="line ${row.kind}"><span class="g">${g1}</span><span class="g">${g2}</span>
        <span class="t">${esc(row.text) || "&nbsp;"}</span></div>`;
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

function renderTimeline() {
  $("timeline").innerHTML = versions().map((v, i) => {
    const score = v.review ? v.review.overall.toFixed(2) : "—";
    const star = v.review && v.review.is_best ? '<span class="star">★</span>' : "";
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
  const live = r.status === "running";
  $("status").textContent = live ? "running" : "done";
  $("status").className = "badge" + (live ? " live" : "");
  $("paths").textContent = (r.paths ? `${r.paths.resume} → ${r.paths.out}` : "");
  $("stop").textContent = live
    ? `round ${versions().length} running…`
    : (r.stop_reason || "");
  $("jd").textContent = r.job_description || "";
  $("footer").innerHTML = `writer ${esc(cfg.writer_model || "")} · reviewer ${esc(cfg.reviewer_model || "")}
    · up to ${cfg.max_iterations} rounds · stop when a round beats the best by less than
    ${cfg.min_improvement} for ${cfg.patience} rounds, or at ${cfg.target_score}
    · undo/next with ← →`;
  const t = r.totals || {};
  $("totals").innerHTML = `<span class="muted">writer</span><span>${t.writer_calls || 0} calls · ${(t.writer_tokens || 0).toLocaleString()} tokens</span>
    <span class="muted">reviewer</span><span>${t.reviewer_calls || 0} calls · ${(t.reviewer_tokens || 0).toLocaleString()} tokens</span>
    <span class="muted">total</span><span>${(t.total_tokens || 0).toLocaleString()} tokens · ${t.seconds || 0}s</span>`;
  $("undo").disabled = state.index <= 0;
  $("next").disabled = state.index >= versions().length - 1;
  // While the loop runs, it owns the output file: it rewrites it whenever a round becomes
  // the new best. Picking a version is a decision to make once the run has stopped.
  const canSave = !live && current() && current().review;
  $("save").disabled = !canSave;
  $("save").title = live
    ? "the run is still writing this file with its best draft"
    : "write this version to the output file";
  renderTimeline();
  renderScores();
  renderMeta();
  renderDiff();
}

function select(index) {
  state.touched = true;
  state.index = Math.max(0, Math.min(versions().length - 1, index));
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
    await fetch("/api/review", {
      method: "POST",
      headers: { "content-type": "application/json", "X-Csrf-Token": CSRF_TOKEN },
      body: JSON.stringify({ line, verdict }),
    });
    await refresh();
  } catch (_) {}
}

async function refresh() {
  try {
    const res = await fetch("/api/report", { cache: "no-store" });
    if (res.ok) {
      state.report = await res.json();
      // Follow the newest round while the run is live, until the reader navigates.
      if (!state.touched && state.report.status === "running") {
        state.index = Math.max(0, versions().length - 1);
      }
      render();
      if (state.report.status === "running") setTimeout(refresh, 1500);
    }
  } catch (error) { /* the server went away; keep the last paint */ }
}

$("undo").addEventListener("click", () => step(-1));
$("next").addEventListener("click", () => step(1));
$("save").addEventListener("click", save);
$("hide").addEventListener("change", (e) => { state.hideUnchanged = e.target.checked; renderDiff(); });
$("vsorig").addEventListener("change", (e) => { state.vsOriginal = e.target.checked; renderDiff(); });
document.addEventListener("keydown", (event) => {
  if (event.target.tagName === "INPUT") return;
  if (event.key === "ArrowLeft") { event.preventDefault(); step(-1); }
  if (event.key === "ArrowRight") { event.preventDefault(); step(1); }
  if (event.key === "h") { $("hide").checked = !$("hide").checked; state.hideUnchanged = $("hide").checked; renderDiff(); }
  if (event.key === "c") { $("vsorig").checked = !$("vsorig").checked; state.vsOriginal = $("vsorig").checked; renderDiff(); }
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
