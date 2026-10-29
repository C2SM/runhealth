"""The Sirocco workflow a run belongs to.

Sirocco runs every task of a cycle in a directory of its own, named after the
task and the cycle's coordinates, such as ``run/icon__date_2020-01-01T00-00-00``,
under the workflow's root, which holds the configuration (``sirocco.yaml`` and
the plain ``sirocco.resolved.yaml``), the log of the workflow manager
(``sirocco.log``) and its state (``run/state.yaml``). A run whose log lies in
such a directory is one chunk of a workflow: its position among the cycles,
the job that restarts from it and the events the workflow manager recorded for
it come from these files. A copy of a run directory that lost the configuration
keeps what the state and the log say, and nothing is read from elsewhere.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml

# Any one of these marks the root of a workflow.
ROOT_FILES = ("sirocco.resolved.yaml", "sirocco.yaml", "sirocco.log")
TASK_DIR = re.compile(r"^(?P<task>[A-Za-z0-9_-]+?)__(?P<coords>[A-Za-z0-9_].*)$")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
LOG_STAMP = re.compile(r"\u2524 (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) \u251c")
LOG_EVENT = re.compile(r"(?P<dir>\S+__\S+) \((?P<job>[^)]*)\) (?P<what>[A-Z]+)\b ?(?P<rest>.*)$")
LOG_ROOT = re.compile(r"Starting workflow at\s+(?P<path>.+?)\s+\.\.\.", re.S)
PERIOD = re.compile(
    r"^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$"
)
# Settings of a task worth showing beside its run, in this order.
TASK_KEYS = (
    "plugin",
    "computer",
    "account",
    "partition",
    "nodes",
    "walltime",
    "procs_per_node",
    "cores_per_proc",
    "uenv",
    "view",
)
# Events of the workflow manager that end a task, as a status level.
EVENT_LEVEL = {"COMPLETED": "ok", "FAILED": "fail", "CANCELED": "fail", "SUBMITTED": "info"}
EVENT_END = ("COMPLETED", "FAILED", "CANCELED")


@dataclass
class Event:
    """One line of ``sirocco.log`` about a task."""

    when: str
    dirname: str
    job: str
    what: str
    detail: str = ""


@dataclass
class Workflow:
    root: Path
    name: str
    config: dict = field(default_factory=dict)
    # Task directory name to the job id and state ``state.yaml`` records.
    state: dict[str, tuple[str, str]] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
    finished: bool = False

    def cycle_of(self, task: str) -> tuple[str, dict]:
        """The name and definition of the cycle that runs ``task``."""
        for entry in self.config.get("cycles") or []:
            for name, cycle in (entry or {}).items():
                if any(task in (t or {}) for t in (cycle or {}).get("tasks") or []):
                    return name, cycle
        return "", {}

    def task_config(self, task: str) -> dict:
        """The task's settings, over those every task inherits from ``ROOT``."""
        merged: dict = {}
        for entry in self.config.get("tasks") or []:
            for name, spec in (entry or {}).items():
                if name in ("ROOT", task) and isinstance(spec, dict):
                    merged.update(spec)
        return merged

    def dates(self, task: str) -> list[str]:
        """The cycle dates the task runs at, from the configuration or what is known of it."""
        _, cycle = self.cycle_of(task)
        cycling = cycle.get("cycling") or {}
        step = parse_period(str(cycling.get("period") or ""))
        start, stop = _date(cycling.get("start_date")), _date(cycling.get("stop_date"))
        if step and start and stop:
            out, at = [], start
            while at < stop and len(out) < 10000:
                out.append(at.isoformat())
                at = step(at)
            return out
        known = {_dir_date(d, task) for d in [*self.state, *(e.dirname for e in self.events)]}
        return sorted(d for d in known if d)

    def status(self) -> str:
        """``completed``, ``failed`` or ``running``, as far as the log and state say."""
        if self.finished:
            return "completed"
        last = self.last_events()
        if any(e.what in ("FAILED", "CANCELED") for e in last.values()):
            return "failed"
        return "running" if last or self.state else "unknown"

    def last_events(self) -> dict[str, Event]:
        """The latest event of every task directory that is not a mere promotion."""
        out: dict[str, Event] = {}
        for e in self.events:
            if e.what in EVENT_LEVEL:
                out[e.dirname] = e
        return out


@dataclass
class Chunk:
    """One run as a task at one cycle of a workflow."""

    workflow: Workflow
    task: str
    dirname: str
    date: str = ""
    index: int | None = None
    count: int | None = None
    end: str = ""
    restart: bool = False

    @property
    def label(self) -> str:
        """For example ``icon · 2020-01-01 → 01-02 · chunk 1/2 · cold start``."""
        parts = [self.task]
        if self.date:
            span = self.date[:10]
            if self.end:
                end = self.end[:10]
                span += " \u2192 " + (end[5:] if end[:4] == span[:4] else end)
            parts.append(span)
        if self.index is not None:
            parts.append(f"chunk {self.index + 1}" + (f"/{self.count}" if self.count else ""))
            parts.append("restart" if self.restart else "cold start")
        return " \u00b7 ".join(parts)

    @property
    def key(self) -> tuple:
        return (self.index if self.index is not None else 1 << 30, self.date, self.task)

    def workflow_job(self) -> str:
        """The job the workflow last ran this chunk as."""
        last = self.workflow.last_events().get(self.dirname)
        if last:
            return last.job
        return self.workflow.state.get(self.dirname, ("", ""))[0]

    def job_state(self, job: str) -> str:
        """How the workflow recorded the end of ``job``: COMPLETED, FAILED, CANCELED or nothing."""
        ends = [e.what for e in self.events() if e.job == job and e.what in EVENT_END]
        if ends:
            return "FAILED" if "FAILED" in ends else ends[-1]
        return "COMPLETED" if self.workflow.state.get(self.dirname) == (job, "completed") else ""

    def events(self) -> list[Event]:
        return [e for e in self.workflow.events if e.dirname == self.dirname]


