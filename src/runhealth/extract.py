"""Turn a log file into a :class:`RunLog`: one streaming pass, bounded memory.

Everything a profile declares is applied here, plus three things the core does
for every log regardless of profile:

* **silence** -- the wall-clock distance between consecutive lines. A hung job
  looks exactly like a healthy one in every other respect, so the largest gaps
  are the most valuable single measurement in the file.
* **error signatures** -- error-looking lines collapsed by shape, so an
  unfamiliar failure still surfaces without anyone having written a rule.
* **node attribution** -- which compute nodes appear, and in what company.

The extractor is resumable: :meth:`Extractor.state` round-trips through JSON so
``--watch`` can continue from where the previous pass stopped instead of
re-reading a 150 MB file every tick.
"""

from __future__ import annotations

import heapq
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .logfile import Line, iter_lines, parse_walltime, sniff
from .profile import Profile
from .tables import Table, TableReader

# Error-looking lines that no profile claimed. Deliberately broad: a false
# positive costs one row in a collapsed table, a false negative hides a crash.
ERROR_RE = re.compile(
    r"\b(?:error|fatal|abort|panic|segmentation fault|bus error|killed|"
    r"out of memory|oom-kill|cannot allocate|traceback|assertion failed|"
    r"exceeded|not permitted|permission denied|no space left)\b",
    re.IGNORECASE,
)
# Lines that match ERROR_RE but say nothing about this run's health.
ERROR_SKIP_RE = re.compile(
    r"(?:^\+ |^\+\+|check_error|FI_LOG_LEVEL|--error=|error_|"
    r"stderr|2>&1|set -e|errexit|^\s*(?:print|echo|cat|if|fi|else)\b|"
    r"\bprint\(|\becho\b.*['\"])",
    re.IGNORECASE,
)
NODE_RE = re.compile(r"\b(nid\d{4,}|[a-z][a-z0-9-]*\d{3,})\b")
MASK_RE = re.compile(r"0x[0-9a-fA-F]+|\d+")

# A resubmitted job can append to the same file. The second attempt starts
# with an unstamped copy of the job script, which is how we spot the seam.
ATTEMPT_STAMPED_MIN = 20
ATTEMPT_GAP_STAMPED_MIN = 5
ATTEMPT_UNSTAMPED_RUN = 3
ATTEMPT_GAP_FALLBACK = 6 * 3600.0

MAX_GROUP_KEYS = 4000
MAX_ERROR_KEYS = 200
MAX_EVENTS = 50_000
TOP_GAPS = 25


@dataclass
class Gap:
    """A stretch of wall-clock silence between two consecutive lines."""

    seconds: float
    start: float
    end: float
    before: str
    after: str
    rank: int | None = None
    line: int = 0


@dataclass
class GroupStat:
    """A high-cardinality message family, counted rather than stored."""

    label: str
    total: int = 0
    keys: dict[str, int] = field(default_factory=dict)
    nodes: dict[str, int] = field(default_factory=dict)
    bins: dict[str, int] = field(default_factory=dict)
    first_wall: float | None = None
    last_wall: float | None = None
    sample: str = ""


@dataclass
class Marker:
    name: str
    wall: float | None
    text: str
    line: int = 0
    label: str = ""


@dataclass
class Outcome:
    level: str
    text: str
    wall: float | None = None


