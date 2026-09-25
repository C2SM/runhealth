"""SLURM accounting: the scheduler's own record of a job, from ``sacct``.

A log states what the job script printed, which is nothing at all when the job
is killed before its epilogue runs. The accounting database still knows how the
job ended (``TIMEOUT``, ``NODE_FAIL``, ``OUT_OF_MEMORY``, ``CANCELLED by <uid>``),
its exit code and how long it ran, including jobs that ``squeue`` has long
forgotten.
"""

from __future__ import annotations

import os
import pwd
import shlex
import shutil
import subprocess
from collections.abc import Iterable

from .extract import RunLog
from .logfile import parse_stamp, parse_walltime

FIELDS = [
    "JobIDRaw",
    "JobID",
    "State",
    "ExitCode",
    "Elapsed",
    "Timelimit",
    "NNodes",
    "NodeList",
    "Start",
    "End",
]
BATCH = 200  # job ids per sacct call, well below the command line limit
# Final states in which the job did not complete its work.
FAILED_STATES = {
    "BOOT_FAIL",
    "CANCELLED",
    "DEADLINE",
    "FAILED",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "TIMEOUT",
}
ACTIVE_STATES = {
    "PENDING",
    "CONFIGURING",
    "RUNNING",
    "COMPLETING",
    "REQUEUED",
    "RESIZING",
    "SUSPENDED",
}


def base_state(state: str) -> str:
    """``CANCELLED`` from ``CANCELLED by 25060``."""
    return (state or "").split()[0] if state else ""


def _user(uid: str) -> str:
    try:
        return pwd.getpwuid(int(uid)).pw_name
    except (KeyError, ValueError):
        return uid


def parse(text: str, users: bool = True) -> dict[str, dict]:
    """Records keyed by job id, from ``sacct -P -n`` output in the order of ``FIELDS``.

    A requeued job appears once per run; the last row is the current one. With
    ``users`` off, a canceling uid is kept as is, since it belongs to another machine.
    """
    out: dict[str, dict] = {}
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) != len(FIELDS):
            continue
        row = dict(zip(FIELDS, parts))
        state = row["State"].strip()
        words = state.split()
        if users and len(words) == 3 and words[1] == "by":
            state = f"{words[0]} by {_user(words[2])}"
        rec = {
            "state": state,
            "exit_code": row["ExitCode"].strip(),
            "elapsed": parse_walltime(row["Elapsed"]),
            "timelimit": parse_walltime(row["Timelimit"]),
            "nnodes": int(row["NNodes"]) if row["NNodes"].strip().isdigit() else None,
            "nodelist": row["NodeList"].strip(),
            "start": parse_stamp(row["Start"].strip()),
            "end": parse_stamp(row["End"].strip()),
        }
        for key in {row["JobIDRaw"].strip(), row["JobID"].strip()} - {""}:
            out[key] = rec
    return out


def query(job_ids: Iterable[str], host: str | None = None, timeout: float = 30) -> dict[str, dict]:
    """Accounting records for ``job_ids``, or empty if ``sacct`` is unavailable.

    With ``host``, ``sacct`` runs there over ``ssh``, which must work without a prompt.
    """
    ids = sorted({j for j in job_ids if j})
    if not ids or shutil.which("ssh" if host else "sacct") is None:
        return {}
    # Absolute timestamps, whatever the user's own SLURM_TIME_FORMAT says.
    stamp = "SLURM_TIME_FORMAT=%Y-%m-%dT%H:%M:%S"
    env = dict(os.environ, SLURM_TIME_FORMAT=stamp.partition("=")[2])
    out: dict[str, dict] = {}
    for i in range(0, len(ids), BATCH):
        command = [
            "sacct",
            "-X",
            "-P",
            "-n",
            "-j",
            ",".join(ids[i : i + BATCH]),
            f"--format={','.join(FIELDS)}",
        ]
        if host:
            command = ["ssh", "-o", "BatchMode=yes", host, shlex.join(["env", stamp, *command])]
        try:
            r = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env)
        except (OSError, subprocess.SubprocessError):
            return out
        if r.returncode != 0:
            return out
        out.update(parse(r.stdout, users=not host))
    return out


def fill_times(log: RunLog, record: dict | None) -> None:
    """Take the start and end of a log without timestamps from the accounting record.

    Such a log carries at most the stamp SLURM puts on its own messages, typically
    the cancellation at the very end, which would otherwise pass for the start.
    """
    if not record or log.line_format == "timestamped" or not record.get("start"):
        return
    log.first_wall = record["start"]
    if record.get("end"):
        log.last_wall = max(log.last_wall or record["end"], record["end"])
