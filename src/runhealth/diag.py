"""Diagnostics a job script leaves next to its log, summarized for the checks.

A job script can write a directory ``diag.<job name>.<job id>/`` beside its log
with the output of standard tools, which says far more about a hang or a sick
node than the log itself. Every part is optional and recognized by name:

``gpu/<node>.csv``
    ``nvidia-smi --query-gpu=... --format=csv -l <seconds>``, one file per node.
    Columns are found by their header, so their order and number may vary.
``<node>/gdb_rank<N>.txt``
    ``gdb -batch -ex 'thread apply all bt'`` of one rank, taken during a hang.
``<node>/proc_rank<N>.txt``
    ``/proc/<pid>/status`` of one rank, followed by a ``wchan:`` line.
``<node>/dmesg.txt``
    The tail of the kernel ring buffer.

The summary is plain JSON so that it is cached together with the parsed log.
"""

from __future__ import annotations

import os
import re
import statistics
from collections import Counter
from pathlib import Path

from .extract import RunLog
from .logfile import parse_stamp

# NVML clock event reasons that mean the hardware slowed the GPU down, as
# opposed to idling or an application clock setting.
SLOWDOWN_BITS = {
    0x8: "hardware slowdown",
    0x20: "software thermal slowdown",
    0x40: "hardware thermal slowdown",
    0x80: "hardware power brake",
}
GPU_COLUMNS = {
    "timestamp": "timestamp",
    "index": "index",
    "utilization.gpu": "util",
    "memory.used": "mem",
    "power.draw": "power",
    "temperature.gpu": "temp",
    "clocks_event_reasons.active": "reasons",
    "clocks_throttle_reasons.active": "reasons",
    "ecc.errors.uncorrected.volatile.total": "ecc",
}
MIN_SILENCE = 120.0  # shorter silences are too brief to say anything about the GPUs
FRAME_RE = re.compile(r"^#\d+\s+(?:0x[0-9a-f]+ in )?(\S+) \(")
SOURCE_RE = re.compile(r" at (\S+):(\d+)\s*$")
THREAD_RE = re.compile(r"^Thread (\d+) ")
RANK_FILE_RE = re.compile(r"_rank(\d+)\.txt$")
XID_RE = re.compile(r"NVRM: Xid \(([^)]*)\): (\d+)")
OOM_RE = re.compile(r"Out of memory: Kill|oom-kill|Memory cgroup out of memory")


def locate(log: RunLog) -> Path | None:
    """The diagnostics directory of a run, if the job script wrote one."""
    for key in ("diag_dir", "diag_dir_on_failure"):
        named = log.fields.get(key)
        if named and Path(named).is_dir():
            return Path(named)
    job_id = log.fields.get("job_id")
    if not job_id or not log.path:
        return None
    hits = sorted(p for p in Path(log.path).parent.glob(f"diag.*.{job_id}") if p.is_dir())
    return hits[0] if hits else None


def signature(path: Path | None) -> str:
    """Changes whenever a file in the directory is added or grows."""
    if path is None:
        return ""
    count = size = 0
    latest = 0.0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                st = os.stat(os.path.join(root, name))
            except OSError:
                continue
            count += 1
            size += st.st_size
            latest = max(latest, st.st_mtime)
    return f"{count}:{size}:{latest:.0f}"


def collect(log: RunLog, path: Path | None = None) -> dict:
    """Summary of the diagnostics directory of ``log``, or ``{}`` if there is none."""
    path = path or locate(log)
    if path is None:
        return {}
    windows = _windows(log)
    out: dict = {"dir": str(path), "windows": windows}
    gpu_dir = path / "gpu"
    if gpu_dir.is_dir():
        nodes = {}
        for f in sorted(gpu_dir.glob("*.csv")):
            summary = _gpu_file(f, windows)
            if summary:
                nodes[f.stem] = summary
        if nodes:
            out["gpu"] = nodes
    dumps = _dumps(path)
    if dumps:
        out["dumps"] = dumps
    kernel = _kernel(path)
    if kernel:
        out["kernel"] = kernel
    return out


