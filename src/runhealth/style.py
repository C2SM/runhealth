"""One palette for the figures and the pages, defined once.

Light first, with a dark variant driven from the same tokens so a report
looks deliberate in either theme. Figures are rendered on the light ground;
the page dims them slightly in dark mode rather than shipping two copies.
"""

from __future__ import annotations

SURFACE = "#fcfcfb"
PANEL = "#f4f3ef"
INK = "#16150f"
MUTED = "#8a887f"
LABEL = "#52514c"
GRID = "#e2e1d9"
EDGE = "#c6c4b8"

# Verdict colours, reused by badges, table rows and bar fills.
OK = "#2f8f5b"
INFO = "#3d7fd6"
WARN = "#c98216"
FAIL = "#c8452f"
LEVEL_COLOR = {"ok": OK, "info": INFO, "warn": WARN, "fail": FAIL}

# Categorical series, in the order they should be used.
SERIES = ["#3d7fd6", "#c98216", "#2f8f5b", "#8b5cc7", "#c8452f", "#0f8c95", "#a6742a"]

# Phases are ordered stages, not categories, and a green phase would read as
# "this part was fine" when it may be exactly where the run hung. One hue.
PHASES = ["#7ea9dd", "#5b8ecb", "#3d75b6", "#2b5c96", "#234a79", "#1c3a5f", "#8fa4bb"]

RC = {
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "font.family": "sans-serif",
    "font.size": 9,
    "axes.edgecolor": EDGE,
    "axes.labelcolor": LABEL,
    "axes.titlesize": 10,
    "axes.titleweight": "bold",
    "axes.titlecolor": INK,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "axes.axisbelow": True,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelcolor": LABEL,
    "ytick.labelcolor": LABEL,
    "legend.frameon": False,
    "figure.autolayout": False,
}
