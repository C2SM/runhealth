"""Draw SVG by hand.

The figures a run report needs -- a phase timeline, ranked bars carrying a
fastest-to-slowest whisker, the spread of a counter across network cards --
are shapes no charting library draws well, and a library large enough to
draw them would have to be fetched before the report could be read. Reports
are routinely opened on a login node with no route to the internet, so the
figures are plain SVG written straight into the page.

Colour lives in CSS classes rather than in ``fill`` attributes, so one
figure serves the light theme, the dark theme and the print stylesheet
without being drawn three times. Any element carrying ``data-tip`` becomes a
hover, focus and tap target; the tooltip engine lives in
:mod:`runhealth.report`.
"""

from __future__ import annotations

import html
import json
import math
from dataclasses import dataclass

from . import style

# Logical drawing width. The SVG is served with ``width: 100%``, so this is a
# coordinate system rather than a pixel size, and the report's own column
# width decides how large a figure ends up.
WIDTH = 900

# Tick steps that read as a duration rather than as an arbitrary number.
NICE_STEPS = [
    1,
    2,
    5,
    10,
    15,
    30,
    60,
    120,
    300,
    600,
    900,
    1800,
    3600,
    7200,
    10800,
    21600,
    43200,
    86400,
]


def esc(text: object) -> str:
    """Escape for an attribute or for text content.

    Newlines become character references rather than staying literal: a
    tooltip is written into an attribute, and an XML parser would otherwise
    normalise the line breaks away when a standalone ``.svg`` file is read.
    """
    return html.escape(str(text if text is not None else ""), quote=True).replace("\n", "&#10;")


def num(value: float) -> str:
    """Coordinates to two decimals, without a trailing ``.0``."""
    if math.isnan(value) or math.isinf(value):
        return "0"
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


def a(**kw) -> str:
    """Render attributes. ``cls`` becomes ``class``, ``_`` becomes ``-``.

    A class that names a colour also gets the matching presentation
    attributes, so a renderer that never reads the page stylesheet still
    draws the figure as intended. See :func:`runhealth.style.svg_attributes`.
    """
    if kw.get("cls"):
        for name, value in style.svg_attributes(kw["cls"]).items():
            kw.setdefault(name.replace("-", "_"), value)
    out = []
    for key, value in kw.items():
        if value is None or value is False or value == "":
            continue
        name = "class" if key == "cls" else key.replace("_", "-")
        if value is True:
            out.append(name)
        elif isinstance(value, float):
            out.append(f'{name}="{num(value)}"')
        else:
            out.append(f'{name}="{esc(value)}"')
    return " ".join(out)


def tag(name: str, body: str = "", **kw) -> str:
    head = f"<{name}" + (" " + a(**kw) if kw else "")
    return f"{head}>{body}</{name}>" if body else f"{head}/>"


# -- scales ---------------------------------------------------------------


@dataclass
class Scale:
    """Map a data interval onto a pixel interval."""

    d0: float
    d1: float
    r0: float
    r1: float

    def __call__(self, value: float) -> float:
        span = self.d1 - self.d0
        if not span:
            return self.r0
        return self.r0 + (value - self.d0) / span * (self.r1 - self.r0)


@dataclass
class LogScale:
    """As :class:`Scale`, on a base-10 log axis. Non-positive input clamps."""

    d0: float
    d1: float
    r0: float
    r1: float

    def __call__(self, value: float) -> float:
        lo, hi = math.log10(max(self.d0, 1e-9)), math.log10(max(self.d1, 1e-9))
        v = math.log10(max(value, 1e-9))
        if hi == lo:
            return self.r0
        return self.r0 + (v - lo) / (hi - lo) * (self.r1 - self.r0)


@dataclass
class SymLogScale:
    """Linear up to ``thresh``, logarithmic above it, starting at zero.

    Message counts per minute are mostly small with occasional bursts of
    thousands. A linear axis flattens the small values into the baseline and
    a log axis cannot show the zeros, which are the point of the plot.
    """

    d1: float
    r0: float
    r1: float
    thresh: float = 10.0
    d0: float = 0.0

    def _unit(self, value: float) -> float:
        t = max(self.thresh, 1.0)
        if value <= t:
            return max(value, 0.0) / t
        return 1.0 + math.log10(value / t)

    def __call__(self, value: float) -> float:
        top = self._unit(max(self.d1, self.thresh))
        if top <= 0:
            return self.r0
        return self.r0 + self._unit(value) / top * (self.r1 - self.r0)

    def ticks(self) -> list[float]:
        out = [0.0, self.thresh]
        v = self.thresh * 10
        while v <= self.d1 * 1.001:
            out.append(v)
            v *= 10
        return out


