"""Write the small hand-built logs the tests run against."""

from datetime import datetime, timedelta
from pathlib import Path

OUT = Path(__file__).parent / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)

COLS = [
    "name",
    "# calls",
    "t_min",
    "min rank",
    "t_avg",
    "t_max",
    "max rank",
    "total min (s)",
    "total min rank",
    "total max (s)",
    "total max rank",
    "total avg (s)",
    "# PEs",
]
TIMERS = [
    (
        "total",
        8,
        "10.0000s",
        "[3]",
        "10.2000s",
        "10.5000s",
        "[5]",
        "10.000",
        "[3]",
        "10.500",
        "[5]",
        "10.200",
        "8",
    ),
    (
        " L integrate_nh",
        100,
        "8.00000s",
        "[3]",
        "8.20000s",
        "8.50000s",
        "[5]",
        "8.000",
        "[3]",
        "8.500",
        "[5]",
        "8.200",
        "8",
    ),
    (
        "    L transport",
        100,
        "2.00000s",
        "[1]",
        "2.10000s",
        "2.30000s",
        "[5]",
        "2.000",
        "[1]",
        "2.300",
        "[5]",
        "2.100",
        "8",
    ),
    (
        " L exch_data.wait",
        100,
        "0.50000s",
        "[1]",
        "1.50000s",
        "4.00000s",
        "[7]",
        "0.500",
        "[1]",
        "4.000",
        "[7]",
        "1.500",
        "8",
    ),
    (
        " L wrt_output",
        4,
        "0.10000s",
        "[0]",
        "0.20000s",
        "0.40000s",
        "[2]",
        "0.100",
        "[0]",
        "0.400",
        "[2]",
        "0.200",
        "8",
    ),
    (
        "model_init",
        8,
        "1.00000s",
        "[0]",
        "1.10000s",
        "1.20000s",
        "[4]",
        "1.000",
        "[0]",
        "1.200",
        "[4]",
        "1.100",
        "8",
    ),
]


# Column widths wide enough for both the header and every cell, so the dash
# rule that defines the spans never clips a name.
WIDTHS = [
    max(len(str(c)) for c in (col, *(t[i] for t in TIMERS))) + 4 for i, col in enumerate(COLS)
]


def row(cells):
    return "  " + "".join(f"{str(c):<{w}}" for c, w in zip(cells, WIDTHS)).rstrip() + "    "


def rule():
    return "  " + "   ".join("-" * max(w - 3, 5) for w in WIDTHS) + "    "


def timer_block():
    out = ["", "Timer report, ranks 0-7", "", rule(), row(COLS), rule(), ""]
    out += [row(t) for t in TIMERS]
    out += ["  " + "-" * (sum(WIDTHS) + 6) + "    ", ""]
    return out


HEADER = """#! /usr/bin/bash
#SBATCH --account=abc01
#SBATCH --job-name=demo
#SBATCH --nodes=2
#SBATCH --gpus-per-node=4
#SBATCH --time=01:00:00
#
#=============================================================================
# ICON run script:
# first created by make_target_runscript for a test machine
#=============================================================================
export ICON_THREADS=1
export MPICH_OFI_CXI_COUNTER_REPORT=3
  echo "Script run successfully: atmo=${finish_atmo} ocean=${finish_ocean}"
  echo "Script FAILED: srun exit status ${srun_status}"
end_of_job_script"""

ENV = [
    (None, "+ set -x"),
    (None, "SLURM_JOB_ID=4242"),
    (None, "SLURM_JOB_NAME=demo"),
    (None, "SLURM_JOB_NUM_NODES=2"),
    (None, "SLURM_JOB_NODELIST=nid[000001-000002]"),
    (None, "SLURM_GPUS_ON_NODE=4"),
    (None, "SLURMD_NODENAME=nid000001"),
]

INIT = [
    (0, " version: 2026.04"),
    (0, " revision: icon-2026.04-1-gabcdef0"),
    (0, " local branch: main"),
    (0, " master_control: start model initialization."),
    (0, " atmo runs on 8 mpi processes."),
    (8, " ocean runs on 8 mpi processes."),
    (0, " Running ICON atmo in coupled mode with YAC version: v3.17.0"),
    (0, " mo_atmo_coupling_frame: Constructing the coupling frame atmosphere-ocean."),
]


