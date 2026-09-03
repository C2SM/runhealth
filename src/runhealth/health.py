"""Turn a parsed :class:`~runhealth.extract.RunLog` into a verdict.

Each check answers one question about the run and carries the evidence for its
answer, so a report never says "load imbalance" without naming the timer, the
ratio and the rank. Checks that a profile cannot feed simply do not appear:
the generic SLURM profile still yields outcome, silence and error checks, and
gains the rest as soon as a model profile is available.

The grade of a run is the worst level any check returned.
"""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .extract import RunLog
from .logfile import format_duration, format_stamp, parse_walltime
from .tables import Table

LEVELS = ["ok", "info", "warn", "fail"]
LEVEL_RANK = {name: i for i, name in enumerate(LEVELS)}
SECONDS_PER_YEAR = 365.25 * 86400.0
MODEL_TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
)


@dataclass
class Check:
    """One question about the run, its answer, and why."""

    key: str
    title: str
    level: str
    headline: str
    detail: str = ""
    evidence: list[str] = field(default_factory=list)


@dataclass
class Phase:
    name: str
    start: float
    end: float

    @property
    def seconds(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class TimerRow:
    label: str
    depth: int
    total: float
    minimum: float
    maximum: float
    min_rank: float | None
    max_rank: float | None
    calls: float | None
    share: float
    imbalance: float | None


@dataclass
class TimerGroup:
    title: str
    root: str
    root_seconds: float
    rows: list[TimerRow]


@dataclass
class Assessment:
    """Everything the report needs beyond the raw :class:`RunLog`."""

    status: str = "UNKNOWN"
    grade: str = "info"
    checks: list[Check] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    phases: list[Phase] = field(default_factory=list)
    intervals: list[dict] = field(default_factory=list)
    timers: list[TimerGroup] = field(default_factory=list)
    suspect_nodes: list[tuple[str, str]] = field(default_factory=list)

    def check(self, key: str) -> Check | None:
        return next((c for c in self.checks if c.key == key), None)


# -- small helpers --------------------------------------------------------


def parse_model_time(text: str) -> datetime | None:
    for fmt in MODEL_TIME_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def _worst(levels: list[str]) -> str:
    return max(levels, key=lambda x: LEVEL_RANK.get(x, 0)) if levels else "info"


def _fmt_count(n: float) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.1f}G"
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"{n / 1e3:.1f}k"
    return f"{n:.0f}"


# -- derived structures ---------------------------------------------------


def phases(log: RunLog) -> list[Phase]:
    """Wall-clock stretches between successive profile markers."""
    marks = sorted((m for m in log.markers if m.wall is not None), key=lambda m: m.wall)
    if not marks or log.first_wall is None or log.last_wall is None:
        return []
    out = [Phase("job setup", log.first_wall, marks[0].wall)]
    for a, b in zip(marks, marks[1:]):
        out.append(Phase(a.label or a.name, a.wall, b.wall))
    out.append(Phase(marks[-1].label or marks[-1].name, marks[-1].wall, log.last_wall))
    return [p for p in out if p.seconds > 0]


def progress_series(log: RunLog) -> list[dict]:
    name = log.setting("progress_series")
    if name and log.series.get(name):
        return log.series[name]
    for key, role in log.series_roles.items():
        if role == "progress" and log.series.get(key):
            return log.series[key]
    return []


def intervals(log: RunLog) -> list[dict]:
    """Wall seconds and model seconds between consecutive progress reports."""
    series = progress_series(log)
    field_name = log.setting("model_time_field", "model_time")
    out = []
    for a, b in zip(series, series[1:]):
        if a.get("wall") is None or b.get("wall") is None:
            continue
        rec = {
            "step": b.get("step"),
            "wall": b["wall"],
            "seconds": b["wall"] - a["wall"],
        }
        ta, tb = parse_model_time(a.get(field_name, "")), parse_model_time(b.get(field_name, ""))
        if ta and tb:
            rec["model_seconds"] = (tb - ta).total_seconds()
        out.append(rec)
    return out


