"""The dashboard layer of the HTML report: layout, viewer preferences, chart tools.

Everything here refines a page that is already complete without it. The
markup the report writes reads, prints and converts to PDF on its own; the
script below only rearranges it, folds it and adds controls, and every choice
a reader makes is kept in their own browser.
"""

PREFS_KEY = "runhealth-prefs"

# Settings applied as attributes on the root element before the first paint,
# so a reader's layout does not jump into place after the page has loaded.
ROOT_PREFS = ("density", "labels", "cols", "captions", "simticks", "side", "checks")

HEAD_JS = (
    """
try {
  var p = JSON.parse(localStorage.getItem('%s') || '{}');
  %s.forEach(function (k) {
    if (typeof p[k] === 'string') document.documentElement.setAttribute('data-' + k, p[k]);
  });
} catch (e) {}
document.documentElement.classList.add('js');
"""
    % (PREFS_KEY, list(ROOT_PREFS))
)

CSS = """
/* == dashboard layer == */
:root { --side-w: 252px; --gap: 16px; --pad: 18px; --radius: 12px; --lk-user: 1; }
:root[data-density="compact"] { --gap: 10px; --pad: 13px; }
:root[data-labels="s"] { --lk-user: .9; }
:root[data-labels="l"] { --lk-user: 1.18; }
:root[data-labels="xl"] { --lk-user: 1.36; }
:root[data-density="compact"] body { font-size: 15px; line-height: 1.5; }

/* -- full-width shell: a sidebar of sections beside the content -- */
.nav-in { max-width: none; }
.shell { max-width: none; }
@media screen and (min-width: 1041px) {
  .nav-in { padding: 0 18px; }
  .shell { gap: 28px; padding: 0 28px 90px 0; grid-template-columns: var(--side-w) minmax(0, 1fr); }
  .toc { position: sticky; align-self: start; top: var(--nav-h);
    height: calc(100vh - var(--nav-h)); padding: 22px 12px 22px 16px;
    border-right: 1px solid var(--line); display: flex; flex-direction: column;
    background: color-mix(in srgb, var(--panel-2) 45%, transparent); }
  /* Rows keep one fixed height and stay at the top: a grid taller than its
     entries would otherwise stretch them, so folding would respace the rest. */
  .toc nav { flex: 1 1 auto; min-height: 0; max-height: none; border-left: none;
    padding-right: 2px; align-content: start; grid-auto-rows: 32px; row-gap: 2px; }
  .toc a { margin: 0; padding: 0 10px; height: 32px; line-height: 32px; border-left: none;
    border-radius: 8px; font-size: 14px; color: var(--muted); }
  .toc a.lv2 { padding-left: 27px; font-size: 13.5px; }
  .toc .tfold { align-self: center; }
  .toc a:hover { background: var(--panel); color: var(--ink); }
  .toc a[aria-current="true"] { color: var(--ink); font-weight: 650;
    background: color-mix(in srgb, var(--info) 13%, transparent); }
  :root[data-side="hidden"] .shell, .shell:not(:has(> .toc)) {
    grid-template-columns: minmax(0, 1fr); padding-left: 28px; }
  :root[data-side="hidden"] .toc { display: none; }
}
main { padding-top: 24px; }
.tfold-all { min-width: 74px; text-align: right; }
.toc nav { overflow-anchor: none; }
.toc a[hidden], .toc a.pref-off, .toc a.pref-off + .tfold { display: none; }

/* -- header controls -- */
.nav .tool { display: grid; place-items: center; width: 34px; height: 34px; padding: 0;
  flex: 0 0 auto; background: none; border: 1px solid transparent; border-radius: 9px;
  color: var(--muted); cursor: pointer; }
.nav .tool:hover, .nav .tool[aria-expanded="true"] { color: var(--ink);
  background: var(--panel-2); border-color: var(--line); }
.nav .tool .ico { width: 17px; height: 17px; }
.side-btn { display: none !important; }
body:not(:has(.toc)) .side-btn { display: none !important; }
.js .side-btn { display: grid !important; }
.prefs-wrap { position: relative; flex: 0 0 auto; display: none; }
.js .prefs-wrap { display: block; }
@media (max-width: 1040px) { .js .side-btn { display: none !important; }
body:not(:has(.toc)) .side-btn { display: none !important; } }

/* -- the customize panel -- */
.prefs { position: absolute; top: calc(100% + 8px); right: 0; z-index: 55;
  width: min(380px, calc(100vw - 24px)); max-height: calc(100vh - var(--nav-h) - 24px);
  overflow-y: auto; padding: 6px 16px 16px; background: var(--panel);
  border: 1px solid var(--line); border-radius: 14px; box-shadow: 0 16px 44px rgba(0,0,0,.18); }
.prefs h3 { margin: 14px 0 8px; font-size: 11.5px; font-weight: 700; color: var(--muted);
  text-transform: uppercase; letter-spacing: .08em; }
.prefs .row { display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 5px 0; font-size: 14px; }
.prefs .row > span { min-width: 0; }
.seg { display: inline-flex; flex: 0 0 auto; padding: 2px; gap: 2px; background: var(--panel-2);
  border: 1px solid var(--line); border-radius: 9px; }
.seg button { min-width: 36px; height: 28px; padding: 0 10px; font: inherit; font-size: 12.5px;
  font-weight: 600; color: var(--muted); background: none; border: none; border-radius: 7px;
  cursor: pointer; }
.seg button:hover { color: var(--ink); }
.seg button[aria-pressed="true"] { background: var(--panel); color: var(--ink);
  box-shadow: 0 1px 2px rgba(0,0,0,.12); }
.plist { list-style: none; margin: 0; padding: 0; border: 1px solid var(--line);
  border-radius: 10px; }
.plist li { display: flex; align-items: center; gap: 8px; padding: 4px 6px 4px 10px;
  font-size: 13.5px; }
.plist li + li { border-top: 1px solid var(--line); }
.plist label { flex: 1 1 auto; min-width: 0; display: flex; align-items: center; gap: 9px;
  cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.plist input { width: 16px; height: 16px; margin: 0; accent-color: var(--info); flex: 0 0 auto; }
.plist .mv { display: grid; place-items: center; width: 28px; height: 28px; padding: 0;
  background: none; border: 1px solid transparent; border-radius: 7px; color: var(--muted);
  cursor: pointer; font-size: 13px; }
.plist .mv:hover:not(:disabled) { background: var(--panel-2); border-color: var(--line); color: var(--ink); }
.plist .mv:disabled { opacity: .3; cursor: default; }
.prefs .reset { margin-top: 16px; width: 100%; height: 34px; font: inherit; font-size: 13.5px;
  font-weight: 600; color: var(--muted); background: none; border: 1px solid var(--line-2);
  border-radius: 9px; cursor: pointer; }
.prefs .reset:hover { color: var(--fail); border-color: var(--fail); }

/* -- overview: stat cards beside the health summary -- */
.overview { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--gap);
  margin: 0 0 26px; align-items: stretch; }
@media (min-width: 1200px) {
  .overview { grid-template-columns: minmax(0, 1fr) minmax(320px, 400px); } }
.overview > .tiles { margin: 0; align-content: start; }
.tiles { grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: var(--gap); }
.tile { position: relative; display: flex; flex-direction: column; gap: 3px;
  padding: 14px var(--pad); border-radius: var(--radius); overflow: hidden; }
.tile .l { order: -1; margin: 0 0 2px; font-size: 11.5px; letter-spacing: .07em; }
.tile .v { font-size: 25px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.tile .s { font-size: 12.5px; color: var(--muted); line-height: 1.4; }
.tile.tone-ok, .tile.tone-info, .tile.tone-warn, .tile.tone-fail { border-top-width: 3px; }
.tile.tone-ok { border-top-color: var(--ok); } .tile.tone-info { border-top-color: var(--info); }
.tile.tone-warn { border-top-color: var(--warn); } .tile.tone-fail { border-top-color: var(--fail); }
.tile .badge { font-size: 14px; padding: 3px 13px 3px 6px; }

.card { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius);
  padding: 16px var(--pad); box-shadow: var(--shadow); min-width: 0; }
.glance { display: flex; flex-direction: column; gap: 12px; }
.glance .gh { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.glance h2 { margin: 0; font-size: 15px; font-weight: 700; letter-spacing: -.005em; }
.glance .gh .muted { font-size: 13px; }
.glance .sub-h { margin: 2px 0 -4px; font-size: 11.5px; font-weight: 700; color: var(--muted);
  text-transform: uppercase; letter-spacing: .07em; }
.segbar { display: flex; height: 12px; gap: 2px; border-radius: 999px; overflow: hidden;
  background: var(--panel-2); }
.segbar > span { min-width: 4px; }
.segbar .g-ok, .seg-key .g-ok { background: var(--ok); }
.segbar .g-info, .seg-key .g-info { background: var(--info); }
.segbar .g-warn, .seg-key .g-warn { background: var(--warn); }
.segbar .g-fail, .seg-key .g-fail { background: var(--fail); }
.seg-key { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 0; padding: 0;
  list-style: none; font-size: 13px; color: var(--ink); }
.seg-key li { display: inline-flex; align-items: center; gap: 6px; }
.seg-key i { width: 9px; height: 9px; border-radius: 3px; display: inline-block; }
.seg-key b { font-variant-numeric: tabular-nums; }
.issues { margin: 0; padding: 0; list-style: none; display: grid; gap: 2px;
  max-height: 290px; overflow-y: auto; }
.issues a { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 1px 10px;
  align-items: baseline; padding: 6px 8px; border: none; border-radius: 8px; color: var(--ink); }
.issues a:hover { background: var(--panel-2); }
.issues .tdot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  grid-row: 1 / span 2; align-self: start; margin-top: 7px; }
.issues .it { font-size: 13.5px; font-weight: 650; }
.issues .ih { grid-column: 2; font-size: 13px; color: var(--muted); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.glance .all-ok { margin: 0; font-size: 14px; color: var(--muted); }

/* -- sections, each a block the reader may hide or move -- */
.panel-sec[hidden] { display: none; }
.panel-sec > h2.sec:first-child { margin-top: 30px; }

/* -- checks: compact rows that open onto their evidence -- */
.checks { display: grid; gap: 8px; }
.check { margin: 0; padding: 0; }
.check .hd { padding: 11px 16px; align-items: center; }
.check .hd .h { flex: 1 1 260px; min-width: 0; }
.check .hd .badge { margin-left: auto; font-size: 12px; padding: 2px 10px 2px 4px; }
.check .hd .badge .mark { min-width: 17px; height: 17px; font-size: 11px; }
.check .ck-body { padding: 0 16px 13px; }
.check .ck-body > .d:first-child { margin-top: 0; }
.js .check.foldable > .hd { cursor: pointer; border-radius: 8px; }
.js .check.foldable > .hd:hover { background: color-mix(in srgb, var(--panel-2) 70%, transparent); }
.js .check.foldable > .hd::after { content: "\\25be"; color: var(--muted); font-size: 13px;
  flex: 0 0 auto; transition: transform .15s ease; }
.js .check.foldable.shut > .hd::after { transform: rotate(-90deg); }
.js .check.shut > .ck-body { display: none; }
:root[data-density="compact"] .check .hd { padding: 8px 13px; }
:root[data-density="compact"] .check .ck-body { padding: 0 13px 10px; }

/* -- figures: a grid of chart cards -- */
.figs { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--gap); }
.figs > figure.fig { margin: 0; display: flex; flex-direction: column; min-width: 0; }
.figs > figure.fig[hidden] { display: none; }
.figs > figure.fig > .chart { margin-top: auto; }
/* Every chart is drawn 900 units wide and shown at one common width, so the
   lettering of all figures comes out at the same size. */
.chart .rh-svg { max-width: 1120px; }
@media screen and (min-width: 1300px) {
  :root[data-cols="2"] .figs { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
figure.fig { padding: 14px var(--pad) var(--pad); border-radius: var(--radius); }
figure.fig .fh { align-items: center; row-gap: 6px; }
figure.fig h3 { font-size: 16.5px; }
figure.fig .cap { font-size: 13.5px; line-height: 1.5; margin: 4px 0 10px; }
:root[data-captions="hide"] figure.fig .cap { display: none; }
:root[data-captions="hide"] figure.fig .fh { margin-bottom: 10px; }
:root[data-simticks="hide"] .rh-svg .tick.sub { display: none; }
.fig-tools { margin-left: auto; display: inline-flex; flex-wrap: wrap; gap: 4px; }
.fig-tools button, figure.fig .fig-tools .zoomed { display: inline-flex; align-items: center;
  justify-content: center; gap: 5px; height: 30px; min-width: 30px; margin: 0; padding: 0 9px;
  font: inherit; font-size: 12.5px; font-weight: 600; color: var(--muted); background: var(--panel);
  border: 1px solid var(--line); border-radius: 8px; cursor: pointer; white-space: nowrap; }
.fig-tools button.ib { padding: 0; width: 30px; }
.fig-tools button:hover { color: var(--ink); background: var(--panel-2); border-color: var(--line-2); }
.fig-tools button[aria-pressed="true"] { color: var(--info);
  border-color: color-mix(in srgb, var(--info) 55%, var(--line));
  background: color-mix(in srgb, var(--info) 11%, var(--panel)); }
.fig-tools .ico { width: 15px; height: 15px; }
.fig-tools .zoomed[hidden] { display: none; }
.chart .rh-svg { --lk: var(--lk-user); }
.chart .rh-svg .tick { font-size: calc(10.5px * var(--lk)); }
.chart .rh-svg .tick.sub { font-size: calc(9.5px * var(--lk)); }
.chart .rh-svg .ax-label { font-size: calc(11px * var(--lk)); }
.chart .rh-svg .ref-label { font-size: calc(10.5px * var(--lk)); }
.chart .rh-svg .panel-title { font-size: calc(12.5px * var(--lk)); }
.chart .tip { font-size: 13.5px; }

/* the expanded view of one figure */
.fig-scrim { position: fixed; inset: 0; z-index: 68; background: rgba(10,10,8,.6); }
.figs > figure.fig.max, figure.fig.max { position: fixed; inset: 18px; z-index: 70; margin: 0;
  overflow: auto; box-shadow: 0 24px 70px rgba(0,0,0,.4); }
figure.fig.max > .chart { margin: auto 0; }
figure.fig.max .rh-svg { max-width: none; max-height: calc(100vh - 170px); margin: 0 auto; }
body.fig-open { overflow: hidden; }

/* -- the index: a toolbar over the runs table -- */
.tbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 12px; }
.tbar .filters { margin: 0; }
.qf { display: none; }
.js .qf { position: relative; display: flex; align-items: center; gap: 7px; height: 34px;
  flex: 0 1 280px; min-width: 180px; margin-left: auto; padding: 0 10px; background: var(--panel);
  border: 1px solid var(--line-2); border-radius: 9px; }
.qf:focus-within { border-color: var(--info);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--info) 28%, transparent); }
.qf .ico { color: var(--muted); flex: 0 0 auto; }
.qf input { flex: 1 1 auto; min-width: 0; padding: 0; border: none; outline: none;
  background: none; color: var(--ink); font: inherit; font-size: 13.5px; }
.qf-n { font-size: 12.5px; color: var(--muted); white-space: nowrap; font-variant-numeric: tabular-nums; }
table.runs tr[data-q-off] { display: none; }
@media screen and (min-width: 1100px) {
  .scroll:has(table.runs) { overflow: visible; }
  table.runs thead th { position: sticky; top: var(--nav-h); z-index: 3; background: var(--panel);
    box-shadow: 0 1px 0 var(--line-2); }
}
:root[data-density="compact"] td, :root[data-density="compact"] th { padding-top: 5px;
  padding-bottom: 5px; }

@media (prefers-reduced-motion: reduce) {
  .js .check.foldable > .hd::after { transition: none; }
}

@media print {
  .tool, .prefs-wrap, .fig-tools, .fig-scrim, .qf { display: none !important; }
  .overview { display: block; } .overview > .tiles { margin-bottom: 14px; }
  .glance { break-inside: avoid; page-break-inside: avoid; box-shadow: none; }
  .figs { display: block; } .figs > figure.fig { margin-bottom: 16px; }
  .check > .ck-body { display: block !important; }
  .check .hd::after { content: none !important; }
  .chart .rh-svg { --lk: 1; max-width: none; }
  .panel-sec[hidden], .figs > figure.fig[hidden] { display: block !important; }
  .panel-sec h2.sec { break-before: page; page-break-before: always; }
  .panel-sec:first-of-type h2.sec { break-before: auto; page-break-before: auto; }
  .tile.tone-ok, .tile.tone-info, .tile.tone-warn, .tile.tone-fail { border-top-width: 1px; }
}
"""

