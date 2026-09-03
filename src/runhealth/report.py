"""Render the assessment as HTML, Markdown or PDF.

No template engine: the pages are small enough that string fragments are
easier to read and to change than a template language, and it keeps the
dependency list to matplotlib and PyYAML.

The HTML carries a real print stylesheet, so a browser's Save as PDF produces
a proper document. ``--format pdf`` uses WeasyPrint when it is installed and
otherwise says so rather than failing.
"""

from __future__ import annotations

import html
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

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


CSS = """
:root {
  --bg: #fcfcfb; --panel: #ffffff; --panel-2: #f5f4f0; --ink: #16150f;
  --muted: #75736b; --line: #e2e1d9; --line-2: #cecdc3;
  --ok: #2f8f5b; --info: #3d7fd6; --warn: #c98216; --fail: #c8452f;
  --shadow: 0 1px 2px rgba(20,18,10,.05), 0 4px 14px rgba(20,18,10,.04);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #14150f; --panel: #1c1e17; --panel-2: #23251d; --ink: #edece4;
    --muted: #9d9b90; --line: #32342a; --line-2: #444639;
    --ok: #64c48c; --info: #7cb0ef; --warn: #e5a94c; --fail: #ef7a63;
    --shadow: none;
  }
}
:root[data-theme="dark"] {
  --bg: #14150f; --panel: #1c1e17; --panel-2: #23251d; --ink: #edece4;
  --muted: #9d9b90; --line: #32342a; --line-2: #444639;
  --ok: #64c48c; --info: #7cb0ef; --warn: #e5a94c; --fail: #ef7a63;
  --shadow: none;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  -webkit-font-smoothing: antialiased;
}
code, .mono, td.n, .kv dd { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
a { color: inherit; text-decoration: none; border-bottom: 1px solid var(--line-2); }
a:hover { border-bottom-color: currentColor; }
.wrap { max-width: 1120px; margin: 0 auto; padding: 34px 26px 90px; }
header.top { display: flex; align-items: flex-start; gap: 18px; flex-wrap: wrap;
  border-bottom: 1px solid var(--line); padding-bottom: 18px; margin-bottom: 26px; }
header.top h1 { font-size: 25px; margin: 0 0 4px; letter-spacing: -.015em; }
header.top .sub { color: var(--muted); font-size: 13px; }
header.top .spacer { flex: 1 1 auto; }
.crumb { font-size: 12px; color: var(--muted); text-transform: uppercase;
  letter-spacing: .09em; margin-bottom: 6px; }
button.theme { background: var(--panel); border: 1px solid var(--line-2); color: var(--muted);
  border-radius: 999px; padding: 5px 13px; font-size: 12px; cursor: pointer; }

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
  border-top: 1px solid var(--line); padding-top: 16px; }

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

figure.fig { margin: 0 0 22px; background: var(--panel); border: 1px solid var(--line);
  border-radius: 10px; padding: 16px; box-shadow: var(--shadow); }
figure.fig h3 { margin: 0 0 2px; font-size: 15px; }
figure.fig .cap { color: var(--muted); font-size: 13px; margin: 0 0 12px; max-width: 74ch; }
figure.fig img { width: 100%; height: auto; display: block; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) figure.fig img { filter: invert(.92) hue-rotate(180deg); }
}
:root[data-theme="dark"] figure.fig img { filter: invert(.92) hue-rotate(180deg); }

table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
th { text-align: left; font-size: 11.5px; text-transform: uppercase; letter-spacing: .06em;
  color: var(--muted); font-weight: 650; padding: 7px 10px; border-bottom: 1px solid var(--line-2);
  white-space: nowrap; }
td { padding: 7px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
td.n { text-align: right; white-space: nowrap; font-size: 12.5px; }
tbody tr:hover { background: var(--panel-2); }
.scroll { overflow-x: auto; background: var(--panel); border: 1px solid var(--line);
  border-radius: 10px; box-shadow: var(--shadow); }
th.sortable { cursor: pointer; } th.sortable:hover { color: var(--ink); }

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

@media print {
  :root { --bg: #fff; --panel: #fff; --panel-2: #fff; --ink: #000; --muted: #444;
    --line: #ccc; --line-2: #999; --shadow: none; }
  body { font-size: 10.5pt; }
  .wrap { max-width: none; padding: 0; }
  button.theme, .filters { display: none; }
  .check, figure.fig, details, .scroll { break-inside: avoid; page-break-inside: avoid;
    box-shadow: none; }
  h2.sec { break-before: page; page-break-before: always; }
  h2.sec:first-of-type { break-before: auto; page-break-before: auto; }
  details { border: none; padding: 0; } details > summary::after { content: ""; }
  details .body { display: block !important; }
  figure.fig img { filter: none !important; }
  a { border-bottom: none; }
}
"""