def timer_groups(log: RunLog) -> list[TimerGroup]:
    """Flatten the profile's timer tables into comparable rows."""
    table_name = log.setting("timer_table")
    if not table_name:
        return []
    cols = log.setting("timer_columns", {}) or {}
    c_total = cols.get("total", "total avg (s)")
    c_min = cols.get("min", "total min (s)")
    c_max = cols.get("max", "total max (s)")
    c_minr = cols.get("min_rank", "total min rank")
    c_maxr = cols.get("max_rank", "total max rank")
    c_calls = cols.get("calls", "# calls")
    root_label = log.setting("timer_root", "")
    groups: list[TimerGroup] = []
    for table in log.tables.get(table_name, []):
        rows = [r for r in table.rows if c_total in r.values]
        if not rows:
            continue
        root = next((r for r in rows if r.label == root_label and r.depth == 0), None)
        if root is not None:
            root_label_shown = root.label
            root_seconds = root.values[c_total] or 1.0
        else:
            # No overall timer in this table: measure against the top level.
            root_label_shown = "measured total"
            root_seconds = sum(r.values[c_total] for r in rows if r.depth == 0) or 1.0
        out = []
        for r in rows:
            lo = r.values.get(c_min)
            hi = r.values.get(c_max)
            imb = (hi / lo) if lo and hi and lo > 0 else None
            out.append(
                TimerRow(
                    label=r.label,
                    depth=r.depth,
                    total=r.values[c_total],
                    minimum=lo if lo is not None else r.values[c_total],
                    maximum=hi if hi is not None else r.values[c_total],
                    min_rank=r.values.get(c_minr),
                    max_rank=r.values.get(c_maxr),
                    calls=r.values.get(c_calls),
                    share=r.values[c_total] / root_seconds,
                    imbalance=imb,
                )
            )
        groups.append(TimerGroup(table.title, root_label_shown, root_seconds, out))
    return groups


def counter_rows(log: RunLog) -> tuple[Table | None, Table | None]:
    counters = log.tables.get(log.setting("counter_table") or "", [])
    ratios = log.tables.get(log.setting("ratio_table") or "", [])
    return (counters[0] if counters else None, ratios[0] if ratios else None)


# -- the checks -----------------------------------------------------------


def assess(log: RunLog, now: float | None = None, slurm_state: str = "") -> Assessment:
    """Run every applicable check and return the verdict."""
    now = time.time() if now is None else now
    a = Assessment()
    a.phases = phases(log)
    a.intervals = intervals(log)
    a.timers = timer_groups(log)
    stall_seconds = float(log.threshold("stall_seconds", 300))

    a.status = _status(log, now, stall_seconds, slurm_state)
    a.stats = _stats(log, a)

    a.checks.append(_check_outcome(log, a, slurm_state))
    a.checks.append(_check_stall(log, a, stall_seconds))
    a.checks.append(_check_walltime(log, a))
    a.checks.extend(_check_progress(log, a))
    a.checks.extend(_check_timers(log, a))
    a.checks.extend(_check_io(log, a))
    a.checks.extend(_check_network(log, a))
    a.checks.append(_check_errors(log, a))
    a.checks.extend(_check_groups(log, a))
    a.suspect_nodes = _suspect_nodes(log, a)
    if a.suspect_nodes:
        a.checks.append(
            Check(
                "suspect_nodes",
                "Suspect nodes",
                "info",
                f"{len(a.suspect_nodes)} node(s) stand out",
                "Nodes named in step failures, or carrying a disproportionate share of "
                "warnings. Consider excluding them on the next submission.",
                [f"{n} - {why}" for n, why in a.suspect_nodes[:12]],
            )
        )
    a.checks = [c for c in a.checks if c is not None]
    a.grade = _worst([c.level for c in a.checks])
    return a


