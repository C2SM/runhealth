"""Render the assessment as HTML, Markdown or PDF.

No template engine: the pages are small enough that string fragments are
easier to read and to change than a template language, and it keeps the
dependency list to PyYAML alone.

A page is a sticky header, a table of contents that tracks the reading
position, and one column of content. The figures are SVG written by
:mod:`runhealth.plots` and are complete before any script runs, so the same
page serves a browser, the print stylesheet and WeasyPrint. The script adds
tooltips, legend toggling, brushing to zoom, and a shared marker across the
charts that share a wall-clock axis.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import style
from .extract import RunLog
from .health import Assessment, Check, counter_rows
from .logfile import format_duration, format_stamp
from .plots import Figure

GRADE_MARK = {"ok": "OK", "info": "i", "warn": "!", "fail": "X"}
GRADE_TEXT = {"ok": "healthy", "info": "worth a look", "warn": "warning", "fail": "problem"}
STATUS_LEVEL = {
    "SUCCESS": "ok",
    "FAILED": "fail",
    "STALLED": "fail",
    "RUNNING": "info",
    "QUEUED": "info",
    "INCOMPLETE": "warn",
    "UNKNOWN": "info",
}
# Lines per block in an embedded log. Each block is skipped by the browser
# until it is scrolled near, which is what keeps a large log openable.
LOG_BLOCK = 200


@dataclass
class RunView:
    """One run, ready to render."""

    log: RunLog
    assessment: Assessment
    figures: list[Figure] = field(default_factory=list)
    page: str = ""
    log_href: str = ""


def esc(text: object) -> str:
    return html.escape(str(text if text is not None else ""))


def _rate(stats: dict) -> str:
    value = stats.get("sypd")
    return f"{value:.2f}" if value else ""


def _num(value, suffix: str = "") -> str:
    if value is None:
        return "&ndash;"
    if isinstance(value, float):
        return f"{value:,.2f}{suffix}"
    return f"{value:,}{suffix}" if isinstance(value, int) else f"{value}{suffix}"


# -- icons ----------------------------------------------------------------

# Line icons in the Lucide idiom, inlined because a report has to work with
# no network. Each is decorative; the button around it carries the label.
_ICON = (
    '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
    'aria-hidden="true" focusable="false">{}</svg>'
)
ICONS = {
    "system": _ICON.format(
        '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>'
    ),
    "light": _ICON.format(
        '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4'
        'M17.7 17.7l1.4 1.4M2 12h2M20 12h2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"/>'
    ),
    "dark": _ICON.format('<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>'),
}
THEME_LABEL = {
    "system": "Follow the system theme",
    "light": "Light theme",
    "dark": "Dark theme",
}


def theme_switch() -> str:
    buttons = "".join(
        f'<button type="button" data-theme-set="{mode}" aria-pressed="false" '
        f'title="{esc(THEME_LABEL[mode])}" aria-label="{esc(THEME_LABEL[mode])}">'
        f"{ICONS[mode]}</button>"
        for mode in ("system", "light", "dark")
    )
    return f'<div class="theme" role="group" aria-label="Colour theme">{buttons}</div>'


# -- table of contents ----------------------------------------------------


class Toc:
    """Anchors collected while a page is built, in reading order."""

    def __init__(self) -> None:
        self.items: list[tuple[str, str, int]] = []

    def add(self, anchor: str, label: str, level: int = 1) -> str:
        self.items.append((anchor, label, level))
        return anchor

    def render(self) -> str:
        if len(self.items) < 2:
            return ""
        links = "".join(
            f'<a href="#{esc(anchor)}" class="lv{level}">{esc(label)}</a>'
            for anchor, label, level in self.items
        )
        return (
            '<aside class="toc" aria-label="On this page">'
            '<p class="toc-h">On this page</p>'
            f'<nav id="toc">{links}</nav></aside>'
        )


CSS = """
:root { --nav-h: 52px; }
/*LIGHT*/
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { /*DARK*/ } }
:root[data-theme="dark"] { /*DARK*/ }

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  -webkit-font-smoothing: antialiased;
}
code, .mono, td.n, .kv dd { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
a { color: inherit; text-decoration: none; border-bottom: 1px solid var(--line-2); }
a:hover { border-bottom-color: currentColor; }
:focus-visible { outline: 2px solid var(--info); outline-offset: 2px; border-radius: 3px; }
.skip { position: absolute; left: -9999px; top: 0; background: var(--panel); z-index: 60;
  padding: 9px 14px; border: 1px solid var(--line-2); border-radius: 0 0 8px 0; }
.skip:focus { left: 0; }

/* -- sticky header -- */
.nav { position: sticky; top: 0; z-index: 40; background: var(--bg);
  background: color-mix(in srgb, var(--bg) 88%, transparent);
  backdrop-filter: saturate(180%) blur(10px); border-bottom: 1px solid var(--line); }
@supports not (backdrop-filter: blur(1px)) { .nav { background: var(--bg); } }
.nav-in { max-width: 1420px; margin: 0 auto; height: var(--nav-h); padding: 0 20px;
  display: flex; align-items: center; gap: 10px; }
.nav .brand { font-weight: 650; font-size: 13.5px; letter-spacing: -.01em; border: none;
  flex: 0 0 auto; }
.nav .sep { color: var(--line-2); }
.nav .here { font-size: 13.5px; font-weight: 550; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; min-width: 0; }
.nav .spacer { flex: 1 1 auto; }
.nav .up { font-size: 12.5px; color: var(--muted); border: none; flex: 0 0 auto; }
.nav .up:hover { color: var(--ink); }

.theme { display: inline-flex; gap: 1px; padding: 2px; flex: 0 0 auto;
  background: var(--panel-2); border: 1px solid var(--line); border-radius: 999px; }
.theme button { display: grid; place-items: center; width: 30px; height: 26px; padding: 0;
  background: none; border: none; border-radius: 999px; color: var(--muted); cursor: pointer; }
.theme button:hover { color: var(--ink); }
.theme button[aria-pressed="true"] { background: var(--panel); color: var(--ink);
  box-shadow: var(--shadow); }
.ico { width: 15px; height: 15px; }

/* -- shell and table of contents -- */
.shell { max-width: 1420px; margin: 0 auto; padding: 0 20px 90px;
  display: grid; grid-template-columns: 216px minmax(0, 1fr); gap: 34px; align-items: start; }
.toc { position: sticky; top: calc(var(--nav-h) + 20px); padding-top: 30px; }
.toc-h { margin: 0 0 9px; font-size: 11px; text-transform: uppercase; letter-spacing: .09em;
  color: var(--muted); font-weight: 650; }
.toc nav { display: flex; flex-direction: column; gap: 1px;
  border-left: 1px solid var(--line); }
.toc a { border: none; font-size: 13px; color: var(--muted); padding: 4px 0 4px 13px;
  margin-left: -1px; border-left: 2px solid transparent; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.toc a.lv2 { padding-left: 25px; font-size: 12.5px; }
.toc a:hover { color: var(--ink); }
.toc a[aria-current="true"] { color: var(--ink); font-weight: 600;
  border-left-color: var(--info); }
main { min-width: 0; padding-top: 30px; }
main > *:first-child { margin-top: 0; }

@media (max-width: 1040px) {
  .shell { grid-template-columns: minmax(0, 1fr); gap: 0; padding: 0 16px 80px; }
  .toc { position: sticky; top: var(--nav-h); z-index: 30; padding: 8px 0 9px;
    background: var(--bg); border-bottom: 1px solid var(--line); }
  .toc-h { display: none; }
  .toc nav { flex-direction: row; gap: 6px; overflow-x: auto; border-left: none;
    scrollbar-width: thin; -webkit-overflow-scrolling: touch; }
  .toc a { border: 1px solid var(--line); border-radius: 999px; padding: 4px 11px;
    margin: 0; flex: 0 0 auto; }
  .toc a.lv2 { display: none; }
  .toc a[aria-current="true"] { border-color: var(--info); }
  main { padding-top: 22px; }
}

/* -- page head -- */
.head { border-bottom: 1px solid var(--line); padding-bottom: 18px; margin-bottom: 24px; }
.head h1 { font-size: 25px; margin: 0 0 5px; letter-spacing: -.018em; overflow-wrap: anywhere; }
.head .sub { color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
.crumb { font-size: 12px; color: var(--muted); text-transform: uppercase;
  letter-spacing: .09em; margin-bottom: 7px; }

.badge { display: inline-flex; align-items: center; gap: 6px; border-radius: 999px;
  padding: 2px 11px 2px 6px; font-size: 12px; font-weight: 600; white-space: nowrap;
  border: 1px solid currentColor; }
.badge .mark { display: inline-grid; place-items: center; width: 17px; height: 17px;
  border-radius: 999px; background: currentColor; color: var(--panel);
  font-size: 10px; font-weight: 700; }
.g-ok { color: var(--ok); } .g-info { color: var(--info); }
.g-warn { color: var(--warn); } .g-fail { color: var(--fail); }

.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  gap: 10px; margin: 0 0 26px; }
.tile { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 12px 14px; box-shadow: var(--shadow); }
.tile .v { font-size: 20px; font-weight: 650; letter-spacing: -.02em; line-height: 1.2; }
.tile .l { font-size: 11.5px; color: var(--muted); margin-top: 3px;
  text-transform: uppercase; letter-spacing: .06em; }

h2.sec { font-size: 13px; text-transform: uppercase; letter-spacing: .1em;
  color: var(--muted); font-weight: 650; margin: 34px 0 12px;
  border-top: 1px solid var(--line); padding-top: 16px;
  scroll-margin-top: calc(var(--nav-h) + 16px); }

.check { background: var(--panel); border: 1px solid var(--line); border-left: 3px solid;
  border-radius: 9px; padding: 13px 16px; margin-bottom: 9px; box-shadow: var(--shadow); }
.check.l-ok { border-left-color: var(--ok); } .check.l-info { border-left-color: var(--info); }
.check.l-warn { border-left-color: var(--warn); } .check.l-fail { border-left-color: var(--fail); }
.check .hd { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.check .t { font-size: 12px; text-transform: uppercase; letter-spacing: .07em;
  color: var(--muted); font-weight: 650; min-width: 132px; }
.check .h { font-weight: 600; }
.check .d { color: var(--muted); font-size: 13.5px; margin-top: 5px; }
.check ul { margin: 8px 0 0; padding-left: 0; list-style: none; }
.check li { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px; color: var(--muted); padding: 2px 0 2px 13px; position: relative;
  overflow-wrap: anywhere; }
.check li::before { content: "\\2014"; position: absolute; left: 0; opacity: .5; }

/* -- figures -- */
figure.fig { margin: 0 0 22px; background: var(--panel); border: 1px solid var(--line);
  border-radius: 10px; padding: 16px; box-shadow: var(--shadow);
  scroll-margin-top: calc(var(--nav-h) + 16px); }
figure.fig .fh { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
figure.fig h3 { margin: 0; font-size: 15px; }
figure.fig .note { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
figure.fig .zoomed { margin-left: auto; font-size: 12px; color: var(--muted);
  background: none; border: 1px solid var(--line-2); border-radius: 999px;
  padding: 2px 10px; cursor: pointer; }
figure.fig .cap { color: var(--muted); font-size: 13px; margin: 4px 0 12px; max-width: 78ch; }
.chart { position: relative; }
.chart .tip { position: absolute; z-index: 20; pointer-events: none; max-width: 340px;
  background: var(--panel); color: var(--ink); border: 1px solid var(--line-2);
  border-radius: 8px; padding: 7px 10px; box-shadow: 0 4px 18px rgba(0,0,0,.16);
  font-size: 12px; line-height: 1.45; }
.chart .tip b { display: block; font-size: 12.5px; margin-bottom: 2px; }
.chart .tip span { display: block; color: var(--muted); overflow-wrap: anywhere; }

table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
th { text-align: left; font-size: 11.5px; text-transform: uppercase; letter-spacing: .06em;
  color: var(--muted); font-weight: 650; padding: 7px 10px; border-bottom: 1px solid var(--line-2);
  white-space: nowrap; }
td { padding: 7px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
td.n { text-align: right; white-space: nowrap; font-size: 12.5px;
  font-variant-numeric: tabular-nums; }
tbody tr:hover { background: var(--panel-2); }
.scroll { overflow-x: auto; background: var(--panel); border: 1px solid var(--line);
  border-radius: 10px; box-shadow: var(--shadow); }
th.sortable { cursor: pointer; } th.sortable:hover { color: var(--ink); }
th.sortable[data-dir="asc"]::after { content: " \\2191"; }
th.sortable[data-dir="desc"]::after { content: " \\2193"; }

details { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 0 16px; margin-bottom: 9px; box-shadow: var(--shadow); }
details > summary { cursor: pointer; padding: 12px 0; font-weight: 600; font-size: 14px;
  list-style: none; display: flex; justify-content: space-between; gap: 12px; }
details > summary::-webkit-details-marker { display: none; }
details > summary::after { content: "+"; color: var(--muted); font-weight: 400; }
details[open] > summary::after { content: "\\2212"; }
details > summary + * { margin-top: 0; }
details .body { padding-bottom: 16px; }
.depth-1 { padding-left: 16px; } .depth-2 { padding-left: 32px; }
.depth-3 { padding-left: 48px; } .depth-4 { padding-left: 64px; }

dl.kv { display: grid; grid-template-columns: minmax(120px, max-content) 1fr;
  gap: 3px 18px; margin: 0; font-size: 13px; }
dl.kv dt { color: var(--muted); } dl.kv dd { margin: 0; overflow-wrap: anywhere; }

.filters { display: flex; gap: 7px; flex-wrap: wrap; margin-bottom: 14px; }
.filters button { background: var(--panel); border: 1px solid var(--line-2); color: var(--muted);
  border-radius: 999px; padding: 4px 13px; font-size: 12px; cursor: pointer; }
.filters button[aria-pressed="true"] { background: var(--ink); color: var(--bg);
  border-color: var(--ink); }
footer { color: var(--muted); font-size: 12px; margin-top: 46px;
  border-top: 1px solid var(--line); padding-top: 14px; }

/* -- embedded log -- */
.logview { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  overflow-x: auto; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px; line-height: 1.55; }
.logview .blk { content-visibility: auto; contain-intrinsic-size: auto 340px; }
.logview b { display: block; padding: 0 14px 0 66px; text-indent: -52px;
  font-weight: 400; white-space: pre-wrap; overflow-wrap: anywhere;
  scroll-margin-top: calc(var(--nav-h) + 90px); }
.logview b::before { content: attr(data-n); display: inline-block; width: 44px;
  margin-right: 8px; text-align: right; color: var(--muted); user-select: none; }
.logview b:target { background: var(--panel-2);
  background: color-mix(in srgb, var(--warn) 24%, transparent); }
.logview b:hover { background: var(--panel-2); }

/*CHART*/
/*INTERACTION*/

@media print {
  :root { --bg: #fff; --panel: #fff; --panel-2: #fff; --ink: #000; --muted: #444;
    --line: #ccc; --line-2: #999; --shadow: none; }
  body { font-size: 10.5pt; }
  .nav, .toc, .filters, .skip, figure.fig .zoomed, .chart .tip { display: none !important; }
  .shell { display: block; max-width: none; padding: 0; }
  main { padding-top: 0; }
  /* auto-fit grids are not universal in print engines; flex is. */
  .tiles { display: flex; flex-wrap: wrap; gap: 8px; }
  .tile { flex: 1 1 132px; }
  .badge { display: inline-block; }
  .check, figure.fig, details, .scroll { break-inside: avoid; page-break-inside: avoid;
    box-shadow: none; }
  h2.sec { break-before: page; page-break-before: always; }
  h2.sec:first-of-type { break-before: auto; page-break-before: auto; }
  details { border: none; padding: 0; } details > summary::after { content: ""; }
  details .body { display: block !important; }
  a { border-bottom: none; }
  .rh-svg .mark { opacity: 1 !important; }
/*PRINT*/
}
"""


def stylesheet() -> str:
    dark = " ".join(f"--{k}: {v};" for k, v in style.tokens(dark=True).items())
    out = CSS
    for marker, text in (
        ("/*LIGHT*/", style.token_block(":root")),
        ("/*DARK*/", dark),
        ("/*CHART*/", style.CHART_CSS),
        ("/*INTERACTION*/", style.CHART_INTERACTION_CSS),
        ("/*PRINT*/", style.print_overrides()),
    ):
        out = out.replace(marker, text)
    return out


# The theme has to be settled before the first paint, or a dark-mode reader
# gets a white flash on every page. This is the only script in the head.
HEAD_JS = """
try {
  var m = localStorage.getItem('runhealth-theme');
  if (m === 'light' || m === 'dark') document.documentElement.setAttribute('data-theme', m);
} catch (e) {}
"""

JS = r"""
(function () {
  'use strict';
  var root = document.documentElement;
  var SVGNS = 'http://www.w3.org/2000/svg';
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // -- theme: system, light or dark ------------------------------------
  var stored = 'system';
  try { stored = localStorage.getItem('runhealth-theme') || 'system'; } catch (e) {}
  function setTheme(mode) {
    if (mode === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', mode);
    try {
      if (mode === 'system') localStorage.removeItem('runhealth-theme');
      else localStorage.setItem('runhealth-theme', mode);
    } catch (e) {}
    document.querySelectorAll('[data-theme-set]').forEach(function (b) {
      b.setAttribute('aria-pressed', b.dataset.themeSet === mode ? 'true' : 'false');
    });
  }
  setTheme(stored === 'light' || stored === 'dark' ? stored : 'system');
  document.querySelectorAll('[data-theme-set]').forEach(function (b) {
    b.addEventListener('click', function () { setTheme(b.dataset.themeSet); });
  });

  // -- table of contents: mark the section being read ------------------
  var links = Array.prototype.slice.call(document.querySelectorAll('#toc a'));
  if (links.length && 'IntersectionObserver' in window) {
    var targets = links.map(function (l) {
      return document.getElementById(decodeURIComponent(l.hash.slice(1)));
    });
    var seen = {};
    var mark = function () {
      var best = -1;
      for (var i = 0; i < targets.length; i++) if (seen[i]) best = i;
      links.forEach(function (l, i) {
        if (i === best) l.setAttribute('aria-current', 'true');
        else l.removeAttribute('aria-current');
      });
      var active = links[best];
      if (active && active.parentNode.scrollWidth > active.parentNode.clientWidth) {
        var box = active.parentNode;
        var want = active.offsetLeft - box.clientWidth / 2 + active.offsetWidth / 2;
        box.scrollTo({ left: want, behavior: reduce ? 'auto' : 'smooth' });
      }
    };
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        var i = targets.indexOf(e.target);
        if (i >= 0) seen[i] = e.isIntersecting || e.boundingClientRect.top < 0;
      });
      mark();
    }, { rootMargin: '-' + (60 + 40) + 'px 0px -55% 0px', threshold: 0 });
    targets.forEach(function (t) { if (t) io.observe(t); });
  }

  // -- index table: filter by grade, sort by column --------------------
  document.querySelectorAll('.filters button').forEach(function (b) {
    b.addEventListener('click', function () {
      var want = b.dataset.grade;
      b.parentNode.querySelectorAll('button').forEach(function (o) {
        o.setAttribute('aria-pressed', o === b ? 'true' : 'false');
      });
      document.querySelectorAll('tbody tr[data-grade]').forEach(function (tr) {
        tr.hidden = want !== 'all' && tr.dataset.grade !== want;
      });
    });
  });
  document.querySelectorAll('th.sortable').forEach(function (th) {
    th.addEventListener('click', function () {
      var table = th.closest('table');
      var tb = table.tBodies[0];
      var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
      var dir = th.dataset.dir === 'asc' ? -1 : 1;
      table.querySelectorAll('th.sortable').forEach(function (o) {
        if (o !== th) o.removeAttribute('data-dir');
      });
      th.dataset.dir = dir === 1 ? 'asc' : 'desc';
      var rows = Array.prototype.slice.call(tb.rows);
      rows.sort(function (a, b) {
        var x = a.cells[idx].dataset.v, y = b.cells[idx].dataset.v;
        var nx = parseFloat(x), ny = parseFloat(y);
        if (!isNaN(nx) && !isNaN(ny)) return (nx - ny) * dir;
        return String(x).localeCompare(String(y)) * dir;
      });
      rows.forEach(function (r) { tb.appendChild(r); });
    });
  });

  // -- figures ---------------------------------------------------------
  var STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200,
               10800, 21600, 43200, 86400];

  function niceTicks(lo, hi, target) {
    if (!(hi > lo)) return [lo];
    var raw = (hi - lo) / target;
    var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var step = [1, 2, 2.5, 5, 10].map(function (m) { return m * mag; })
      .filter(function (s) { return s >= raw; })[0] || 10 * mag;
    var out = [], v = Math.ceil(lo / step) * step;
    for (; v <= hi + step * 1e-6; v += step) out.push(v);
    return out.length ? out : [lo, hi];
  }
  function timeTicks(lo, hi) {
    var want = (hi - lo) / 7;
    var step = STEPS.filter(function (s) { return s >= want; })[0] || STEPS[STEPS.length - 1];
    var out = [], v = Math.ceil(lo / step) * step;
    for (; v <= hi; v += step) out.push(v);
    return out.length ? out : [lo, hi];
  }
  function fmtDuration(span) {
    var size = span >= 7200 ? 3600 : span >= 120 ? 60 : 1;
    var dec = span >= 7200 ? 1 : 0;
    return function (v) { return (v / size).toFixed(dec); };
  }
  function fmtSi(v) {
    var a = Math.abs(v);
    if (a >= 1e9) return (v / 1e9).toFixed(1).replace(/\.0$/, '') + 'G';
    if (a >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
    if (a >= 1e3) return (v / 1e3).toFixed(1).replace(/\.0$/, '') + 'k';
    if (a && a < 1) return String(Number(v.toPrecision(2)));
    return Math.round(v).toLocaleString();
  }

  var clocks = [];   // charts that can mark an instant for their peers

  document.querySelectorAll('.chart').forEach(function (host) {
    var svg = host.querySelector('svg.rh-svg');
    if (!svg) return;
    var tip = host.querySelector('.tip');
    var plot = (svg.dataset.plot || '').split(',').map(Number);
    var timeBox = (svg.dataset.xbox || svg.dataset.plot || '').split(',').map(Number);
    var samples = svg.dataset.samples ? JSON.parse(svg.dataset.samples) : null;
    var dragging = false;
    var domain = svg.dataset.xdomain ? svg.dataset.xdomain.split(',').map(Number) : null;
    var overlay = document.createElementNS(SVGNS, 'g');
    overlay.setAttribute('class', 'rh-overlay');
    svg.appendChild(overlay);

    function el(name, attrs) {
      var n = document.createElementNS(SVGNS, name);
      for (var k in attrs) n.setAttribute(k, attrs[k]);
      return n;
    }
    function userX(clientX) {
      var r = svg.getBoundingClientRect();
      var vb = svg.viewBox.baseVal;
      return vb.x + (clientX - r.left) / r.width * vb.width;
    }
    function pageXY(ux, uy) {
      var r = svg.getBoundingClientRect();
      var vb = svg.viewBox.baseVal;
      var hostRect = host.getBoundingClientRect();
      return [
        r.left - hostRect.left + (ux - vb.x) / vb.width * r.width,
        r.top - hostRect.top + (uy - vb.y) / vb.height * r.height
      ];
    }

    // -- tooltip --
    function showTip(text, left, top) {
      if (!tip) return;
      while (tip.firstChild) tip.removeChild(tip.firstChild);
      var lines = String(text).split('\n');
      var head = document.createElement('b');
      head.textContent = lines[0];
      tip.appendChild(head);
      lines.slice(1).forEach(function (line) {
        var s = document.createElement('span');
        s.textContent = line;
        tip.appendChild(s);
      });
      tip.hidden = false;
      var w = tip.offsetWidth, h = tip.offsetHeight;
      var maxX = host.clientWidth - w - 4;
      tip.style.left = Math.max(4, Math.min(left + 12, maxX)) + 'px';
      tip.style.top = (top - h - 12 < 0 ? top + 18 : top - h - 12) + 'px';
    }
    function hideTip() { if (tip) tip.hidden = true; }

    host.addEventListener('pointerover', function (e) {
      var m = e.target.closest && e.target.closest('[data-tip]');
      if (m) showTip(m.dataset.tip, e.clientX - host.getBoundingClientRect().left,
                     e.clientY - host.getBoundingClientRect().top);
    });
    host.addEventListener('pointermove', function (e) {
      var m = e.target.closest && e.target.closest('[data-tip]');
      if (m) showTip(m.dataset.tip, e.clientX - host.getBoundingClientRect().left,
                     e.clientY - host.getBoundingClientRect().top);
    });
    host.addEventListener('pointerleave', function () { hideTip(); clearCross(); tell(null); });
    host.addEventListener('focusin', function (e) {
      var m = e.target.closest && e.target.closest('[data-tip]');
      if (!m || !m.getBoundingClientRect) return;
      var b = m.getBoundingClientRect(), h = host.getBoundingClientRect();
      showTip(m.dataset.tip, b.left - h.left + b.width / 2, b.top - h.top);
    });
    host.addEventListener('focusout', hideTip);

    // Clicking a mark that names a log line, or a run, follows it.
    host.addEventListener('click', function (e) {
      var m = e.target.closest && e.target.closest('[data-line],[data-href]');
      if (!m) return;
      if (m.dataset.href) { window.location.href = m.dataset.href; return; }
      var target = host.dataset.logHref;
      if (target) window.location.href = target + '#L' + m.dataset.line;
    });
    host.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      var m = e.target.closest && e.target.closest('[data-line],[data-href]');
      if (m) { e.preventDefault(); m.dispatchEvent(new MouseEvent('click', { bubbles: true })); }
    });

    // -- legend toggles a series --
    svg.querySelectorAll('.legend-item').forEach(function (item) {
      function toggle() {
        var on = item.getAttribute('aria-pressed') !== 'false';
        item.setAttribute('aria-pressed', on ? 'false' : 'true');
        var series = svg.querySelector('.series[data-series="' + item.dataset.series + '"]');
        if (series) series.hidden = on;
      }
      item.addEventListener('click', toggle);
      item.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
      });
    });

    // -- crosshair over a sampled series --
    var cross = null;
    function clearCross() { if (cross) { overlay.removeChild(cross); cross = null; } }
    function nearest(ux) {
      var best = null, gap = Infinity;
      for (var i = 0; i < samples.length; i++) {
        var d = Math.abs(samples[i][0] - ux);
        if (d < gap) { gap = d; best = samples[i]; }
      }
      return best;
    }
    if (samples && samples.length) {
      svg.addEventListener('pointermove', function (e) {
        if (dragging) return;
        var ux = userX(e.clientX);
        if (ux < timeBox[0] - 2 || ux > timeBox[0] + timeBox[2] + 2) { clearCross(); return; }
        var s = nearest(ux);
        if (!s) return;
        clearCross();
        cross = el('g', {});
        cross.appendChild(el('line', {
          'class': 'cross', x1: s[0], y1: timeBox[1], x2: s[0], y2: timeBox[1] + timeBox[3]
        }));
        cross.appendChild(el('circle', { 'class': 'cross-dot', cx: s[0], cy: s[1], r: 3 }));
        overlay.appendChild(cross);
        var at = pageXY(s[0], s[1]);
        showTip(s[3], at[0], at[1]);
        tell(s[2]);
      });
    }

    // -- share the hovered instant with the other time charts --
    function tell(t) {
      clocks.forEach(function (c) { if (c.svg !== svg) c.peer(t); });
    }
    function xForTime(t) {
      if (domain && svg.dataset.xfmt === 'duration') {
        var span = domain[1] - domain[0];
        if (!span) return null;
        return timeBox[0] + (t - domain[0]) / span * timeBox[2];
      }
      if (samples && samples.length) {
        var best = null, gap = Infinity;
        for (var i = 0; i < samples.length; i++) {
          var d = Math.abs(samples[i][2] - t);
          if (d < gap) { gap = d; best = samples[i]; }
        }
        return best ? best[0] : null;
      }
      return null;
    }
    if (svg.dataset.time) {
      var peerLine = null;
      clocks.push({
        svg: svg,
        peer: function (t) {
          if (peerLine) { overlay.removeChild(peerLine); peerLine = null; }
          if (t === null || t === undefined) return;
          var x = xForTime(t);
          if (x === null || x < timeBox[0] - 1 || x > timeBox[0] + timeBox[2] + 1) return;
          peerLine = el('line', {
            'class': 'peer', x1: x, y1: timeBox[1], x2: x, y2: timeBox[1] + timeBox[3]
          });
          overlay.appendChild(peerLine);
        }
      });
      if (!samples) {
        svg.addEventListener('pointermove', function (e) {
          if (dragging || !domain) return;
          var ux = userX(e.clientX);
          if (ux < timeBox[0] || ux > timeBox[0] + timeBox[2]) { tell(null); return; }
          var span = domain[1] - domain[0];
          tell(domain[0] + (ux - timeBox[0]) / timeBox[2] * span);
        });
      }
    }

    // -- brush to zoom the x axis --
    if (svg.dataset.zoom && domain) {
      var geometry = svg.querySelector('.rh-geometry');
      // Text and markers keep their own size, so they are moved rather than
      // transformed with the geometry.
      var floating = Array.prototype.slice.call(
        svg.querySelectorAll('.rh-labels [x], .rh-points [cx]'));
      var xticks = svg.querySelector('.rh-xticks');
      var button = host.parentNode.querySelector('.zoomed');
      var view = domain.slice();
      var start = null, band = null;

      floating.forEach(function (n) {
        n.dataset.x0 = n.getAttribute(n.hasAttribute('cx') ? 'cx' : 'x');
      });

      function toData(ux) {
        return domain[0] + (ux - plot[0]) / plot[2] * (domain[1] - domain[0]);
      }
      function toPixel(value) {
        return plot[0] + (value - view[0]) / (view[1] - view[0]) * plot[2];
      }
      function apply() {
        // Map the visible window onto the plot area: x' = k * x + shift.
        var k = (domain[1] - domain[0]) / (view[1] - view[0]);
        var left = plot[0] + (view[0] - domain[0]) / (domain[1] - domain[0]) * plot[2];
        var shift = plot[0] - k * left;
        if (geometry) {
          geometry.setAttribute('transform', 'matrix(' + k + ',0,0,1,' + shift + ',0)');
        }
        floating.forEach(function (n) {
          var key = n.hasAttribute('cx') ? 'cx' : 'x';
          var moved = k * Number(n.dataset.x0) + shift;
          n.setAttribute(key, moved);
          n.style.display = (moved < plot[0] - 1 || moved > plot[0] + plot[2] + 1) ? 'none' : '';
        });
        redrawAxis();
        if (button) button.hidden = (view[0] === domain[0] && view[1] === domain[1]);
      }
      function redrawAxis() {
        if (!xticks) return;
        while (xticks.firstChild) xticks.removeChild(xticks.firstChild);
        var duration = svg.dataset.xfmt === 'duration';
        var ticks = duration ? timeTicks(view[0], view[1]) : niceTicks(view[0], view[1], 7);
        var fmt = duration ? fmtDuration(view[1] - view[0]) : fmtSi;
        var base = plot[1] + plot[3];
        ticks.forEach(function (t) {
          var x = toPixel(t);
          if (x < plot[0] - 0.5 || x > plot[0] + plot[2] + 0.5) return;
          xticks.appendChild(el('line', {
            'class': 'grid', x1: x, y1: plot[1], x2: x, y2: base
          }));
          xticks.appendChild(el('line', {
            'class': 'ax-line', x1: x, y1: base, x2: x, y2: base + 4
          }));
          var label = el('text', {
            'class': 'tick', x: x, y: base + 15, 'text-anchor': 'middle'
          });
          label.textContent = fmt(t);
          xticks.appendChild(label);
        });
      }
      function reset() { view = domain.slice(); apply(); }
      if (button) button.addEventListener('click', reset);

      svg.addEventListener('pointerdown', function (e) {
        if (e.button !== 0) return;
        var ux = userX(e.clientX);
        if (ux < plot[0] || ux > plot[0] + plot[2]) return;
        dragging = true;
        start = ux;
        band = el('rect', { 'class': 'brush', x: ux, y: plot[1], width: 0, height: plot[3] });
        overlay.appendChild(band);
        try { svg.setPointerCapture(e.pointerId); } catch (err) {}
        hideTip();
        clearCross();
      });
      svg.addEventListener('pointermove', function (e) {
        if (!dragging || !band) return;
        var ux = Math.max(plot[0], Math.min(userX(e.clientX), plot[0] + plot[2]));
        band.setAttribute('x', Math.min(start, ux));
        band.setAttribute('width', Math.abs(ux - start));
      });
      svg.addEventListener('pointerup', function (e) {
        if (!dragging) return;
        dragging = false;
        var ux = Math.max(plot[0], Math.min(userX(e.clientX), plot[0] + plot[2]));
        if (band) { overlay.removeChild(band); band = null; }
        if (Math.abs(ux - start) < 6) return;
        var lo = toData(Math.min(start, ux)), hi = toData(Math.max(start, ux));
        if (hi - lo <= 0) return;
        view = [lo, hi];
        apply();
      });
      svg.addEventListener('dblclick', reset);
    }
  });
})();
"""


def _page(title: str, nav: str, toc: str, body: str) -> str:
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n"
        f"<script>{HEAD_JS}</script>\n"
        f"<style>{stylesheet()}</style>\n</head>\n<body>\n"
        '<a class="skip" href="#main">Skip to content</a>\n'
        f"{nav}\n"
        f'<div class="shell">\n{toc}\n<main id="main">\n{body}\n</main>\n</div>\n'
        f"<script>{JS}</script>\n</body>\n</html>\n"
    )


def _nav(here: str, badge: str = "", up: str = "") -> str:
    trail = f'<span class="sep">/</span><span class="here">{esc(here)}</span>' if here else ""
    return (
        '<header class="nav"><div class="nav-in">'
        f'<a class="brand" href="{esc(up or "#main")}">runhealth</a>'
        f"{trail}{badge}"
        '<div class="spacer"></div>'
        f"{theme_switch()}"
        "</div></header>"
    )


def _badge(level: str, text: str = "") -> str:
    return (
        f'<span class="badge g-{level}"><span class="mark">{GRADE_MARK.get(level, "?")}</span>'
        f"{esc(text or GRADE_TEXT.get(level, level))}</span>"
    )


def _tile(value: str, label: str) -> str:
    return f'<div class="tile"><div class="v">{value}</div><div class="l">{esc(label)}</div></div>'


def _check_card(c: Check) -> str:
    ev = "".join(f"<li>{esc(e)}</li>" for e in c.evidence)
    return (
        f'<div class="check l-{c.level}"><div class="hd">'
        f'<span class="t">{esc(c.title)}</span><span class="h">{esc(c.headline)}</span></div>'
        + (f'<div class="d">{esc(c.detail)}</div>' if c.detail else "")
        + (f"<ul>{ev}</ul>" if ev else "")
        + "</div>"
    )


def _figure(f: Figure, log_href: str = "") -> str:
    note = f'<span class="note">{esc(f.note)}</span>' if f.note else ""
    reset = (
        '<button type="button" class="zoomed" hidden>reset zoom</button>'
        if 'data-zoom="1"' in f.svg
        else ""
    )
    chart = f' data-log-href="{esc(log_href)}"' if log_href else ""
    return (
        f'<figure class="fig" id="fig-{esc(f.key)}">'
        f'<div class="fh"><h3>{esc(f.title)}</h3>{note}{reset}</div>'
        f'<p class="cap">{esc(f.caption)}</p>'
        f'<div class="chart"{chart}>{f.svg}<div class="tip" role="tooltip" hidden></div></div>'
        "</figure>"
    )


def _kv(pairs: list[tuple[str, str]]) -> str:
    rows = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in pairs if v not in (None, ""))
    return f'<dl class="kv">{rows}</dl>' if rows else ""


def _details(summary: str, body: str, note: str = "") -> str:
    if not body:
        return ""
    tail = f'<span style="color:var(--muted);font-weight:400">{esc(note)}</span>' if note else ""
    return (
        f"<details><summary><span>{esc(summary)}</span>{tail}</summary>"
        f'<div class="body">{body}</div></details>'
    )


def _timer_tables(a: Assessment) -> str:
    out = []
    for g in a.timers:
        rows = "".join(
            f'<tr><td class="depth-{min(r.depth, 4)}">{esc(r.label)}</td>'
            f'<td class="n">{_num(int(r.calls)) if r.calls else "&ndash;"}</td>'
            f'<td class="n">{format_duration(r.total)}</td>'
            f'<td class="n">{format_duration(r.minimum)}</td>'
            f'<td class="n">{format_duration(r.maximum)}</td>'
            f'<td class="n">{f"{r.imbalance:.2f}x" if r.imbalance else "&ndash;"}</td>'
            f'<td class="n">{r.share * 100:.1f}%</td></tr>'
            for r in g.rows
        )
        out.append(
            _details(
                g.title,
                '<div class="scroll"><table><thead><tr><th>timer</th><th>calls</th>'
                "<th>average</th><th>fastest rank</th><th>slowest rank</th>"
                "<th>spread</th><th>share</th></tr></thead>"
                f"<tbody>{rows}</tbody></table></div>",
                f"{g.root} = {format_duration(g.root_seconds)}",
            )
        )
    return "".join(out)


def _counter_table(log: RunLog) -> str:
    counters, ratios = counter_rows(log)
    out = []
    for table in (counters, ratios):
        if table is None or not table.rows:
            continue
        head = "".join(f"<th>{esc(c)}</th>" for c in table.columns)
        rows = "".join(
            "<tr>"
            + "".join(
                (
                    "<td>" + esc(r.cells.get(c, "")) + "</td>"
                    if i == 0
                    else '<td class="n">' + esc(r.cells.get(c, "")) + "</td>"
                )
                for i, c in enumerate(table.columns)
            )
            + "</tr>"
            for r in table.rows
        )
        out.append(
            _details(
                table.title,
                f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
                f"<tbody>{rows}</tbody></table></div>",
            )
        )
    return "".join(out)


def _provenance(log: RunLog) -> str:
    f = log.fields
    sb = log.keyvalues.get("sbatch", {})
    pairs = [
        ("Log file", log.path),
        ("Job id", f.get("job_id", "")),
        ("Job name", f.get("job_name") or sb.get("job-name", "")),
        ("Partition", sb.get("partition", "")),
        ("Account", sb.get("account", "")),
        ("Nodes", str(f.get("node_count") or sb.get("nodes", ""))),
        ("Node list", (f.get("nodelist") or "").strip("'\"")),
        ("GPUs per node", str(f.get("gpus_per_node", ""))),
        ("Wall-clock request", sb.get("time", "")),
        ("Environment", sb.get("uenv", "")),
        ("Profiles applied", ", ".join(log.profiles)),
        ("Line format", log.line_format),
        ("Log size", f"{log.size / 1e6:.1f} MB, {log.n_lines:,} lines"),
    ]
    model = [
        ("Model version", f.get("model_version", "")),
        ("Revision", f.get("model_revision", "")),
        ("Branch", f.get("model_branch", "")),
        ("MPI", f.get("mpi_library", "")),
        ("Compiler", f.get("fortran_compiler", "")),
        ("Coupler", f.get("yac_version", "")),
        (
            "Ranks",
            ", ".join(
                f"{k.replace('_ranks', '')}: {v}" for k, v in f.items() if k.endswith("_ranks")
            ),
        ),
    ]
    body = _kv(pairs)
    if any(v for _, v in model):
        body += '<div style="height:14px"></div>' + _kv(model)
    return _details("Job and build provenance", body)


def _node_table(log: RunLog) -> str:
    if not log.nodes:
        return ""
    rows = "".join(
        f'<tr><td>{esc(n)}</td><td class="n">{c:,}</td></tr>'
        for n, c in sorted(log.nodes.items(), key=lambda kv: -kv[1])[:64]
    )
    return _details(
        "Nodes seen in the log",
        '<div class="scroll"><table><thead><tr><th>node</th>'
        "<th>lines mentioning it</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>",
        f"{len(log.nodes)} nodes",
    )


def run_tiles(log: RunLog, a: Assessment) -> str:
    s = a.stats
    out = [
        _tile(_badge(STATUS_LEVEL.get(a.status, "info"), a.status.title()), "status"),
        _tile(format_duration(s.get("wall_seconds")) or "&ndash;", "wall clock"),
    ]
    if s.get("sypd"):
        out.append(_tile(f"{s['sypd']:.2f}", log.setting("throughput_label", "rate")))
    if s.get("progress_last") is not None:
        out.append(_tile(f"{s['progress_last']:,}", log.setting("progress_label", "progress")))
    if s.get("nodes"):
        out.append(_tile(f"{s['nodes']:,}", "nodes"))
    if s.get("max_gap"):
        out.append(_tile(format_duration(s["max_gap"]), "longest silence"))
    out.append(_tile(_badge(a.grade), "health"))
    return f'<div class="tiles">{"".join(out)}</div>'


def render_run(view: RunView, index_href: str = "index.html") -> str:
    log, a = view.log, view.assessment
    name = log.fields.get("job_name") or log.name
    title = f"{name} - run health"
    toc = Toc()
    body = [
        f'<div class="head" id="{toc.add("summary", "Summary")}">'
        f'<div class="crumb"><a href="{esc(index_href)}">All runs</a></div>'
        f"<h1>{esc(name)}</h1>"
        f'<div class="sub">job {esc(log.fields.get("job_id") or "?")} &middot; '
        f'{esc(format_stamp(log.first_wall) or "unknown start")} &rarr; '
        f'{esc(format_stamp(log.last_wall) or "unknown end")}</div></div>',
        run_tiles(log, a),
        f'<h2 class="sec" id="{toc.add("checks", "Checks")}">Checks</h2>',
        "".join(_check_card(c) for c in a.checks),
    ]
    if view.figures:
        body.append(f'<h2 class="sec" id="{toc.add("figures", "Figures")}">Figures</h2>')
        for f in view.figures:
            toc.add(f"fig-{f.key}", f.title, level=2)
            body.append(_figure(f, view.log_href))
    detail = _timer_tables(a) + _counter_table(log) + _node_table(log) + _provenance(log)
    if view.log_href:
        detail += _details(
            "Raw log",
            f'<p><a href="{esc(view.log_href)}">{esc(Path(view.log_href).name)}</a> '
            f"&mdash; {log.n_lines:,} lines. Clicking a silence in the timeline opens "
            "it at the line the run went quiet.</p>",
        )
    if detail:
        body += [f'<h2 class="sec" id="{toc.add("detail", "Detail")}">Detail</h2>', detail]
    if log.notes:
        body.append("<footer>" + "<br>".join(esc(n) for n in log.notes) + "</footer>")
    body.append(_footer())
    nav = _nav(name, _badge(a.grade), up=index_href)
    return _page(title, nav, toc.render(), "\n".join(body))


def _footer() -> str:
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"<footer>Generated by runhealth on {when}. "
        "Print this page to PDF from your browser for a shareable copy.</footer>"
    )


def render_index(
    views: list[RunView], sources: list[str], overview: Figure | None, title: str
) -> str:
    counts: dict[str, int] = {}
    for v in views:
        counts[v.assessment.grade] = counts.get(v.assessment.grade, 0) + 1
    tiles = [_tile(str(len(views)), "runs")] + [
        _tile(_badge(g, str(counts[g])), GRADE_TEXT[g])
        for g in ("fail", "warn", "info", "ok")
        if counts.get(g)
    ]
    rows = []
    for v in sorted(views, key=lambda v: v.log.first_wall or 0, reverse=True):
        log, a = v.log, v.assessment
        s = a.stats
        started = format_stamp(log.first_wall)
        outcome = log.outcome.text if log.outcome else ""
        rows.append(
            f'<tr data-grade="{a.grade}">'
            f'<td data-v="{esc(a.grade)}">{_badge(a.grade)}</td>'
            f'<td data-v="{esc(log.name)}"><a href="{esc(v.page)}">'
            f'{esc(log.fields.get("job_name") or log.name)}</a><br>'
            f'<span style="color:var(--muted);font-size:12px">{esc(a.status.title())}'
            + (f" &middot; {esc(outcome[:70])}" if outcome else "")
            + "</span></td>"
            f'<td class="n" data-v="{esc(log.fields.get("job_id") or "")}">'
            f'{esc(log.fields.get("job_id") or "&ndash;")}</td>'
            f'<td class="n" data-v="{log.first_wall or 0}">{esc(started)}</td>'
            f'<td class="n" data-v="{s.get("wall_seconds") or 0}">'
            f'{format_duration(s.get("wall_seconds")) or "&ndash;"}</td>'
            f'<td class="n" data-v="{s.get("nodes") or 0}">{_num(s.get("nodes"))}</td>'
            f'<td class="n" data-v="{s.get("progress_last") or 0}">'
            f'{_num(s.get("progress_last"))}</td>'
            f'<td class="n" data-v="{s.get("sypd") or 0}">'
            f'{_rate(s) or "&ndash;"}</td>'
            f'<td class="n" data-v="{s.get("max_gap") or 0}">'
            f'{format_duration(s.get("max_gap")) or "&ndash;"}</td>'
            "</tr>"
        )
    filters = (
        '<div class="filters"><button data-grade="all" aria-pressed="true">all</button>'
        + "".join(
            f'<button data-grade="{g}">{GRADE_TEXT[g]} ({counts[g]})</button>'
            for g in ("fail", "warn", "info", "ok")
            if counts.get(g)
        )
        + "</div>"
    )
    toc = Toc()
    body = [
        f'<div class="head" id="{toc.add("summary", "Summary")}">'
        '<div class="crumb">runhealth</div>'
        f"<h1>{esc(title)}</h1>"
        f'<div class="sub">{esc(", ".join(sources))}</div></div>',
        f'<div class="tiles">{"".join(tiles)}</div>',
    ]
    if overview:
        body.append(f'<h2 class="sec" id="{toc.add("overview", "All runs")}">Comparison</h2>')
        body.append(_figure(overview))
    body += [
        f'<h2 class="sec" id="{toc.add("runs", "Runs")}">Runs</h2>',
        filters,
        '<div class="scroll"><table><thead><tr>'
        '<th class="sortable">health</th><th class="sortable">run</th>'
        '<th class="sortable">job</th><th class="sortable">started</th>'
        '<th class="sortable">wall</th><th class="sortable">nodes</th>'
        '<th class="sortable">progress</th><th class="sortable">rate</th>'
        '<th class="sortable">longest silence</th>'
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>",
        _footer(),
    ]
    return _page(title, _nav("", ""), toc.render(), "\n".join(body))


# -- Markdown -------------------------------------------------------------


def render_markdown(views: list[RunView], sources: list[str], title: str) -> str:
    out = [f"# {title}", "", f"Sources: {', '.join(sources)}", ""]
    out += [
        "| health | run | job | started | wall | progress | rate | longest silence |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for v in sorted(views, key=lambda v: v.log.first_wall or 0, reverse=True):
        s = v.assessment.stats
        out.append(
            f"| **{v.assessment.grade.upper()}** | {v.log.fields.get('job_name') or v.log.name} "
            f"| {v.log.fields.get('job_id') or '-'} | {format_stamp(v.log.first_wall) or '-'} "
            f"| {format_duration(s.get('wall_seconds')) or '-'} "
            f"| {s.get('progress_last') or '-'} "
            f"| {_rate(s) or '-'} "
            f"| {format_duration(s.get('max_gap')) or '-'} |"
        )
    for v in sorted(views, key=lambda v: v.log.first_wall or 0, reverse=True):
        log, a = v.log, v.assessment
        out += [
            "",
            f"## {log.fields.get('job_name') or log.name} "
            f"({log.fields.get('job_id') or '?'}) - {a.status}, grade {a.grade.upper()}",
            "",
        ]
        for c in a.checks:
            out.append(f"- **{c.title}** [{c.level}]: {c.headline}")
            for e in c.evidence[:6]:
                out.append(f"    - `{e}`")
        for f in v.figures:
            if not f.href:
                continue
            out += ["", f"### {f.title}", "", f"![{f.title}]({f.href})", "", f"*{f.caption}*"]
    out.append("")
    return "\n".join(out)


# -- PDF ------------------------------------------------------------------


def to_pdf(html_path: Path, pdf_path: Path) -> str:
    """Render an HTML page to PDF. Returns a message for the caller to print."""
    try:
        from weasyprint import HTML  # noqa: PLC0415
    except ImportError:
        return (
            f"PDF needs WeasyPrint, which is not installed. Wrote {html_path} instead - "
            "open it and use the browser's Print to PDF, or install the extra with "
            "'uv sync --extra pdf'."
        )
    HTML(filename=str(html_path)).write_pdf(str(pdf_path))
    return f"Wrote {pdf_path}"


# -- the embedded log -----------------------------------------------------


def copy_log(log: RunLog, outdir: Path, max_bytes: int) -> str:
    """Write the raw log as a page whose lines can be linked to.

    A plain copy of the file cannot be opened at a particular line, and the
    line a run went quiet at is exactly what a silence in the timeline should
    lead to. Lines are grouped into blocks the browser can skip rendering
    until they are scrolled near, so a large log still opens.
    """
    src = Path(log.path)
    if not src.is_file() or src.stat().st_size > max_bytes:
        return ""
    dest = outdir / "logs" / f"{src.name}.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    blocks, current = [], []
    with src.open("r", errors="replace") as handle:
        for n, line in enumerate(handle, 1):
            current.append(f'<b id="L{n}" data-n="{n}">{esc(line.rstrip(chr(10)))}</b>')
            if len(current) >= LOG_BLOCK:
                blocks.append(f'<div class="blk">{"".join(current)}</div>')
                current = []
    if current:
        blocks.append(f'<div class="blk">{"".join(current)}</div>')
    name = log.fields.get("job_name") or log.name
    toc = Toc()
    body = (
        f'<div class="head" id="{toc.add("summary", "Log")}">'
        f'<div class="crumb"><a href="../{esc(page_name(log))}">Back to the report</a></div>'
        f"<h1>{esc(src.name)}</h1>"
        f'<div class="sub">{log.n_lines:,} lines, {src.stat().st_size / 1e6:.1f} MB</div></div>'
        f'<div class="logview">{"".join(blocks)}</div>'
    )
    nav = _nav(src.name, "", up=f"../{page_name(log)}")
    dest.write_text(_page(f"{name} - raw log", nav, "", body))
    return f"logs/{dest.name}"


def page_name(log: RunLog) -> str:
    """The run page a log view belongs to. Mirrors the CLI's slug."""
    stem = Path(log.path).stem
    return (re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-") or "run") + ".html"
