"""Figures for a run report, drawn as SVG.

Each function answers one question and returns ``None`` when the log does not
carry what it needs, so a report built from the generic profile simply has
fewer figures rather than failing.

The figures are interactive in a browser: every mark carries the text of its
own tooltip, the charts sharing a wall-clock axis mark the same instant when
one of them is hovered, and the long ones can be brushed to zoom. None of
that is needed to read them. The markup is complete before any script runs,
which is what lets one figure serve the page, the print stylesheet and the
PDF.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import style, svg
from .extract import RunLog
from .health import Assessment, counter_rows
from .logfile import format_duration, format_stamp

# Above this many points the drawn line is decimated per pixel column, which
# keeps a spike visible while the file stays a sensible size.
MAX_DRAWN_POINTS = 2400
# Samples backing the hover crosshair. Thinned separately from the line.
MAX_HOVER_SAMPLES = 1500


@dataclass
class Figure:
    key: str
    title: str
    caption: str = ""
    note: str = ""
    svg: str = ""
    href: str = ""


def _dur(seconds: float) -> str:
    return format_duration(seconds) or "0s"


def _time_fmt(span: float):
    """A tick formatter for a wall-clock axis, plus the unit it labels."""
    unit, size, decimals = svg.time_unit(span)
    return unit, lambda t: f"{t / size:.{decimals}f}"


def _decimate(points: list[tuple[float, float]], columns: float) -> list[tuple[float, float]]:
    """Keep the extremes of each pixel column, so spikes survive thinning."""
    if len(points) <= MAX_DRAWN_POINTS:
        return points
    buckets: dict[int, list[tuple[float, float]]] = {}
    for x, y in points:
        buckets.setdefault(int(x), []).append((x, y))
    out: list[tuple[float, float]] = []
    for key in sorted(buckets):
        column = buckets[key]
        lo = min(column, key=lambda p: p[1])
        hi = max(column, key=lambda p: p[1])
        out += [column[0]] if lo is hi else sorted({lo, hi}, key=lambda p: p[0])
    return out


def _thin(items: list, limit: int) -> list:
    if len(items) <= limit:
        return items
    stride = len(items) // limit + 1
    return items[::stride]


def _tip(*lines: str) -> str:
    return "\n".join(line for line in lines if line)


def _aria(text: str) -> str:
    return text.replace("\n", ". ")


def _mark(cls: str, tip: str, **kw) -> dict:
    """Attributes shared by every hoverable shape.

    ``tabindex`` is what makes the tooltip reachable without a pointer; the
    skill's own rule is that hover must never be the only way to a fact.
    """
    return {
        "cls": f"{cls} mark",
        "data_tip": tip,
        "tabindex": "0",
        "role": "img",
        "aria_label": _aria(tip),
        **kw,
    }


# -- figures --------------------------------------------------------------


def phase_timeline(log: RunLog, a: Assessment, uid: str) -> Figure | None:
    if not a.phases or log.first_wall is None:
        return None
    t0 = log.first_wall
    total = log.wall_seconds or 1.0
    unit, fmt = _time_fmt(total)
    ch = svg.Chart(height=188, pad=(64, 20, 20, 46), uid=uid)
    p = ch.plot
    x = svg.Scale(0, total, p.x, p.right)
    lanes = {"silence": (p.y + 2, 13), "phase": (p.y + 32, 38), "output": (p.y + 86, 12)}
    used = {"phase"}

    y_ph, h_ph = lanes["phase"]
    for i, ph in enumerate(a.phases):
        x0, w = x(ph.start - t0), max(x(ph.end - t0) - x(ph.start - t0), 1.0)
        tip = _tip(
            ph.name,
            f"{_dur(ph.seconds)}  ({ph.seconds / total * 100:.0f}% of the wall clock)",
            f"starts {format_stamp(ph.start)}",
        )
        ch.geometry.append(
            ch.rect(x0, y_ph, w, h_ph, rx=2.0, **_mark(f"p{i % len(style.PHASES)} fill", tip))
        )
        if w > 56:
            middle = x0 + w / 2
            ch.labels.append(
                ch.text(
                    middle,
                    y_ph + 16,
                    svg.truncate(ph.name, int(w / 4.9)),
                    cls="in-bar",
                    text_anchor="middle",
                )
            )
            ch.labels.append(
                ch.text(middle, y_ph + 28, _dur(ph.seconds), cls="in-bar dim", text_anchor="middle")
            )

    stall = float(log.threshold("stall_seconds", 300))
    y_gap, h_gap = lanes["silence"]
    shown = 0
    for g in log.gaps:
        if g.seconds < max(stall * 0.2, total * 0.02) or shown >= 5:
            continue
        x0, w = x(g.start - t0), max(x(g.end - t0) - x(g.start - t0), 1.5)
        tip = _tip(
            f"{_dur(g.seconds)} with no output",
            f"{format_stamp(g.start)} to {format_stamp(g.end)}",
            f"last line: {svg.truncate(g.before, 90)}" if g.before else "",
            f"line {g.line:,} of the log" if g.line else "",
        )
        ch.geometry.append(
            ch.rect(
                x0, y_gap, w, h_gap, rx=1.5, **_mark("lv-fail fill", tip, data_line=g.line or None)
            )
        )
        if w > 34:
            ch.labels.append(
                ch.text(x0 + w / 2, y_gap + 10, _dur(g.seconds), cls="in-bar", text_anchor="middle")
            )
        used.add("silence")
        shown += 1

    y_io = lanes["output"][0] + 6
    seen: set[int] = set()
    for name, series in log.series.items():
        if log.series_roles.get(name) != "io":
            continue
        for record in series:
            if record.get("wall") is None or len(seen) > 400:
                continue
            column = int(x(record["wall"] - t0))
            if column in seen:
                continue
            seen.add(column)
            used.add("output")
            ch.geometry.append(ch.line(column, y_io - 5, column, y_io + 5, cls="io-tick"))

    for name, (y, h) in lanes.items():
        if name in used:
            ch.frame.append(
                ch.text(p.x - 8, y + h / 2 + 3, name, cls="row-label", text_anchor="end")
            )

    ch.x_axis(
        x,
        svg.time_ticks(total),
        fmt,
        f"wall clock since the first stamped line ({unit})",
    )
    aria = f"Timeline of {len(a.phases)} phase(s) over {_dur(total)}" + (
        f", with {shown} stretch(es) of silence marked above" if shown else ""
    )
    return Figure(
        key="timeline",
        title="Run timeline",
        note=_dur(total),
        caption=(
            "Phases between the markers the profile defines. Red bars above the timeline "
            "are stretches with no output at all; a wide one is where a run hangs. Ticks "
            "below mark output and checkpoint writes. Drag across the chart to zoom."
        ),
        svg=ch.render(aria, zoom=True, xdomain=f"0,{svg.num(total)}", xfmt="duration", time="1"),
    )


def progress_rate(log: RunLog, a: Assessment, uid: str) -> Figure | None:
    if len(a.intervals) < 4:
        return None
    steps = [record.get("step") or n for n, record in enumerate(a.intervals)]
    seconds = [record["seconds"] for record in a.intervals]
    median = a.stats.get("interval_median") or 0.0
    factor = float(log.threshold("outlier_factor", 3))
    ch = svg.Chart(height=268, pad=(60, 24, 20, 52), uid=uid)
    p = ch.plot
    x = svg.Scale(min(steps), max(steps), p.x, p.right)
    # One slow first step (kernel compilation, cache warm-up) would otherwise
    # flatten the rest of the run into a straight line.
    if median > 0 and max(seconds) > 20 * median:
        floor = min((v for v in seconds if v > 0), default=1.0)
        y = svg.LogScale(floor * 0.8, max(seconds) * 1.3, p.bottom, p.y)
        y_ticks = svg.log_ticks(y.d0, y.d1)
        y_fmt = _dur
    else:
        y = svg.Scale(0, max(seconds) * 1.14 or 1.0, p.bottom, p.y)
        y_ticks = svg.nice_ticks(0, y.d1, 5)
        y_fmt = _dur

    points = [(x(s), y(v)) for s, v in zip(steps, seconds)]
    drawn = _decimate(points, p.w)
    ch.geometry.append(
        ch.path(
            drawn + [(drawn[-1][0], p.bottom), (drawn[0][0], p.bottom)], cls="s0 area", close=True
        )
    )
    ch.geometry.append(ch.path(drawn, cls="s0 stroke", vector_effect="non-scaling-stroke"))

    if median:
        y_median = y(median)
        ch.frame.append(ch.line(p.x, y_median, p.right, y_median, cls="ref dash"))
        ch.frame.append(
            ch.text(
                p.right - 3,
                y_median - 5,
                f"median {_dur(median)}",
                cls="ref-label",
                text_anchor="end",
            )
        )

    label = log.setting("progress_label", "events")
    hot = [
        (px, py, step, value)
        for (px, py), step, value in zip(points, steps, seconds)
        if median and value > factor * median
    ]
    for px, py, step, value in _thin(hot, 120):
        tip = _tip(
            f"{label} {step:,}",
            f"{_dur(value)} between reports",
            f"{value / median:.1f}x the median",
        )
        ch.points.append(ch.circle(px, py, 3.4, **_mark("lv-warn fill", tip)))

    t0 = log.first_wall or 0.0
    samples = []
    for (px, py), record, step, value in _thin(
        list(zip(points, a.intervals, steps, seconds)), MAX_HOVER_SAMPLES
    ):
        tip = _tip(
            f"{label} {step:,}",
            f"{_dur(value)} between reports",
            f"{value / median:.2f}x the median" if median else "",
            (
                f"model time advanced {_dur(record['model_seconds'])}"
                if record.get("model_seconds")
                else ""
            ),
        )
        samples.append([round(px, 1), round(py, 1), round(record["wall"] - t0, 1), tip])

    ch.x_axis(x, svg.nice_ticks(min(steps), max(steps), 7), lambda v: svg.si(v), label)
    ch.y_axis(y, y_ticks, y_fmt, "wall time per report")
    rate = a.stats.get("sypd")
    return Figure(
        key="progress",
        title="Progress rate",
        note=(
            f"{rate:.2f} {log.setting('throughput_label', 'rate')}"
            if rate
            else f"{len(a.intervals):,} reports"
        ),
        caption=(
            "Wall time between successive progress reports. A flat line is a healthy "
            "run; spikes are output, checkpointing or a transient stall, and a rising "
            "trend means the run is degrading. Hover for a single report, drag to zoom."
        ),
        svg=ch.render(
            f"Wall time between {len(a.intervals):,} progress reports, median {_dur(median)}",
            zoom=True,
            xdomain=f"{min(steps)},{max(steps)}",
            xfmt="si",
            samples=svg.pack(samples),
            time="1",
        ),
    )


def top_gaps(log: RunLog, a: Assessment, uid: str) -> Figure | None:
    gaps = [g for g in log.gaps if g.seconds >= 1.0][:10]
    if len(gaps) < 2:
        return None
    stall = float(log.threshold("stall_seconds", 300))
    row = 26
    ch = svg.Chart(height=row * len(gaps) + 66, pad=(300, 14, 70, 46), uid=uid)
    p = ch.plot
    x = svg.Scale(0, max(g.seconds for g in gaps), p.x, p.right)
    labels = []
    for i, g in enumerate(gaps):
        y = p.y + i * row
        level = "lv-fail" if g.seconds >= stall else "s0"
        tip = _tip(
            f"{_dur(g.seconds)} with no output",
            f"{format_stamp(g.start)} to {format_stamp(g.end)}",
            f"last line: {svg.truncate(g.before, 110)}" if g.before else "",
            f"next line: {svg.truncate(g.after, 110)}" if g.after else "",
            f"line {g.line:,} of the log" if g.line else "",
        )
        ch.geometry.append(
            ch.rect(
                p.x,
                y,
                x(g.seconds) - p.x,
                row - 9,
                rx=2.0,
                **_mark(f"{level} fill", tip, data_line=g.line or None),
            )
        )
        ch.frame.append(
            ch.text(p.right + 6, y + row / 2 - 1, _dur(g.seconds), cls="val", text_anchor="start")
        )
        labels.append((y + (row - 9) / 2, g.before or "(start of log)"))
    ch.y_categories(labels, chars=48)
    unit, fmt = _time_fmt(max(g.seconds for g in gaps))
    ch.x_axis(x, svg.nice_ticks(0, x.d1, 6), fmt, f"silence ({unit})")
    return Figure(
        key="gaps",
        title="Longest silences",
        note=f"{len(gaps)} shown",
        caption=(
            f"Each bar is a stretch with no output. Red marks anything past the "
            f"{_dur(stall)} stall threshold. The label is the last thing written before "
            "the silence, which is where to start looking."
        ),
        svg=ch.render(f"The {len(gaps)} longest stretches of silence in the log"),
    )


def timer_breakdown(log: RunLog, a: Assessment, uid: str) -> Figure | None:
    picks = []
    for group in a.timers:
        if len(group.rows) <= 1:
            continue
        rows = sorted(
            (r for r in group.rows if r.depth == 1 and r.total > 0), key=lambda r: -r.total
        )[:9]
        if rows:
            picks.append((group, rows))
    if not picks:
        return None
    row, head, foot = 24, 28, 50
    heights = [head + row * len(rows) + foot for _, rows in picks]
    ch = svg.Chart(height=sum(heights) + 6, pad=(232, 6, 62, 6), uid=uid)
    top = 6
    for (group, rows), height in zip(picks, heights):
        box = svg.Box(ch.pad_l, top + head, ch.width - ch.pad_l - ch.pad_r, row * len(rows))
        biggest = max(r.maximum for r in rows) or 1.0
        x = svg.Scale(0, biggest * 1.02, box.x, box.right)
        ch.frame.append(
            ch.text(
                8,
                top + 16,
                f"{group.title}   {group.root} = {_dur(group.root_seconds)}",
                cls="panel-title",
            )
        )
        labels = []
        for i, r in enumerate(rows):
            y = box.y + i * row
            middle = y + (row - 8) / 2
            tip = _tip(
                r.label,
                f"{_dur(r.total)} average across ranks  ({r.share * 100:.1f}% of {group.root})",
                f"fastest rank {_dur(r.minimum)}, slowest {_dur(r.maximum)}",
                f"spread {r.imbalance:.2f}x" if r.imbalance else "",
                f"slowest rank {int(r.max_rank)}" if r.max_rank is not None else "",
                f"{int(r.calls):,} calls" if r.calls else "",
            )
            ch.geometry.append(
                ch.rect(box.x, y, x(r.total) - box.x, row - 8, rx=2.0, **_mark("s0 fill", tip))
            )
            ch.geometry.append(ch.line(x(r.minimum), middle, x(r.maximum), middle, cls="whisker"))
            for edge in (r.minimum, r.maximum):
                ch.geometry.append(ch.line(x(edge), middle - 4, x(edge), middle + 4, cls="whisker"))
            ch.frame.append(
                ch.text(
                    box.right + 6,
                    middle + 3,
                    f"{r.share * 100:.0f}%",
                    cls="val",
                    text_anchor="start",
                )
            )
            labels.append((middle, r.label))
        ch.y_categories(labels, chars=38)
        unit, fmt = _time_fmt(biggest)
        ch.x_axis(x, svg.nice_ticks(0, x.d1, 5), fmt, f"average across ranks ({unit})", box=box)
        top += height
    return Figure(
        key="timers",
        title="Where the time went",
        note=f"{len(picks)} rank group(s)",
        caption=(
            "Top-level timers per rank group. The bar is the average across ranks and "
            "the whisker spans fastest to slowest, so a long whisker is imbalance."
        ),
        svg=ch.render("Top-level timer totals per rank group, with per-rank spread"),
    )


def imbalance(log: RunLog, a: Assessment, uid: str) -> Figure | None:
    floor = float(log.threshold("timer_share_floor", 0.05))
    rows = [
        (r, g)
        for g in a.timers
        for r in g.rows
        if r.imbalance and r.share >= floor and r.label != g.root
    ]
    if len(rows) < 2:
        return None
    rows.sort(key=lambda pair: -(pair[0].imbalance or 0))
    rows = rows[:12]
    warn = float(log.threshold("imbalance_warn", 1.25))
    fail = float(log.threshold("imbalance_fail", 2.0))
    row = 25
    ch = svg.Chart(height=row * len(rows) + 62, pad=(214, 14, 76, 44), uid=uid)
    p = ch.plot
    worst = max(r.imbalance for r, _ in rows)
    x = svg.Scale(0, worst * 1.06, p.x, p.right)
    labels = []
    for i, (r, group) in enumerate(rows):
        y = p.y + i * row
        ratio = r.imbalance or 0.0
        level = "lv-warn" if ratio >= fail else "lv-info" if ratio >= warn else "lv-ok"
        rank = f", on rank {int(r.max_rank)}" if r.max_rank is not None else ""
        tip = _tip(
            r.label,
            f"slowest rank took {ratio:.2f}x the fastest{rank}",
            f"{_dur(r.minimum)} to {_dur(r.maximum)}",
            f"{r.share * 100:.1f}% of {group.root}",
        )
        ch.geometry.append(
            ch.rect(p.x, y, x(ratio) - p.x, row - 9, rx=2.0, **_mark(f"{level} fill", tip))
        )
        ch.frame.append(
            ch.text(
                p.right + 6,
                y + row / 2 - 1,
                f"{ratio:.1f}x{rank.replace(', on ', ' ')}",
                cls="val",
                text_anchor="start",
            )
        )
        labels.append((y + (row - 9) / 2, r.label))
    ch.y_categories(labels, chars=34)
    ch.frame.append(ch.line(x(1.0), p.y, x(1.0), p.bottom, cls="ref"))
    ch.x_axis(x, svg.nice_ticks(0, x.d1, 6), lambda v: f"{v:.1f}x", "slowest rank / fastest rank")
    return Figure(
        key="imbalance",
        title="Load imbalance",
        note=f"worst {worst:.1f}x",
        caption=(
            "How much longer the slowest rank spent in each timer than the fastest. "
            "A ratio on a wait or synchronisation timer measures imbalance created "
            f"somewhere else. Only timers holding more than {floor * 100:.0f}% of the "
            "run are shown."
        ),
        svg=ch.render(f"Load imbalance for {len(rows)} timers, worst {worst:.1f}x"),
    )


def warning_rate(log: RunLog, a: Assessment, uid: str) -> Figure | None:
    live = {name: g for name, g in log.groups.items() if g.total and g.bins}
    if not live:
        return None
    families = sorted(live.items(), key=lambda kv: -kv[1].total)[:5]
    span = int((log.wall_seconds or 60.0) // 60) + 1
    ch = svg.Chart(height=258, pad=(52, 40, 18, 50), uid=uid)
    left = svg.Box(52, 40, 488, 258 - 40 - 50)
    right = svg.Box(626, 40, 256, left.h)

    peak = max(max(g.bins.get(str(m), 0) for m in range(span)) for _, g in families) or 1
    x = svg.Scale(0, max(span - 1, 1), left.x, left.right)
    y = svg.SymLogScale(d1=peak * 1.1, r0=left.bottom, r1=left.y, thresh=10.0)
    for i, (_, group) in enumerate(families):
        # Minutes with no message are zeros; without them the line would jump
        # across a quiet stretch and read as continuous activity.
        counts = [group.bins.get(str(m), 0) for m in range(span)]
        points = [(x(m), y(c)) for m, c in enumerate(counts)]
        body = svg.tag(
            "path",
            cls=f"s{i % 7} area",
            d=(
                f"M{svg.num(points[0][0])},{svg.num(left.bottom)} "
                + " ".join(f"L{svg.num(px)},{svg.num(py)}" for px, py in points)
                + f" L{svg.num(points[-1][0])},{svg.num(left.bottom)} Z"
            ),
        ) + ch.steps(points, cls=f"s{i % 7} stroke", vector_effect="non-scaling-stroke")
        ch.geometry.append(
            svg.tag("g", body, cls="series", data_series=str(i), aria_label=group.label)
        )
    ch.legend(
        [(f"s{i % 7}", f"{g.label} ({g.total:,})") for i, (_, g) in enumerate(families)], y=22
    )
    ch.y_axis(y, y.ticks(), svg.si, "lines per minute", box=left)
    ch.x_axis(
        x, svg.nice_ticks(0, span - 1, 7), svg.si, "minutes since the first stamped line", box=left
    )

    samples = []
    busiest = families[0][1]
    for minute in range(span):
        rows = [f"minute {minute}"] + [
            f"{g.label}: {g.bins.get(str(minute), 0):,}" for _, g in families
        ]
        samples.append(
            [
                round(x(minute), 1),
                round(y(busiest.bins.get(str(minute), 0)), 1),
                minute * 60.0,
                "\n".join(rows),
            ]
        )

    nodes = sorted(busiest.nodes.items(), key=lambda kv: -kv[1])[:12]
    if nodes:
        row = min(right.h / max(len(nodes), 1), 22.0)
        nx = svg.Scale(0, max(c for _, c in nodes) * 1.04, right.x, right.right)
        ch.frame.append(
            ch.text(right.x - 66, right.y - 8, f"nodes: {busiest.label}", cls="panel-title")
        )
        labels = []
        for i, (node, count) in enumerate(nodes):
            y_node = right.y + i * row
            tip = _tip(node, f"{count:,} lines of {busiest.label}")
            ch.geometry.append(
                ch.rect(
                    right.x,
                    y_node + 1,
                    nx(count) - right.x,
                    max(row - 4, 3),
                    rx=1.5,
                    **_mark("s0 fill", tip),
                )
            )
            labels.append((y_node + row / 2 - 3, node))
        for y_label, text in labels:
            ch.frame.append(
                ch.text(
                    right.x - 7, y_label + 3, svg.truncate(text, 13), cls="tick", text_anchor="end"
                )
            )
        ch.x_axis(nx, svg.nice_ticks(0, nx.d1, 3), svg.si, "lines", box=right)

    return Figure(
        key="warnings",
        title="Message rate",
        note=f"{sum(g.total for _, g in families):,} lines",
        caption=(
            "How message families are distributed over the run, and which nodes "
            "produce them. A burst that lines up with a slow stretch in the progress "
            "plot points at the network rather than the code. Click a legend entry to "
            "hide that family."
        ),
        svg=ch.render(
            f"Message rate for {len(families)} families over {span} minutes",
            samples=svg.pack(samples),
            time="1",
            xbox=f"{svg.num(left.x)},{svg.num(left.y)},{svg.num(left.w)},{svg.num(left.h)}",
        ),
    )


def counter_spread(log: RunLog, a: Assessment, uid: str) -> Figure | None:
    counters, _ = counter_rows(log)
    if counters is None or not counters.rows:
        return None
    columns = log.setting("counter_columns", {}) or {}
    c_min = columns.get("min", "Min")
    c_mean = columns.get("mean", "Mean")
    c_max = columns.get("max", "Max")
    rows = [
        r for r in counters.rows if r.values.get(c_max, 0) > 0 and r.values.get(c_min) is not None
    ]
    if len(rows) < 3:
        return None
    rows = sorted(rows, key=lambda r: -(r.values[c_max] / max(r.values[c_min], 1.0)))[:14]
    row = 25
    ch = svg.Chart(height=row * len(rows) + 64, pad=(268, 14, 66, 48), uid=uid)
    p = ch.plot
    lows = [max(r.values.get(c_min, 0.0), 0.5) for r in rows]
    highs = [max(r.values.get(c_max, 0.0), lo) for r, lo in zip(rows, lows)]
    x = svg.LogScale(min(lows) * 0.7, max(highs) * 1.4, p.x, p.right)
    labels = []
    for i, (r, lo, hi) in enumerate(zip(rows, lows, highs)):
        y = p.y + i * row + (row - 9) / 2
        mean = max(r.values.get(c_mean, lo), 0.5)
        spread = hi / lo
        level = "lv-warn" if spread > 20 else "s0"
        tip = _tip(
            r.label,
            f"lowest {svg.si(lo)}, mean {svg.si(mean)}, highest {svg.si(hi)}",
            f"{spread:.0f}x between the quietest and the busiest card",
        )
        ch.geometry.append(
            svg.tag("line", x1=x(lo), y1=y, x2=x(hi), y2=y, **_mark(f"{level} range", tip))
        )
        ch.geometry.append(ch.circle(x(mean), y, 3.0, cls="ink fill"))
        ch.frame.append(
            ch.text(p.right + 6, y + 3, f"{spread:.0f}x", cls="val", text_anchor="start")
        )
        labels.append((y, r.label))
    ch.y_categories(labels, chars=44)
    ch.x_axis(x, svg.log_ticks(x.d0, x.d1), svg.si, "counter value, log scale")
    return Figure(
        key="counters",
        title="Network counters",
        note=f"{len(rows)} counters",
        caption=(
            "Each line spans the lowest and highest value any network card reported, "
            "with the mean marked. A wide span means the load is concentrated on a few "
            "links rather than shared."
        ),
        svg=ch.render(f"Spread of {len(rows)} network counters across cards"),
    )


MAKERS = [
    phase_timeline,
    progress_rate,
    top_gaps,
    timer_breakdown,
    imbalance,
    warning_rate,
    counter_spread,
]


def render_run(
    log: RunLog, a: Assessment, outdir: Path, prefix: str, standalone: bool = False
) -> list[Figure]:
    """Draw every applicable figure for one run; skip the ones without input."""
    out: list[Figure] = []
    for maker in MAKERS:
        try:
            figure = maker(log, a, f"{prefix}-{maker.__name__}")
        except Exception as exc:  # a figure must never sink the report
            log.notes.append(f"figure {maker.__name__} failed: {exc}")
            continue
        if figure is None:
            continue
        if standalone:
            figure.href = write_standalone(figure, outdir, prefix)
        out.append(figure)
    return out


def render_index(
    runs: list[tuple[RunLog, Assessment, str]], outdir: Path, standalone: bool = False
) -> Figure | None:
    """Cross-run comparison for the overview page."""
    usable = [(log, a, href) for log, a, href in runs if log.wall_seconds]
    if len(usable) < 2:
        return None
    usable = sorted(usable, key=lambda triple: triple[0].first_wall or 0)
    rates = [a.stats.get("sypd") or 0.0 for _, a, _ in usable]
    has_rate = any(rates)
    panels = 2 if has_rate else 1
    panel_h, gap, foot = 104, 34, 74
    ch = svg.Chart(height=panels * (panel_h + gap) + foot, pad=(60, 16, 18, foot), uid="overview")
    rate_label = usable[0][0].setting("throughput_label", "rate")
    width = ch.width - ch.pad_l - ch.pad_r
    slot = width / len(usable)
    bar = min(slot * 0.62, 46.0)

    def draw(box: svg.Box, values: list[float], axis_label: str, fmt) -> None:
        top = max(values) * 1.14 or 1.0
        y = svg.Scale(0, top, box.bottom, box.y)
        ch.y_axis(y, svg.nice_ticks(0, top, 4), fmt, axis_label, box=box)
        ch.frame.append(ch.line(box.x, box.bottom, box.right, box.bottom, cls="ax-line"))
        for i, ((log, a, href), value) in enumerate(zip(usable, values)):
            center = box.x + slot * (i + 0.5)
            tip = _tip(
                log.fields.get("job_name") or log.name,
                f"job {log.fields.get('job_id') or '?'}  -  {a.status.lower()}, grade {a.grade}",
                f"wall clock {_dur(log.wall_seconds)}",
                f"{a.stats['sypd']:.2f} {rate_label}" if a.stats.get("sypd") else "",
                f"started {format_stamp(log.first_wall)}",
                "click to open this run",
            )
            ch.geometry.append(
                ch.rect(
                    center - bar / 2,
                    y(value),
                    bar,
                    box.bottom - y(value),
                    rx=2.0,
                    **_mark(f"lv-{a.grade} fill", tip, data_href=href),
                )
            )

    boxes = [svg.Box(ch.pad_l, 16 + i * (panel_h + gap), width, panel_h) for i in range(panels)]
    draw(
        boxes[0],
        [(log.wall_seconds or 0) / 60.0 for log, _, _ in usable],
        "wall clock (min)",
        svg.si,
    )
    if has_rate:
        draw(boxes[1], rates, rate_label, lambda v: f"{v:.2g}")

    baseline = boxes[-1].bottom
    ids = [str(log.fields.get("job_id") or "") for log, _, _ in usable]
    for i, (log, _, _) in enumerate(usable):
        center = ch.pad_l + slot * (i + 0.5)
        unique = ids[i] and ids.count(ids[i]) == 1
        text = svg.truncate(ids[i] if unique else log.name, 16)
        ch.frame.append(
            ch.text(
                0,
                0,
                text,
                cls="tick",
                text_anchor="end",
                transform=f"translate({svg.num(center + 3)},{svg.num(baseline + 12)}) rotate(-42)",
            )
        )
    figure = Figure(
        key="overview",
        title="All runs",
        note=f"{len(usable)} runs",
        caption=(
            "Wall clock and throughput per run, oldest first, coloured by health grade. "
            "Click a bar to open that run."
        ),
        svg=ch.render(f"Wall clock and throughput across {len(usable)} runs"),
    )
    if standalone:
        figure.href = write_standalone(figure, outdir, "overview")
    return figure


# -- standalone files, for the Markdown output ----------------------------


def write_standalone(figure: Figure, outdir: Path, prefix: str) -> str:
    """Write one figure as a self-contained ``.svg`` and return its href.

    The HTML report inlines the same markup instead, so this runs only for
    ``--format md``, where a figure has to be a file a Markdown reader can
    point at.
    """
    path = outdir / "images" / f"{prefix}__{figure.key}.svg"
    path.parent.mkdir(parents=True, exist_ok=True)
    head = '<svg xmlns="http://www.w3.org/2000/svg" '
    document = figure.svg.replace("<svg ", head, 1)
    opening = document.index(">") + 1
    sheet = f"<style>{style.svg_stylesheet()}</style>"
    path.write_text(document[:opening] + sheet + document[opening:])
    return f"images/{path.name}"