def _windows(log: RunLog) -> dict[str, list]:
    """Wall-clock stretches the GPU samples are averaged over.

    ``loop`` runs from the first to the last progress report. ``silence`` is the
    longest stretch without output, which for a hung job is often the tail
    after its last line rather than a gap between two lines.
    """
    out: dict[str, list] = {}
    name = log.settings.get("progress_series")
    series = log.series.get(name) if name else None
    if not series:
        series = next(
            (log.series[k] for k, role in log.series_roles.items() if role == "progress"), []
        )
    walls = [s["wall"] for s in series if s.get("wall") is not None]
    if len(walls) >= 2:
        out["loop"] = [walls[0], walls[-1]]
    if log.gaps and log.gaps[0].seconds >= MIN_SILENCE:
        out["silence"] = [log.gaps[0].start, log.gaps[0].end]
    if log.last_wall is not None:
        out["tail"] = [log.last_wall, None]
    return out


def _number(text: str) -> float | None:
    token = text.strip().split(" ")[0]
    try:
        return float(int(token, 16)) if token.startswith("0x") else float(token)
    except ValueError:
        return None


def _gpu_file(path: Path, windows: dict[str, list]) -> dict:
    """Per-GPU aggregates of one node's monitor file."""
    gpus: dict[str, dict] = {}
    cols: dict[str, int] = {}
    first = last = None
    with path.open(errors="replace") as fh:
        for raw in fh:
            parts = [p.strip() for p in raw.split(",")]
            if not cols:
                for i, head in enumerate(parts):
                    key = GPU_COLUMNS.get(head.split(" [")[0])
                    if key:
                        cols[key] = i
                if "timestamp" not in cols or "index" not in cols:
                    return {}
                continue
            if len(parts) <= max(cols.values()):
                continue
            wall = parse_stamp(parts[cols["timestamp"]])
            if wall is None:
                continue
            first = wall if first is None else first
            last = wall
            g = gpus.setdefault(parts[cols["index"]], _empty_gpu())
            g["samples"] += 1
            values = {
                k: _number(parts[i]) for k, i in cols.items() if k not in ("timestamp", "index")
            }
            for key in ("mem", "power", "temp", "ecc"):
                v = values.get(key)
                if v is not None:
                    g[f"{key}_max"] = max(g[f"{key}_max"] or 0.0, v)
            reasons = int(values.get("reasons") or 0)
            for bit in SLOWDOWN_BITS:
                if reasons & bit:
                    g["slowdown"][str(bit)] = g["slowdown"].get(str(bit), 0) + 1
            util = values.get("util")
            if util is None:
                continue
            g["util_n"] += 1
            g["util_sum"] += util
            for name, (lo, hi) in windows.items():
                if lo <= wall and (hi is None or wall <= hi):
                    w = g["windows"].setdefault(name, {"n": 0, "sum": 0.0, "max": 0.0})
                    w["n"] += 1
                    w["sum"] += util
                    w["max"] = max(w["max"], util)
    if not gpus:
        return {}
    return {"first": first, "last": last, "gpus": gpus}


def _empty_gpu() -> dict:
    return {
        "samples": 0,
        "util_n": 0,
        "util_sum": 0.0,
        "mem_max": None,
        "power_max": None,
        "temp_max": None,
        "ecc_max": None,
        "slowdown": {},
        "windows": {},
    }