JS = r"""
(function () {
  'use strict';
  var root = document.documentElement;
  var KEY = '__KEY__';
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var prefs = {};
  try { prefs = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) {}
  prefs.hide = prefs.hide || {};
  prefs.order = prefs.order || {};
  prefs.charts = prefs.charts || {};
  function save() { try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch (e) {} }
  function setRoot(key, value, fallback) {
    if (value === fallback) { delete prefs[key]; root.removeAttribute('data-' + key); }
    else { prefs[key] = value; root.setAttribute('data-' + key, value); }
    save();
  }
  function make(tag, attrs, text) {
    var n = document.createElement(tag);
    for (var k in attrs || {}) n.setAttribute(k, attrs[k]);
    if (text) n.textContent = text;
    return n;
  }
  function icon(name) {
    var t = document.getElementById('rh-icon-' + name);
    return t ? t.content.firstElementChild.cloneNode(true) : document.createTextNode('');
  }
  var $$ = function (sel, el) { return Array.prototype.slice.call((el || document).querySelectorAll(sel)); };

  // -- sidebar ------------------------------------------------------------
  var sideBtn = document.querySelector('.side-btn');
  function sideState() { return root.getAttribute('data-side') === 'hidden' ? 'hidden' : 'show'; }
  if (sideBtn) {
    sideBtn.setAttribute('aria-pressed', sideState() === 'show' ? 'true' : 'false');
    sideBtn.addEventListener('click', function () {
      // The content reflows to the new width; the block at the top of the
      // window is put back where it was.
      var navH = (document.querySelector('.nav') || { offsetHeight: 0 }).offsetHeight;
      var anchor = $$('main > *, main .panel-sec > *, .figs > figure, .checks > .check')
        .filter(function (el) { return el.getBoundingClientRect().bottom > navH; })[0];
      var before = anchor ? anchor.getBoundingClientRect().top : 0;
      setRoot('side', sideState() === 'show' ? 'hidden' : 'show', 'show');
      if (anchor) window.scrollBy(0, anchor.getBoundingClientRect().top - before);
      sideBtn.setAttribute('aria-pressed', sideState() === 'show' ? 'true' : 'false');
    });
  }

  // -- checks: fold to their headline -------------------------------------
  function checkMode() { return root.getAttribute('data-checks') || 'problems'; }
  var checks = $$('.check').filter(function (c) { return c.querySelector('.ck-body'); });
  function setOpen(c, open) {
    c.classList.toggle('shut', !open);
    var hd = c.querySelector('.hd');
    if (hd) hd.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  function foldChecks() {
    var mode = checkMode();
    checks.forEach(function (c) {
      var bad = c.dataset.grade === 'fail' || c.dataset.grade === 'warn';
      setOpen(c, mode === 'all' || (mode === 'problems' && bad));
    });
  }
  checks.forEach(function (c) {
    var hd = c.querySelector('.hd');
    c.classList.add('foldable');
    hd.setAttribute('role', 'button');
    hd.setAttribute('tabindex', '0');
    function flip(e) {
      if (e.target.closest('a, button')) return;
      setOpen(c, c.classList.contains('shut'));
    }
    hd.addEventListener('click', flip);
    hd.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); flip(e); }
    });
  });
  foldChecks();
  // A link to a check, from the summary, the sidebar or a search, opens it.
  function reveal(id) {
    var el = id && document.getElementById(id);
    if (!el) return;
    var sec = el.closest('.panel-sec[hidden]');
    if (sec) sec.hidden = false;
    var fig = el.closest('figure.fig[hidden]');
    if (fig) fig.hidden = false;
    if (el.classList.contains('check')) setOpen(el, true);
  }
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[href^="#"]');
    if (a) reveal(decodeURIComponent(a.hash.slice(1)));
  }, true);
  window.addEventListener('hashchange', function () { reveal(decodeURIComponent(location.hash.slice(1))); });
  reveal(decodeURIComponent(location.hash.slice(1)));

  // -- sections and figures: hide and reorder -----------------------------
  var main = document.querySelector('main');
  var toc = document.getElementById('toc');
  var figBox = document.querySelector('.figs');
  function sections() { return $$('main > .panel-sec'); }
  function figures() { return figBox ? $$(':scope > figure.fig', figBox) : []; }
  function label(el) {
    var h = el.querySelector('h2, h3');
    return h ? h.textContent.trim() : el.id;
  }
  // The sidebar entries of one anchor: its link, its fold button and, for a
  // section, the entries nested under it.
  function tocNodes(el) {
    var id = el.getAttribute('aria-labelledby') || el.id;
    if (!toc) return [];
    var a = toc.querySelector('a[href="#' + id + '"]');
    if (!a) return [];
    var out = [a], n = a.nextElementSibling;
    if (n && n.classList.contains('tfold')) { out.push(n); n = n.nextElementSibling; }
    if (a.classList.contains('lv1')) {
      while (n && !n.classList.contains('lv1')) { out.push(n); n = n.nextElementSibling; }
    }
    return out;
  }
  function ordered(items, key) {
    var want = prefs.order[key] || [];
    return items.slice().sort(function (a, b) {
      var x = want.indexOf(a.id), y = want.indexOf(b.id);
      if (x === -1 && y === -1) return items.indexOf(a) - items.indexOf(b);
      if (x === -1) return 1;
      if (y === -1) return -1;
      return x - y;
    });
  }
  function arrange() {
    var secs = sections();
    if (secs.length) {
      var after = secs[secs.length - 1].nextSibling;
      ordered(secs, 'secs').forEach(function (s) {
        main.insertBefore(s, after);
        if (toc) tocNodes(s).forEach(function (n) { toc.appendChild(n); });
      });
    }
    if (figBox) {
      var figTail = null;
      ordered(figures(), 'figs').forEach(function (f) {
        figBox.appendChild(f);
        var nodes = tocNodes(f);
        if (!nodes.length || !toc) return;
        // Figure entries stay inside the Figures group of the sidebar.
        var anchor = figTail ? figTail.nextSibling : nodes[0];
        nodes.forEach(function (n) { toc.insertBefore(n, anchor); });
        figTail = nodes[nodes.length - 1];
      });
    }
    var hide = (prefs.hide.secs || []).concat(prefs.hide.figs || []);
    secs.concat(figures()).forEach(function (el) {
      var off = hide.indexOf(el.id) !== -1;
      el.hidden = off;
      tocNodes(el).forEach(function (n) { n.classList.toggle('pref-off', off); });
    });
    window.dispatchEvent(new Event('scroll'));
  }
  arrange();

  // -- index columns ------------------------------------------------------
  var runs = document.querySelector('table.runs');
  var colStyle = make('style');
  document.head.appendChild(colStyle);
  function columns() {
    return runs ? $$('thead th', runs).map(function (th, i) {
      return { i: i + 1, id: 'col-' + th.textContent.trim().replace(/\s+/g, '-'), name: th.textContent.trim() };
    }) : [];
  }
  function applyColumns() {
    var off = prefs.hide.cols || [];
    colStyle.textContent = columns().filter(function (c) { return off.indexOf(c.id) !== -1; })
      .map(function (c) {
        return 'table.runs thead th:nth-child(' + c.i + '), table.runs tr:not(.grp-hd) > :nth-child(' +
          c.i + ') { display: none; }';
      }).join('\n');
  }
  applyColumns();

  // -- quick filter over the runs table -----------------------------------
  var qf = document.querySelector('.qf input');
  if (qf && runs) {
    var count = document.querySelector('.qf-n');
    var rows = $$('tbody tr[data-grade]', runs);
    rows.forEach(function (r) { r._text = r.textContent.toLowerCase(); });
    var t = null;
    function filterRows() {
      var words = qf.value.toLowerCase().split(/\s+/).filter(Boolean);
      var shown = 0;
      rows.forEach(function (r) {
        var ok = words.every(function (w) { return r._text.indexOf(w) !== -1; });
        if (ok) r.removeAttribute('data-q-off'); else r.setAttribute('data-q-off', '');
        if (ok && !r.hidden) shown++;
      });
      $$('tbody.grp', runs).forEach(function (g) {
        g.hidden = !g.querySelector('tr[data-grade]:not([hidden]):not([data-q-off])');
      });
      if (count) count.textContent = words.length ? shown + ' of ' + rows.length : '';
    }
    qf.addEventListener('input', function () { clearTimeout(t); t = setTimeout(filterRows, 60); });
    qf.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { qf.value = ''; filterRows(); }
    });
    // The grade filter hides rows too, so both are settled together.
    $$('.filters button').forEach(function (b) {
      b.addEventListener('click', function () { setTimeout(filterRows, 0); });
    });
  }

  // -- figures: tools and the expanded view -------------------------------

  var cssText = (document.getElementById('rh-svg-css') || {}).textContent || '';
  function standalone(svg) {
    var copy = svg.cloneNode(true);
    $$('.rh-overlay', copy).forEach(function (n) { n.remove(); });
    copy.removeAttribute('style');
    copy.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    var st = document.createElementNS('http://www.w3.org/2000/svg', 'style');
    st.textContent = cssText;
    copy.insertBefore(st, copy.firstChild);
    return new XMLSerializer().serializeToString(copy);
  }
  function download(blob, name) {
    var url = URL.createObjectURL(blob);
    var a = make('a', { href: url, download: name });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1500);
  }
  function fileName(fig, ext) {
    var page = (document.querySelector('.nav') || {}).dataset || {};
    var stem = (page.page || 'runhealth').replace(/\.html$/, '');
    return stem + '-' + fig.id.replace(/^fig-/, '') + '.' + ext;
  }
  function savePng(fig, svg) {
    var vb = svg.viewBox.baseVal, scale = 2;
    var img = new Image();
    var url = URL.createObjectURL(new Blob([standalone(svg)], { type: 'image/svg+xml' }));
    img.onload = function () {
      var c = make('canvas');
      c.width = vb.width * scale;
      c.height = vb.height * scale;
      var g = c.getContext('2d');
      g.fillStyle = '#ffffff';
      g.fillRect(0, 0, c.width, c.height);
      g.drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      c.toBlob(function (b) { if (b) download(b, fileName(fig, 'png')); });
    };
    img.src = url;
  }

  var open = null, scrim = null, opener = null;
  function closeMax() {
    if (!open) return;
    open.classList.remove('max');
    var b = open.querySelector('[data-act="max"]');
    if (b) { b.setAttribute('aria-pressed', 'false'); b.replaceChildren(icon('maximize')); }
    open.removeAttribute('role');
    open.removeAttribute('aria-modal');
    if (scrim) scrim.remove();
    document.body.classList.remove('fig-open');
    open = null;
    if (opener) opener.focus();
  }
  function openMax(fig, btn) {
    closeMax();
    open = fig;
    opener = btn;
    scrim = make('div', { 'class': 'fig-scrim' });
    scrim.addEventListener('click', closeMax);
    document.body.appendChild(scrim);
    document.body.classList.add('fig-open');
    fig.classList.add('max');
    fig.setAttribute('role', 'dialog');
    fig.setAttribute('aria-modal', 'true');
    btn.setAttribute('aria-pressed', 'true');
    btn.replaceChildren(icon('minimize'));
    btn.focus();
  }
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeMax(); });

  function toolButton(act, title, content, pressed) {
    var b = make('button', { type: 'button', 'data-act': act, title: title, 'aria-label': title });
    if (typeof content === 'string') b.textContent = content;
    else { b.appendChild(content); b.className = 'ib'; }
    if (pressed !== undefined) b.setAttribute('aria-pressed', pressed ? 'true' : 'false');
    return b;
  }

  $$('figure.fig').forEach(function (fig) {
    var svg = fig.querySelector('.rh-svg');
    var head = fig.querySelector('.fh');
    if (!svg || !head) return;
    var tools = make('div', { 'class': 'fig-tools', role: 'toolbar', 'aria-label': 'Chart tools' });
    var zoomed = head.querySelector('.zoomed');
    if (zoomed) tools.appendChild(zoomed);
    var axis = svg.dataset.y ? yAxis(fig, svg) : null;
    if (axis) {
      var st = prefs.charts[fig.id] || {};
      var logB = toolButton('log', 'Logarithmic y axis', 'Log', axis.kind() === 'log');
      var smB = toolButton('smooth', 'Smooth the lines with a moving average', 'Smooth', false);
      logB.addEventListener('click', function () {
        axis.set(axis.kind() === 'log' ? 'lin' : 'log', axis.smooth());
        logB.setAttribute('aria-pressed', axis.kind() === 'log' ? 'true' : 'false');
        remember();
      });
      smB.addEventListener('click', function () {
        axis.set(axis.kind(), !axis.smooth());
        smB.setAttribute('aria-pressed', axis.smooth() ? 'true' : 'false');
        remember();
      });
      // Only a departure from how the figure was drawn is kept, so a choice
      // made on one run does not override a scale another run needs.
      function remember() {
        if (axis.kind() === axis.drawn && !axis.smooth()) delete prefs.charts[fig.id];
        else prefs.charts[fig.id] = { y: axis.kind(), smooth: axis.smooth() };
        save();
      }
      if (st.y || st.smooth) {
        axis.set(st.y || axis.kind(), !!st.smooth);
        logB.setAttribute('aria-pressed', axis.kind() === 'log' ? 'true' : 'false');
        smB.setAttribute('aria-pressed', axis.smooth() ? 'true' : 'false');
      }
      if (!axis.canLog) logB.disabled = true;
      tools.appendChild(logB);
      tools.appendChild(smB);
    }
    var svgB = toolButton('svg', 'Download as SVG', 'SVG');
    svgB.addEventListener('click', function () {
      download(new Blob([standalone(svg)], { type: 'image/svg+xml' }), fileName(fig, 'svg'));
    });
    var pngB = toolButton('png', 'Download as PNG', 'PNG');
    pngB.addEventListener('click', function () { savePng(fig, svg); });
    var maxB = toolButton('max', 'Expand this chart', icon('maximize'), false);
    maxB.addEventListener('click', function () {
      if (open === fig) closeMax(); else openMax(fig, maxB);
    });
    tools.appendChild(svgB);
    tools.appendChild(pngB);
    tools.appendChild(maxB);
    head.appendChild(tools);
  });

  // -- a y axis that can be switched between linear and log ---------------
  // The figure is drawn in pixels, so every mark is read back into data
  // values once and placed again whenever the scale or the smoothing changes.
  function yAxis(fig, svg) {
    var spec = svg.dataset.y.split(',');
    var kind0 = spec[0], d0 = +spec[1], d1 = +spec[2], fmt = spec[3] || 'si';
    var plot = (svg.dataset.plot || '').split(',').map(Number);
    var top = plot[1], bottom = plot[1] + plot[3];
    var ticksBox = svg.querySelector('.rh-yticks');
    if (!(d1 > d0) || !ticksBox || plot.length < 4) return null;
    function toValue(kind, lo, hi, py) {
      var f = (bottom - py) / (bottom - top);
      if (kind === 'log') {
        var a = Math.log(lo) / Math.LN10, b = Math.log(hi) / Math.LN10;
        return Math.pow(10, a + f * (b - a));
      }
      return lo + f * (hi - lo);
    }
    function toPixel(kind, lo, hi, v) {
      var f;
      if (kind === 'log') {
        var a = Math.log(lo) / Math.LN10, b = Math.log(hi) / Math.LN10;
        f = (Math.log(Math.max(v, lo)) / Math.LN10 - a) / (b - a);
      } else {
        f = (v - lo) / (hi - lo);
      }
      return bottom - Math.max(0, Math.min(1, f)) * (bottom - top);
    }
    var read = function (py) { return toValue(kind0, d0, d1, py); };
    var paths = $$('.rh-geometry path', svg).map(function (p) {
      var d = p.getAttribute('d') || '';
      var nums = (d.match(/-?\d*\.?\d+(?:e[-+]?\d+)?/gi) || []).map(Number);
      var xs = [], vs = [];
      for (var i = 0; i + 1 < nums.length; i += 2) { xs.push(nums[i]); vs.push(read(nums[i + 1])); }
      var area = p.classList.contains('area');
      return { el: p, xs: xs, vs: vs, closed: /z\s*$/i.test(d), area: area,
               line: area || p.classList.contains('stroke') };
    });
    var dots = $$('.rh-points circle:not(.evt)', svg).map(function (c) {
      return { el: c, v: read(+c.getAttribute('cy')) };
    });
    var refs = $$('.rh-frame > line.ref', svg).map(function (l) {
      return { el: l, v: read(+l.getAttribute('y1')) };
    });
    var refLabels = $$('.rh-frame > text.ref-label', svg).map(function (t) {
      var y = +t.getAttribute('y'), best = null;
      refs.forEach(function (r) {
        var ry = +r.el.getAttribute('y1');
        if (!best || Math.abs(ry - y) < Math.abs(best.y - y)) best = { y: ry, r: r };
      });
      return best ? { el: t, ref: best.r, dy: y - best.y } : null;
    }).filter(Boolean);
    var samples = svg._rhSamples || [];
    var sampleV = samples.map(function (s) { return read(s[1]); });
    var positive = [];
    paths.forEach(function (p) {
      var n = p.area && p.closed ? p.vs.length - 2 : p.vs.length;
      for (var i = 0; i < n; i++) if (p.vs[i] > 0) positive.push(p.vs[i]);
    });
    dots.forEach(function (d) { if (d.v > 0) positive.push(d.v); });
    var floor = kind0 === 'log' ? d0 : (positive.length ? Math.min.apply(null, positive) * 0.8 : 0);
    var state = { kind: kind0, smooth: false };

    function smoothed(vs, n) {
      var w = Math.max(2, Math.round(n / 60)), out = [];
      for (var i = 0; i < n; i++) {
        var lo = Math.max(0, i - w), hi = Math.min(n - 1, i + w), s = 0;
        for (var j = lo; j <= hi; j++) s += vs[j];
        out.push(s / (hi - lo + 1));
      }
      return out.concat(vs.slice(n));
    }
    function fmtDur(v) {
      if (v < 10) return (Math.round(v * 100) / 100) + 's';
      var t = Math.round(v), d = Math.floor(t / 86400), h = Math.floor(t % 86400 / 3600);
      var m = Math.floor(t % 3600 / 60), s = t % 60;
      var p2 = function (n) { return (n < 10 ? '0' : '') + n; };
      if (d) return d + 'd ' + p2(h) + 'h';
      if (h) return h + 'h ' + p2(m) + 'm';
      if (m) return m + 'm ' + p2(s) + 's';
      return s + 's';
    }
    function fmtNum(v) {
      var a = Math.abs(v);
      if (a >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
      if (a >= 1e3) return (v / 1e3).toFixed(1).replace(/\.0$/, '') + 'k';
      return String(Number(v.toPrecision(3)));
    }
    function ticksFor(kind, lo, hi) {
      var out = [];
      if (kind === 'log') {
        var e0 = Math.floor(Math.log(lo) / Math.LN10), e1 = Math.ceil(Math.log(hi) / Math.LN10);
        var mults = e1 - e0 > 4 ? [1] : [1, 2, 5];
        for (var e = e0; e <= e1; e++) mults.forEach(function (m) {
          var v = m * Math.pow(10, e);
          if (v >= lo * 0.999 && v <= hi * 1.001) out.push(v);
        });
        return out;
      }
      var raw = (hi - lo) / 5, mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
      var step = [1, 2, 2.5, 5, 10].map(function (m) { return m * mag; })
        .filter(function (s) { return s >= raw; })[0];
      for (var v = Math.ceil(lo / step) * step; v <= hi + step * 1e-6; v += step) out.push(v);
      return out;
    }
    var NS = 'http://www.w3.org/2000/svg';
    function el(name, attrs, text) {
      var n = document.createElementNS(NS, name);
      for (var k in attrs) n.setAttribute(k, attrs[k]);
      if (text) n.textContent = text;
      return n;
    }
    function draw() {
      var kind = state.kind, lo = kind === 'log' ? floor : (kind0 === 'log' ? 0 : d0), hi = d1;
      var px = function (v) { return toPixel(kind, lo, hi, v).toFixed(1); };
      paths.forEach(function (p) {
        var n = p.area && p.closed ? p.vs.length - 2 : p.vs.length;
        var vs = state.smooth && p.line && n > 8 ? smoothed(p.vs, n) : p.vs;
        var d = '';
        for (var i = 0; i < p.xs.length; i++) d += (i ? ' L' : 'M') + p.xs[i] + ',' + px(vs[i]);
        p.el.setAttribute('d', d + (p.closed ? 'Z' : ''));
      });
      dots.forEach(function (d) { d.el.setAttribute('cy', px(d.v)); });
      refs.forEach(function (r) { var y = px(r.v); r.el.setAttribute('y1', y); r.el.setAttribute('y2', y); });
      refLabels.forEach(function (t) { t.el.setAttribute('y', (+px(t.ref.v) + t.dy).toFixed(1)); });
      samples.forEach(function (s, i) { s[1] = +px(sampleV[i]); });
      while (ticksBox.firstChild) ticksBox.removeChild(ticksBox.firstChild);
      var f = fmt === 'duration' ? fmtDur : fmtNum;
      ticksFor(kind, lo, hi).forEach(function (v) {
        var y = +px(v);
        ticksBox.appendChild(el('line', { 'class': 'grid', x1: plot[0], y1: y, x2: plot[0] + plot[2], y2: y }));
        ticksBox.appendChild(el('text', { 'class': 'tick', x: plot[0] - 9, y: (y + 3.7).toFixed(1),
          'text-anchor': 'end' }, f(v)));
      });
    }
    return {
      drawn: kind0,
      canLog: floor > 0,
      kind: function () { return state.kind; },
      smooth: function () { return state.smooth; },
      set: function (kind, smooth) {
        state.kind = kind === 'log' && floor > 0 ? 'log' : 'lin';
        state.smooth = !!smooth;
        draw();
      }
    };
  }

  // -- the customize panel ------------------------------------------------
  var wrap = document.querySelector('.prefs-wrap');
  if (!wrap) return;
  var btn = wrap.querySelector('.prefs-btn');
  var panel = wrap.querySelector('.prefs');

  function seg(title, key, options, fallback, after) {
    var row = make('div', { 'class': 'row' });
    var name = make('span', { id: 'pl-' + key }, title);
    var box = make('div', { 'class': 'seg', role: 'group', 'aria-labelledby': 'pl-' + key });
    var cur = root.getAttribute('data-' + key) || fallback;
    options.forEach(function (o) {
      var b = make('button', { type: 'button', 'aria-pressed': o[0] === cur ? 'true' : 'false' }, o[1]);
      if (o[2]) b.title = o[2];
      b.addEventListener('click', function () {
        setRoot(key, o[0], fallback);
        $$('button', box).forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
        if (after) after();
      });
      box.appendChild(b);
    });
    row.appendChild(name);
    row.appendChild(box);
    return row;
  }
  function list(title, items, kind, movable, after) {
    var frag = document.createDocumentFragment();
    frag.appendChild(make('h3', {}, title));
    var ul = make('ul', { 'class': 'plist' });
    function render() {
      ul.textContent = '';
      var off = prefs.hide[kind] || [];
      var cur = movable ? ordered(items(), kind) : items();
      cur.forEach(function (it, i) {
        var li = make('li');
        var lab = make('label');
        var box = make('input', { type: 'checkbox' });
        box.checked = off.indexOf(it.id) === -1;
        box.addEventListener('change', function () {
          var list = (prefs.hide[kind] || []).filter(function (x) { return x !== it.id; });
          if (!box.checked) list.push(it.id);
          prefs.hide[kind] = list;
          save();
          after();
        });
        lab.appendChild(box);
        lab.appendChild(document.createTextNode(it.name || label(it)));
        li.appendChild(lab);
        if (movable) {
          [['↑', -1, 'Move up'], ['↓', 1, 'Move down']].forEach(function (m) {
            var mv = make('button', { type: 'button', 'class': 'mv', title: m[2] + ': ' + (it.name || label(it)),
              'aria-label': m[2] + ': ' + (it.name || label(it)) }, m[0]);
            var j = i + m[1];
            mv.disabled = j < 0 || j >= cur.length;
            mv.addEventListener('click', function () {
              var ids = cur.map(function (x) { return x.id; });
              ids.splice(j, 0, ids.splice(i, 1)[0]);
              prefs.order[kind] = ids;
              save();
              after();
              render();
              var again = ul.children[j] && ul.children[j].querySelectorAll('.mv')[m[1] < 0 ? 0 : 1];
              if (again && !again.disabled) again.focus();
            });
            li.appendChild(mv);
          });
        }
        ul.appendChild(li);
      });
    }
    render();
    frag.appendChild(ul);
    return frag;
  }

  function build() {
    panel.textContent = '';
    panel.appendChild(make('h3', {}, 'Appearance'));
    panel.appendChild(seg('Density', 'density', [['comfortable', 'Comfy'], ['compact', 'Compact']],
                          'comfortable'));
    panel.appendChild(seg('Chart labels', 'labels',
                          [['s', 'S', 'Small'], ['m', 'M', 'Medium'], ['l', 'L', 'Large'], ['xl', 'XL', 'Extra large']],
                          'm'));
    if (document.querySelector('.toc')) {
      panel.appendChild(seg('Sidebar', 'side', [['show', 'Show'], ['hidden', 'Hide']], 'show', function () {
        if (sideBtn) sideBtn.setAttribute('aria-pressed', sideState() === 'show' ? 'true' : 'false');
      }));
    }
    if (document.querySelector('figure.fig')) {
      panel.appendChild(make('h3', {}, 'Charts'));
      if (figBox) {
        panel.appendChild(seg('Chart columns', 'cols', [['1', '1'], ['2', '2']], '1'));
      }
      panel.appendChild(seg('Captions', 'captions', [['show', 'Show'], ['hide', 'Hide']], 'show'));
      if (document.querySelector('.rh-svg .tick.sub')) {
        panel.appendChild(seg('Simulated time under the axis', 'simticks',
                              [['show', 'Show'], ['hide', 'Hide']], 'show'));
      }
    }
    if (checks.length) {
      panel.appendChild(make('h3', {}, 'Checks'));
      panel.appendChild(seg('Open on load', 'checks',
                            [['problems', 'Problems', 'Open warnings and problems only'],
                             ['all', 'All'], ['none', 'None']], 'problems', foldChecks));
    }
    if (sections().length > 1) {
      panel.appendChild(list('Sections', function () {
        return sections().map(function (s) { return { id: s.id, name: label(s), el: s }; });
      }, 'secs', true, arrange));
    }
    if (figures().length > 1) {
      panel.appendChild(list('Figures', function () {
        return figures().map(function (f) { return { id: f.id, name: label(f), el: f }; });
      }, 'figs', true, arrange));
    }
    if (runs) {
      panel.appendChild(list('Table columns', function () {
        return columns().filter(function (c) { return c.name !== 'run'; });
      }, 'cols', false, applyColumns));
    }
    var reset = make('button', { type: 'button', 'class': 'reset' }, 'Reset to defaults');
    reset.addEventListener('click', function () {
      try { localStorage.removeItem(KEY); } catch (e) {}
      location.reload();
    });
    panel.appendChild(reset);
  }

  function show(on) {
    if (on) build();
    panel.hidden = !on;
    btn.setAttribute('aria-expanded', on ? 'true' : 'false');
    var first = on && panel.querySelector('button[aria-pressed="true"], button');
    if (first) first.focus();
  }
  btn.addEventListener('click', function () { show(panel.hidden); });
  document.addEventListener('click', function (e) {
    if (!panel.hidden && !wrap.contains(e.target)) show(false);
  });
  panel.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { show(false); btn.focus(); }
  });
})();
""".replace("__KEY__", PREFS_KEY)
