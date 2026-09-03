"""Figures for a run report.

Each function draws one question. All of them return ``None`` when the log
does not contain what they need, so a report built from the generic profile
simply has fewer figures rather than failing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, MultipleLocator  # noqa: E402

from . import style  # noqa: E402
from .extract import RunLog  # noqa: E402
from .health import Assessment, counter_rows  # noqa: E402
from .logfile import format_duration  # noqa: E402


@dataclass
class Figure:
    key: str
    href: str
    title: str
    caption: str = ""


def _save(fig, path: Path, dpi: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


# Tick steps that read as a duration rather than as an arbitrary number.
NICE_STEPS = [10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200]


def _nice_step(span: float, target: int = 7) -> float:
    want = span / target
    return next((s for s in NICE_STEPS if s >= want), NICE_STEPS[-1])


def _time_axis(span: float):
    """Label and formatter for a wall-clock axis, with enough precision to be
    monotonic: hours to one decimal, minutes to whole numbers."""
    if span >= 7200:
        return "h", FuncFormatter(lambda v, _: f"{v / 3600:.1f}")
    if span >= 120:
        return "min", FuncFormatter(lambda v, _: f"{v / 60:.0f}")
    return "s", FuncFormatter(lambda v, _: f"{v:.0f}")


def _wrap(text: str, width: int = 58) -> str:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    return "\n".join(lines[:2])


# -- figures --------------------------------------------------------------


def phase_timeline(log: RunLog, a: Assessment, path: Path, dpi: int) -> Figure | None:
    if not a.phases or log.first_wall is None:
        return None
    t0 = log.first_wall
    total = log.wall_seconds or 1.0
    unit, fmt = _time_axis(total)
    fig, ax = plt.subplots(figsize=(9.5, 2.6))
    for i, ph in enumerate(a.phases):
        ax.broken_barh(
            [(ph.start - t0, ph.seconds)],
            (0.25, 0.5),
            facecolors=style.PHASES[i % len(style.PHASES)],
            edgecolor=style.SURFACE,
            linewidth=1.2,
        )
        if ph.seconds / total > 0.045:
            ax.text(
                ph.start - t0 + ph.seconds / 2,
                0.5,
                f"{ph.name}\n{format_duration(ph.seconds)}",
                ha="center",
                va="center",
                fontsize=8,
                color="white",
                fontweight="bold",
            )
    stall = float(log.threshold("stall_seconds", 300))
    shown = 0
    for g in log.gaps:
        if g.seconds < max(stall * 0.2, total * 0.03) or shown >= 4:
            continue
        ax.broken_barh(
            [(g.start - t0, g.seconds)],
            (0.78, 0.13),
            facecolors=style.FAIL,
            alpha=0.85,
        )
        ax.text(
            g.start - t0 + g.seconds / 2,
            0.97,
            format_duration(g.seconds),
            ha="center",
            va="bottom",
            fontsize=7.5,
            color=style.FAIL,
        )
        shown += 1
    for name, series in log.series.items():
        if log.series_roles.get(name) != "io":
            continue
        xs = [s["wall"] - t0 for s in series if s.get("wall") is not None]
        ax.plot(xs, [0.14] * len(xs), marker="|", linestyle="none", color=style.MUTED, markersize=6)
    ax.set_ylim(0, 1.15)
    ax.set_xlim(0, total)
    ax.set_yticks([])
    ax.xaxis.set_major_locator(MultipleLocator(_nice_step(total)))
    ax.xaxis.set_major_formatter(fmt)
    ax.set_xlabel(f"wall clock since the first stamped line ({unit})")
    ax.grid(axis="x", color=style.SURFACE, linewidth=0.8)
    ax.grid(axis="y", visible=False)
    ax.set_title("Where the wall clock went")
    _save(fig, path, dpi)
    return Figure(
        "timeline",
        path.name,
        "Run timeline",
        "Phases between the markers the profile defines. Red bars above the timeline "
        "are stretches with no output at all; a wide one is where a run hangs. Ticks "
        "below mark output and checkpoint writes.",
    )


def progress_rate(log: RunLog, a: Assessment, path: Path, dpi: int) -> Figure | None:
    if len(a.intervals) < 4:
        return None
    xs = [i.get("step") or n for n, i in enumerate(a.intervals)]
    ys = [i["seconds"] for i in a.intervals]
    median = a.stats.get("interval_median") or 0.0
    factor = float(log.threshold("outlier_factor", 3))
    fig, ax = plt.subplots(figsize=(9.5, 3.2))
    ax.plot(xs, ys, color=style.SERIES[0], linewidth=1.2)
    ax.axhline(median, color=style.MUTED, linestyle="--", linewidth=1)
    ax.annotate(
        f"median {format_duration(median)}",
        xy=(xs[-1], median),
        xytext=(-4, 5),
        textcoords="offset points",
        ha="right",
        va="bottom",
        fontsize=8,
        color=style.LABEL,
        bbox=dict(boxstyle="round,pad=0.22", fc=style.SURFACE, ec="none", alpha=0.9),
    )
    hot = [(x, y) for x, y in zip(xs, ys) if y > factor * median]
    if hot:
        ax.plot(
            *zip(*hot),
            marker="o",
            linestyle="none",
            color=style.WARN,
            markersize=5,
            label=f"> {factor:g}x median",
        )
        ax.legend(loc="upper right", fontsize=8)
    ax.set_xlabel(log.setting("progress_label", "events"))
    ax.set_ylabel("wall seconds per report")
    # One slow first step (kernel compilation, cache warm-up) would otherwise
    # flatten the rest of the run into a straight line.
    if median > 0 and max(ys) > 20 * median:
        ax.set_yscale("log")
    else:
        ax.set_ylim(bottom=0)
    title = "Progress rate"
    sypd = a.stats.get("sypd")
    if sypd:
        title += f"  -  {sypd:.2f} {log.setting('throughput_label', 'rate')} overall"
    ax.set_title(title)
    _save(fig, path, dpi)
    return Figure(
        "progress",
        path.name,
        "Progress rate",
        "Wall time between successive progress reports. A flat line is a healthy "
        "run; spikes are output, checkpointing or a transient stall, and a rising "
        "trend means the run is degrading.",
    )


def top_gaps(log: RunLog, a: Assessment, path: Path, dpi: int) -> Figure | None:
    gaps = [g for g in log.gaps if g.seconds >= 1.0][:10]
    if len(gaps) < 2:
        return None
    stall = float(log.threshold("stall_seconds", 300))
    fig, ax = plt.subplots(figsize=(9.5, 0.42 * len(gaps) + 1.4))
    ys = list(range(len(gaps)))[::-1]
    colors = [style.FAIL if g.seconds >= stall else style.SERIES[0] for g in gaps]
    ax.barh(ys, [g.seconds for g in gaps], color=colors, height=0.62)
    ax.set_yticks(ys)
    ax.set_yticklabels([_wrap(g.before or "(start of log)", 62) for g in gaps], fontsize=7.5)
    for y, g in zip(ys, gaps):
        ax.text(
            g.seconds,
            y,
            f"  {format_duration(g.seconds)}",
            va="center",
            fontsize=8,
            color=style.LABEL,
        )
    ax.set_xlabel("seconds of silence")
    ax.set_xlim(0, max(g.seconds for g in gaps) * 1.25)
    ax.grid(axis="y", visible=False)
    ax.set_title("Longest silences, labelled with the last line before them")
    _save(fig, path, dpi)
    return Figure(
        "gaps",
        path.name,
        "Longest silences",
        f"Each bar is a stretch with no output. Red marks anything past the "
        f"{format_duration(stall)} stall threshold. The label is the last thing "
        "written before the silence, which is where to start looking.",
    )


def timer_breakdown(log: RunLog, a: Assessment, path: Path, dpi: int) -> Figure | None:
    groups = [g for g in a.timers if len(g.rows) > 1]
    if not groups:
        return None
    picks = []
    for g in groups:
        rows = sorted(
            (r for r in g.rows if r.depth == 1 and r.total > 0),
            key=lambda r: -r.total,
        )[:9]
        if rows:
            picks.append((g, rows))
    if not picks:
        return None
    height = sum(0.32 * len(rows) + 1.1 for _, rows in picks)
    fig, axes = plt.subplots(
        len(picks),
        1,
        figsize=(9.5, height),
        gridspec_kw={"height_ratios": [len(r) + 1 for _, r in picks]},
    )
    axes = [axes] if len(picks) == 1 else list(axes)
    for ax, (g, rows) in zip(axes, picks):
        ys = list(range(len(rows)))[::-1]
        ax.barh(ys, [r.total for r in rows], color=style.SERIES[0], height=0.6)
        ax.errorbar(
            [r.total for r in rows],
            ys,
            xerr=[
                [max(0.0, r.total - r.minimum) for r in rows],
                [max(0.0, r.maximum - r.total) for r in rows],
            ],
            fmt="none",
            ecolor=style.INK,
            elinewidth=1,
            capsize=3,
            alpha=0.7,
        )
        ax.set_yticks(ys)
        ax.set_yticklabels([r.label for r in rows], fontsize=8)
        for y, r in zip(ys, rows):
            ax.text(
                r.maximum,
                y,
                f"  {r.share * 100:.0f}%",
                va="center",
                fontsize=7.5,
                color=style.LABEL,
            )
        ax.set_xlim(0, max(r.maximum for r in rows) * 1.16)
        ax.grid(axis="y", visible=False)
        ax.set_title(f"{g.title}  ({g.root} = {format_duration(g.root_seconds)})", fontsize=9)
        ax.set_xlabel("seconds")
    fig.tight_layout()
    _save(fig, path, dpi)
    return Figure(
        "timers",
        path.name,
        "Where the time went",
        "Top-level timers per rank group. The bar is the average across ranks and "
        "the whisker spans fastest to slowest, so a long whisker is imbalance.",
    )


def imbalance(log: RunLog, a: Assessment, path: Path, dpi: int) -> Figure | None:
    floor = float(log.threshold("timer_share_floor", 0.05))
    rows = [
        (r, g)
        for g in a.timers
        for r in g.rows
        if r.imbalance and r.share >= floor and r.label != g.root
    ]
    if len(rows) < 2:
        return None
    rows.sort(key=lambda rg: -(rg[0].imbalance or 0))
    rows = rows[:12]
    warn = float(log.threshold("imbalance_warn", 1.25))
    fail = float(log.threshold("imbalance_fail", 2.0))
    fig, ax = plt.subplots(figsize=(9.5, 0.36 * len(rows) + 1.4))
    ys = list(range(len(rows)))[::-1]
    colors = [
        (
            style.WARN
            if (r.imbalance or 0) >= fail
            else style.INFO if (r.imbalance or 0) >= warn else style.OK
        )
        for r, _ in rows
    ]
    ax.barh(ys, [r.imbalance for r, _ in rows], color=colors, height=0.6)
    ax.axvline(1.0, color=style.MUTED, linewidth=1)
    ax.set_yticks(ys)
    ax.set_yticklabels([f"{r.label}" for r, _ in rows], fontsize=8)
    for y, (r, _) in zip(ys, rows):
        rank = f" (rank {int(r.max_rank)})" if r.max_rank is not None else ""
        ax.text(
            r.imbalance,
            y,
            f"  {r.imbalance:.1f}x{rank}",
            va="center",
            fontsize=7.5,
            color=style.LABEL,
        )
    ax.set_xlim(0, max(r.imbalance for r, _ in rows) * 1.3)
    ax.set_xlabel("slowest rank / fastest rank")
    ax.grid(axis="y", visible=False)
    ax.set_title("Load imbalance among timers holding more than " f"{floor * 100:.0f}% of the run")
    _save(fig, path, dpi)
    return Figure(
        "imbalance",
        path.name,
        "Load imbalance",
        "How much longer the slowest rank spent in each timer than the fastest. "
        "A ratio on a wait or synchronisation timer measures imbalance created "
        "somewhere else.",
    )


def warning_rate(log: RunLog, a: Assessment, path: Path, dpi: int) -> Figure | None:
    live = {n: g for n, g in log.groups.items() if g.total and g.bins}
    if not live:
        return None
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(9.5, 3.0), gridspec_kw={"width_ratios": [2.1, 1]})
    span = int((log.wall_seconds or 60.0) // 60) + 1
    for i, (name, g) in enumerate(sorted(live.items(), key=lambda kv: -kv[1].total)[:5]):
        # Minutes with no message are zeros; without them the line would jump
        # across a quiet stretch and read as continuous activity.
        ys = [g.bins.get(str(x), 0) for x in range(span)]
        ax.fill_between(
            range(span),
            ys,
            step="mid",
            alpha=0.12,
            color=style.SERIES[i % len(style.SERIES)],
            linewidth=0,
        )
        ax.plot(
            range(span),
            ys,
            linewidth=1.3,
            drawstyle="steps-mid",
            color=style.SERIES[i % len(style.SERIES)],
            label=f"{g.label} ({g.total:,})",
        )
    ax.set_xlabel("minutes since the first stamped line")
    ax.set_ylabel("lines per minute")
    ax.set_yscale("symlog", linthresh=10)
    ax.legend(fontsize=7.5, loc="upper right")
    ax.set_title("Message rate over the run", fontsize=9)

    worst = max(live.values(), key=lambda g: g.total)
    nodes = sorted(worst.nodes.items(), key=lambda kv: -kv[1])[:12]
    if nodes:
        ys = list(range(len(nodes)))[::-1]
        bx.barh(ys, [c for _, c in nodes], color=style.SERIES[0], height=0.62)
        bx.set_yticks(ys)
        bx.set_yticklabels([n for n, _ in nodes], fontsize=7.5)
        bx.grid(axis="y", visible=False)
        bx.set_title(f"Nodes producing them: {worst.label}", fontsize=9)
        bx.set_xlabel("lines")
    else:
        bx.axis("off")
    fig.tight_layout()
    _save(fig, path, dpi)
    return Figure(
        "warnings",
        path.name,
        "Message rate",
        "How message families are distributed over the run, and which nodes "
        "produce them. A burst that lines up with a slow stretch in the progress "
        "plot points at the network rather than the code.",
    )


def counter_spread(log: RunLog, a: Assessment, path: Path, dpi: int) -> Figure | None:
    counters, _ = counter_rows(log)
    if counters is None or not counters.rows:
        return None
    cols = log.setting("counter_columns", {}) or {}
    c_min, c_mean, c_max = cols.get("min", "Min"), cols.get("mean", "Mean"), cols.get("max", "Max")
    rows = [
        r for r in counters.rows if r.values.get(c_max, 0) > 0 and r.values.get(c_min) is not None
    ]
    if len(rows) < 3:
        return None
    rows = sorted(rows, key=lambda r: -(r.values[c_max] / max(r.values[c_min], 1.0)))[:14]
    fig, ax = plt.subplots(figsize=(9.5, 0.35 * len(rows) + 1.5))
    ys = list(range(len(rows)))[::-1]
    for y, r in zip(ys, rows):
        lo = max(r.values.get(c_min, 0.0), 0.5)
        hi = max(r.values.get(c_max, 0.0), lo)
        mean = max(r.values.get(c_mean, lo), 0.5)
        spread = hi / lo
        color = style.WARN if spread > 20 else style.SERIES[0]
        ax.plot([lo, hi], [y, y], color=color, linewidth=3, solid_capstyle="round", alpha=0.65)
        ax.plot([mean], [y], marker="o", color=style.INK, markersize=4)
        ax.text(hi, y, f"  {spread:.0f}x", va="center", fontsize=7.5, color=style.LABEL)
    ax.set_xscale("log")
    ax.set_yticks(ys)
    ax.set_yticklabels([r.label for r in rows], fontsize=7.5)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("counter value (log scale): fastest NIC to slowest, dot is the mean")
    ax.set_title("Network counter spread across NICs")
    _save(fig, path, dpi)
    return Figure(
        "counters",
        path.name,
        "Network counters",
        "Each line spans the lowest and highest value any NIC reported. A wide "
        "span means the load is concentrated on a few links rather than shared.",
    )


def render_run(log: RunLog, a: Assessment, outdir: Path, prefix: str, dpi: int) -> list[Figure]:
    """Draw every applicable figure for one run; skip the ones without input."""
    plt.rcParams.update(style.RC)
    out: list[Figure] = []
    makers = [
        ("timeline", phase_timeline),
        ("progress", progress_rate),
        ("gaps", top_gaps),
        ("timers", timer_breakdown),
        ("imbalance", imbalance),
        ("warnings", warning_rate),
        ("counters", counter_spread),
    ]
    for key, fn in makers:
        path = outdir / "images" / f"{prefix}__{key}.png"
        try:
            fig = fn(log, a, path, dpi)
        except Exception as exc:  # a figure must never sink the report
            log.notes.append(f"figure {key} failed: {exc}")
            fig = None
        if fig is not None:
            fig.href = f"images/{path.name}"
            out.append(fig)
    return out


def render_index(runs: list[tuple[RunLog, Assessment]], path: Path, dpi: int) -> Figure | None:
    """Cross-run comparison for the overview page."""
    usable = [(l, a) for l, a in runs if l.wall_seconds]
    if len(usable) < 2:
        return None
    plt.rcParams.update(style.RC)
    usable = sorted(usable, key=lambda p: p[0].first_wall or 0)
    labels = [f"{l.fields.get('job_id') or l.name[:14]}" for l, _ in usable]
    walls = [(l.wall_seconds or 0) / 60.0 for l, _ in usable]
    rates = [a.stats.get("sypd") or 0.0 for _, a in usable]
    colors = [style.LEVEL_COLOR.get(a.grade, style.INFO) for _, a in usable]
    has_rate = any(rates)
    fig, axes = plt.subplots(
        2 if has_rate else 1, 1, figsize=(9.5, 4.6 if has_rate else 2.7), sharex=True
    )
    axes = list(axes) if has_rate else [axes]
    xs = range(len(usable))
    axes[0].bar(xs, walls, color=colors, width=0.62)
    axes[0].set_ylabel("wall clock (min)")
    axes[0].set_title("Runs, newest last")
    if has_rate:
        axes[1].bar(xs, rates, color=colors, width=0.62)
        axes[1].set_ylabel(usable[0][0].setting("throughput_label", "rate"))
    axes[-1].set_xticks(list(xs))
    axes[-1].set_xticklabels(labels, rotation=45, ha="right", fontsize=7.5)
    for ax in axes:
        ax.grid(axis="x", visible=False)
    fig.tight_layout()
    _save(fig, path, dpi)
    return Figure(
        "overview",
        f"images/{path.name}",
        "All runs",
        "Wall clock and throughput per run, coloured by health grade.",
    )
