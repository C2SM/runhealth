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
import re
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from . import diag
from .accounting import ACTIVE_STATES, FAILED_STATES, base_state
from .extract import RunLog
from .logfile import format_duration, format_stamp, parse_walltime
from .tables import Table

LEVELS = ["ok", "info", "warn", "fail"]
LEVEL_RANK = {name: i for i, name in enumerate(LEVELS)}
# The level each scheduler outcome is drawn in, so status and health share
# one palette.
STATUS_LEVEL = {
    "SUCCESS": "ok",
    "FAILED": "fail",
    "STALLED": "fail",
    "RUNNING": "info",
    "QUEUED": "info",
    "INCOMPLETE": "warn",
    "UNKNOWN": "info",
}
DAYS_PER_YEAR = 365.25
SECONDS_PER_YEAR = DAYS_PER_YEAR * 86400.0
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
    io_gaps: dict[str, list[dict]] = field(default_factory=dict)
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
    """Wall seconds and model seconds between consecutive progress reports.

    The first intervals carry one-off costs such as kernel compilation and the
    first coupled exchange, so they are flagged as warm-up and kept out of the
    steady-state rate, the outlier count and the plot scale.
    """
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
    warmup = int(log.threshold("warmup_intervals", 1))
    if len(out) >= warmup + 3:
        for rec in out[:warmup]:
            rec["warmup"] = True
    return out


def steady(intervals: list[dict]) -> list[dict]:
    """The intervals after warm-up."""
    return [i for i in intervals if not i.get("warmup")]


def throughput(intervals: list[dict]) -> float | None:
    """Simulated years per wall-clock day over the given intervals."""
    model_secs = sum(i.get("model_seconds", 0.0) for i in intervals)
    wall_secs = sum(i["seconds"] for i in intervals)
    if model_secs > 0 and wall_secs > 0:
        return (model_secs / wall_secs) * 86400.0 / SECONDS_PER_YEAR
    return None


def rate_text(sypd: float, label: str = "SYPD") -> str:
    """``0.09 SYPD (32.9 SDPD)``: the rate in years and in days per day."""
    return f"{sypd:.2f} {label} ({sypd * DAYS_PER_YEAR:,.1f} SDPD)"


def io_cadence(log: RunLog) -> dict[str, list[dict]]:
    """Wall-time gaps between successive events of each I/O series.

    One entry per series carrying ``role: io`` (output writes, checkpoints,
    ...), so a stall between two output files shows up the same way a stall
    between progress reports does.
    """
    out: dict[str, list[dict]] = {}
    for name, role in log.series_roles.items():
        if role != "io":
            continue
        walls = [r["wall"] for r in log.series.get(name, []) if r.get("wall") is not None]
        if len(walls) < 2:
            continue
        out[name] = [{"wall": b, "seconds": b - a} for a, b in zip(walls, walls[1:]) if b > a]
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


def assess(
    log: RunLog,
    now: float | None = None,
    slurm_state: str = "",
    accounting: dict | None = None,
) -> Assessment:
    """Run every applicable check and return the verdict.

    ``accounting`` is the job's record from :func:`runhealth.accounting.query`,
    if SLURM still has one.
    """
    now = time.time() if now is None else now
    acct = accounting or {}
    a = Assessment()
    a.phases = phases(log)
    a.intervals = intervals(log)
    a.io_gaps = io_cadence(log)
    a.timers = timer_groups(log)
    stall_seconds = float(log.threshold("stall_seconds", 300))

    a.status = _status(log, now, stall_seconds, slurm_state, acct)
    a.stats = _stats(log, a, acct)

    a.checks.append(_check_outcome(log, a, slurm_state, acct))
    a.checks.append(_check_accounting(log, acct))
    a.checks.append(_check_watchdog(log))
    a.checks.append(_check_stall(log, a, stall_seconds))
    a.checks.append(_check_walltime(log, a, acct))
    a.checks.extend(_check_progress(log, a))
    a.checks.extend(_check_timers(log, a))
    a.checks.extend(_check_coupling(log, a))
    a.checks.extend(_check_io(log, a))
    a.checks.extend(_check_io_cadence(log, a))
    a.checks.extend(_check_network(log, a))
    a.checks.append(_check_errors(log, a))
    a.checks.extend(_check_groups(log, a))
    a.checks.append(_check_gpu_health(log))
    a.checks.append(_check_gpu_activity(log))
    a.checks.append(_check_dumps(log))
    a.checks.append(_check_kernel(log))
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