def _status(log: RunLog, now: float, stall_seconds: float, slurm_state: str) -> str:
    """SUCCESS, FAILED, QUEUED, RUNNING, STALLED or INCOMPLETE.

    STALLED means the scheduler still believes the job is running while its log
    has gone quiet -- the one case where a live intervention is worth making. A
    log that simply stops without a verdict and is not in the queue any more is
    INCOMPLETE: the job is long gone, and the silence check explains what
    happened.
    """
    if slurm_state in {"PENDING", "CONFIGURING"}:
        return "QUEUED"
    if log.outcome and log.outcome.level == "fail":
        return "FAILED"
    if log.outcome and log.outcome.level == "ok":
        return "SUCCESS"
    age = now - (log.last_wall or log.mtime or now)
    if slurm_state == "RUNNING":
        return "STALLED" if age >= stall_seconds else "RUNNING"
    return "RUNNING" if age < stall_seconds else "INCOMPLETE"


def _stats(log: RunLog, a: Assessment) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "wall_seconds": log.wall_seconds,
        "lines": log.n_lines,
        "size": log.size,
        "nodes": log.fields.get("node_count") or len(log.nodes) or None,
        "max_gap": log.gaps[0].seconds if log.gaps else None,
    }
    series = progress_series(log)
    if series:
        stats["progress_last"] = series[-1].get("step")
        stats["progress_count"] = len(series)
    good = [i["seconds"] for i in a.intervals if i["seconds"] > 0]
    if good:
        stats["interval_median"] = statistics.median(good)
    model_secs = sum(i.get("model_seconds", 0.0) for i in a.intervals)
    wall_secs = sum(i["seconds"] for i in a.intervals)
    if model_secs > 0 and wall_secs > 0:
        stats["sypd"] = (model_secs / wall_secs) * 86400.0 / SECONDS_PER_YEAR
        stats["model_seconds"] = model_secs
    if wall_secs > 0 and stats.get("progress_count"):
        stats["loop_seconds"] = wall_secs
    if a.timers:
        stats["timer_root_seconds"] = max(g.root_seconds for g in a.timers)
    return stats


def _check_outcome(log: RunLog, a: Assessment, slurm_state: str) -> Check:
    ev = []
    if log.outcome:
        ev.append(log.outcome.text)
    status_field = log.fields.get("srun_status")
    if status_field is not None:
        ev.append(f"srun exit status {status_field}")
    if slurm_state:
        ev.append(f"SLURM reports the job as {slurm_state}")
    if a.status == "SUCCESS":
        return Check("outcome", "Outcome", "ok", "The run reported success", "", ev)
    if a.status == "FAILED":
        return Check(
            "outcome",
            "Outcome",
            "fail",
            log.outcome.text if log.outcome else "The run failed",
            "The job script or SLURM reported a failure.",
            ev,
        )
    if a.status in {"RUNNING", "QUEUED"}:
        return Check("outcome", "Outcome", "info", f"The job is {a.status.lower()}", "", ev)
    if a.status == "STALLED":
        return Check(
            "outcome",
            "Outcome",
            "fail",
            "The job is silent but not finished",
            "No final status was written and nothing has been logged recently.",
            ev,
        )
    return Check(
        "outcome",
        "Outcome",
        "warn",
        "The log ends without a final status",
        "Neither success nor failure was recorded. The job may have been killed "
        "before its epilogue ran, or the log may be truncated.",
        ev,
    )