def nice_ticks(lo: float, hi: float, target: int = 6) -> list[float]:
    """Round tick positions covering ``lo`` to ``hi``, on a 1-2-5 ladder."""
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / max(target, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = next((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), 10 * mag)
    start = math.ceil(lo / step) * step
    out, v = [], start
    while v <= hi + step * 1e-6:
        out.append(round(v, 10))
        v += step
    return out or [lo, hi]


def log_ticks(lo: float, hi: float) -> list[float]:
    """Decade ticks, thinned to keep the axis readable over a wide range."""
    lo, hi = max(lo, 1e-9), max(hi, 1e-9)
    first, last = math.floor(math.log10(lo)), math.ceil(math.log10(hi))
    decades = list(range(int(first), int(last) + 1))
    stride = max(1, len(decades) // 7)
    return [10.0**d for d in decades[::stride]]


def time_ticks(span: float, target: int = 7) -> list[float]:
    """Tick positions on a wall-clock axis running from zero to ``span``."""
    want = span / max(target, 1)
    step = next((s for s in NICE_STEPS if s >= want), NICE_STEPS[-1])
    return [t for t in (i * step for i in range(int(span // step) + 2)) if t <= span]


def time_unit(span: float) -> tuple[str, float, int]:
    """Axis unit name, its size in seconds, and the decimals to show."""
    if span >= 7200:
        return "h", 3600.0, 1
    if span >= 120:
        return "min", 60.0, 0
    return "s", 1.0, 0


def si(value: float) -> str:
    """Compact number for an axis label: 1500 -> 1.5k."""
    for limit, suffix in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if abs(value) >= limit:
            trimmed = f"{value / limit:.1f}".rstrip("0").rstrip(".")
            return f"{trimmed}{suffix}"
    if value and abs(value) < 1:
        return f"{value:.2g}"
    return f"{value:,.0f}"


def truncate(text: str, chars: int) -> str:
    text = str(text)
    return text if len(text) <= chars else text[: chars - 1] + "…"


def label_width(text: str, size: float = 8.0) -> float:
    """Estimated rendered width. Used only to reserve axis room."""
    return len(str(text)) * size * 0.55


# -- the canvas -----------------------------------------------------------


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


class Chart:
    """A padded drawing surface with a plot area inside it.

    Content goes into one of three layers, because zooming the x axis has to
    stretch geometry without stretching the lettering on top of it:

    ``geometry``
        bars, lines and areas; transformed on zoom, strokes held constant.
    ``points``
        markers whose shape must survive a stretched axis, such as a circle
        that would otherwise become an ellipse; repositioned, never scaled.
    ``labels``
        text that sits inside the plot area; repositioned, never scaled.
    ``frame``
        axes, grid and legend; regenerated on zoom by the report's script.
    """

    def __init__(
        self,
        height: float,
        pad: tuple[float, float, float, float] = (54, 16, 18, 40),
        width: float = WIDTH,
        uid: str = "c",
    ):
        self.uid = uid
        self.width, self.height = width, height
        self.pad_l, self.pad_t, self.pad_r, self.pad_b = pad
        self.geometry: list[str] = []
        self.points: list[str] = []
        self.labels: list[str] = []
        self.frame: list[str] = []

    @property
    def plot(self) -> Box:
        return Box(
            self.pad_l,
            self.pad_t,
            max(1.0, self.width - self.pad_l - self.pad_r),
            max(1.0, self.height - self.pad_t - self.pad_b),
        )

    # -- primitives (each returns markup; callers append to a layer) --

    @staticmethod
    def rect(x, y, w, h, cls="", **kw) -> str:
        return tag(
            "rect",
            x=float(x),
            y=float(y),
            width=float(max(w, 0)),
            height=float(max(h, 0)),
            cls=cls,
            **kw,
        )

    @staticmethod
    def line(x1, y1, x2, y2, cls="", **kw) -> str:
        return tag("line", x1=float(x1), y1=float(y1), x2=float(x2), y2=float(y2), cls=cls, **kw)

    @staticmethod
    def path(points: list[tuple[float, float]], cls="", close=False, **kw) -> str:
        if not points:
            return ""
        d = "M" + " L".join(f"{num(x)},{num(y)}" for x, y in points) + ("Z" if close else "")
        return tag("path", d=d, cls=cls, **kw)

    @staticmethod
    def steps(points: list[tuple[float, float]], cls="", **kw) -> str:
        """A step-mid line, for counts that belong to a bucket not a moment."""
        if not points:
            return ""
        d = [f"M{num(points[0][0])},{num(points[0][1])}"]
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            mid = (x0 + x1) / 2
            d.append(f"L{num(mid)},{num(y0)} L{num(mid)},{num(y1)} L{num(x1)},{num(y1)}")
        return tag("path", d=" ".join(d), cls=cls, **kw)

    @staticmethod
    def circle(cx, cy, r, cls="", **kw) -> str:
        return tag("circle", cx=float(cx), cy=float(cy), r=float(r), cls=cls, **kw)

    @staticmethod
    def text(x, y, body: str, cls="", **kw) -> str:
        return tag("text", esc(body), x=float(x), y=float(y), cls=cls, **kw)

    # -- axes --

    def x_axis(
        self,
        scale: Scale | LogScale,
        ticks: list[float],
        fmt,
        label: str = "",
        grid: bool = True,
        box: Box | None = None,
    ) -> None:
        p = box or self.plot
        self.frame.append(self.line(p.x, p.bottom, p.right, p.bottom, cls="ax-line"))
        parts = []
        for t in ticks:
            x = scale(t)
            if x < p.x - 0.5 or x > p.right + 0.5:
                continue
            if grid:
                parts.append(self.line(x, p.y, x, p.bottom, cls="grid"))
            parts.append(self.line(x, p.bottom, x, p.bottom + 4, cls="ax-line"))
            parts.append(self.text(x, p.bottom + 15, fmt(t), cls="tick", text_anchor="middle"))
        self.frame.append(tag("g", "".join(parts), cls="rh-xticks"))
        if label:
            self.frame.append(
                self.text(
                    p.x + p.w / 2,
                    p.bottom + 31,
                    label,
                    cls="ax-label",
                    text_anchor="middle",
                )
            )

    def y_axis(
        self,
        scale: Scale | LogScale,
        ticks: list[float],
        fmt,
        label: str = "",
        grid: bool = True,
        box: Box | None = None,
    ) -> None:
        p = box or self.plot
        for t in ticks:
            y = scale(t)
            if y < p.y - 0.5 or y > p.bottom + 0.5:
                continue
            if grid:
                self.frame.append(self.line(p.x, y, p.right, y, cls="grid"))
            self.frame.append(self.text(p.x - 7, y + 3, fmt(t), cls="tick", text_anchor="end"))
        if label:
            self.frame.append(
                self.text(
                    0,
                    0,
                    label,
                    cls="ax-label",
                    text_anchor="middle",
                    transform=f"translate(11,{num(p.y + p.h / 2)}) rotate(-90)",
                )
            )

    def y_categories(self, rows: list[tuple[float, str]], chars: int = 40) -> None:
        """Left-hand category labels for a horizontal bar chart."""
        for y, text in rows:
            self.frame.append(
                self.text(
                    self.plot.x - 8,
                    y + 3,
                    truncate(text, chars),
                    cls="tick",
                    text_anchor="end",
                )
            )

    def legend(self, entries: list[tuple[str, str]], y: float | None = None) -> None:
        """Clickable legend. Each entry is ``(css class, text)``."""
        p = self.plot
        x = p.x
        y = self.pad_t - 5 if y is None else y
        for i, (cls, text) in enumerate(entries):
            self.frame.append(
                tag(
                    "g",
                    tag(
                        "rect", x=float(x), y=float(y - 7), width=9.0, height=9.0, cls=f"{cls} fill"
                    )
                    + tag(
                        "text",
                        esc(text),
                        x=float(x + 13),
                        y=float(y + 1),
                        cls="legend-text",
                    ),
                    cls="legend-item",
                    data_series=str(i),
                    tabindex="0",
                    role="button",
                    aria_pressed="true",
                    aria_label=f"toggle {text}",
                )
            )
            x += 26 + label_width(text, 9.5)

    # -- output --

    def render(
        self,
        aria: str,
        desc: str = "",
        zoom: bool = False,
        **data,
    ) -> str:
        """The complete ``<svg>`` element."""
        p = self.plot
        clip = tag(
            "clipPath",
            self.rect(p.x, p.y - 4, p.w, p.h + 8),
            id=f"clip-{self.uid}",
        )
        layers = [
            ("rh-geometry", self.geometry),
            ("rh-points", self.points),
            ("rh-labels", self.labels),
        ]
        inner = "".join(
            tag("g", "\n".join(content), cls=name, clip_path=f"url(#clip-{self.uid})")
            for name, content in layers
            if content
        )
        body = (
            tag("title", esc(aria))
            + (tag("desc", esc(desc)) if desc else "")
            + tag("defs", clip)
            + tag("g", "\n".join(self.frame), cls="rh-frame")
            + inner
        )
        attributes = {
            "viewBox": f"0 0 {num(self.width)} {num(self.height)}",
            "width": num(self.width),
            "height": num(self.height),
            "cls": "rh-svg",
            "role": "img",
            "aria_label": aria,
            "preserveAspectRatio": "xMidYMid meet",
            "data_plot": f"{num(p.x)},{num(p.y)},{num(p.w)},{num(p.h)}",
            "data_zoom": "1" if zoom else None,
        }
        attributes.update({f"data_{k}": v for k, v in data.items() if v is not None})
        return tag("svg", body, **attributes)


def pack(value) -> str:
    """Compact JSON for a data attribute."""
    return json.dumps(value, separators=(",", ":"))