def _status(log: RunLog, now: float, stall_seconds: float, slurm_state: str, acct: dict) -> str:
    """SUCCESS, FAILED, QUEUED, RUNNING, STALLED or INCOMPLETE.

    STALLED means the scheduler still believes the job is running while its log
    has gone quiet, which is the one case in which intervention can still help.
    A log that simply stops without a verdict and is no longer in the queue is
    INCOMPLETE: the job has ended, and the silence check explains what
    happened. SLURM accounting, when available, settles the verdict of a log
    that ends without one.
    """
    acct_state = base_state(acct.get("state", ""))
    live = slurm_state or (acct_state if acct_state in ACTIVE_STATES else "")
    if live in {"PENDING", "CONFIGURING"}:
        return "QUEUED"
    if log.outcome and log.outcome.level == "fail":
        return "FAILED"
    if log.outcome and log.outcome.level == "ok":
        return "SUCCESS"
    if acct_state in FAILED_STATES:
        return "FAILED"
    if acct_state == "COMPLETED":
        return "SUCCESS" if acct.get("exit_code") == "0:0" else "FAILED"
    age = now - (log.last_wall or log.mtime or now)
    limit = max(stall_seconds, _setup_allowance(log) or 0.0)
    if live == "RUNNING":
        return "STALLED" if age >= limit else "RUNNING"
    return "RUNNING" if age < limit else "INCOMPLETE"


def _setup_allowance(log: RunLog) -> float | None:
    """Silence the job script's own watchdog tolerates before the main loop.

    Only while the run has not reached its loop: kernel compilation and input
    reading can legitimately keep a job silent far longer than the default
    threshold, and a script that declares how long says so better than any
    default.
    """
    allowance = log.fields.get("watchdog_init_timeout")
    return float(allowance) if allowance and not progress_series(log) else None


def _stats(log: RunLog, a: Assessment, acct: dict) -> dict[str, Any]:
    stats: dict[str, Any] = {
        # A log without timestamps has no duration, but the scheduler knows it.
        "wall_seconds": log.wall_seconds or acct.get("elapsed"),
        "lines": log.n_lines,
        "size": log.size,
        "nodes": log.fields.get("node_count") or len(log.nodes) or None,
        "max_gap": log.gaps[0].seconds if log.gaps else None,
    }
    series = progress_series(log)
    if series:
        stats["progress_last"] = series[-1].get("step")
        stats["progress_count"] = len(series)
    good = [i["seconds"] for i in steady(a.intervals) if i["seconds"] > 0]
    if good:
        stats["interval_median"] = statistics.median(good)
    model_secs = sum(i.get("model_seconds", 0.0) for i in a.intervals)
    wall_secs = sum(i["seconds"] for i in a.intervals)
    sypd = throughput(a.intervals)
    if sypd:
        stats["sypd"] = sypd
        stats["model_seconds"] = model_secs
        if len(steady(a.intervals)) < len(a.intervals):
            stats["sypd_steady"] = throughput(steady(a.intervals))
    if wall_secs > 0 and stats.get("progress_count"):
        stats["loop_seconds"] = wall_secs
    if a.timers:
        stats["timer_root_seconds"] = max(g.root_seconds for g in a.timers)
    return stats