def _check_stall(log: RunLog, a: Assessment, stall_seconds: float) -> Check:
    if log.line_format != "timestamped":
        return Check(
            "stall",
            "Silence",
            "info",
            "Not measurable without line timestamps",
            "Stamp the job output (for example by piping it through a helper that "
            "prefixes the wall clock) to enable hang detection.",
        )
    if not log.gaps:
        return Check("stall", "Silence", "ok", "No measurable pause")
    gap = log.gaps[0]
    median = a.stats.get("interval_median")
    factor = float(log.threshold("gap_warn_factor", 5))
    ev = [
        f"{format_duration(g.seconds)} at {format_stamp(g.start)} after: {g.before}"
        + ("  [in the main loop]" if _in_loop(log, g.start) else "")
        for g in log.gaps[:5]
    ]
    detail = (
        "The longest stretch in which no rank wrote anything. Silence during setup "
        "is normal -- input is being read and kernels compiled -- so only silence "
        "inside the main loop is judged against the typical progress interval."
    )
    # Silence before the first progress report is startup: reading input,
    # compiling kernels, negotiating a coupling. Judge it against a much longer
    # threshold, unless the run never reached its main loop at all.
    reached_loop = bool(progress_series(log))
    setup_limit = float(log.threshold("setup_stall_seconds", stall_seconds * 4))
    for g in log.gaps:
        hard = stall_seconds if (_in_loop(log, g.start) or not reached_loop) else None
        if hard is not None and g.seconds >= hard:
            where = "in the main loop" if reached_loop else "before the main loop started"
            return Check(
                "stall",
                "Silence",
                "fail",
                f"{format_duration(g.seconds)} of silence {where}, after: {g.before[:90]}",
                detail,
                ev,
            )
        if hard is None and g.seconds >= setup_limit:
            return Check(
                "stall",
                "Silence",
                "warn",
                f"{format_duration(g.seconds)} of silence during setup, after: " f"{g.before[:90]}",
                detail + " This one is outside the main loop, so it delayed the run "
                "rather than interrupting it.",
                ev,
            )
    in_loop = [g for g in log.gaps if _in_loop(log, g.start)]
    if median and in_loop and in_loop[0].seconds > factor * median:
        worst = in_loop[0]
        return Check(
            "stall",
            "Silence",
            "warn",
            f"{format_duration(worst.seconds)} pause inside the main loop, "
            f"{worst.seconds / median:.0f}x the typical {format_duration(median)} interval",
            detail,
            ev,
        )
    return Check(
        "stall",
        "Silence",
        "ok",
        f"Longest pause {format_duration(gap.seconds)}"
        + ("" if _in_loop(log, gap.start) else ", outside the main loop"),
        detail,
        ev,
    )


def _in_loop(log: RunLog, when: float) -> bool:
    """Whether a wall-clock instant falls between the first and last progress report."""
    series = progress_series(log)
    walls = [s["wall"] for s in series if s.get("wall") is not None]
    return bool(walls) and walls[0] <= when <= walls[-1]


def _check_walltime(log: RunLog, a: Assessment) -> Check | None:
    requested = parse_walltime(log.keyvalues.get("sbatch", {}).get("time", ""))
    used = log.wall_seconds
    if not requested or not used:
        return None
    frac = used / requested
    ev = [f"{format_duration(used)} used of {format_duration(requested)} requested"]
    if log.outcome and "TIME LIMIT" in (log.outcome.text or "").upper():
        return Check(
            "walltime",
            "Wall time",
            "fail",
            "The job hit its wall-clock limit",
            "SLURM cancelled the job because the requested time ran out.",
            ev,
        )
    warn = float(log.threshold("walltime_warn", 0.9))
    if frac >= warn:
        return Check(
            "walltime",
            "Wall time",
            "warn",
            f"{frac * 100:.0f}% of the requested limit used",
            "Little headroom left. A slightly slower run would be cancelled.",
            ev,
        )
    return Check(
        "walltime", "Wall time", "ok", f"{frac * 100:.0f}% of the requested limit used", "", ev
    )