JS = """
(function () {
  var root = document.documentElement;
  var saved = null;
  try { saved = localStorage.getItem('runhealth-theme'); } catch (e) {}
  if (saved) root.setAttribute('data-theme', saved);
  var btn = document.getElementById('theme');
  if (btn) btn.addEventListener('click', function () {
    var dark = root.getAttribute('data-theme') === 'dark' ||
      (!root.getAttribute('data-theme') &&
       window.matchMedia('(prefers-color-scheme: dark)').matches);
    var next = dark ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('runhealth-theme', next); } catch (e) {}
  });
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
  document.querySelectorAll('th.sortable').forEach(function (th, i) {
    th.addEventListener('click', function () {
      var tb = th.closest('table').tBodies[0];
      var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
      var dir = th.dataset.dir === 'asc' ? -1 : 1;
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
})();
"""


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        f'<div class="wrap">\n{body}\n</div>\n<script>{JS}</script>\n</body>\n</html>\n'
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
    tiles = [
        _badge(STATUS_LEVEL.get(a.status, "info"), a.status.title()),
        format_duration(s.get("wall_seconds")) or "&ndash;",
    ]
    out = [
        _tile(tiles[0], "status"),
        _tile(tiles[1], "wall clock"),
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
    title = f"{log.fields.get('job_name') or log.name} - run health"
    figures = "".join(
        f'<figure class="fig"><h3>{esc(f.title)}</h3>'
        f'<p class="cap">{esc(f.caption)}</p>'
        f'<img src="{esc(f.href)}" alt="{esc(f.title)}"></figure>'
        for f in view.figures
    )
    body = [
        '<header class="top"><div>'
        f'<div class="crumb"><a href="{esc(index_href)}">All runs</a></div>'
        f"<h1>{esc(log.fields.get('job_name') or log.name)}</h1>"
        f'<div class="sub">job {esc(log.fields.get("job_id") or "?")} &middot; '
        f'{esc(format_stamp(log.first_wall) or "unknown start")} &rarr; '
        f'{esc(format_stamp(log.last_wall) or "unknown end")}</div>'
        '</div><div class="spacer"></div>'
        '<button class="theme" id="theme">theme</button></header>',
        run_tiles(log, a),
        '<h2 class="sec">Checks</h2>',
        "".join(_check_card(c) for c in a.checks),
    ]
    if figures:
        body += ['<h2 class="sec">Figures</h2>', figures]
    detail = _timer_tables(a) + _counter_table(log) + _node_table(log) + _provenance(log)
    if view.log_href:
        detail += _details(
            "Raw log", f'<p><a href="{esc(view.log_href)}">{esc(Path(view.log_href).name)}</a></p>'
        )
    if detail:
        body += ['<h2 class="sec">Detail</h2>', detail]
    if log.notes:
        body.append("<footer>" + "<br>".join(esc(n) for n in log.notes) + "</footer>")
    body.append(_footer())
    return _page(title, "\n".join(body))


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
    figure = ""
    if overview:
        figure = (
            f'<figure class="fig"><h3>{esc(overview.title)}</h3>'
            f'<p class="cap">{esc(overview.caption)}</p>'
            f'<img src="{esc(overview.href)}" alt="{esc(overview.title)}"></figure>'
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
    body = [
        '<header class="top"><div>'
        '<div class="crumb">runhealth</div>'
        f"<h1>{esc(title)}</h1>"
        f'<div class="sub">{esc(", ".join(sources))}</div>'
        '</div><div class="spacer"></div>'
        '<button class="theme" id="theme">theme</button></header>',
        f'<div class="tiles">{"".join(tiles)}</div>',
        figure,
        '<h2 class="sec">Runs</h2>',
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
    return _page(title, "\n".join(body))


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


def copy_log(log: RunLog, outdir: Path, max_bytes: int) -> str:
    """Copy the raw log next to the report when it is small enough to be useful."""
    src = Path(log.path)
    if not src.is_file() or src.stat().st_size > max_bytes:
        return ""
    dest = outdir / "logs" / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return f"logs/{dest.name}"