def _check_outcome(log: RunLog, a: Assessment, slurm_state: str, acct: dict) -> Check:
    ev = []
    if log.outcome:
        ev.append(log.outcome.text)
    status_field = log.fields.get("srun_status")
    if status_field is not None:
        ev.append(f"srun exit status {status_field}")
    if slurm_state:
        ev.append(f"SLURM reports the job as {slurm_state}")
    if acct.get("state"):
        ev.append(f"SLURM accounting: {acct['state']}, exit code {acct.get('exit_code', '?')}")
    verdict = log.outcome and log.outcome.level in {"ok", "fail"}
    if a.status == "SUCCESS":
        headline = "The run reported success" if verdict else "SLURM recorded the job as completed"
        return Check("outcome", "Outcome", "ok", headline, "", ev)
    if a.status == "FAILED":
        if verdict:
            headline = log.outcome.text
        elif acct.get("state"):
            headline = f"SLURM recorded the job as {acct['state']}"
        else:
            headline = "The run failed"
        return Check(
            "outcome",
            "Outcome",
            "fail",
            headline,
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
        "Neither success nor failure was recorded. The job may have been terminated "
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
        "is normal, because input is being read and kernels compiled, so only "
        "silence inside the main loop is judged against the typical progress "
        "interval."
    )
    # Silence before the first progress report is startup, so it is judged
    # against a longer threshold unless the run never reached its main loop.
    reached_loop = bool(progress_series(log))
    setup_limit = float(log.threshold("setup_stall_seconds", stall_seconds * 4))
    allowance = _setup_allowance(log)
    if allowance:
        detail += (
            f" The job script's watchdog allows {format_duration(allowance)} of silence "
            "before the main loop, which is the limit applied until the loop starts."
        )
    for g in log.gaps:
        if _in_loop(log, g.start):
            hard = stall_seconds
        elif not reached_loop:
            hard = max(stall_seconds, allowance or 0.0)
        else:
            hard = None
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


def _check_walltime(log: RunLog, a: Assessment, acct: dict) -> Check | None:
    # The scheduler's account, when there is one, includes the time before the
    # first stamped line and after the last one.
    requested = acct.get("timelimit") or parse_walltime(
        log.keyvalues.get("sbatch", {}).get("time", "")
    )
    used = acct.get("elapsed") or log.wall_seconds
    if not requested or not used:
        return None
    frac = used / requested
    ev = [f"{format_duration(used)} used of {format_duration(requested)} requested"]
    timed_out = base_state(acct.get("state", "")) == "TIMEOUT"
    if timed_out or (log.outcome and "TIME LIMIT" in (log.outcome.text or "").upper()):
        return Check(
            "walltime",
            "Wall time",
            "fail",
            "The job hit its wall-clock limit",
            "SLURM canceled the job because the requested time ran out.",
            ev,
        )
    warn = float(log.threshold("walltime_warn", 0.9))
    if frac >= warn:
        return Check(
            "walltime",
            "Wall time",
            "warn",
            f"{frac * 100:.0f}% of the requested limit used",
            "Little margin remains. A slightly slower run would be canceled.",
            ev,
        )
    return Check(
        "walltime", "Wall time", "ok", f"{frac * 100:.0f}% of the requested limit used", "", ev
    )


