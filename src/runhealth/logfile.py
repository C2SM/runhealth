"""Line grammar of a batch job log: timestamps, rank labels, streaming reads.

Batch logs reach us in three shapes, and the difference decides how much a
health report can say about *when* things happened:

``timestamped``
    Every line carries a wall clock, because the run script pipes its output
    through a stamping helper (ICON's ``utils/timewarp`` does exactly this).
    With ``srun -l`` a right-aligned MPI rank follows the stamp.
``ranked``
    Plain ``srun -l``: a rank but no wall clock.
``plain``
    Neither.

Only the timestamped shape supports silence detection, which is the single
most valuable signal in a hung run, so the reader reports which shape it found
and the rest of the tool degrades honestly rather than inventing timings.

Reading is strictly line by line. Real logs here reach 150 MB and 800k lines,
so nothing may hold a file, or a list of its lines, in memory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

# "2026-09-01T13:45:57.628: " as written by a stamping wrapper, and the
# "[2026-08-21T23:50:06.031] error: ..." that slurmd injects unstamped.
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?): ?")
BRACKET_TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)\] ?")
# srun -l pads the rank to a fixed width; require the colon-space to avoid
# swallowing model text that happens to start with digits.
RANK_RE = re.compile(r"^ {0,8}(\d{1,7}): ?")

SNIFF_LINES = 3000
SNIFF_TAIL = 256 << 10
_DAY_EPOCH: dict[str, float] = {}


def parse_stamp(s: str) -> float | None:
    """Seconds since the epoch for ``YYYY-MM-DDThh:mm:ss[.frac]``, else None.

    Hand-rolled rather than ``strptime`` because this runs once per line of a
    file that can hold a million of them.
    """
    try:
        day = _DAY_EPOCH.get(s[:10])
        if day is None:
            d = datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]), tzinfo=timezone.utc)
            day = d.timestamp()
            _DAY_EPOCH[s[:10]] = day
        secs = day + int(s[11:13]) * 3600 + int(s[14:16]) * 60 + int(s[17:19])
        if len(s) > 20 and s[19] == ".":
            frac = s[20:]
            secs += int(frac) / (10 ** len(frac))
        return secs
    except (ValueError, IndexError):
        return None


def format_stamp(t: float | None) -> str:
    if t is None:
        return ""
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


WALLTIME_RE = re.compile(r"^(?:(\d+)-)?(\d+):(\d+)(?::(\d+))?$")


def parse_walltime(text: str) -> float | None:
    """Seconds from a SLURM ``--time`` value (``3:00:00``, ``1-12:00``, ``30``)."""
    text = (text or "").strip()
    if text.isdigit():
        return int(text) * 60.0
    m = WALLTIME_RE.match(text)
    if not m:
        return None
    days, a, b, c = m.groups()
    # Without a seconds field SLURM reads the pair as hours:minutes.
    h, mi, s = (int(a), int(b), int(c)) if c else (int(a), int(b), 0)
    return int(days or 0) * 86400 + h * 3600 + mi * 60 + s


def format_duration(seconds: float | None) -> str:
    """Compact human duration: ``2h 13m 07s``, ``46s``, ``0.35s``."""
    if seconds is None:
        return ""
    if seconds < 10:
        return f"{seconds:.2f}s"
    total = int(round(seconds))
    m, s = divmod(total, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d:
        return f"{d}d {h:02d}h {m:02d}m"
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


@dataclass(slots=True)
class Line:
    """One decoded log line."""

    wall: float | None
    rank: int | None
    text: str
    offset: int
    number: int


def _decode(raw: str, offset: int, number: int) -> Line:
    wall = None
    rest = raw
    m = TS_RE.match(rest)
    if m:
        wall = parse_stamp(m.group(1))
        rest = rest[m.end() :]
    else:
        m = BRACKET_TS_RE.match(rest)
        if m:
            wall = parse_stamp(m.group(1))
    rank = None
    m = RANK_RE.match(rest)
    if m:
        rank = int(m.group(1))
        rest = rest[m.end() :]
    return Line(wall, rank, rest.rstrip("\n"), offset, number)


def _sample(fh, limit: int) -> tuple[int, int, int]:
    stamped = ranked = seen = 0
    for i, raw in enumerate(fh):
        if i >= limit:
            break
        line = _decode(raw.decode("utf-8", "replace"), 0, i)
        seen += 1
        stamped += line.wall is not None
        ranked += line.rank is not None
    return stamped, ranked, seen


def sniff(path: Path) -> str:
    """Return the line shape: ``timestamped``, ``ranked`` or ``plain``.

    Sampled from both ends. A run script that echoes a copy of itself before
    output is stamped can push thousands of unstamped lines in front of the
    first real one, so the head alone is not conclusive.
    """
    stamped = ranked = seen = 0
    try:
        with path.open("rb") as fh:
            stamped, ranked, seen = _sample(fh, SNIFF_LINES)
        start = tail_offset(path, SNIFF_TAIL)
        if start:
            with path.open("rb") as fh:
                fh.seek(start)
                s2, r2, n2 = _sample(fh, SNIFF_LINES)
            stamped, ranked, seen = stamped + s2, ranked + r2, seen + n2
    except OSError:
        return "plain"
    if not seen:
        return "plain"
    if stamped / seen > 0.15:
        return "timestamped"
    return "ranked" if ranked / seen > 0.3 else "plain"


def iter_lines(path: Path, start: int = 0) -> Iterator[Line]:
    """Yield decoded lines from byte offset ``start`` to end of file."""
    offset = start
    number = 0
    with path.open("rb") as fh:
        if start:
            fh.seek(start)
        for raw in fh:
            yield _decode(raw.decode("utf-8", "replace"), offset, number)
            offset += len(raw)
            number += 1


def tail_offset(path: Path, window: int) -> int:
    """Byte offset of a line boundary at most ``window`` bytes before the end."""
    size = path.stat().st_size
    if size <= window:
        return 0
    with path.open("rb") as fh:
        fh.seek(size - window)
        fh.readline()  # discard the partial line
        return fh.tell()
