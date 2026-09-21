"""The HTML view: the verdict, the decisions it forces, the draft, and the evidence.

One self-contained page — no CDN, no build step. The run payload is embedded for the
first paint and re-fetched from ``/api/report`` while the loop is still running.

The design follows https://typesafe.ai: paper and black ink, one halftone accent spent on
the only block that asks for a decision, heavy display type at tight leading, hanging
monospace micro-labels, two-pixel borders with a hard offset shadow, and corner ticks
framing the sections. Monospace carries anything a reader might compare; the display face
carries the one number the page exists to report.

The order is the order a decision is made: what the draft scored, what a person has to
rule on, what the draft says, why the number came out that way, and only then the
evidence behind it.
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
  --paper:#fefefe; --ink:#1e1e1e; --ink-2:rgba(30,30,30,.86);
  --mute:rgba(30,30,30,.5); --rule:rgba(30,30,30,.22); --wash:#f3f1ef;
  /* The TypeSafe palette, sampled from the site: pink, magenta and sage are the only hues
     it uses, over paper, ink and three greys. */
  --pink:#f386a1; --magenta:#d45bb2; --sage:#abbab9;
  --grey:#dedede; --grey-2:#e5e5e5;
  /* A darker step of the same three hues. The palette is bright, and the numbers on this
     page are small text, so they need a step that stays legible on paper. */
  --pink-ink:#a83a56; --magenta-ink:#96227f; --sage-ink:#4f6462;
  --shadow:6px 6px 0 var(--ink);
  --halftone:radial-gradient(rgba(30,30,30,.28) 1.15px, transparent 1.35px);
  --mono:"JetBrains Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --sans:"Helvetica Neue",Helvetica,Inter,ui-sans-serif,system-ui,-apple-system,Arial,sans-serif;
}
*{box-sizing:border-box}
/* A page for a browser window: a ceiling so a diff does not stretch to 2000px, and one
   column, because the report has a reading order. */
body{margin:0 auto;max-width:1300px;padding:0 30px 44px;background:var(--paper);
  color:var(--ink-2);font:15px/1.5 var(--sans);-webkit-font-smoothing:antialiased}
h1,h2,p{margin:0}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0,0,0,0);white-space:nowrap;border:0}

/* ── The two voices: display type for the one number, mono for everything read as data ── */
.display{color:var(--ink);font-weight:500;line-height:.86;letter-spacing:-.028em;
  text-transform:capitalize}
/* No text-transform on .badge, #paths or #stop: those carry run state, and a status a
   reader has to parse should read exactly as the run reports it. */
.label{font:400 10.5px/1.4 var(--mono);letter-spacing:.06em;text-transform:capitalize;
  color:var(--ink-2)}
/* A mono label that is a sentence rather than a title keeps its own case. */
.label.plain{text-transform:none}
.label-block{border-left:1px solid var(--ink);min-height:22px;padding-left:12px}
.muted{color:var(--mute)}
.mono{font-family:var(--mono)}

/* ── Shell ─────────────────────────────────────────────────────────────────── */
.topbar{display:flex;flex-wrap:wrap;align-items:stretch;margin:26px 0 0;
  border:2px solid var(--ink)}
.topbar > *{display:flex;align-items:center;min-width:0;padding:9px 13px;
  border-right:2px solid var(--ink)}
.topbar > *:last-child{border-right:none}
.brand{background:var(--ink);color:var(--paper);font:400 11px/1 var(--mono);
  letter-spacing:.06em;text-transform:capitalize;white-space:nowrap}
.topbar h1{color:var(--ink);font-size:15px;font-weight:600;letter-spacing:-.005em;
  white-space:nowrap}
#paths{display:block;flex:1 1 auto;align-self:stretch;padding:9px 13px;
  font:400 11.5px/1.6 var(--mono);color:var(--mute);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}
.badge{font:400 11.5px/1 var(--mono);letter-spacing:.04em;border:1px solid var(--ink);
  padding:4px 8px;white-space:nowrap}
.badge:empty{display:none}
.badge.live{background:var(--ink);color:var(--paper)}
.badge.blocked{background:var(--pink);border-color:var(--pink);color:var(--ink)}
/* The run's outcome, on a pink band the way the reference bands its sections: the state on
   the left, the reason the loop gave on the right. */
#stop{display:flex;flex-wrap:wrap;gap:4px 16px;justify-content:space-between;
  align-items:baseline;background:var(--pink);color:var(--ink);padding:8px 13px;
  font:400 11.5px/1.5 var(--mono);letter-spacing:.03em}
#stop .state{letter-spacing:.08em;text-transform:capitalize;white-space:nowrap}
#stop .detail{min-width:0;text-align:right;color:rgba(30,30,30,.72)}

.page{position:relative}
.toolbar{position:sticky;top:0;z-index:6;display:flex;flex-wrap:wrap;gap:9px;
  align-items:center;padding:10px 12px;margin:26px 0 30px;background:var(--paper);
  border:2px solid var(--ink);box-shadow:var(--shadow)}
.timeline{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.tools{display:flex;flex-wrap:wrap;gap:7px;align-items:center;margin-left:auto}
.status-note{flex:1 1 100%;font:400 11.5px/1.5 var(--mono);color:var(--sage-ink)}
.status-note:empty{display:none}
.chip{display:inline-flex;align-items:center;gap:8px;padding:6px 10px;cursor:pointer;
  background:var(--paper);border:1px solid var(--ink);color:var(--ink);
  font:400 11.5px/1 var(--mono);letter-spacing:.03em;text-transform:capitalize}
.chip:hover{background:var(--wash)}
.chip.sel{background:var(--magenta);color:var(--ink)}
.chip .n{color:var(--mute);font-variant-numeric:tabular-nums}
.chip.sel .n{color:rgba(30,30,30,.66)}
/* The timeline marks two different things: the draft the loop kept, and the one on disk. */
.star{color:var(--magenta-ink)}
.chip.sel .star{color:var(--ink)}
.star.muted{color:rgba(30,30,30,.35)}
.saved{color:var(--sage-ink)}
.chip.sel .saved{color:var(--ink)}

button{padding:7px 11px;cursor:pointer;background:var(--paper);border:1px solid var(--ink);
  color:var(--ink);font:400 11.5px/1 var(--mono);letter-spacing:.03em}
button:hover:not(:disabled){background:var(--ink);color:var(--paper)}
button:disabled{opacity:.3;cursor:default}
button.primary{background:var(--ink);color:var(--paper)}
button.primary:hover:not(:disabled){background:#000;color:var(--paper)}
/* The one pair of buttons that changes the run: proceed, or stop the line. */
button.keep{background:var(--sage);border-color:var(--ink);color:var(--ink)}
button.keep:hover:not(:disabled){background:var(--sage-ink);color:var(--paper)}
button.drop{background:var(--pink);border-color:var(--ink);color:var(--ink)}
button.drop:hover:not(:disabled){background:var(--pink-ink);color:var(--paper)}
button:focus-visible,.chip:focus-visible,.editable:focus-visible{outline:2px solid var(--ink);
  outline-offset:2px}
kbd{border:1px solid var(--ink);background:var(--paper);padding:1px 5px;
  font:400 10.5px/1.5 var(--mono)}
input[type=checkbox],input[type=range]{accent-color:var(--ink)}
.toggle{display:inline-flex;gap:6px;align-items:center;cursor:pointer;user-select:none;
  font:400 11.5px/1 var(--mono);letter-spacing:.03em;color:var(--ink-2)}
.note{font:400 11.5px/1.45 var(--mono);color:var(--mute)}
.note.warn{color:var(--magenta-ink)}

.rubric{margin:-30px 0 30px;padding:14px 12px;background:var(--paper);
  border:2px solid var(--ink);border-top:none;box-shadow:var(--shadow)}
.rubric-inner{display:flex;flex-wrap:wrap;gap:14px 24px;align-items:flex-start}
.wsliders{display:grid;grid-template-columns:repeat(auto-fit,minmax(288px,1fr));gap:9px 30px}
.wslider-row{display:flex;gap:8px;align-items:center;white-space:nowrap;
  font:400 11.5px/1 var(--mono);text-transform:capitalize}
.wslider-row input[type=range]{width:72px}
.rubric-foot{display:flex;flex-wrap:wrap;gap:9px;align-items:center}

/* ── Sections, framed by corner ticks ──────────────────────────────────────── */
main > section{margin:0 0 30px}
main > section:empty{display:none}
main > section > .win + .win{margin-top:30px}
/* Four corner marks drawn from gradients: the reference frames its bands this way, and it
   needs no extra elements in the markup the renderer builds. */
.frame{position:relative;padding:26px 26px 22px}
.frame::before{content:"";position:absolute;inset:0;pointer-events:none;
  background-image:
    linear-gradient(var(--magenta),var(--magenta)),linear-gradient(var(--magenta),var(--magenta)),
    linear-gradient(var(--magenta),var(--magenta)),linear-gradient(var(--magenta),var(--magenta)),
    linear-gradient(var(--magenta),var(--magenta)),linear-gradient(var(--magenta),var(--magenta)),
    linear-gradient(var(--magenta),var(--magenta)),linear-gradient(var(--magenta),var(--magenta));
  background-repeat:no-repeat;
  background-size:15px 1px,1px 15px,15px 1px,1px 15px,15px 1px,1px 15px,15px 1px,1px 15px;
  background-position:left top,left top,right top,right top,left bottom,left bottom,
    right bottom,right bottom}

/* ── Windows: the block, its bar, its contents ────────────────────────────── */
/* The bar is the section's colour, always with ink on it: the palette is light enough that
   ink keeps ~5:1 or better on pink, magenta and sage, so the coloured bands stay readable
   and the black bar is left for the draft, which is the one block that is not a judgment. */
.win{border:2px solid var(--ink);box-shadow:var(--shadow);background:var(--paper)}
.win-bar{display:flex;flex-wrap:wrap;gap:5px 16px;align-items:baseline;
  justify-content:space-between;padding:8px 13px;background:var(--ink);color:var(--paper);
  font:400 10.5px/1.5 var(--mono);letter-spacing:.06em;text-transform:capitalize}
.win.magenta > .win-bar{background:var(--magenta);color:var(--ink)}
.win.pink > .win-bar{background:var(--pink);color:var(--ink)}
.win.sage > .win-bar{background:var(--sage);color:var(--ink)}
.win.grey > .win-bar{background:var(--grey);color:var(--ink)}
.win-bar .t{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.win-bar .r{min-width:0;text-align:right;color:rgba(254,254,254,.6);letter-spacing:.02em;
  text-transform:none;font-size:11.5px}
.win.pink > .win-bar .r, .win.magenta > .win-bar .r, .win.sage > .win-bar .r,
.win.grey > .win-bar .r{color:rgba(30,30,30,.62)}
.win-bar .r .up{color:#a8e0bd}
.win-bar .r .down{color:#efa9a2}
.win-bar .r .flat{color:rgba(254,254,254,.6)}
summary.win-bar{cursor:pointer;list-style:none}
summary.win-bar::-webkit-details-marker{display:none}
summary.win-bar:hover{filter:brightness(.92)}
.caret::before{content:"▸";margin-right:8px;opacity:.7}
details[open] > summary .caret::before{content:"▾"}
.band-head{display:flex;flex-wrap:wrap;gap:4px 16px;justify-content:space-between;
  align-items:baseline;padding:11px 16px;border-bottom:1px solid var(--ink)}
.band-head .r{font:400 11px/1.5 var(--mono);color:var(--mute)}
.lead{padding:18px 16px;font-size:17px;line-height:1.4;letter-spacing:.02em;
  color:var(--ink-2);max-width:74ch}

/* ── Verdict: the one number, at display size ─────────────────────────────── */
.hero-head{display:flex;flex-wrap:wrap;gap:6px 18px;justify-content:space-between;
  align-items:baseline;padding-bottom:12px;border-bottom:2px solid var(--magenta)}
.hero-body{display:flex;flex-wrap:wrap;gap:16px 44px;align-items:flex-end;padding:22px 0 0}
/* The one number the page exists to report, in the palette's magenta. At this size it needs
   3:1, not 4.5:1, so the bright brand step is the right one here. */
.hero-number{font-weight:500;font-size:clamp(66px,9.4vw,126px);line-height:.82;
  letter-spacing:-.045em;color:var(--magenta);font-variant-numeric:tabular-nums}
.hero-side{min-width:0;flex:1 1 300px;padding-bottom:6px}
.hero-line{font-size:17px;line-height:1.45;letter-spacing:.02em;color:var(--ink-2)}
.hero-line b{color:var(--ink);font-weight:600}
.hero-line + .hero-line{margin-top:4px}
.hero-line.muted{color:var(--mute);font-size:15px}
.hero-line .risk{color:var(--pink-ink);font-weight:600}
.hero-line .safe{color:var(--sage-ink);font-weight:600}
.hero-eyebrow{color:var(--magenta-ink)}
.tag{display:inline-block;margin-left:10px;padding:2px 6px;border:1px solid var(--ink);
  color:var(--ink);font-size:10.5px;letter-spacing:.06em;text-transform:capitalize;
  vertical-align:3px}
.tag.bad{background:var(--pink);border-color:var(--pink);color:var(--ink)}
.hero-trust{display:flex;flex-wrap:wrap;gap:7px 22px;align-items:baseline;margin-top:24px;
  padding-top:11px;border-top:1px dotted var(--rule);
  font:400 11.5px/1.6 var(--mono);color:var(--mute)}
.hero-trust b{color:var(--ink);font-weight:400}
.hero-trust .weakest{flex-basis:100%;min-width:0;color:var(--ink-2)}
.hero-trust .unsupported b{color:var(--pink-ink)}
.hero-trust .uncertain b{color:var(--magenta-ink)}
.hero-trust .carried b{color:var(--sage-ink)}

/* ── Measurements: a name, a leader, a number, and the bar it came from ───── */
.rows{padding:0}
.row{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:0 18px;
  align-items:baseline;padding:12px 16px 10px;border-bottom:1px dotted var(--rule)}
.row:last-child{border-bottom:none}
/* The name and the dots share the first column so the dots really do lead from the name
   to the number, whatever the name's length. */
.row .name{display:flex;align-items:baseline;gap:11px;min-width:0;font-size:15px;
  letter-spacing:.01em;color:var(--ink);text-transform:capitalize}
.row .name > span:first-child{min-width:0;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.row .dots{flex:1 1 24px;min-width:18px;transform:translateY(-4px);
  border-bottom:1px dotted var(--rule)}
.row .value{font:400 15px/1.4 var(--mono);color:var(--ink);font-variant-numeric:tabular-nums;
  white-space:nowrap}
.row .value .of{color:var(--mute);font-size:12px}
.row .meta{font:400 11px/1.5 var(--mono);color:var(--mute);white-space:nowrap;min-width:0}
.row .meta.warn{color:var(--pink-ink)}
/* Bar colour carries the reading so the row does not have to be read: sage under the line,
   magenta scored, pink a risk. The track stays paper, because the light steps of the palette
   sit too close to a grey track to read as a fill. */
.row .meter{grid-column:1 / -1;display:block;margin-top:8px;height:7px;background:var(--paper);
  border:1px solid var(--ink)}
.row .meter > i{display:block;height:100%;background:var(--magenta)}
.row .meter.safe > i{background:var(--sage-ink)}
.row .meter.risk > i{background:var(--pink)}
.row .meter.plain > i{background:var(--ink)}

/* One hue per reading, used everywhere the same reading appears. */
.risk{color:var(--pink-ink)} .safe{color:var(--sage-ink)} .scored{color:var(--magenta-ink)}
.ok{color:var(--sage-ink)} .unc{color:var(--magenta-ink)} .bad{color:var(--pink-ink)}
.up{color:var(--sage-ink)} .down{color:var(--pink-ink)} .flat{color:var(--mute)}

/* ── The decision band: the one place the accent is spent ─────────────────── */
.decide{padding:20px 16px;background-color:var(--pink);background-image:var(--halftone);
  background-size:5px 5px;background-repeat:repeat}
.decide ul{list-style:none;margin:0;padding:0}
.decide li{background:var(--paper);border:2px solid var(--ink);box-shadow:4px 4px 0 var(--ink);
  padding:15px 17px}
.decide li + li{margin-top:16px}
.decide .quote{display:flex;flex-wrap:wrap;gap:2px 16px;justify-content:space-between;
  margin-bottom:9px;font:400 10.5px/1.5 var(--mono);letter-spacing:.06em;color:var(--mute)}
.decide .line-text{font-size:16px;line-height:1.45;letter-spacing:.015em;color:var(--ink)}
.decide .why{margin-top:9px;padding-top:9px;border-top:1px dotted var(--rule);
  font:400 12px/1.55 var(--mono);color:var(--pink-ink)}
.decide .acts{display:flex;flex-wrap:wrap;gap:9px;margin-top:13px}
.decide .acts button{padding:9px 15px}
.verdict-tag{display:inline-block;margin-left:10px;padding:2px 7px;border:1px solid var(--sage-ink);
  color:var(--sage-ink);font:400 11px/1.5 var(--mono);letter-spacing:.04em;vertical-align:2px}
.verdict-tag.rejected{border-color:var(--pink-ink);color:var(--pink-ink)}

/* ── The draft: line numbers, a +/− column, the text, and its evidence ────── */
.diff-body{max-height:74vh;overflow:auto}
.line{display:grid;grid-template-columns:40px 40px 26px minmax(0,1fr) 106px;align-items:start;
  padding:3px 0;font:400 11.5px/1.65 var(--mono);border-left:3px solid transparent;
  border-bottom:1px dotted var(--rule)}
.line .g{color:var(--mute);font-size:11px;text-align:right;padding-right:9px;user-select:none}
.line .g.r{border-right:1px solid var(--rule)}
.line .mark{text-align:center;color:var(--mute)}
.line .t{min-width:0;padding-right:12px;white-space:pre-wrap;word-break:break-word;
  color:var(--ink)}
.line .act{padding-right:11px;text-align:right}
/* Added and removed lines take the palette's two signal hues, so a scan of the diff reads
   as colour rather than as two shades of grey. */
.line.add{background:rgba(171,186,185,.26);border-left-color:var(--sage-ink)}
.line.add .mark{color:var(--sage-ink)}
.line.remove{background:rgba(243,134,161,.22);border-left-color:var(--pink-ink)}
.line.remove .mark{color:var(--pink-ink)}
.line.remove .t{color:var(--mute)}
.line.eq .mark{color:transparent}
.line.skip{display:block;padding:6px 14px;background:var(--grey-2);color:var(--mute);
  border-left-color:transparent;border-bottom:1px dotted var(--rule);text-align:center;
  font-size:11.5px}
/* The evidence control is a link, not a button: it opens a footnote under the line. */
.src-btn{background:none;border:none;padding:0;cursor:pointer;color:var(--sage-ink);
  text-align:right;font:400 10.5px/1.65 var(--mono);letter-spacing:.04em;
  text-decoration:underline;text-underline-offset:3px}
button.src-btn:hover{background:none;color:var(--ink)}
.src-btn.nosrc{color:var(--pink-ink);font-weight:600}
.src-row{display:none;padding:11px 14px 13px 118px;background:var(--grey-2);color:var(--ink-2);
  border-bottom:1px dotted var(--rule);font:400 11.5px/1.65 var(--mono)}
.src-row.open{display:block}
.src-row .no{color:var(--pink-ink)}

/* ── Editing a draft, with the reviewer's verdict in the gutter ───────────── */
.editrow{display:grid;grid-template-columns:28px minmax(0,1fr);align-items:start;
  padding:2px 14px 2px 0;border-bottom:1px dotted var(--rule)}
.editrow .dot{text-align:center;font:400 11px/2.3 var(--mono);color:var(--mute);cursor:help}
.editrow .dot.unc{color:var(--magenta-ink)}
.editrow .dot.bad{color:var(--pink-ink)}
.editrow .dot.ok{color:var(--sage-ink)}
.editable{outline:none;font:400 11.5px/1.65 var(--mono);color:var(--ink);
  white-space:pre-wrap;word-break:break-word;padding:0 2px}
.editable:focus{background:var(--wash)}

/* ── Evidence behind the verdict ─────────────────────────────────────────── */
.filters{display:flex;flex-wrap:wrap;gap:6px;padding:12px 16px;border-bottom:1px solid var(--ink)}
.filters button{padding:5px 9px;font-size:11px}
.filters button.on{background:var(--ink);color:var(--paper)}
.ledger{list-style:none;margin:0;padding:0;max-height:440px;overflow:auto}
.ledger li{padding:11px 16px;border-bottom:1px dotted var(--rule)}
.ledger li:last-child{border-bottom:none}
.ledger .ln{display:flex;gap:12px;align-items:baseline}
.ledger .p{flex:0 0 38px;text-align:right;font:400 12px/1.65 var(--mono);
  font-variant-numeric:tabular-nums}
.ledger .t{flex:1;min-width:0;font-size:14px;line-height:1.5;letter-spacing:.01em;
  color:var(--ink);word-break:break-word}
/* One row per clause of a multi-clause line, clipped rather than wrapped: the claim set is
   a distribution to scan, and the full text is in the line above and on hover. */
.claim{display:flex;gap:9px;align-items:baseline;padding:3px 0 0 50px;
  font:400 11px/1.65 var(--mono);color:var(--mute)}
.claim .t{flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.claim .fails{flex:0 0 auto;color:var(--pink-ink);font-size:10px;letter-spacing:.06em;
  text-transform:capitalize}

.cov{padding:0 16px}
.cov-row{display:grid;grid-template-columns:22px minmax(0,1fr);gap:3px 11px;padding:12px 0;
  border-bottom:1px dotted var(--rule)}
.cov-row:last-child{border-bottom:none}
.cov-row .mark{text-align:center;font:400 13px/1.5 var(--mono)}
.cov-row .mark.ok{color:var(--sage-ink)}
.cov-row .mark.no{color:var(--pink-ink)}
.cov-row .req{font-size:15px;line-height:1.45;letter-spacing:.01em;color:var(--ink)}
.cov-row .ans{grid-column:2;font:400 11px/1.6 var(--mono);color:var(--mute)}
/* A requirement nothing answers is the point of the matrix, so it gets the attention hue. */
.cov-row.open-req{background:rgba(243,134,161,.16);margin:0 -8px;padding-left:8px;
  padding-right:8px}
.cov-row.open-req .ans{color:var(--pink-ink)}
details.sub{border-top:1px solid var(--ink)}
details.sub > summary{display:flex;flex-wrap:wrap;gap:4px 16px;
  justify-content:space-between;padding:11px 16px;cursor:pointer;list-style:none;
  font:400 11px/1.5 var(--mono);letter-spacing:.04em;color:var(--mute)}
details.sub > summary::-webkit-details-marker{display:none}
details.sub > summary:hover{color:var(--ink)}
.jd{margin:0;padding:14px 16px;background:var(--grey-2);
  font:400 11.5px/1.7 var(--mono);color:var(--ink-2);white-space:pre-wrap;
  max-height:240px;overflow:auto}

.kv{display:grid;grid-template-columns:auto minmax(0,1fr);gap:10px 24px;padding:16px;
  font:400 12px/1.6 var(--mono)}
.kv .k{color:var(--magenta-ink);text-transform:capitalize}
.cost-rows{padding:0 16px 16px}
.cost-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 14px;
  align-items:baseline;padding:11px 0;border-bottom:1px dotted var(--rule)}
.cost-row:last-child{border-bottom:none}
.cost-row .num{font-variant-numeric:tabular-nums;color:var(--mute)}
.cost-row .meter{grid-column:1 / -1;margin-top:4px}

footer{display:flex;flex-wrap:wrap;gap:10px 24px;align-items:baseline;padding-top:22px;
  border-top:2px solid var(--ink);font:400 11px/1.6 var(--mono);color:var(--mute)}
footer .keys{display:flex;flex-wrap:wrap;gap:9px;align-items:baseline;margin-left:auto}
/* The colour key. Three hues carry three readings all over the page, so the page says so
   once, in the place a reader ends up anyway. */
.key{display:flex;flex-wrap:wrap;gap:8px 18px;flex-basis:100%;align-items:baseline}
.key span{display:inline-flex;gap:7px;align-items:baseline}
.key i{width:11px;height:11px;border:1px solid var(--ink);flex:0 0 auto;
  transform:translateY(1px)}
.key .k-sage i{background:var(--sage)}
.key .k-pink i{background:var(--pink)}
.key .k-magenta i{background:var(--magenta)}
.key .k-sage{color:var(--sage-ink)}
.key .k-pink{color:var(--pink-ink)}
.key .k-magenta{color:var(--magenta-ink)}
</style>
</head>
<body>
<div class="topbar">
  <span class="brand">resume polisher</span>
  <h1>deepseek writes, jev judges</h1>
  <span id="paths"></span>
  <span id="status" class="badge"></span>
</div>
<div id="stop"></div>
<!-- Rounds arrive on their own, so the newest one is announced rather than hunted for. -->
<p id="live" class="sr-only" role="status" aria-live="polite"></p>

<div class="page">
  <div class="toolbar">
    <div id="timeline" class="timeline"></div>
    <div class="tools">
      <button id="undo" title="previous version (←)">←</button>
      <button id="next" title="next version (→)">→</button>
      <label class="toggle" title="hide the lines this draft did not touch (h)"><input type="checkbox" id="hide" checked /> unchanged</label>
      <label class="toggle" title="compare against the original resume rather than the previous round (c)"><input type="checkbox" id="vsorig" /> vs original</label>
      <button id="rubric-btn" title="re-weight the rubric (w)">weights</button>
      <button id="edit" title="edit this draft and re-check only the lines you change (e)">edit</button>
      <button id="save" class="primary" title="write this version to the output file">save</button>
      <button id="saveedit" class="primary" style="display:none" title="write the edited draft to the output file">save edit</button>
    </div>
    <span id="savestatus" class="status-note"></span>
  </div>
  <div id="rubric-panel" class="rubric" style="display:none">
    <div class="rubric-inner">
      <span class="label label-block">re-weight</span>
      <div id="wsliders" class="wsliders"></div>
      <div class="rubric-foot">
        <span id="wsum" class="note"></span>
        <button id="wreset">reset</button>
        <button id="wexport">copy weights</button>
        <span id="wreweight-note" class="note warn"></span>
      </div>
    </div>
  </div>

  <main>
    <section id="scores"></section>
    <section id="flagged"></section>
    <section>
      <div class="win">
        <div class="win-bar" id="diffhead"></div>
        <div class="diff-body" id="diff"></div>
      </div>
    </section>
    <section id="checks"></section>
    <section id="ledger"></section>
    <section id="coverage"></section>
    <section id="totals"></section>
  </main>
</div>

<footer id="footer"></footer>

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
const spaced = (name) => String(name).replace(/_/g, " ");
// Dimension and check names are lowercase identifiers; these read as words except for the
// two the reviewer knows by their capitals. Done with a map, not a word-boundary regex,
// because a backslash in this template is eaten by the Python string it lives in.
const ACRONYMS = { jd: "JD", api: "API" };
const words = (name) => spaced(name).split(" ")
  .map((word) => ACRONYMS[word] || word).join(" ");

// Folded windows the reader opened. Every window is rebuilt from scratch on each poll, so
// the open state has to live out here or a live run would keep shutting them.
const _open = { ledger:true, coverage:true, totals:false };
function foldWindow(id, title, meta, body, tone) {
  return `<details class="win${tone ? " " + tone : ""}" data-fold="${id}"${
    _open[id] ? " open" : ""}>
    <summary class="win-bar"><span class="t"><span class="caret"></span>${title}</span>
      <span class="r">${meta}</span></summary>${body}</details>`;
}
function bindWindows(root) {
  root.querySelectorAll("details[data-fold]").forEach((card) => {
    card.addEventListener("toggle", () => { _open[card.dataset.fold] = card.open; });
  });
}
function meter(value, cls) {
  const width = Math.max(0, Math.min(1, value)) * 100;
  return `<span class="meter ${cls || ""}"><i style="width:${width.toFixed(1)}%"></i></span>`;
}
function delta(now, before, digits = 2) {
  if (before === undefined || before === null) return "";
  const change = now - before;
  const cls = Math.abs(change) < 0.005 ? "flat" : change > 0 ? "up" : "down";
  return `<span class="delta ${cls}">${change > 0 ? "+" : ""}${change.toFixed(digits)}</span>`;
}
// The overall a reader is looking at: the loop's own number, or the re-weighted one when the
// sliders are off their defaults. Comparing a re-weighted draft to a loop number would be
// two different scales in one delta, so the comparison follows the same definition.
function scoreOf(version) {
  if (!version || !version.review) return null;
  const reweighted = _isReweighted() ? _recomputeOverall(version, _activeWeights()) : null;
  return reweighted === null ? version.review.overall : reweighted;
}
// Which of the palette's three hues a reading gets. Chosen the same way everywhere, so the
// same colour means the same thing in the verdict, the bars, the ledger and the diff.
function bandClass(value, safeAt, riskBelow) {
  return value >= safeAt ? "safe" : value >= riskBelow ? "" : "risk";
}
// One measurement as a leader row: the name, dots that carry the eye across to the number,
// and the meter the number came from underneath. Same shape for a score and a probability,
// so the two bands are read the same way. `cls` is the reading its bar is painted in.
function leaderRow(name, value, of, meta, metaWarn, ratio, cls) {
  return `<div class="row">
      <span class="name"><span>${esc(words(name))}</span><span class="dots"></span></span>
      <span class="value">${value}${of ? `<span class="of">${of}</span>` : ""}</span>
      <span class="meta${metaWarn ? " warn" : ""}">${meta}</span>
      ${meter(ratio, cls)}
    </div>`;
}
function dimensionRows(version, prev) {
  const cfg = state.report.config || {};
  const order = cfg.dimension_order || Object.keys(version.review.scores);
  const floor = cfg.confidence_floor ?? 0.6;
  return order.map((name) => {
    const score = version.review.scores[name];
    const before = prev && prev.review ? prev.review.scores[name].score : null;
    const low = score.confidence < floor;
    const meta = `level ${score.level}/${cfg.top_level}${low
      ? ` · confidence only ${score.confidence.toFixed(2)}` : ""}`;
    return leaderRow(name, score.score.toFixed(2), "/4", `${meta} ${delta(score.score, before)}`,
                     low, score.normalized, bandClass(score.normalized, 0.75, 0.5));
  }).join("");
}
function checkRows(version) {
  const cfg = state.report.config || {};
  const block = cfg.fabrication_block ?? 0.5;
  const review = version.review;
  const checks = Object.entries(review.guardrails || {}).sort((a, b) => b[1] - a[1]);
  const rows = checks.map(([name, probability]) => {
    const hot = probability >= block;
    return leaderRow(name, probability.toFixed(2), "",
                     hot ? `blocks at ${block.toFixed(2)}` : "under the block line",
                     hot, probability, hot ? "risk" : "safe");
  });
  rows.push(leaderRow("mean line grounding", review.line_grounding.toFixed(2), "",
    `over ${review.audited_lines} lines`, false, review.line_grounding,
    bandClass(review.line_grounding, 0.8, 0.5)));
  // The gate itself, last: the mean can be high while one line sinks the score, and the
  // whole point of the number is that it is the worst signal, not the average one.
  const risk = review.fabrication_risk;
  rows.push(leaderRow("fabrication risk", risk.toFixed(2), "",
    risk >= block ? `blocks at ${block.toFixed(2)}`
      : "the loudest signal: the worst check or the weakest line",
    risk >= block, risk, risk >= block ? "risk" : "safe"));
  return rows.join("");
}

function renderScores() {
  const el = $("scores");
  const version = current();
  if (!version || !version.review) {
    el.innerHTML = `<div class="frame">
      <div class="hero-head"><span class="label hero-eyebrow">verdict ......</span>
        <span class="label plain">nothing scored yet</span></div>
      <div class="hero-body"><div class="hero-side">
        <p class="hero-line">Every round lands here with five dimension scores, three
          fabrication checks, and a grounding verdict on each line of the draft. The run has
          not judged anything yet.</p></div></div></div>`;
    return;
  }
  const cfg = state.report.config || {};
  const review = version.review;
  const prev = previous();
  const overall = scoreOf(version);
  const before = scoreOf(prev);
  const change = delta(overall, before);
  const gap = review.gap_is_split
    ? "the reviewer is split — " + Object.entries(review.gap_distribution)
        .sort((a, b) => b[1] - a[1]).slice(0, 2)
        .map(([name, probability]) => `${esc(words(name))} ${probability.toFixed(2)}`)
        .join(" against ")
    : esc(words(review.biggest_gap));
  const trust = review.trust || {};
  const block = cfg.fabrication_block ?? 0.5;
  const gated = review.fabrication_risk >= block;
  const weakest = review.weakest_line
    ? `<span class="weakest">weakest line · ${review.weakest_line.support.toFixed(2)} · ${
        esc(review.weakest_line.text)}</span>`
    : "";
  const best = review.is_best ? `<span class="tag">best</span>` : "";
  const blocked = review.blocked ? `<span class="tag bad">blocked</span>` : "";
  const carried = version.reviewed ? "" : "unchanged, scores carried over";
  el.innerHTML = `<div class="frame">
    <div class="hero-head">
      <span class="label hero-eyebrow">verdict ......</span>
      <span class="label plain">${esc(version.label)}${best}${blocked} · ${carried
        || `${trust.audited || 0} lines audited`}</span>
    </div>
    <div class="hero-body">
      <div class="hero-number">${overall.toFixed(2)}</div>
      <div class="hero-side">
        <p class="hero-line">quality <b>${review.quality.toFixed(2)}</b> ×
          grounded <b class="${gated ? "risk" : "safe"}">${review.groundedness.toFixed(2)}</b>
          ${_isReweighted() ? "<b>· re-weighted view</b>" : ""}</p>
        <p class="hero-line muted">grounded = 1 − fabrication risk
          <b class="${gated ? "risk" : "safe"}">${review.fabrication_risk.toFixed(2)}</b>${
          gated ? " — over the block line" : ""}</p>
        <p class="hero-line">${before === null
          ? "<b>the first draft</b> — nothing to compare it against yet"
          : `${change} against the previous round`}</p>
        <p class="hero-line">biggest gap — <b>${gap}</b></p>
      </div>
    </div>
    <div class="hero-trust">
      <span><b>${trust.audited || 0}</b> lines audited</span>
      <span class="carried"><b>${trust.carried || 0}</b> carried, not re-asked</span>
      <span class="unsupported"><b>${trust.unsupported || 0}</b> unsupported</span>
      <span class="uncertain"><b>${trust.uncertain || 0}</b> uncertain</span>
      <span class="uncertain"><b>${trust.low_confidence || 0}</b> low-confidence dimensions</span>
      ${weakest}
    </div>
  </div>`;
}

function renderChecks() {
  const el = $("checks");
  const version = current();
  if (!version || !version.review) { el.innerHTML = ""; return; }
  const cfg = state.report.config || {};
  el.innerHTML = `<div class="win magenta">
      <div class="win-bar"><span class="t">dimensions</span>
        <span class="r">weighted mean, each scored against a level of ${cfg.top_level}</span></div>
      <div class="rows">${dimensionRows(version, previous())}</div>
    </div>
    <div class="win pink">
      <div class="win-bar"><span class="t">fabrication checks</span>
        <span class="r">probability the draft added something the original does not support —
          a draft is blocked at ${(cfg.fabrication_block ?? 0.5).toFixed(2)}</span></div>
      <div class="rows">${checkRows(version)}</div>
    </div>`;
}

// The lines the reviewer could not ground, with the decision they need. They come straight
// after the verdict because they are the only thing on the page that needs a person, and
// this is the one band that gets the accent colour.
// The buttons carry the flagged line's position, never its text: a line containing a quote
// cannot break out of an HTML attribute, and the click handler reads the text back from the
// payload, so nothing user-supplied is interpolated into markup.
function renderFlagged() {
  const el = $("flagged");
  const version = current();
  const review = version && version.review;
  const lines = (review && review.flagged_lines) || [];
  if (!lines.length) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = `<div class="win pink">
    <div class="win-bar"><span class="t">needs a decision</span>
      <span class="r">${lines.length} line${lines.length === 1 ? "" : "s"} the reviewer could
        not ground — approve or reject before this ships</span></div>
    <div class="decide"><ul>${lines.map((text, i) => {
      const entry = (review.lines_to_review || []).find((line) => line.text === text);
      const decision = entry && entry.decision;
      const claim = entry && entry.failing_claim
        ? `<div class="why">failing claim — “${esc(entry.failing_claim)}”</div>`
        : "";
      const tag = decision
        ? `<span class="verdict-tag${decision === "rejected" ? " rejected" : ""}">${esc(decision)}</span>`
        : "";
      const acts = decision ? ""
        : `<div class="acts">
             <button class="review keep" data-version="${version.index}" data-line-index="${i}" data-verdict="approved">Approve</button>
             <button class="review drop" data-version="${version.index}" data-line-index="${i}" data-verdict="rejected">Reject</button>
           </div>`;
      return `<li><div class="quote"><span>unverified line ${i + 1} of ${lines.length}</span>
        <span>grounding ${entry ? entry.support.toFixed(2) : "—"}${tag}</span></div>
        <div class="line-text">${esc(text)}</div>${claim}${acts}</li>`;
    }).join("")}</ul></div></div>`;
}

function diffRows(version) {
  const evidence = (version.review && version.review.evidence) ? version.review.evidence : {};
  const key = state.vsOriginal ? "diff_vs_original" : "diff_vs_previous";
  const diff = version[key];
  if (!diff || !diff.rows.length) return `<div class="line skip">nothing to compare yet</div>`;
  return diff.rows.filter((row) => !state.hideUnchanged || row.kind !== "equal")
    .map((row) => {
      if (row.kind === "skip") {
        return `<div class="line skip">⋯ ${row.count} unchanged line${
          row.count === 1 ? "" : "s"}</div>`;
      }
      const oldNo = row.old ?? "", newNo = row.new ?? "";
      const mark = row.kind === "add" ? "+" : row.kind === "remove" ? "−" : "·";
      const lineKey = auditKey(row.text);
      const sourced = Object.prototype.hasOwnProperty.call(evidence, lineKey);
      const source = evidence[lineKey];
      // The absence of evidence is the evidence: a line nothing in the original supports
      // says so in the row itself, in the colour reserved for it.
      const missing = sourced && (source === null || source === undefined);
      const action = sourced
        ? `<button class="src-btn${missing ? " nosrc" : ""}" data-missing="${
            missing ? "1" : ""}" title="${
            missing ? "this line has no source in the original resume" : "show the original line"
            }">${missing ? "no source" : "source"} ▸</button>`
        : "";
      const sourceRow = sourced
        ? `<div class="src-row">${missing
            ? '<span class="no">⊘ no line in the original resume supports this claim</span>'
            : `<span class="muted">from the original — </span>${esc(source)}`}</div>`
        : "";
      return `<div class="line ${row.kind}"><span class="g">${oldNo}</span>` +
             `<span class="g r">${newNo}</span><span class="mark">${mark}</span>` +
             `<span class="t">${esc(row.text) || "&nbsp;"}</span>` +
             `<span class="act">${action}</span></div>${sourceRow}`;
    }).join("");
}

function renderDiff() {
  const version = current();
  if (!version || !version.review) {
    $("diffhead").innerHTML = `<span class="t">original resume</span>
      <span class="r">the input — nothing has been scored yet</span>`;
    $("diff").innerHTML = version
      ? version.text.split("\\n").map((text) => `<div class="line eq"><span class="g"></span>` +
          `<span class="g r"></span><span class="mark"></span>` +
          `<span class="t">${esc(text)}</span><span class="act"></span></div>`).join("")
      : "";
    return;
  }
  if (state.editing) { renderEditable(version); return; }
  const diff = version[state.vsOriginal ? "diff_vs_original" : "diff_vs_previous"];
  const from = state.vsOriginal ? "the original" : (previous() || {}).label || "the original";
  const unchanged = diff.added === 0 && diff.removed === 0;
  $("diffhead").innerHTML = `<span class="t">draft — ${esc(version.label)}</span>
    <span class="r">${unchanged
      ? `identical to ${esc(from)}`
      : `against ${esc(from)} · <span class="up">+${diff.added}</span> <span class="down">−${diff.removed}</span>`}${
      unchanged ? "" : ` · ${diff.unchanged} unchanged`}${
      version.review.improvement === null ? ""
        : ` · overall ${version.review.improvement > 0 ? "+" : ""}${version.review.improvement.toFixed(2)} against the best`}</span>`;
  $("diff").innerHTML = unchanged
    ? `<div class="line skip">identical to ${esc(from)}</div>`
    : diffRows(version);
}

// ── The grounding ledger, the coverage matrix, and the cost of the run ───────
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
        const claimBand = _band(claim.support);
        // The claim that dragged the line down is the reason the line is flagged, so it is
        // marked rather than left for the reader to find by comparing numbers.
        const fails = entry.failing_claim && claim.text === entry.failing_claim
          ? ` <span class="fails">fails</span>` : "";
        return `<div class="claim"><span class="p ${claimBand}">${claim.support.toFixed(2)}</span>` +
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
  const version = current();
  const entries = (version && version.review && version.review.ledger) || [];
  if (!entries.length) { el.innerHTML = ""; return; }
  const cfg = state.report.config || {};
  const floor = cfg.line_support_floor ?? 0.5;
  const review = cfg.line_review_floor ?? 0.8;
  const trust = version.review.trust || {};
  const withBand = entries.map((entry) => Object.assign({}, entry, { band: _band(entry.support) }));
  const attention = withBand.filter((entry) => entry.band !== "ok");
  // A run that grounded everything has nothing to put in the default band, and an empty
  // "needs attention" reads as a broken panel rather than as good news: fall back to all.
  const filter = (_ledgerFilter === "attention" && !attention.length) ? "all" : _ledgerFilter;
  const shown = filter === "all" ? withBand
    : filter === "attention" ? attention
    : withBand.filter((entry) => entry.band === filter);
  const filters = [
    ["attention", `needs attention (${attention.length})`],
    ["all", `all (${withBand.length})`],
    ["unc", `uncertain (${trust.uncertain || 0})`],
    ["bad", `unsupported (${trust.unsupported || 0})`],
  ];
  const body = `<div class="filters">${filters.map(([key, label]) =>
      `<button data-filter="${key}" class="${filter === key ? "on" : ""}">${esc(label)}</button>`
    ).join("")}</div>
    ${shown.length ? `<ul class="ledger">${shown.map(ledgerItem).join("")}</ul>`
                   : `<p class="lead">nothing in this band</p>`}`;
  el.innerHTML = foldWindow("ledger", "grounding ledger",
    `${trust.audited || 0} audited · ${trust.carried || 0} carried · uncertain band ${floor}–${review}`,
    body, "sage");
  bindWindows(el);
  el.querySelectorAll(".filters button").forEach((button) => {
    button.addEventListener("click", () => { _ledgerFilter = button.dataset.filter; renderLedger(); });
  });
}

function renderCoverage() {
  const el = $("coverage");
  const version = current();
  const coverage = (version && version.review && version.review.coverage) || [];
  if (!coverage.length) { el.innerHTML = ""; return; }
  const answered = coverage.filter((entry) => entry.draft_line).length;
  const job = state.report.job_description || "";
  const rows = coverage.map((entry) => `<div class="cov-row${entry.draft_line ? "" : " open-req"}">
      <span class="mark ${entry.draft_line ? "ok" : "no"}">${entry.draft_line ? "✓" : "○"}</span>
      <span class="req">${esc(entry.requirement)}</span>
      <span class="ans">${entry.draft_line
        ? "answered by · " + esc(entry.draft_line)
        : "no line in this draft answers it — leave it out rather than invent it"}</span>
    </div>`).join("");
  const body = `<div class="cov">${rows}</div>
    <details class="sub"><summary>
      <span>show the target job description</span>
      <span>${job ? job.split("\\n").length + " lines" : "not captured"}</span></summary>
      <pre class="jd" id="jd">${esc(job)}</pre></details>`;
  el.innerHTML = foldWindow("coverage", "requirement coverage",
    `${answered} of ${coverage.length} job requirements answered`, body, "sage");
  bindWindows(el);
}

function renderTotals() {
  const el = $("totals");
  const report = state.report;
  const cfg = report.config || {};
  const totals = report.totals || {};
  const total = totals.total_tokens || 0;
  const reviewer = totals.reviewer_tokens || 0;
  const share = total ? Math.round((reviewer / total) * 100) : 0;
  let budget = "";
  if (cfg.max_tokens) {
    const used = total / cfg.max_tokens;
    budget = `<div class="cost-row"><span>token budget</span>
      <span class="num">${total.toLocaleString()} of ${cfg.max_tokens.toLocaleString()} ·
        ${Math.round(used * 100)}%</span>${meter(used, used >= 0.9 ? "bad" : "")}</div>`;
  } else if (cfg.max_seconds) {
    const used = (totals.seconds || 0) / cfg.max_seconds;
    budget = `<div class="cost-row"><span>time budget</span>
      <span class="num">${totals.seconds || 0}s of ${cfg.max_seconds}s ·
        ${Math.round(used * 100)}%</span>${meter(used, used >= 0.9 ? "bad" : "")}</div>`;
  } else {
    budget = `<div class="cost-row"><span>no budget cap</span>
      <span class="num">the loop stops on the score alone</span></div>`;
  }
  const perRound = versions().filter((version) => version.review).map((version) => {
    const writer = (version.review.writer && version.review.writer.total_tokens) || 0;
    const reviewed = (version.review.reviewer && version.review.reviewer.total_tokens) || 0;
    const sum = writer + reviewed || 1;
    return `<div class="cost-row"><span>${esc(version.label)}</span>
      <span class="num">${writer.toLocaleString()} writer · ${reviewed.toLocaleString()} reviewer</span>
      ${meter(reviewed / sum, "")}</div>`;
  }).join("");
  const body = `<div class="kv">
      <span class="k">writer</span><span>${totals.writer_calls || 0} calls · ${(totals.writer_tokens || 0).toLocaleString()} tokens</span>
      <span class="k">reviewer</span><span>${totals.reviewer_calls || 0} calls · ${reviewer.toLocaleString()} tokens · ${share}% of the run</span>
      <span class="k">total</span><span>${total.toLocaleString()} tokens · ${totals.seconds || 0}s</span>
    </div>
    <div class="band-head"><span>cost per round</span>
      <span class="r">the meter is the reviewer's share</span></div>
    <div class="cost-rows">${budget}${perRound}</div>`;
  el.innerHTML = foldWindow("totals", "run cost",
    `${total.toLocaleString()} tokens · ${totals.seconds || 0}s`, body, "grey");
  bindWindows(el);
}

// ── Editing a draft, with JEV in the gutter ───────────────────────────────────

let _editTimer = null;

function editText() {
  return Array.from($("diff").querySelectorAll(".editable"))
    .map((el) => el.textContent).join("\\n");
}
function _carriedMap(text) {
  const version = current();
  if (!version || !version.review) return {};
  const now = new Set(text.split("\\n").map((line) => auditKey(line)));
  const carried = {};
  (version.review.ledger || []).forEach((entry) => {
    if (now.has(entry.text)) carried[entry.text] = entry.support;
  });
  return carried;
}
function toggleEdit() {
  const version = current();
  if (!version || !version.review) { setSaved("pick a reviewed round to edit"); return; }
  state.editing = !state.editing;
  state.editResults = null;
  state.editCheckedText = null;
  state.editUnsupported = [];
  setSaved(state.editing ? "edit the draft — only the lines you change are re-checked" : "");
  render();
}
function renderEditable(version) {
  $("diffhead").innerHTML = `<span class="t">editing — ${esc(version.label)}</span>
    <span class="r">only the lines you change are re-checked<span id="lints"></span></span>`;
  $("diff").innerHTML = version.text.split("\\n").map((text) =>
    `<div class="editrow"><span class="dot">·</span>` +
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
    lints.textContent = " · " + (unsupported.length
      ? `${unsupported.length} line(s) cannot be grounded`
      : "every line is grounded");
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
  $("edit").textContent = state.editing ? "done" : "edit";
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
  const rwBest = reweighted ? _reweightedBestIndex() : null;
  $("timeline").innerHTML = versions().map((version, i) => {
    const score = scoreOf(version);
    const isLoopBest = version.review && version.review.is_best;
    const isRwBest = reweighted && version.index === rwBest && version.review;
    let star = "";
    if (isRwBest || (isLoopBest && !reweighted)) star = '<span class="star">★</span>';
    else if (isLoopBest) star = '<span class="star muted" title="the loop best">◆</span>';
    const dot = version.saved
      ? '<span class="saved" title="written to the output file">●</span>' : "";
    return `<span class="chip ${i === state.index ? "sel" : ""}" data-i="${i}">
      ${esc(version.label)} <span class="n">${score === null ? "—" : score.toFixed(2)}</span>${star}${dot}</span>`;
  }).join("");
  $("timeline").querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => select(Number(chip.dataset.i)));
  });
}

function render() {
  const report = state.report;
  const cfg = report.config || {};
  // The page is opened as soon as the server is listening, which can be before the first
  // payload exists. That state is "starting", not "done" — and it has to keep polling, or
  // the browser would sit on an empty page for the whole run.
  const waiting = !report.status && !versions().length;
  const live = report.status === "running" || waiting;
  $("status").textContent = waiting ? "starting" : live ? "running" : "done";
  $("status").className = "badge" + (live && !waiting ? " live" : "");
  $("paths").textContent = report.paths ? `${report.paths.resume} → ${report.paths.out}` : "";
  $("stop").innerHTML = `<span class="state">${waiting ? "starting" : live
      ? "running" : "stopped"}</span><span class="detail">${waiting
      ? "waiting for the first round…"
      : live ? `round ${versions().length} running…` : esc(report.stop_reason || "")}</span>`;
  $("footer").innerHTML = `<span>writer ${esc(cfg.writer_model || "")} · reviewer
      ${esc(cfg.reviewer_model || "")} · stops when a round beats the best by less than
      ${cfg.min_improvement} for ${cfg.patience} rounds, or reaches ${cfg.target_score}</span>
    <span class="keys"><kbd>←</kbd><kbd>→</kbd> versions <kbd>h</kbd> unchanged
      <kbd>c</kbd> against the original <kbd>w</kbd> weights <kbd>e</kbd> edit</span>
    <span class="key">
      <span class="k-sage"><i></i> grounded, answered, carried</span>
      <span class="k-magenta"><i></i> scored, uncertain</span>
      <span class="k-pink"><i></i> unsupported, blocked, needs a person</span>
    </span>`;
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
  renderDiff();
  renderChecks();
  renderLedger();
  renderCoverage();
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
  const version = current();
  if (!version || !version.review) return;
  setSaved("saving…");
  try {
    const res = await fetch("/api/save", {
      method: "POST",
      headers: { "content-type": "application/json", "X-Csrf-Token": CSRF_TOKEN },
      body: JSON.stringify({ index: version.index }),
    });
    const data = await res.json();
    setSaved(res.ok ? `saved ${version.label} → ${data.saved}` : `error: ${data.error}`);
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
$("diff").addEventListener("click", (event) => {
  const button = event.target.closest("button.src-btn");
  if (!button) return;
  const line = button.closest(".line");
  const source = line && line.nextElementSibling;
  if (!source || !source.classList.contains("src-row")) return;
  const open = source.classList.toggle("open");
  const label = button.dataset.missing ? "no source" : "source";
  button.textContent = `${label} ${open ? "▾" : "▸"}`;
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
function _recomputeOverall(version, weights) {
  if (!version || !version.review) return null;
  const total = Object.values(weights).reduce((a, b) => a + b, 0) || 1;
  let quality = 0;
  for (const [name, weight] of Object.entries(weights)) {
    const score = version.review.scores && version.review.scores[name];
    if (score) quality += (weight / total) * score.normalized;
  }
  return quality * version.review.groundedness;
}
function _reweightedBestIndex() {
  const weights = _activeWeights();
  let best = -1, bestScore = -1;
  for (const version of versions()) {
    const score = _recomputeOverall(version, weights);
    if (score !== null && score > bestScore) { bestScore = score; best = version.index; }
  }
  return best;
}
function _updateWeightPanel() {
  const weights = _activeWeights();
  const total = Object.values(weights).reduce((a, b) => a + b, 0);
  const sum = $("wsum");
  if (sum) sum.textContent = `sum ${Math.round(total * 100)}%`;
  const note = $("wreweight-note");
  if (note) note.textContent = _isReweighted() ? "re-weighted view — the scores are unchanged" : "";
}
function _initWeightSliders() {
  const weights = _defaultWeights();
  if (!Object.keys(weights).length) return;
  $("wsliders").innerHTML = Object.entries(weights).map(([dimension, weight]) => {
    const current_ = (_customWeights && _customWeights[dimension] !== undefined)
      ? _customWeights[dimension] : weight;
    return `<div class="wslider-row">
      <span style="min-width:126px;overflow:hidden;text-overflow:ellipsis" title="${esc(dimension)}">${esc(words(dimension))}</span>
      <input type="range" min="0" max="50" step="1" value="${Math.round(current_ * 100)}" data-dim="${esc(dimension)}">
      <span data-wpct="${esc(dimension)}" style="min-width:34px;text-align:right">${Math.round(current_ * 100)}%</span>
    </div>`;
  }).join("");
  _updateWeightPanel();
}
$("rubric-btn").addEventListener("click", () => {
  const panel = $("rubric-panel");
  const open = panel.style.display === "none";
  panel.style.display = open ? "block" : "none";
  $("rubric-btn").textContent = open ? "weights ▾" : "weights";
  if (open) _initWeightSliders();
});
$("wsliders").addEventListener("input", (event) => {
  const slider = event.target.closest("input[type=range]");
  if (!slider || !slider.dataset.dim) return;
  const dimension = slider.dataset.dim;
  if (!_customWeights) _customWeights = Object.assign({}, _defaultWeights());
  _customWeights[dimension] = Number(slider.value) / 100;
  const pct = $("wsliders").querySelector(`[data-wpct="${CSS.escape(dimension)}"]`);
  if (pct) pct.textContent = `${slider.value}%`;
  _updateWeightPanel();
  renderTimeline();
  renderScores();
});
$("wreset").addEventListener("click", () => {
  _customWeights = null;
  _initWeightSliders();
  renderTimeline();
  renderScores();
});
$("wexport").addEventListener("click", () => {
  const weights = _activeWeights();
  const total = Object.values(weights).reduce((a, b) => a + b, 0) || 1;
  const normalized = Object.fromEntries(
    Object.entries(weights).map(([k, v]) => [k, Math.round(v / total * 1000) / 1000])
  );
  if (navigator.clipboard) {
    navigator.clipboard.writeText(JSON.stringify(normalized, null, 2))
      .then(() => setSaved("weights copied to clipboard"))
      .catch(() => setSaved("copy failed — see console"));
  }
});

document.addEventListener("keydown", (event) => {
  const target = event.target;
  // Never steal a keystroke from an input or from the editable draft.
  if (target.tagName === "INPUT" || target.isContentEditable) return;
  if (event.key === "ArrowLeft") { event.preventDefault(); step(-1); }
  if (event.key === "ArrowRight") { event.preventDefault(); step(1); }
  if (event.key === "h") { $("hide").checked = !$("hide").checked; state.hideUnchanged = $("hide").checked; renderDiff(); }
  if (event.key === "c") { $("vsorig").checked = !$("vsorig").checked; state.vsOriginal = $("vsorig").checked; renderDiff(); }
  if (event.key === "w") { $("rubric-btn").click(); }
  if (event.key === "e") { toggleEdit(); }
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