def _check_progress(log: RunLog, a: Assessment) -> list[Check]:
    if not a.intervals:
        return []
    out: list[Check] = []
    good = [i["seconds"] for i in a.intervals if i["seconds"] > 0]
    if not good:
        return []
    median = statistics.median(good)
    label = log.setting("progress_label", "events")
    sypd = a.stats.get("sypd")
    headline = f"{a.stats.get('progress_last')} {label}"
    if sypd:
        headline += f", {sypd:.2f} {log.setting('throughput_label', 'SYPD')}"
    ev = [
        f"typical interval {format_duration(median)} between progress reports",
        f"{format_duration(a.stats.get('loop_seconds'))} spent in the main loop",
    ]
    out.append(Check("throughput", "Throughput", "ok", headline, "", ev))

    # Drift: a run that slows down as it goes usually means a leak, a filling
    # file system, or a node degrading under load.
    n = len(good) // 4
    if n >= 3:
        first, last = statistics.median(good[:n]), statistics.median(good[-n:])
        drift = (last - first) / first if first else 0.0
        limit = float(log.threshold("drift_warn", 0.2))
        dev = [
            f"first quarter {format_duration(first)} per interval",
            f"last quarter {format_duration(last)} per interval",
        ]
        if drift > limit:
            out.append(
                Check(
                    "drift",
                    "Throughput drift",
                    "warn",
                    f"The run slowed by {drift * 100:.0f}% between its first and last quarter",
                    "A progressive slowdown points at a resource that degrades over the "
                    "run rather than at a single bad interval.",
                    dev,
                )
            )
        else:
            out.append(
                Check(
                    "drift",
                    "Throughput drift",
                    "ok",
                    f"Rate stable to within {abs(drift) * 100:.0f}%",
                    "",
                    dev,
                )
            )

    factor = float(log.threshold("outlier_factor", 3))
    slow = [i for i in a.intervals if i["seconds"] > factor * median]
    if slow:
        worst = sorted(slow, key=lambda i: -i["seconds"])[:5]
        out.append(
            Check(
                "outliers",
                "Slow intervals",
                "warn" if len(slow) > 1 else "info",
                f"{len(slow)} of {len(a.intervals)} intervals took more than "
                f"{factor:g}x the median",
                "Isolated slow intervals usually mark output, checkpointing or a "
                "transient network stall.",
                [f"{label} {i['step']}: {format_duration(i['seconds'])}" for i in worst],
            )
        )
    return out


def _check_timers(log: RunLog, a: Assessment) -> list[Check]:
    if not a.timers:
        return []
    floor = float(log.threshold("timer_share_floor", 0.05))
    warn = float(log.threshold("imbalance_warn", 1.25))
    fail = float(log.threshold("imbalance_fail", 2.0))
    worst: list[tuple[float, str]] = []
    hot: list[str] = []
    for g in a.timers:
        for r in g.rows:
            if r.share < floor or r.label == g.root:
                continue
            if r.depth <= 1:
                hot.append(
                    f"{r.label}: {r.share * 100:.0f}% of {g.root} "
                    f"({format_duration(r.total)}) - {g.title}"
                )
            if r.imbalance and r.imbalance >= warn:
                worst.append(
                    (
                        r.imbalance,
                        f"{r.label}: slowest rank {r.imbalance:.2f}x the fastest "
                        f"({format_duration(r.minimum)} to {format_duration(r.maximum)}, "
                        f"slowest rank {int(r.max_rank) if r.max_rank is not None else '?'})",
                    )
                )
    out = []
    if hot:
        out.append(
            Check(
                "hotspots",
                "Where the time went",
                "ok",
                f"{len(hot)} timer(s) above {floor * 100:.0f}% of the total",
                "The largest contributors at the top two levels of the timer tree.",
                sorted(hot, reverse=True)[:12],
            )
        )
    worst.sort(reverse=True)
    if worst:
        severe = worst[0][0] >= fail
        out.append(
            Check(
                "imbalance",
                "Load imbalance",
                "warn" if severe else "info",
                f"Worst timer runs {worst[0][0]:.2f}x slower on the slowest rank",
                "A large spread across ranks means most of them are waiting. Look for "
                "an uneven decomposition, or one node running slower than the rest. "
                "Spread on a wait or synchronisation timer is the symptom of imbalance "
                "elsewhere, not its cause. This never fails a run by itself.",
                [msg for _, msg in worst[:10]],
            )
        )
    elif a.timers:
        out.append(
            Check(
                "imbalance",
                "Load imbalance",
                "ok",
                f"No timer above {floor * 100:.0f}% share exceeds {warn:g}x spread",
            )
        )
    return out


