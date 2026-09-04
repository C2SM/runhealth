"""One palette for the figures and the pages, defined once.

The figures are SVG drawn with CSS classes rather than baked-in colours, so
the same markup serves the light theme, the dark theme and the print
stylesheet. That is what this module exists for: the token tables below are
emitted as custom properties into the page, and :data:`CHART_CSS` is the one
set of rules that reads them.

Every series colour clears 3:1 against its own background and every phase in
the ramp clears 4.5:1 against white, so the labels drawn inside a phase bar
stay legible without a second palette for dark mode.
"""

from __future__ import annotations

# Ordered stages, not categories. A green phase would read as "this part was
# fine" when it may be exactly where the run hung, so the ramp is one hue,
# dark enough throughout that white lettering on top of it stays readable.
PHASES = ["#3d75b6", "#35669f", "#2d5789", "#264a74", "#1f3d60", "#18314d", "#4b6b8c"]

# Categorical series, in the order they should be used.
SERIES_LIGHT = ["#3d7fd6", "#c98216", "#2f8f5b", "#8b5cc7", "#c8452f", "#0f8c95", "#a6742a"]
SERIES_DARK = ["#7cb0ef", "#e5a94c", "#64c48c", "#b18ce0", "#ef7a63", "#45b3bc", "#cfa055"]

LIGHT = {
    "bg": "#fcfcfb",
    "panel": "#ffffff",
    "panel-2": "#f5f4f0",
    "ink": "#16150f",
    "muted": "#75736b",
    "line": "#e2e1d9",
    "line-2": "#cecdc3",
    "ok": "#2f8f5b",
    "info": "#3d7fd6",
    "warn": "#c98216",
    "fail": "#c8452f",
    "grid": "#e8e7e0",
    "axis": "#c1bfb4",
    "tick": "#6a6862",
    "whisker": "#3f3e38",
    "shadow": "0 1px 2px rgba(20,18,10,.05), 0 4px 14px rgba(20,18,10,.04)",
}

DARK = {
    "bg": "#14150f",
    "panel": "#1c1e17",
    "panel-2": "#23251d",
    "ink": "#edece4",
    "muted": "#9d9b90",
    "line": "#32342a",
    "line-2": "#444639",
    "ok": "#64c48c",
    "info": "#7cb0ef",
    "warn": "#e5a94c",
    "fail": "#ef7a63",
    "grid": "#2a2c23",
    "axis": "#4c4e41",
    "tick": "#a8a69b",
    "whisker": "#c9c7bc",
    "shadow": "none",
}


def tokens(dark: bool = False) -> dict[str, str]:
    base = dict(DARK if dark else LIGHT)
    for i, color in enumerate(SERIES_DARK if dark else SERIES_LIGHT):
        base[f"s{i}"] = color
    for i, color in enumerate(PHASES):
        base[f"p{i}"] = color
    return base


def token_block(selector: str, dark: bool = False) -> str:
    body = " ".join(f"--{k}: {v};" for k, v in tokens(dark).items())
    return f"{selector} {{ {body} }}"