def _check_progress(log: RunLog, a: Assessment) -> list[Check]:
    if not a.intervals:
        return []
    out: list[Check] = []
    runs = steady(a.intervals)
    good = [i["seconds"] for i in runs if i["seconds"] > 0]
    if not good:
        return []
    median = statistics.median(good)
    label = log.setting("progress_label", "events")
    unit = log.setting("throughput_label", "SYPD")
    sypd, sypd_steady = a.stats.get("sypd"), a.stats.get("sypd_steady")
    headline = f"{a.stats.get('progress_last')} {label}"
    if sypd:
        headline += f", {rate_text(sypd, unit)}"
        headline += " overall" if sypd_steady else ""
    if sypd_steady:
        headline += f", {rate_text(sypd_steady, unit)} after warm-up"
    ev = [
        f"typical interval {format_duration(median)} between progress reports",
        f"{format_duration(a.stats.get('loop_seconds'))} spent in the main loop",
    ]
    warm = [i for i in a.intervals if i.get("warmup")]
    if warm:
        ev.append(
            f"warm-up: first {len(warm)} interval(s), "
            f"{format_duration(sum(i['seconds'] for i in warm))}, "
            "excluded from the steady-state rate"
        )
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
    slow = [i for i in runs if i["seconds"] > factor * median]
    if slow:
        worst = sorted(slow, key=lambda i: -i["seconds"])[:5]
        out.append(
            Check(
                "outliers",
                "Slow intervals",
                "warn" if len(slow) > 1 else "info",
                f"{len(slow)} of {len(runs)} intervals took more than " f"{factor:g}x the median",
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


def _components(log: RunLog) -> list[tuple[str, int, int]]:
    """Rank range of every component, from the profile's ``*_ranks`` fields.

    A coupled model gives its components consecutive blocks of ranks in the
    order in which it announces them, so the counts alone place each component
    on the rank axis.
    """
    out: list[tuple[str, int, int]] = []
    start = 0
    for key, value in log.fields.items():
        if key.endswith("_ranks") and isinstance(value, int) and value > 0:
            out.append((key[: -len("_ranks")], start, start + value - 1))
            start += value
    return out


def _component_of(title: str, pattern: str, components: list[tuple[str, int, int]]) -> str:
    """Name the component a timer table belongs to, from the ranks in its title."""
    m = re.search(pattern, title) if pattern else None
    if not m:
        return ""
    first, last = int(m.group(1)), int(m.group(2))
    name = next((n for n, lo, hi in components if lo <= first <= hi), "")
    return name or f"ranks {first}-{last}"


def _check_coupling(log: RunLog, a: Assessment) -> list[Check]:
    """Compare how much of its time each component spends in the coupler.

    A coupled run prints one timer report per component, so the share of the
    coupling timers is directly comparable between them. The component with
    the much larger share is the one that arrives at the exchange first and
    then waits for its partner, which is the usual signature of a rank split
    that does not match the cost of the two components.
    """
    names = set(log.setting("coupling_timers", []) or [])
    waits = set(log.setting("coupling_wait_timers", []) or [])
    if not (names or waits) or not a.timers:
        return []
    components = _components(log)
    pattern = log.setting("timer_group_ranks", "")
    warn_share = float(log.threshold("coupling_share_warn", 0.15))
    warn_ratio = float(log.threshold("coupling_ratio_warn", 2.0))

    measured: list[tuple[float, str, str]] = []
    for g in a.timers:
        # A coupling timer nested below another one is already contained in it
        # and must not be added a second time.
        counted: list[TimerRow] = []
        nested: list[TimerRow] = []
        outer: int | None = None
        for r in g.rows:
            if outer is not None and r.depth <= outer:
                outer = None
            if r.label in names or r.label in waits:
                if outer is None:
                    counted.append(r)
                    outer = r.depth
                else:
                    nested.append(r)
        if not counted:
            continue
        share = sum(r.share for r in counted)
        label = _component_of(g.title, pattern, components) or g.title
        parts = ", ".join(
            f"{r.label} {r.share * 100:.0f}% ({format_duration(r.total)})"
            for r in sorted(counted + nested, key=lambda r: -r.share)
        )
        measured.append(
            (share, label, f"{label}: {share * 100:.0f}% of {g.root} in the coupler - {parts}")
        )
    if not measured:
        return []

    measured.sort(key=lambda m: -m[0])
    detail = (
        "The coupling timers cover the exchange itself together with the wait for the "
        "partner component. A share that is much larger in one component than in the "
        "other means that component reaches the exchange first and then waits, which "
        "usually calls for a different rank split. This never fails a run by itself."
    )
    if len(measured) > 1:
        (hi, hi_name, _), (lo, lo_name, _) = measured[0], measured[1]
        waiting = hi >= warn_share and (lo <= 0 or hi / lo >= warn_ratio)
        level = "warn" if waiting else ("info" if hi >= warn_share else "ok")
        headline = (
            f"{hi_name} spends {hi * 100:.0f}% of its time in the coupler against "
            f"{lo * 100:.0f}% for {lo_name}"
        )
        if waiting:
            headline += f": {hi_name} is waiting for {lo_name}"
    else:
        hi, hi_name, _ = measured[0]
        level = "info" if hi >= warn_share else "ok"
        headline = f"{hi_name} spends {hi * 100:.0f}% of its time in the coupler"
        detail += (
            " Only one timer report was found here, so the wait cannot be attributed "
            "to a partner component."
        )
    return [
        Check("coupling", "Coupling cost", level, headline, detail, [e for _, _, e in measured])
    ]


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


def _check_io_cadence(log: RunLog, a: Assessment) -> list[Check]:
    """Flag an uneven cadence between the events of an I/O series.

    A single output file that took far longer than its neighbors to appear is
    usually a transient file system stall rather than the model itself. This is
    the reasoning of the silence check, narrowed to one recurring event.
    """
    out = []
    factor = float(log.threshold("io_gap_outlier_factor", 4))
    for name, gaps in a.io_gaps.items():
        if len(gaps) < 4:
            continue
        seconds = [g["seconds"] for g in gaps]
        good = [s for s in seconds if s > 0]
        if not good:
            continue
        median = statistics.median(good)
        label = name.replace("_", " ")
        ev = [f"typical gap {format_duration(median)} across {len(gaps) + 1} events"]
        slow = sorted(
            (g for g in gaps if median and g["seconds"] > factor * median),
            key=lambda g: -g["seconds"],
        )
        if slow:
            ev += [
                f"{format_stamp(g['wall'])}: {format_duration(g['seconds'])} "
                f"({g['seconds'] / median:.0f}x the median)"
                for g in slow[:5]
            ]
            out.append(
                Check(
                    f"io_cadence_{name}",
                    f"{label.capitalize()} cadence",
                    "warn" if len(slow) > 1 else "info",
                    f"{len(slow)} of {len(gaps)} gaps between {label} events took more "
                    f"than {factor:g}x the typical {format_duration(median)}",
                    "An irregular cadence between recurring writes usually points at a "
                    "transient file system stall rather than the model itself.",
                    ev,
                )
            )
        else:
            out.append(
                Check(
                    f"io_cadence_{name}",
                    f"{label.capitalize()} cadence",
                    "ok",
                    f"Regular cadence, typical gap {format_duration(median)}",
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

    # Timeouts are retransmissions the fabric recovered from; an unrecoverable
    # one aborts the job, so the count alone rarely explains a failure.
    if timeouts is not None:
        ev.append(f"{timeouts} network timeouts")
        if timeouts:
            headline = f"{timeouts} network timeouts"
            if timeouts >= float(log.threshold("network_timeouts_fail", 100000)):
                level = "fail"
            elif timeouts >= float(log.threshold("network_timeouts_warn", 10000)) or (
                a.status in {"FAILED", "STALLED"}
            ):
                level = "warn"
            else:
                level = "info"

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
    """Busiest minute of a message family, when it is a burst rather than a steady rate."""
    if not stat.bins:
        return None
    minute, count = max(stat.bins.items(), key=lambda kv: kv[1])
    return (int(minute), count) if count > 0.25 * stat.total else None


def _node_blame(stat) -> str:
    """Name a node only when its share is clearly disproportionate."""
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
        "Lines that look like errors, collapsed by shape; digits are masked so "
        "that repetitions from many ranks group together.",
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


def _check_accounting(log: RunLog, acct: dict) -> Check | None:
    """The scheduler's record, and whether it agrees with the log."""
    if not acct.get("state"):
        return None
    state, code = acct["state"], acct.get("exit_code", "?")
    base = base_state(state)
    ev = [f"state {state}, exit code {code}"]
    if acct.get("elapsed") is not None:
        limit = acct.get("timelimit")
        ev.append(
            f"ran {format_duration(acct['elapsed'])}"
            + (f" of {format_duration(limit)} allowed" if limit else "")
        )
    if acct.get("nnodes"):
        ev.append(f"{acct['nnodes']} node(s): {acct.get('nodelist', '')}")
    if acct.get("start"):
        ev.append(
            f"{format_stamp(acct['start'])} to {format_stamp(acct.get('end')) or 'still running'}"
        )
    detail = (
        "The scheduler's own record of the job, which remains available when the log "
        "stops early, for example because the job was killed before its epilogue ran."
    )
    if base in ACTIVE_STATES:
        return Check(
            "accounting", "SLURM accounting", "info", f"The job is {state.lower()}", detail, ev
        )
    if base == "COMPLETED" and code == "0:0":
        return Check(
            "accounting", "SLURM accounting", "ok", "Completed with exit code 0", detail, ev
        )
    if log.outcome and log.outcome.level == "ok":
        return Check(
            "accounting",
            "SLURM accounting",
            "warn",
            f"SLURM recorded {state} with exit code {code} although the job script "
            "reported success",
            detail + " A command after the success message failed, for example the "
            "submission of the next job in a chain.",
            ev,
        )
    return Check("accounting", "SLURM accounting", "fail", f"{state}, exit code {code}", detail, ev)


def _check_watchdog(log: RunLog) -> Check | None:
    """Whether the job script's own hang detection fired."""
    fired = next((m for m in log.markers if m.name == "watchdog_fired"), None)
    in_loop = log.fields.get("watchdog_timeout")
    setup = log.fields.get("watchdog_init_timeout")
    if fired is None and not (in_loop or setup):
        return None
    armed = ", ".join(
        part
        for part in (
            f"{format_duration(in_loop)} in the main loop" if in_loop else "",
            f"{format_duration(setup)} before it" if setup else "",
        )
        if part
    )
    detail = (
        "A background loop in the job script that treats a log which has stopped "
        "growing as a hang, collects diagnostics on every node and then ends the "
        "model step, first with SIGABRT so that the runtimes print tracebacks."
    )
    ev = [f"timeouts: {armed}"] if armed else []
    if fired is None:
        headline = "Configured in the job script, did not fire"
        return Check("watchdog", "Hang watchdog", "ok", headline, detail, ev)
    steps = [m for m in log.markers if m.name.startswith("watchdog_")]
    ev += [f"{format_stamp(m.wall)}: {m.text}" for m in steps]
    idle = log.fields.get("watchdog_idle")
    silence = f"no output for {format_duration(idle)}" if idle else "a hang"
    return Check(
        "watchdog",
        "Hang watchdog",
        "fail",
        f"The watchdog found {silence} at {format_stamp(fired.wall)} and ended the step",
        detail,
        ev,
    )


def _gpus(log: RunLog):
    """Every monitored GPU as ``(node, index, aggregates)``."""
    for node, summary in sorted((log.diag.get("gpu") or {}).items()):
        for index, g in sorted(summary["gpus"].items(), key=lambda kv: int(kv[0])):
            yield node, index, g


def _check_gpu_health(log: RunLog) -> Check | None:
    """Uncorrected memory errors and hardware slowdown in the GPU monitor."""
    gpus = list(_gpus(log))
    if not gpus:
        return None
    ecc = [
        f"{node} GPU {i}: {int(g['ecc_max'])} uncorrected ECC error(s)"
        for node, i, g in gpus
        if g.get("ecc_max")
    ]
    slow = [
        f"{node} GPU {i}: {diag.SLOWDOWN_BITS[int(bit)]} in {n} of {g['samples']} samples"
        for node, i, g in gpus
        for bit, n in sorted(g["slowdown"].items())
    ]
    nodes = {node for node, _, _ in gpus}
    ev = ecc + slow
    temps = [g["temp_max"] for _, _, g in gpus if g.get("temp_max") is not None]
    power = [g["power_max"] for _, _, g in gpus if g.get("power_max") is not None]
    mem = [g["mem_max"] for _, _, g in gpus if g.get("mem_max") is not None]
    ev.append(f"{len(gpus)} GPU(s) on {len(nodes)} node(s), {_sample_interval(log)}")
    peaks = []
    if temps:
        peaks.append(f"{max(temps):.0f} °C")
    if power:
        peaks.append(f"{max(power):.0f} W")
    if mem:
        peaks.append(f"{max(mem) / 1024:.1f} GiB memory")
    if peaks:
        ev.append("peak " + ", ".join(peaks))
    detail = (
        "From the per-node GPU monitor in the diagnostics directory. Uncorrected ECC "
        "errors mean the GPU memory returned wrong data; a hardware slowdown, thermal "
        "slowdown or power brake means the GPU ran below its clocks, which makes its "
        "node the slowest of the run."
    )
    if ecc:
        headline = f"{len(ecc)} GPU(s) with uncorrected ECC errors: {ecc[0]}"
        return Check("gpu_health", "GPU health", "fail", headline, detail, ev[:20])
    if slow:
        headline = f"{len(slow)} GPU(s) slowed down by the hardware: {slow[0]}"
        return Check("gpu_health", "GPU health", "warn", headline, detail, ev[:20])
    return Check(
        "gpu_health",
        "GPU health",
        "ok",
        f"No ECC errors or hardware slowdown on {len(gpus)} GPU(s)",
        detail,
        ev,
    )


def _sample_interval(log: RunLog) -> str:
    spans = [
        (s["last"] - s["first"]) / max(1, max(g["samples"] for g in s["gpus"].values()) - 1)
        for s in (log.diag.get("gpu") or {}).values()
        if s.get("first") is not None and s.get("last") is not None
    ]
    spans = [s for s in spans if s > 0]
    return f"sampled every {format_duration(statistics.median(spans))}" if spans else "one sample"


GPU_BUSY = 50.0  # mean utilization above which a GPU counts as busy
GPU_IDLE = 5.0


def _silence_window(log: RunLog) -> tuple[str, float] | None:
    """The monitor window covering the longest silence, and its length.

    For a hung job the silence is usually the tail after its last line, which
    the gap list does not contain, so the tail wins when the monitor kept
    sampling for longer after the log stopped than the longest gap lasted.
    """
    d = log.diag
    windows = d.get("windows", {})
    last = max((s["last"] for s in (d.get("gpu") or {}).values() if s.get("last")), default=None)
    tail = (last - log.last_wall) if last and log.last_wall else 0.0
    gap = windows.get("silence")
    gap_len = (gap[1] - gap[0]) if gap else 0.0
    if tail >= diag.MIN_SILENCE and tail > gap_len:
        return "tail", tail
    if gap_len >= diag.MIN_SILENCE:
        return "silence", gap_len
    return None


def _check_gpu_activity(log: RunLog) -> Check | None:
    """How busy the GPUs were in the main loop, and during the longest silence."""
    gpu = log.diag.get("gpu")
    if not gpu:
        return None
    ev: list[str] = []
    headline = ""
    level = "ok"
    loop = diag.node_utils(gpu, "loop") or diag.node_utils(gpu, None)
    where = "in the main loop" if diag.node_utils(gpu, "loop") else "over the whole run"
    if loop:
        median = statistics.median(loop.values())
        lo, hi = min(loop, key=loop.get), max(loop, key=loop.get)
        headline = f"GPUs {median:.0f}% busy {where} (median over {len(loop)} node(s))"
        if lo != hi:
            ev.append(f"node means {where}: {loop[lo]:.0f}% on {lo} to {loop[hi]:.0f}% on {hi}")
        odd = [n for n, u in loop.items() if abs(u - median) >= 20]
        if odd and len(loop) > 2:
            level = "info"
            ev += [f"{n}: {loop[n]:.0f}% against a median of {median:.0f}%" for n in odd[:8]]
    silence = _silence_window(log)
    if silence:
        window, seconds = silence
        per_gpu = [
            (node, i, u)
            for node, i, g in _gpus(log)
            if (u := diag.mean_util(g, window)) is not None
        ]
        if per_gpu:
            busy = [(n, i, u) for n, i, u in per_gpu if u >= GPU_BUSY]
            idle = [x for x in per_gpu if x[2] < GPU_IDLE]
            span = format_duration(seconds)
            if busy and len(busy) < len(per_gpu):
                level = "info"
                headline = (
                    f"During the {span} of silence {len(busy)} of {len(per_gpu)} GPU(s) "
                    f"stayed busy while {len(idle)} were idle"
                )
                ev += [f"busy during the silence: {n} GPU {i} ({u:.0f}%)" for n, i, u in busy[:8]]
            elif busy:
                headline = f"All {len(per_gpu)} GPU(s) stayed busy during the {span} of silence"
            else:
                headline = f"All {len(per_gpu)} GPU(s) were idle during the {span} of silence"
    if not headline:
        return None
    return Check(
        "gpu_activity",
        "GPU activity",
        level,
        headline,
        "Mean utilization from the GPU monitor. In a run whose ranks advance in "
        "lockstep, a node much busier than the others is the one the rest wait for. "
        "During a hang, the GPUs still busy point at the ranks that did not reach "
        "the point where the others wait.",
        ev,
    )


def _ranges(values: list[int]) -> str:
    """``0-3, 7, 9-12`` from a sorted list of integers."""
    runs: list[list[int]] = []
    for v in values:
        if runs and v == runs[-1][1] + 1:
            runs[-1][1] = v
        else:
            runs.append([v, v])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


PROC_STATES = {
    "R": "running",
    "S": "sleeping",
    "D": "uninterruptible (I/O)",
    "T": "stopped",
    "Z": "zombie",
}


def _check_dumps(log: RunLog) -> Check | None:
    """Where the ranks were when the hang was dumped."""
    d = log.diag.get("dumps")
    if not d:
        return None
    groups = d.get("groups", [])
    ev = [
        f"{len(g['ranks'])} rank(s) [{_ranges(g['ranks'])}] on {len(g['nodes'])} node(s): "
        f"{g['place']}"
        for g in groups[:8]
    ]
    states = d.get("states", {})
    if states:
        ev.append(
            "process states: "
            + ", ".join(f"{PROC_STATES.get(s, s)} {n}" for s, n in sorted(states.items()))
        )
    if d.get("wchan"):
        top = sorted(d["wchan"].items(), key=lambda kv: -kv[1])[:4]
        ev.append("kernel wait channels: " + ", ".join(f"{w} {n}" for w, n in top))
    if groups:
        biggest = groups[0]
        headline = (
            f"{d['ranks']} backtrace(s) in {len(groups)} distinct place(s); "
            f"{len(biggest['ranks'])} rank(s) in {biggest['place'][:90]}"
        )
    else:
        headline = f"Process states of {sum(states.values())} rank(s)"
    level = "warn" if states.get("D") else "info"
    return Check(
        "hang_dumps",
        "Hang backtraces",
        level,
        headline,
        "Backtraces of the main thread taken by gdb while the job hung, grouped by the "
        "innermost frame and the innermost frame with a source location. The small "
        "groups are usually the interesting ones: the ranks the others wait for. Ranks "
        "in uninterruptible sleep are blocked in the kernel, typically on I/O.",
        ev,
    )


# GPU Xid events that indicate a hardware or driver fault rather than a bug in
# the application (NVIDIA's Xid catalog).
FATAL_XID = {"48", "63", "64", "74", "79", "92", "94", "95", "119", "120"}


def _check_kernel(log: RunLog) -> Check | None:
    """GPU Xid events and out-of-memory kills in the nodes' kernel logs."""
    k = log.diag.get("kernel")
    if not k:
        return None
    readable = {n: v for n, v in k.items() if v.get("readable", True)}
    if not readable:
        return Check(
            "kernel",
            "Kernel messages",
            "info",
            "The kernel log was not readable",
            "dmesg is restricted on these nodes.",
        )
    ev = []
    level = "ok"
    for node, v in sorted(readable.items()):
        if v.get("xid"):
            codes = ", ".join(f"Xid {c} ({n}x)" for c, n in sorted(v["xid"].items()))
            ev.append(f"{node}: {codes}")
            fatal = bool(set(v["xid"]) & FATAL_XID)
            level = "fail" if fatal or level == "fail" else "warn"
        if v.get("oom"):
            ev.append(f"{node}: {v['oom']} out-of-memory kill(s)")
            level = "fail"
        if v.get("sample") and len(ev) < 12:
            ev.append(f"    {v['sample']}")
    headline = (
        f"GPU or memory faults on {sum(1 for v in readable.values() if v.get('xid') or v.get('oom'))} "
        "node(s)"
        if ev
        else f"No GPU Xid or out-of-memory messages on {len(readable)} node(s)"
    )
    return Check(
        "kernel",
        "Kernel messages",
        level,
        headline,
        "Kernel logs collected on each node. An Xid is the GPU driver reporting a "
        "fault; codes such as 48, 79 or 94 point at the hardware, others at the "
        "application.",
        ev[:20],
    )


def _diag_suspects(log: RunLog) -> list[tuple[str, str]]:
    """Nodes the diagnostics directory implicates."""
    out = []
    for node, i, g in _gpus(log):
        if g.get("ecc_max"):
            out.append((node, f"uncorrected ECC errors on GPU {i}"))
        for bit in g["slowdown"]:
            out.append((node, f"{diag.SLOWDOWN_BITS[int(bit)]} on GPU {i}"))
    for node, v in (log.diag.get("kernel") or {}).items():
        if set(v.get("xid", {})) & FATAL_XID:
            out.append((node, "GPU Xid " + ", ".join(sorted(v["xid"]))))
        if v.get("oom"):
            out.append((node, "out-of-memory kill"))
    silence = _silence_window(log)
    if silence:
        per_gpu = [(n, diag.mean_util(g, silence[0])) for n, _, g in _gpus(log)]
        busy = {n for n, u in per_gpu if u is not None and u >= GPU_BUSY}
        if busy and len(busy) < len({n for n, _ in per_gpu}):
            out += [(n, "GPUs busy during the silence while others were idle") for n in busy]
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
    for node, why in _diag_suspects(log):
        reasons.setdefault(node, []).append(why)
    return sorted(((n, "; ".join(v[:3])) for n, v in reasons.items()))