class Writer:
    def __init__(self, start="2026-01-05T10:00:00"):
        self.t = datetime.fromisoformat(start)
        self.lines = []

    def raw(self, text):
        self.lines.append(text)

    def say(self, text, rank=None, after=1.0):
        self.t += timedelta(seconds=after)
        stamp = self.t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{self.t.microsecond // 1000:03d}"
        prefix = f"{stamp}: " + (f"{rank:>5}: " if rank is not None else "")
        self.lines.append(prefix + text)

    def text(self):
        return "\n".join(self.lines) + "\n"


def preamble(w):
    for line in HEADER.splitlines():
        w.raw(line)
    for rank, text in ENV:
        w.say(text, rank, 0.1)


def startup(w):
    for rank, text in INIT:
        w.say(text, rank, 0.5)


def steps(w, count=5, every=10.0):
    model = datetime(2020, 1, 1)
    for i in range(count):
        step = 1 if i == 0 else i * 25
        model = datetime(2020, 1, 1) + timedelta(seconds=step * 20)
        w.say(
            f" Time step: {step:8d} model time " f"{model.strftime('%Y-%m-%d %H:%M:%S')}.000",
            0,
            every,
        )


# 1. a healthy ICON run
w = Writer()
preamble(w)
startup(w)
steps(w)
w.say("    WARNING PE:    3 mo_demo:some_routine: a variable was missing", 3, 0.2)
w.say(" mo_ocean_output:output_ocean: Write output at:2020-01-01 01:00:00", 4, 0.3)
w.say(
    " :writeRestartInternal: restart: finished: 12.50000GB of data in "
    "0.5000000s (25.000000GB/s)",
    0,
    0.4,
)
for line in timer_block():
    w.say(line, 0, 0.01)
w.say("MPICH Slingshot Network Summary: 0 network timeouts", 0, 0.1)
w.say("MPICH Slingshot CXI Counter Summary:", 0, 0.01)
w.say(
    "Counter                     Samples          Min         (/s)         Mean"
    "         (/s)          Max         (/s)",
    0,
    0.01,
)
w.say(
    "rh:nacks                          8            5          0.0           25"
    "          0.0           85          0.1",
    0,
    0.01,
)
w.say(
    "hni_rx_paused_0                   8         1000          1.0        20000"
    "         20.0       400000        400.0",
    0,
    0.01,
)
w.say("", 0, 0.01)
w.say("Computed Ratios                              Min   Mean    Max", 0, 0.01)
w.say("PCIe posted (write) blocked cycles/pkt       0.4    0.7    1.3", 0, 0.01)
w.say("+ srun_status=0", after=0.5)
w.say("Script run successfully: atmo=OK ocean=OK", after=0.1)
(OUT / "icon_success.log").write_text(w.text())

# 2. a run that hangs in the coupling setup and is killed by the time limit
w = Writer("2026-01-06T09:00:00")
preamble(w)
startup(w)
w.say(" mo_atmo_coupling_frame: Constructing the coupling frame atmosphere/hydrology.", 0, 1.0)
w.say("srun: Job step aborted: Waiting up to 32 seconds for job step to finish.", after=3300.0)
w.raw(
    "[2026-01-06T09:55:10.000] error: *** JOB 4243 ON nid000001 CANCELLED AT "
    "2026-01-06T09:55:10 DUE TO TIME LIMIT ***"
)
w.say("++ rm -f ICON_run_1234.pipe", after=5.0)
(OUT / "icon_hang.log").write_text(w.text().replace("SLURM_JOB_ID=4242", "SLURM_JOB_ID=4243"))

# 3. two attempts appended to the same file
w = Writer("2026-01-07T08:00:00")
preamble(w)
startup(w)
steps(w, 3)
w.say("+ srun_status=1", after=0.2)
w.say(
    "Script FAILED: srun exit status 1, finish_atmo.status missing, " "finish_ocean.status missing",
    after=0.1,
)
first = w.text()
w = Writer("2026-01-07T14:00:00")
preamble(w)
startup(w)
steps(w, 5)
w.say("+ srun_status=0", after=0.2)
w.say("Script run successfully: atmo=OK ocean=OK", after=0.1)
(OUT / "icon_two_attempts.log").write_text(first + w.text())

# 4. a generic SLURM job from a code runhealth knows nothing about
w = Writer("2026-01-08T12:00:00")
w.raw("#!/bin/bash")
w.raw("#SBATCH --job-name=mystery")
w.raw("#SBATCH --nodes=4")
w.raw("#SBATCH --time=00:30:00")
w.say("SLURM_JOB_ID=5150", after=0.1)
w.say("SLURM_JOB_NUM_NODES=4", after=0.1)
w.say("solver: starting", 0, 1.0)
w.say("solver: iteration 1 residual 1.0e-2", 0, 2.0)
w.say("solver: iteration 2 residual 1.0e-4", 0, 2.0)
w.say("srun: error: nid000007: tasks 12-15: Terminated", after=600.0)
w.say("srun: Force Terminated StepId=5150.0", after=0.2)
(OUT / "slurm_generic.log").write_text(w.text())

# 5. ICON output with no wall-clock prefix at all
lines = [t for _, t in INIT]
lines += [
    f" Time step: {i * 25 or 1:8d} model time 2020-01-01 "
    f"{(datetime(2020, 1, 1) + timedelta(seconds=(i * 25 or 1) * 20)).strftime('%H:%M:%S')}.000"
    for i in range(4)
]
lines += timer_block()
lines.append("Script run successfully: atmo=OK ocean=OK")
(OUT / "icon_no_timestamps.log").write_text("\n".join(lines) + "\n")

# 6. degenerate inputs
(OUT / "empty.log").write_text("")
(OUT / "truncated.log").write_text(
    (OUT / "icon_success.log").read_text()[:1400].rsplit("\n", 1)[0] + "\n"
)
(OUT / "not_a_log.log").write_text("just some prose, no job here at all.\n" * 5)

for f in sorted(OUT.iterdir()):
    print(f"{f.name:<26} {f.stat().st_size:>7} bytes")