def _check_io(log: RunLog, a: Assessment) -> list[Check]:
    out = []
    restarts = log.series.get("restart_write") or []
    if restarts:
        rate = [r.get("gb_per_s") for r in restarts if r.get("gb_per_s")]
        total = sum(r.get("gigabytes", 0.0) for r in restarts)
        if rate:
            out.append(
                Check(
                    "restart_io",
                    "Checkpoint write",
                    "ok",
                    f"{total:.0f} GB at {statistics.mean(rate):.0f} GB/s",
                    "",
                    [
                        f"{r.get('gigabytes', 0):.1f} GB in {format_duration(r.get('seconds'))} "
                        f"({r.get('gb_per_s', 0):.1f} GB/s)"
                        for r in restarts[:5]
                    ],
                )
            )
    io_names = set(log.setting("io_timers", []) or [])
    if io_names and a.timers:
        share = 0.0
        ev = []
        for g in a.timers:
            for r in g.rows:
                if r.label in io_names and r.depth <= 1:
                    share = max(share, r.share)
                    ev.append(f"{r.label}: {r.share * 100:.0f}% of {g.root} - {g.title}")
        if ev:
            out.append(
                Check(
                    "io_share",
                    "Output cost",
                    "warn" if share > 0.25 else "ok",
                    f"Output timers account for up to {share * 100:.0f}% of the run",
                    "",
                    ev,
                )
            )
    return out


def _check_network(log: RunLog, a: Assessment) -> list[Check]:
    out: list[Check] = []
    counters, ratios = counter_rows(log)
    timeouts = log.fields.get("network_timeouts")
    ev: list[str] = []
    level = "ok"
    headline = "No network trouble reported"

    if timeouts is not None:
        ev.append(f"{timeouts} network timeouts")
        if timeouts:
            level, headline = "fail", f"{timeouts} network timeouts"

    if counters:
        cols = log.setting("counter_columns", {}) or {}
        c_min, c_mean, c_max = (
            cols.get("min", "Min"),
            cols.get("mean", "Mean"),
            cols.get("max", "Max"),
        )
        watch = set(log.setting("counter_watch", []) or [])
        for row in counters.rows:
            if row.label not in watch:
                continue
            lo = row.values.get(c_min, 0.0)
            mean = row.values.get(c_mean, 0.0)
            hi = row.values.get(c_max, 0.0)
            if not hi:
                continue
            spread = hi / lo if lo else math.inf
            ev.append(
                f"{row.label}: min {_fmt_count(lo)}, mean {_fmt_count(mean)}, "
                f"max {_fmt_count(hi)}" + (f" ({spread:.0f}x spread)" if spread != math.inf else "")
            )
            if row.label.startswith("rh:nack") and hi > 0 and level == "ok":
                level, headline = "info", "The fabric retried some packets"
            if spread > 20 and mean and hi / max(mean, 1.0) > 5 and level == "ok":
                level = "info"
                headline = f"Congestion is very uneven across NICs ({row.label})"
    if ratios:
        for row in ratios.rows:
            vals = [f"{v:g}" for v in row.values.values()]
            ev.append(f"{row.label}: " + " / ".join(vals))

    # Fabric chatter: a retry storm shows up as libfabric warnings per minute.
    watch_keys = set(log.setting("congestion_keys", []) or [])
    for name in log.setting("congestion_groups", []) or []:
        stat = log.groups.get(name)
        if not stat or not stat.total:
            continue
        minutes = max(1.0, (log.wall_seconds or 60.0) / 60.0)
        top = sorted(stat.keys.items(), key=lambda kv: -kv[1])[:4]
        ev.append(f"{stat.label}: {_fmt_count(stat.total)} lines in {minutes:.0f} min")
        ev += [f"    {k}: {_fmt_count(v)}" for k, v in top]
        hot = sum(v for k, v in stat.keys.items() if k in watch_keys) if watch_keys else 0
        rate = hot / minutes
        if hot and rate > 10:
            level = "fail" if rate > 1000 else "warn"
            headline = f"{_fmt_count(hot)} dropped flow-control messages"
            peak = _peak_minute(stat)
            if peak:
                minute, count = peak
                headline += (
                    f", {_fmt_count(count)} of them in one minute " f"{minute} min into the run"
                )
                ev.append(f"    busiest minute: {_fmt_count(count)} lines at minute {minute}")
            else:
                headline += f" ({rate:.0f}/min)"
            headline += _node_blame(stat)
    if not ev:
        return out
    out.append(
        Check(
            "network",
            "Network",
            level,
            headline,
            "Slingshot counters and fabric warnings. A high rate of dropped "
            "flow-control messages means the network, not the code, is the limit.",
            ev[:20],
        )
    )
    return out


