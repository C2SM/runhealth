"""The machine-readable summary a report carries beside its pages.

``summary.json`` holds the verdict on every run in a form that a workflow
manager, a script or a test can read without parsing HTML. Its layout is part
of the stable interface: fields may be added, but a field is only removed or
changed together with an increase of ``schema_version``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, simoutput
from .health import LEVEL_RANK
from .report import RunView

SUMMARY_FILE = "summary.json"
SCHEMA_VERSION = 1
# Statistics of a run that are part of the summary, by their key in the assessment.
STATS = ["wall_seconds", "nodes", "sypd", "sypd_steady", "sim_seconds", "progress_last"]


def _utc(t: float | None) -> str | None:
    return datetime.fromtimestamp(t, timezone.utc).isoformat() if t is not None else None


def worst(views: list[RunView]) -> str:
    return max((v.assessment.grade for v in views), key=LEVEL_RANK.get, default="ok")


def run(view: RunView, page: bool = True) -> dict:
    """One run: what it is, how it ended, and every check."""
    log, a = view.log, view.assessment
    clock = [a.stats.get(k) for k in ("sim_start", "sim_end")]
    return {
        "name": log.name,
        "log": str(Path(log.path).resolve()),
        "job_id": log.fields.get("job_id"),
        "job_name": log.fields.get("job_name"),
        "page": view.page if page else None,
        "status": a.status,
        "grade": a.grade,
        "started": _utc(log.first_wall),
        "ended": _utc(log.last_wall),
        "model_start": clock[0].isoformat() if clock[0] else None,
        "model_end": clock[1].isoformat() if clock[1] else None,
        "stats": {k: a.stats.get(k) for k in STATS},
        "checks": [
            {"key": c.key, "title": c.title, "level": c.level, "headline": c.headline}
            for c in a.checks
        ],
        "output": _output(log),
        "sirocco": _sirocco(view),
    }


def _sirocco(view: RunView) -> dict | None:
    """The Sirocco workflow and chunk the run belongs to, if any."""
    c = view.chunk
    if c is None:
        return None
    return {
        "workflow": c.workflow.name,
        "root": str(c.workflow.root),
        "workflow_status": c.workflow.status(),
        "task": c.task,
        "date": c.date or None,
        "chunk": c.index + 1 if c.index is not None else None,
        "chunks": c.count,
        "restart": c.restart,
        "workflow_job_id": c.workflow_job() or None,
    }


def _output(log) -> dict:
    """Each output variable's statistics per output step, as parallel lists."""
    out = {}
    for name, records in simoutput.series(log.output).items():
        out[name] = {
            "time": [r["time"] for r in records],
            **{k: [r[k] for r in records] for k in ("min", "max", "nonfinite")},
            "means": {level: [r["means"][level] for r in records] for level in records[0]["means"]},
        }
    return out


def build(views: list[RunView], page: bool = True) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "runhealth": __version__,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "grade": worst(views),
        "runs": [run(v, page) for v in views],
    }


def write(views: list[RunView], outdir: Path, page: bool = True) -> Path:
    path = outdir / SUMMARY_FILE
    path.write_text(json.dumps(build(views, page), indent=1) + "\n")
    return path
