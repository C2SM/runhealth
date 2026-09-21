"""Compare a run script with the one the previous run of the same kind used.

Two runs belong together when their job name matches: a generated run script
carries its own name as ``--job-name``, so the name is what distinguishes one
simulation from another rather than the log file, which differs per job.

The comparison is a unified diff with a few lines of context. What changes
between two runs of the same experiment is usually a handful of directives,
and printing the whole script around them would bury them.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

from .extract import RunLog
from .highlight import bash_html

CONTEXT = 3
# A job id appended to a log name, which is what SLURM's LOG.%x.%j.o leaves.
JOB_ID_SUFFIX = re.compile(r"[._-]\d{4,}$")


def run_kind(log: RunLog) -> str:
    """The name that decides which runs are the same kind of simulation."""
    name = (log.fields.get("job_name") or "").strip()
    if name:
        return name
    # Without SLURM metadata the log name is the only name there is; the job
    # id has to go, or every run looks like a kind of its own.
    stem = Path(log.path).stem or log.name
    return JOB_ID_SUFFIX.sub("", stem) or stem


@dataclass
class Diff:
    """One unified diff, ready to render."""

    added: int = 0
    removed: int = 0
    rows: str = ""

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)

    @property
    def summary(self) -> str:
        return f"+{self.added} −{self.removed}" if self.changed else "no change"


def _row(kind: str, old: object, new: object, text: str) -> str:
    return (
        f'<tr class="{kind}"><td class="ln">{old}</td><td class="ln">{new}</td>'
        f'<td class="tx">{bash_html(text)}</td></tr>'
    )


def compare(old: str, new: str, context: int = CONTEXT) -> Diff:
    """``old`` against ``new``, as counted changes and table rows."""
    a, b = old.splitlines(), new.splitlines()
    out = Diff()
    rows: list[str] = []
    for group in difflib.SequenceMatcher(None, a, b).get_grouped_opcodes(context):
        i1, j1 = group[0][1], group[0][3]
        i2, j2 = group[-1][2], group[-1][4]
        head = f"@@ -{i1 + 1},{i2 - i1} +{j1 + 1},{j2 - j1} @@"
        rows.append(f'<tr class="hunk"><td class="tx" colspan="3">{head}</td></tr>')
        for tag, ai, aj, bi, bj in group:
            if tag == "equal":
                rows += [_row("ctx", ai + k + 1, bi + k + 1, a[ai + k]) for k in range(aj - ai)]
                continue
            if tag in ("replace", "delete"):
                rows += [_row("del", n + 1, "", a[n]) for n in range(ai, aj)]
                out.removed += aj - ai
            if tag in ("replace", "insert"):
                rows += [_row("add", "", n + 1, b[n]) for n in range(bi, bj)]
                out.added += bj - bi
    if rows:
        out.rows = f'<table class="diff"><tbody>{"".join(rows)}</tbody></table>'
    return out