def _dumps(path: Path) -> dict:
    """Where the ranks were when the hang was dumped, grouped by place."""
    places: dict[str, dict] = {}
    states: Counter = Counter()
    wchans: Counter = Counter()
    ranks = 0
    for node_dir in sorted(p for p in path.iterdir() if p.is_dir() and p.name != "gpu"):
        for f in sorted(node_dir.glob("gdb_rank*.txt")):
            m = RANK_FILE_RE.search(f.name)
            frames = _main_thread(f)
            if not m or not frames:
                continue
            ranks += 1
            key = _place(frames)
            entry = places.setdefault(
                key, {"place": key, "frames": frames[:6], "ranks": [], "nodes": []}
            )
            entry["ranks"].append(int(m.group(1)))
            if node_dir.name not in entry["nodes"]:
                entry["nodes"].append(node_dir.name)
        for f in node_dir.glob("proc_rank*.txt"):
            state, wchan = _proc(f)
            if state:
                states[state] += 1
            if wchan:
                wchans[wchan] += 1
    if not ranks and not states:
        return {}
    groups = sorted(places.values(), key=lambda g: (-len(g["ranks"]), g["place"]))
    for g in groups:
        g["ranks"].sort()
    return {"ranks": ranks, "groups": groups, "states": dict(states), "wchan": dict(wchans)}


def _main_thread(path: Path) -> list[str]:
    """Frames of the lowest-numbered thread, innermost first, as ``func`` or ``func (file:line)``."""
    threads: dict[int, list[str]] = {}
    current = 0  # a plain "bt" has no thread headers
    with path.open(errors="replace") as fh:
        for line in fh:
            t = THREAD_RE.match(line)
            if t:
                current = int(t.group(1))
                continue
            m = FRAME_RE.match(line)
            if m:
                src = SOURCE_RE.search(line)
                frame = m.group(1)
                if src:
                    frame += f" ({Path(src.group(1)).name}:{src.group(2)})"
                threads.setdefault(current, []).append(frame)
    return threads[min(threads)] if threads else []


def _place(frames: list[str]) -> str:
    """The innermost frame, plus the innermost one with a source location.

    The innermost frame says what the rank is doing (polling, waiting on a
    lock), the first frame with source says where in the program it is.
    """
    source = next((f for f in frames if " (" in f), "")
    if not source or source == frames[0]:
        return frames[0]
    return f"{frames[0]} <- {source}"


def _proc(path: Path) -> tuple[str, str]:
    state = wchan = ""
    with path.open(errors="replace") as fh:
        for line in fh:
            if line.startswith("State:"):
                state = line.split(":", 1)[1].strip()[:1]
            elif line.startswith("wchan:"):
                wchan = line.split(":", 1)[1].strip()
    return state, wchan if wchan not in ("", "0") else ""


def _kernel(path: Path) -> dict:
    """GPU Xid events and out-of-memory kills in each node's kernel log."""
    out: dict[str, dict] = {}
    for f in sorted(path.glob("*/dmesg.txt")):
        xids: Counter = Counter()
        oom = 0
        sample = ""
        readable = True
        with f.open(errors="replace") as fh:
            for line in fh:
                if "read kernel buffer failed" in line:
                    readable = False
                m = XID_RE.search(line)
                if m:
                    xids[m.group(2)] += 1
                    sample = sample or line.strip()[:200]
                elif OOM_RE.search(line):
                    oom += 1
                    sample = sample or line.strip()[:200]
        out[f.parent.name] = {"readable": readable, "xid": dict(xids), "oom": oom, "sample": sample}
    return out


def mean_util(g: dict, window: str | None = None) -> float | None:
    """Mean utilization of one GPU over a window, or over all its samples."""
    if window is None:
        return g["util_sum"] / g["util_n"] if g["util_n"] else None
    w = g["windows"].get(window)
    return w["sum"] / w["n"] if w and w["n"] else None


def node_utils(gpu: dict, window: str | None) -> dict[str, float]:
    """Mean utilization of every node over a window."""
    out = {}
    for node, summary in gpu.items():
        values = [u for g in summary["gpus"].values() if (u := mean_util(g, window)) is not None]
        if values:
            out[node] = statistics.mean(values)
    return out