# Structural figure rules. Colour comes from the tokens above, so this text is
# identical in the page, in a standalone .svg file and on paper.
CHART_CSS = """
.rh-svg { width: 100%; height: auto; display: block; overflow: visible;
  font: 9px ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
.rh-svg .grid { stroke: var(--grid); stroke-width: 1; }
.rh-svg .ax-line { stroke: var(--axis); stroke-width: 1; }
.rh-svg .tick { fill: var(--tick); font-size: 8.5px; }
.rh-svg .ax-label { fill: var(--muted); font-size: 9px; }
.rh-svg .panel-title { fill: var(--ink); font-size: 10px; font-weight: 650; }
.rh-svg .row-label { fill: var(--muted); font-size: 8.5px; }
.rh-svg .val { fill: var(--tick); font-size: 8.5px; }
.rh-svg .in-bar { fill: #fff; font-size: 8.5px; font-weight: 650; }
.rh-svg .in-bar.dim { font-weight: 400; opacity: .85; }
.rh-svg .ref { stroke: var(--muted); stroke-width: 1; }
.rh-svg .dash { stroke-dasharray: 4 3; }
.rh-svg .ref-label { fill: var(--muted); font-size: 8.5px; }
.rh-svg .whisker { stroke: var(--whisker); stroke-width: 1.1; opacity: .75; }
.rh-svg .io-tick { stroke: var(--muted); stroke-width: 1.2; opacity: .7; }
.rh-svg .legend-text { fill: var(--muted); font-size: 9px; }

/* Paint modes. A class sets --c; these three decide what is done with it. */
.rh-svg .fill { fill: var(--c); stroke: none; }
.rh-svg .stroke { fill: none; stroke: var(--c); stroke-width: 1.6;
  stroke-linejoin: round; stroke-linecap: round; }
.rh-svg .area { fill: var(--c); stroke: none; opacity: .13; }
.rh-svg .range { fill: none; stroke: var(--c); stroke-width: 5;
  stroke-linecap: round; opacity: .6; }
.rh-svg .s0 { --c: var(--s0); } .rh-svg .s1 { --c: var(--s1); }
.rh-svg .s2 { --c: var(--s2); } .rh-svg .s3 { --c: var(--s3); }
.rh-svg .s4 { --c: var(--s4); } .rh-svg .s5 { --c: var(--s5); }
.rh-svg .s6 { --c: var(--s6); }
.rh-svg .p0 { --c: var(--p0); } .rh-svg .p1 { --c: var(--p1); }
.rh-svg .p2 { --c: var(--p2); } .rh-svg .p3 { --c: var(--p3); }
.rh-svg .p4 { --c: var(--p4); } .rh-svg .p5 { --c: var(--p5); }
.rh-svg .p6 { --c: var(--p6); }
.rh-svg .lv-ok { --c: var(--ok); } .rh-svg .lv-info { --c: var(--info); }
.rh-svg .lv-warn { --c: var(--warn); } .rh-svg .lv-fail { --c: var(--fail); }
.rh-svg .ink { --c: var(--ink); }
"""

# Interaction is layered on top, and only ever in a browser.
CHART_INTERACTION_CSS = """
.rh-svg .mark { transition: opacity .12s ease; }
.rh-svg .mark:hover, .rh-svg .mark:focus-visible { opacity: .8; }
.rh-svg .mark { cursor: default; }
.rh-svg .mark[data-line], .rh-svg .mark[data-href] { cursor: pointer; }
.rh-svg .mark:focus { outline: none; }
.rh-svg .mark:focus-visible { outline: 2px solid var(--ink); outline-offset: 1px; }
.rh-svg .legend-item { cursor: pointer; }
.rh-svg .legend-item[aria-pressed="false"] { opacity: .35; }
.rh-svg .legend-item:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
.rh-svg .series[hidden] { display: none; }
.rh-svg .cross { stroke: var(--ink); stroke-width: 1; opacity: .5; pointer-events: none; }
.rh-svg .cross-dot { fill: var(--ink); pointer-events: none; }
.rh-svg .peer { stroke: var(--info); stroke-width: 1.5; stroke-dasharray: 3 3;
  opacity: .8; pointer-events: none; }
.rh-svg .brush { fill: var(--ink); opacity: .1; pointer-events: none; }
@media (prefers-reduced-motion: reduce) {
  .rh-svg .mark { transition: none; }
}
"""


# What each figure class paints, as plain values. An inline SVG is not
# always reached by the page stylesheet -- WeasyPrint, and so the PDF output,
# treats it as its own document -- so every element also carries presentation
# attributes. A browser's CSS outranks a presentation attribute, which is why
# the theme still switches while the PDF still comes out in colour.
_PAINT: dict[str, str] = {}
for _i, _c in enumerate(SERIES_LIGHT):
    _PAINT[f"s{_i}"] = _c
for _i, _c in enumerate(PHASES):
    _PAINT[f"p{_i}"] = _c
_PAINT.update(
    {
        "lv-ok": LIGHT["ok"],
        "lv-info": LIGHT["info"],
        "lv-warn": LIGHT["warn"],
        "lv-fail": LIGHT["fail"],
        "ink": LIGHT["ink"],
    }
)

