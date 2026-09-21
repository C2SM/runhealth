"""The search index a report carries beside its pages.

A report is a directory of static pages that has to work from a ``file://``
URL with no server, so the index travels as a script that assigns one object
to ``window``. It is written once per report and loaded only when a reader
first opens the search, which leaves a page that is never searched as cheap
as it was before.

The run scripts are most of what the index holds. They are the one place in
which a reader looks for a literal string, such as the number of nodes a run
requested or the module version it loaded, and a report already holds every
script it has seen.
"""

from __future__ import annotations

import json
from pathlib import Path

from .logfile import format_stamp
from .report import RunView, field_anchor, provenance_pairs

INDEX_FILE = "search.js"


def _checks(view: RunView) -> list[list[str]]:
    """Every check as ``[level, title, headline, searchable extra]``."""
    return [
        [c.level, c.title, c.headline, " ".join([c.detail, *c.evidence]).strip()]
        for c in view.assessment.checks
    ]


def entry(view: RunView) -> dict:
    """One run, as much of it as is worth searching."""
    log, a = view.log, view.assessment
    job, model = provenance_pairs(log)
    return {
        "page": view.page,
        "name": log.fields.get("job_name") or log.name,
        "file": Path(log.path).name,
        "job": log.fields.get("job_id") or "",
        "started": format_stamp(log.first_wall),
        "status": a.status,
        "grade": a.grade,
        "source": view.source or log.path,
        "script": log.runscript,
        "checks": _checks(view),
        # The anchor is the row the field is shown in, so a result on it
        # takes the reader to that row and not merely to the page.
        "fields": [[k, v, field_anchor(k)] for k, v in job + model if v],
    }


def payload(views: list[RunView]) -> dict:
    return {
        "runs": [entry(v) for v in sorted(views, key=lambda v: v.log.first_wall or 0, reverse=True)]
    }


def write(views: list[RunView], outdir: Path) -> str:
    """Write the index beside the report. Returns the file name pages load."""
    # A closing tag inside the data would end the element that loads it; the
    # escape is a plain solidus to JSON and to the parser that reads it back.
    text = json.dumps(payload(views), separators=(",", ":")).replace("</", "<\\/")
    (outdir / INDEX_FILE).write_text(f"window.RUNHEALTH_SEARCH={text};\n")
    return INDEX_FILE