# -- reading --------------------------------------------------------------


def split_dir(name: str) -> tuple[str, dict[str, str]] | None:
    """``icon__date_2020-01-01T00-00-00`` as ``("icon", {"date": "2020-01-01T00-00-00"})``."""
    m = TASK_DIR.match(name)
    if not m:
        return None
    coords = {}
    for part in m["coords"].split("__"):
        key, sep, value = part.partition("_")
        if not sep:
            return None
        coords[key] = value
    return m["task"], coords


def coord_date(value: str) -> str:
    """A date as it appears in a directory name or ``state.yaml``, in ISO form."""
    m = re.match(r"^(\d{4}-\d\d-\d\d)[T ](\d\d)[-:](\d\d)[-:](\d\d)", value or "")
    return f"{m[1]}T{m[2]}:{m[3]}:{m[4]}" if m else ""


def _dir_date(dirname: str, task: str) -> str:
    split = split_dir(dirname)
    return coord_date(split[1].get("date", "")) if split and split[0] == task else ""


def _date(value) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = coord_date(str(value or ""))
    return datetime.fromisoformat(text) if text else None


def parse_period(text: str):
    """An ISO 8601 duration such as ``P1M`` or ``PT6H`` as a function that adds it to a date."""
    m = PERIOD.match(text.strip())
    if not m or not any(m.groups()):
        return None
    y, mo, w, d, h, mi, s = (int(g or 0) for g in m.groups())
    delta = timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)

    def step(at: datetime) -> datetime:
        month = at.month - 1 + mo + 12 * y
        year, month = at.year + month // 12, month % 12 + 1
        day = min(at.day, calendar.monthrange(year, month)[1])
        return at.replace(year=year, month=month, day=day) + delta

    return step


def find_root(task_dir: Path) -> Path | None:
    """The workflow root above a task directory: the highest of two levels with a Sirocco file."""
    found = None
    for d in (task_dir.parent, task_dir.parent.parent):
        if any((d / f).is_file() for f in ROOT_FILES):
            found = d
    return found


def _state(root: Path) -> dict[str, tuple[str, str]]:
    path = next(
        (p for p in (root / "run" / "state.yaml", root / "state.yaml") if p.is_file()), None
    )
    if path is None:
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}

    def entries(items, state):
        for item in items or []:
            if isinstance(item, list):
                yield from entries(item, state)
                continue
            for task, spec in (item or {}).items():
                coords = (spec or {}).get("coordinates") or {}
                parts = "".join(
                    f"__{k}_{coord_date(str(v)).replace(':', '-') or v}" for k, v in coords.items()
                )
                yield f"{task}{parts}", (str((spec or {}).get("jobid") or ""), state)

    return dict(
        [*entries(data.get("completed_tasks"), "completed"), *entries(data.get("front"), "queued")]
    )


def _log(root: Path) -> tuple[list[Event], bool, str]:
    """The task events of ``sirocco.log``, whether the workflow completed, and its original root."""
    try:
        text = ANSI.sub("", (root / "sirocco.log").read_text(errors="replace"))
    except OSError:
        return [], False, ""
    events, when = [], ""
    for line in text.splitlines():
        if m := LOG_STAMP.search(line):
            when = m[1]
        elif m := LOG_EVENT.search(line):
            events.append(Event(when, m["dir"], m["job"], m["what"], m["rest"].strip()))
    origin = ""
    if m := LOG_ROOT.search(text):
        # The log wraps long paths across lines.
        origin = re.sub(r"\s*\n\s*", "", m["path"])
    return events, "Workflow completed" in text, origin


def _config(root: Path) -> dict:
    """The resolved configuration; the template is only read when it needs no rendering."""
    for name in ("sirocco.resolved.yaml", "sirocco.yaml"):
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(errors="replace")
        if name == "sirocco.yaml" and ("{{" in text or "{%" in text):
            continue
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def load(root: Path) -> Workflow:
    config = _config(root)
    events, finished, origin = _log(root)
    name = str(config.get("name") or Path(origin).name or root.name)
    return Workflow(root, name, config, _state(root), events, finished)


def chunk_of(log_path: str | Path, cache: dict[Path, Workflow | None]) -> Chunk | None:
    """The chunk a log belongs to, or None when it lies outside a Sirocco task directory."""
    task_dir = Path(log_path).resolve().parent
    split = split_dir(task_dir.name)
    if split is None:
        return None
    root = find_root(task_dir)
    if root is None:
        return None
    if root not in cache:
        cache[root] = load(root)
    wf = cache[root]
    task, coords = split
    date = coord_date(coords.get("date", ""))
    c = Chunk(wf, task, task_dir.name, date)
    if date:
        dates = wf.dates(task)
        if date in dates:
            c.index, c.count = dates.index(date), len(dates)
            c.count = c.count if wf.config else None
            nxt = dates[c.index + 1] if c.index + 1 < len(dates) else ""
            _, cycle = wf.cycle_of(task)
            stop = (cycle.get("cycling") or {}).get("stop_date") or wf.config.get("stop_date")
            c.end = nxt or coord_date(str(stop or ""))
        # Without the configuration, a later chunk is assumed to restart from the one before it.
        _, cycle = wf.cycle_of(task)
        c.restart = bool(c.index) and ("target_cycle" in str(cycle) or not wf.config)
    return c