def _peak_minute(stat) -> tuple[int, int] | None:
    """Busiest minute of a message family, when it is a burst rather than a hum."""
    if not stat.bins:
        return None
    minute, count = max(stat.bins.items(), key=lambda kv: kv[1])
    return (int(minute), count) if count > 0.25 * stat.total else None


def _node_blame(stat) -> str:
    """Name a node only when it really stands out; otherwise say it is fabric-wide."""
    if not stat.nodes:
        return ""
    counts = sorted(stat.nodes.values(), reverse=True)
    worst = max(stat.nodes.items(), key=lambda kv: kv[1])
    if len(stat.nodes) == 1:
        return f", all of it on {worst[0]}"
    typical = statistics.median(counts)
    if typical and worst[1] > 2 * typical:
        return f", concentrated on {worst[0]}"
    return f", spread evenly over {len(stat.nodes)} nodes"


def _check_errors(log: RunLog, a: Assessment) -> Check:
    if not log.errors:
        return Check("errors", "Errors", "ok", "No error lines found")
    ranked = sorted(log.errors.values(), key=lambda e: -e.total)
    total = sum(e.total for e in ranked)
    if a.status in {"FAILED", "STALLED"}:
        level = "fail"
    else:
        level = "warn" if total > 100 else "info"
    return Check(
        "errors",
        "Errors",
        level,
        f"{len(ranked)} distinct error signature(s), {_fmt_count(total)} line(s)",
        "Error-looking lines collapsed by shape; digits are masked so repeats "
        "from many ranks group together.",
        [
            f"{e.total}x {e.sample[:150]}"
            + (f"  [{', '.join(sorted(e.nodes)[:4])}]" if e.nodes else "")
            for e in ranked[:8]
        ],
    )


def _check_groups(log: RunLog, a: Assessment) -> list[Check]:
    out = []
    warn_at = float(log.threshold("group_warn", 1000))
    share_at = float(log.threshold("group_share_warn", 0.2))
    congestion = set(log.setting("congestion_groups", []) or [])
    for name, stat in log.groups.items():
        if not stat.total or name in congestion:
            continue
        top = sorted(stat.keys.items(), key=lambda kv: -kv[1])[:6]
        share = stat.total / max(log.n_lines, 1)
        loud = stat.total >= warn_at and share >= share_at
        out.append(
            Check(
                f"group_{name}",
                stat.label.capitalize(),
                "warn" if loud else "info",
                f"{_fmt_count(stat.total)} line(s) in {len(stat.keys)} family(ies)",
                stat.sample,
                [f"{_fmt_count(v)}x {k}" for k, v in top],
            )
        )
    return out


def _suspect_nodes(log: RunLog, a: Assessment) -> list[tuple[str, str]]:
    """Nodes worth excluding on the next submission, with the reason."""
    reasons: dict[str, list[str]] = {}
    for stat in log.groups.values():
        for node, count in stat.nodes.items():
            if stat.total and count / stat.total >= float(log.threshold("node_share_warn", 0.25)):
                reasons.setdefault(node, []).append(
                    f"{count / stat.total * 100:.0f}% of {stat.label}"
                )
    for stat in log.errors.values():
        for node in stat.nodes:
            reasons.setdefault(node, []).append(f"named in: {stat.label[:60]}")
    for g in a.timers:
        slowest = sorted(
            (r for r in g.rows if r.imbalance and r.share > 0.05),
            key=lambda r: -(r.imbalance or 0),
        )[:1]
        for r in slowest:
            if r.max_rank is not None and (r.imbalance or 0) >= 2.0:
                reasons.setdefault(f"rank {int(r.max_rank)}", []).append(
                    f"slowest on {r.label} ({r.imbalance:.1f}x)"
                )
    return sorted(((n, "; ".join(v[:3])) for n, v in reasons.items()))