# Classes that paint themselves, without a colour token beside them.
_PLAIN: dict[str, dict[str, str]] = {
    "grid": {"stroke": LIGHT["grid"], "fill": "none"},
    "ax-line": {"stroke": LIGHT["axis"], "fill": "none"},
    "ref": {"stroke": LIGHT["muted"], "fill": "none"},
    "whisker": {"stroke": LIGHT["whisker"], "fill": "none"},
    "io-tick": {"stroke": LIGHT["muted"], "fill": "none"},
    "cross": {"stroke": LIGHT["ink"], "fill": "none"},
    "tick": {"fill": LIGHT["tick"], "font-size": "8.5px"},
    "val": {"fill": LIGHT["tick"], "font-size": "8.5px"},
    "row-label": {"fill": LIGHT["muted"], "font-size": "8.5px"},
    "ref-label": {"fill": LIGHT["muted"], "font-size": "8.5px"},
    "ax-label": {"fill": LIGHT["muted"], "font-size": "9px"},
    "legend-text": {"fill": LIGHT["muted"], "font-size": "9px"},
    "panel-title": {"fill": LIGHT["ink"], "font-size": "10px", "font-weight": "650"},
    "in-bar": {"fill": "#ffffff", "font-size": "8.5px", "font-weight": "650"},
    "rh-svg": {
        "font-size": "9px",
        "font-family": "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    },
}
_MODES = {
    "fill": lambda c: {"fill": c},
    "area": lambda c: {"fill": c, "opacity": "0.13"},
    "stroke": lambda c: {"stroke": c, "fill": "none", "stroke-width": "1.6"},
    "range": lambda c: {
        "stroke": c,
        "fill": "none",
        "stroke-width": "5",
        "stroke-linecap": "round",
        "opacity": "0.6",
    },
}


def svg_attributes(classes: str) -> dict[str, str]:
    """Presentation attributes matching what :data:`CHART_CSS` would paint."""
    parts = classes.split()
    out: dict[str, str] = {}
    for part in parts:
        if part in _PLAIN:
            out.update(_PLAIN[part])
    token = next((p for p in parts if p in _PAINT), None)
    mode = next((p for p in parts if p in _MODES), None)
    if token and mode:
        out.update(_MODES[mode](_PAINT[token]))
    elif token:
        out.update({"fill": _PAINT[token]})
    if "dash" in parts:
        out["stroke-dasharray"] = "4 3"
    return out


def print_overrides() -> str:
    """Literal colours for the print stylesheet.

    WeasyPrint's support for custom properties varies by version, and a PDF
    of grey rectangles would be worse than a slightly duller palette, so the
    print rules restate the light tokens as plain values.
    """
    rules = [
        f".rh-svg .{name} {{ fill: {color}; }} .rh-svg .{name}.stroke {{ stroke: {color}; }}"
        for name, color in (
            [(f"s{i}", c) for i, c in enumerate(SERIES_LIGHT)]
            + [(f"p{i}", c) for i, c in enumerate(PHASES)]
            + [
                ("lv-ok", LIGHT["ok"]),
                ("lv-info", LIGHT["info"]),
                ("lv-warn", LIGHT["warn"]),
                ("lv-fail", LIGHT["fail"]),
            ]
        )
    ]
    rules.append(".rh-svg .stroke { fill: none; } .rh-svg .area { opacity: .13; }")
    rules.append(f".rh-svg .grid {{ stroke: {LIGHT['grid']}; }}")
    rules.append(f".rh-svg .ax-line {{ stroke: {LIGHT['axis']}; }}")
    rules.append(f".rh-svg .tick, .rh-svg .val {{ fill: {LIGHT['tick']}; }}")
    rules.append(f".rh-svg .whisker {{ stroke: {LIGHT['whisker']}; }}")
    return "\n".join(rules)


def svg_stylesheet() -> str:
    """Everything a standalone ``.svg`` file needs to stand on its own."""
    return token_block(":root") + CHART_CSS