@dataclass
class RunLog:
    """Everything one pass over a log yielded."""

    path: str = ""
    name: str = ""
    run_id: str = ""
    size: int = 0
    mtime: float = 0.0
    offset: int = 0
    line_format: str = "plain"
    profiles: list[str] = field(default_factory=list)
    n_lines: int = 0
    first_wall: float | None = None
    last_wall: float | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    keyvalues: dict[str, dict[str, str]] = field(default_factory=dict)
    series: dict[str, list[dict]] = field(default_factory=dict)
    series_roles: dict[str, str] = field(default_factory=dict)
    markers: list[Marker] = field(default_factory=list)
    groups: dict[str, GroupStat] = field(default_factory=dict)
    errors: dict[str, GroupStat] = field(default_factory=dict)
    tables: dict[str, list[Table]] = field(default_factory=dict)
    gaps: list[Gap] = field(default_factory=list)
    nodes: dict[str, int] = field(default_factory=dict)
    outcome: Outcome | None = None
    attempts: int = 1
    settings: dict[str, Any] = field(default_factory=dict)
    thresholds: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def wall_seconds(self) -> float | None:
        if self.first_wall is None or self.last_wall is None:
            return None
        return self.last_wall - self.first_wall

    def setting(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def threshold(self, key: str, default: Any) -> Any:
        v = self.thresholds.get(key)
        return default if v is None else v

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tables"] = {k: [t.to_dict() for t in v] for k, v in self.tables.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RunLog":
        d = dict(d)
        d["markers"] = [Marker(**m) for m in d.get("markers", [])]
        d["gaps"] = [Gap(**g) for g in d.get("gaps", [])]
        d["groups"] = {k: GroupStat(**v) for k, v in d.get("groups", {}).items()}
        d["errors"] = {k: GroupStat(**v) for k, v in d.get("errors", {}).items()}
        d["tables"] = {k: [Table.from_dict(t) for t in v] for k, v in d.get("tables", {}).items()}
        oc = d.get("outcome")
        d["outcome"] = Outcome(**oc) if oc else None
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def _mask(text: str) -> str:
    return MASK_RE.sub("#", text.strip())[:200]


def _bump(counter: dict[str, int], key: str, cap: int) -> None:
    if key in counter:
        counter[key] += 1
    elif len(counter) < cap:
        counter[key] = 1


class Extractor:
    """Applies a set of profiles to a stream of decoded lines."""

    def __init__(self, profiles: list[Profile], log: RunLog | None = None):
        self.profiles = profiles
        self.log = log or RunLog()
        self.log.profiles = [p.name for p in profiles]
        for p in profiles:
            self.log.settings.update(p.settings)
            self.log.thresholds.update(p.thresholds)
        self._fields = [r for p in profiles for r in p.fields]
        self._keyvalues = [r for p in profiles for r in p.keyvalues]
        self._series = [r for p in profiles for r in p.series]
        self._markers = [r for p in profiles for r in p.markers]
        self._groups = [r for p in profiles for r in p.groups]
        self._tables = [r for p in profiles for r in p.tables]
        self._outcome = [r for p in profiles for r in p.outcome]
        self._boundary = [r for p in profiles for r in p.boundary]
        for r in self._series:
            self.log.series.setdefault(r.name, [])
            self.log.series_roles[r.name] = r.spec.get("role", "")
        for r in self._groups:
            self.log.groups.setdefault(r.name, GroupStat(label=r.spec.get("label", r.name)))
        self._gap_heap: list[tuple[float, int, Gap]] = []
        self._seq = 0
        self._prev_wall: float | None = None
        self._prev_text: str = ""
        self._reader: TableReader | None = None
        self._reader_name: str = ""
        self._reader_rank: int | None = None
        self._t0: float | None = self.log.first_wall
        self._min_gap = 1.0
        self._has_preamble = False
        self._stamped_since_reset = 0
        self._unstamped: list[Line] = []

    # -- resume support ---------------------------------------------------

    def state(self) -> dict:
        d = self.log.to_dict()
        d["_prev_wall"] = self._prev_wall
        d["_prev_text"] = self._prev_text
        d["_stamped_since_reset"] = self._stamped_since_reset
        return d

    @classmethod
    def resume(cls, profiles: list[Profile], state: dict) -> "Extractor":
        prev_wall = state.pop("_prev_wall", None)
        prev_text = state.pop("_prev_text", "")
        stamped = state.pop("_stamped_since_reset", 0)
        ex = cls(profiles, RunLog.from_dict(state))
        ex._prev_wall = prev_wall
        ex._prev_text = prev_text
        ex._stamped_since_reset = stamped
        ex._t0 = ex.log.first_wall
        for g in ex.log.gaps:
            ex._seq += 1
            heapq.heappush(ex._gap_heap, (g.seconds, ex._seq, g))
        return ex

    # -- main loop --------------------------------------------------------

    def feed(self, line: Line) -> None:
        log = self.log
        log.n_lines += 1
        log.offset = line.offset
        text = line.text
        # Many run scripts echo a copy of themselves before output is stamped.
        # That copy contains every string the script can ever print, so rules
        # must not fire there -- except the ones that want it (#SBATCH).
        in_preamble = log.line_format == "timestamped" and log.first_wall is None
        if self._has_preamble and self._detect_new_attempt(line):
            return
        if line.wall is not None:
            if log.first_wall is None or line.wall < log.first_wall:
                log.first_wall = line.wall
                self._t0 = log.first_wall
            if log.last_wall is None or line.wall > log.last_wall:
                log.last_wall = line.wall
            if self._prev_wall is not None:
                delta = line.wall - self._prev_wall
                if delta >= self._min_gap:
                    self._push_gap(delta, line, text)
            self._prev_wall = line.wall
        if text:
            self._prev_text = text

        if self._reader is not None and self._feed_table(line, text):
            return
        if not text:
            return

        skip = self._skip
        for rule in self._fields:
            if not skip(rule, in_preamble):
                self._do_field(rule, text)
        for rule in self._keyvalues:
            if skip(rule, in_preamble):
                continue
            m = rule.search(text)
            if m and m.lastindex and m.lastindex >= 2:
                log.keyvalues.setdefault(rule.name, {})[m.group(1)] = m.group(2).strip()
        if in_preamble and self._has_preamble:
            return
        for rule in self._series:
            self._do_series(rule, text, line)
        for rule in self._markers:
            self._do_marker(rule, text, line)
        claimed = False
        for rule in self._groups:
            claimed |= self._do_group(rule, text, line)
        for rule in self._tables:
            if self._reader is None:
                self._open_table(rule, text, line)
        for rule in self._outcome:
            m = rule.search(text)
            if m:
                log.outcome = Outcome(
                    level=rule.spec.get("level", "info"),
                    text=(m.group(1) if m.lastindex else m.group(0)).strip()[:400],
                    wall=line.wall,
                )
        if not claimed:
            self._do_error(text, line)

    def _detect_new_attempt(self, line: Line) -> bool:
        """Reset the analysis when a second job attempt starts in the same file.

        Three signals, any of which is conclusive once enough of an attempt has
        been seen: a run of unstamped lines (a job script echoing itself again),
        a pause longer than the wall-clock limit the scheduler would have
        enforced, or a boundary pattern the profile declares.
        """
        settled = self._stamped_since_reset >= ATTEMPT_STAMPED_MIN
        if settled and line.text.strip():
            for rule in self._boundary:
                if rule.search(line.text):
                    self._reset_attempt()
                    return False
        if line.wall is not None:
            # A pause longer than the scheduler's own limit cannot be inside
            # one attempt, so this signal needs far less evidence than the rest.
            if self._stamped_since_reset >= ATTEMPT_GAP_STAMPED_MIN and self._prev_wall:
                if line.wall - self._prev_wall > self._attempt_gap():
                    self._reset_attempt()
                    return False
            self._stamped_since_reset += 1
            self._unstamped.clear()
            return False
        if not line.text.strip():
            return False
        self._unstamped.append(line)
        if (
            len(self._unstamped) < ATTEMPT_UNSTAMPED_RUN
            or self._stamped_since_reset < ATTEMPT_STAMPED_MIN
        ):
            return False
        buffered = list(self._unstamped)
        self._reset_attempt()
        for b in buffered:
            self.feed(b)
        return True

    def _attempt_gap(self) -> float:
        """A pause this long cannot happen inside one scheduled job."""
        limit = parse_walltime(self.log.keyvalues.get("sbatch", {}).get("time", ""))
        # Half again the limit: the scheduler kills at the limit, but the
        # epilogue keeps writing for a while afterwards.
        return max((limit or ATTEMPT_GAP_FALLBACK) * 1.5, 900.0)

    def _reset_attempt(self) -> None:
        keep = self.log
        fresh = RunLog(
            path=keep.path,
            name=keep.name,
            run_id=keep.run_id,
            size=keep.size,
            mtime=keep.mtime,
            offset=keep.offset,
            line_format=keep.line_format,
            profiles=list(keep.profiles),
            attempts=keep.attempts + 1,
            settings=dict(keep.settings),
            thresholds=dict(keep.thresholds),
            n_lines=keep.n_lines,
        )
        # The job script header belongs to the file, not to one attempt.
        fresh.keyvalues["sbatch"] = dict(keep.keyvalues.get("sbatch", {}))
        self.log = fresh
        for r in self._series:
            fresh.series.setdefault(r.name, [])
            fresh.series_roles[r.name] = r.spec.get("role", "")
        for r in self._groups:
            fresh.groups.setdefault(r.name, GroupStat(label=r.spec.get("label", r.name)))
        self._gap_heap.clear()
        self._min_gap = 1.0
        self._prev_wall = None
        self._prev_text = ""
        self._t0 = None
        self._reader = None
        self._reader_rank = None
        self._stamped_since_reset = 0
        self._unstamped.clear()

    def _skip(self, rule, in_preamble: bool) -> bool:
        if not self._has_preamble:
            return False
        return bool(rule.spec.get("preamble", False)) != in_preamble

    def finish(self) -> RunLog:
        if self._reader is not None:
            self._close_table()
        self.log.gaps = sorted(
            (g for _, _, g in self._gap_heap), key=lambda g: g.seconds, reverse=True
        )
        return self.log

    # -- pieces -----------------------------------------------------------

    def _push_gap(self, delta: float, line: Line, text: str) -> None:
        self._seq += 1
        gap = Gap(
            seconds=delta,
            start=self._prev_wall or 0.0,
            end=line.wall or 0.0,
            before=self._prev_text[:200],
            after=text[:200],
            rank=line.rank,
            line=line.number,
        )
        if len(self._gap_heap) < TOP_GAPS:
            heapq.heappush(self._gap_heap, (delta, self._seq, gap))
        elif delta > self._gap_heap[0][0]:
            heapq.heapreplace(self._gap_heap, (delta, self._seq, gap))
            # Once the shortlist is full, ignore anything smaller outright.
            self._min_gap = max(self._min_gap, self._gap_heap[0][0])

    def _do_field(self, rule, text: str) -> None:
        name = rule.name
        keep = rule.spec.get("keep", "first")
        if keep == "first" and name in self.log.fields:
            return
        m = rule.search(text)
        if not m:
            return
        raw = m.group(int(rule.spec.get("group", 1)) if m.lastindex else 0)
        self.log.fields[name] = _cast(raw, rule.spec.get("cast"))

    def _do_series(self, rule, text: str, line: Line) -> None:
        bucket = self.log.series[rule.name]
        if len(bucket) >= MAX_EVENTS:
            return
        m = rule.search(text)
        if not m:
            return
        names = rule.spec.get("fields") or []
        casts = rule.spec.get("cast") or {}
        if not isinstance(casts, dict):
            casts = {}
        rec: dict[str, Any] = {"wall": line.wall}
        for i, key in enumerate(names, start=1):
            if m.lastindex and i <= m.lastindex:
                rec[key] = _cast(m.group(i), casts.get(key))
        bucket.append(rec)

    def _do_marker(self, rule, text: str, line: Line) -> None:
        if not rule.spec.get("all") and any(m.name == rule.name for m in self.log.markers):
            return
        m = rule.search(text)
        if m:
            self.log.markers.append(
                Marker(
                    rule.name,
                    line.wall,
                    text.strip()[:200],
                    line.number,
                    rule.spec.get("label", rule.name.replace("_", " ")),
                )
            )

    def _do_group(self, rule, text: str, line: Line) -> bool:
        m = rule.search(text)
        if not m:
            return False
        stat = self.log.groups[rule.name]
        stat.total += 1
        idx = rule.spec.get("key", 0)
        try:
            key = m.group(int(idx)) or m.group(0)
        except (IndexError, ValueError, TypeError):
            key = m.group(0)
        _bump(stat.keys, _mask(key), MAX_GROUP_KEYS)
        node_idx = rule.spec.get("node")
        node = None
        if node_idx is not None:
            try:
                node = m.group(int(node_idx))
            except (IndexError, ValueError, TypeError):
                node = None
        if node is None:
            nm = NODE_RE.search(text)
            node = nm.group(1) if nm else None
        if node:
            _bump(stat.nodes, node, MAX_GROUP_KEYS)
            _bump(self.log.nodes, node, MAX_GROUP_KEYS)
        if not stat.sample:
            stat.sample = text.strip()[:300]
        if line.wall is not None:
            stat.first_wall = stat.first_wall if stat.first_wall is not None else line.wall
            stat.last_wall = line.wall
            if self._t0 is not None:
                _bump(stat.bins, str(int((line.wall - self._t0) // 60)), 100_000)
        return bool(rule.spec.get("claim"))

    def _do_error(self, text: str, line: Line) -> None:
        if not ERROR_RE.search(text) or ERROR_SKIP_RE.search(text):
            return
        key = _mask(text)
        stat = self.log.errors.get(key)
        if stat is None:
            if len(self.log.errors) >= MAX_ERROR_KEYS:
                return
            stat = GroupStat(label=key, sample=text.strip()[:300], first_wall=line.wall)
            self.log.errors[key] = stat
        stat.total += 1
        stat.last_wall = line.wall
        nm = NODE_RE.search(text)
        if nm:
            _bump(stat.nodes, nm.group(1), 512)
            _bump(self.log.nodes, nm.group(1), MAX_GROUP_KEYS)

    def _open_table(self, rule, text: str, line: Line) -> None:
        m = rule.search(text)
        if not m:
            return
        self._reader = TableReader(rule.name, rule.spec, text.strip()[:120], line.wall)
        self._reader_name = rule.name
        self._reader_rank = line.rank
        if self._reader.include_start:
            self._reader.feed(text)

    def _feed_table(self, line: Line, text: str) -> bool:
        """Feed a line to the open table. Returns True if it was consumed."""
        if self._reader_rank is not None and line.rank != self._reader_rank:
            return False  # another rank's output interleaved; not part of the table
        if not self._reader.feed(text):
            self._close_table()
        return True

    def _close_table(self) -> None:
        table = self._reader.table
        if table.rows:
            self.log.tables.setdefault(self._reader_name, []).append(table)
        self._reader = None
        self._reader_rank = None


def _cast(raw: str, kind: str | None):
    if kind == "int":
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return None
    if kind == "float":
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    return raw.strip() if isinstance(raw, str) else raw


def parse(
    path: Path,
    profiles: list[Profile],
    start: int = 0,
    state: dict | None = None,
) -> RunLog:
    """Read ``path`` from ``start`` and return the accumulated :class:`RunLog`."""
    ex = Extractor.resume(profiles, state) if state else Extractor(profiles)
    log = ex.log
    st = path.stat()
    log.path = str(path)
    log.name = path.name
    log.size = st.st_size
    log.mtime = st.st_mtime
    if not start:
        log.line_format = sniff(path)
    ex._has_preamble = log.line_format == "timestamped"
    for line in iter_lines(path, start):
        ex.feed(line)
    ex.log.offset = st.st_size
    if ex.log.attempts > 1:
        ex.log.notes.append(
            f"This file holds {ex.log.attempts} job attempts; only the last is analysed."
        )
    return ex.finish()
