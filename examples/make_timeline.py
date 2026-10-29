"""Write a synthetic log for the timeline figure in the README.

The phases of a real run differ in length by orders of magnitude, so on a
linear axis everything but the time loop shrinks to a sliver. This log
stretches the setup and teardown phases until each one carries its label,
and adds one silence in the coupling setup and regular output writes.

    python examples/make_timeline.py /tmp/timeline/timeline.log
    runhealth /tmp/timeline/timeline.log --format md -o /tmp/timeline/report --no-squeue
    cp /tmp/timeline/report/images/timeline__timeline.svg docs/images/timeline.svg
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

from make_demo import HEADER, NODES, Log, timer_report

STEPS = 90  # progress reports in the time loop, one every 20 s


def busy(log: Log, seconds: float, text: str, every: float = 20.0) -> None:
    """Lines at a steady pace, so a long phase does not read as a silence."""
    for _ in range(int(seconds / every)):
        log.say(text, 0, every)


def main(out: Path) -> None:
    random.seed(20260317)
    log = Log()
    for line in HEADER.splitlines():
        log.raw(line)
    for key, value in [
        ("SLURM_JOB_ID", "774120"),
        ("SLURM_JOB_NAME", "demo_r2b6"),
        ("SLURM_JOB_NUM_NODES", "4"),
        ("SLURM_NTASKS", "32"),
        ("SLURMD_NODENAME", NODES[0]),
    ]:
        log.say(f"{key}={value}", after=0.05)
    busy(log, 480, "+ cp input files to the run directory")

    log.say(" master_control: start model initialization.", 0, 2.0)
    busy(log, 420, " mo_read_netcdf_distributed_base::distrib_nf_open_base: input.nc")

    log.say(" mo_atmo_coupling_frame: Constructing the atmosphere coupling frame.", 0, 2.0)
    busy(log, 150, " mo_atmo_coupling_frame: exchanging grid information")
    # The coupler waits for the ocean, which is the one silence of the run.
    log.say(" mo_atmo_coupling_frame: Constructing the coupling frame atmosphere-ocean.", 0, 285)
    busy(log, 160, " mo_atmo_coupling_frame: computing the interpolation weights")

    log.say(" normal exit from read_restart_files", 0, 2.0)
    busy(log, 780, " mo_init_restart: initializing prognostic fields")

    model = datetime(2020, 6, 1)
    for n in range(STEPS):
        step = 1 if n == 0 else n * 25
        model = datetime(2020, 6, 1) + timedelta(seconds=step * 36)
        log.say(
            f" Time step: {step:8d} model time {model:%Y-%m-%d %H:%M:%S}.000",
            0,
            random.uniform(18.0, 22.0),
        )
        if n and n % 10 == 0:
            log.say(f" mo_name_list_output: Write output at:{model:%Y-%m-%d %H:%M:%S}", 4, 3.0)

    log.say(" mo_atmo_coupling_frame: Destructing the coupling frame.", 0, 2.0)
    timer_report(log)
    busy(log, 480, " mo_restart: writing the final restart files")
    log.say(" clean-up finished", 0, 2.0)
    busy(log, 420, "+ archive the output")
    log.say("+ srun_status=0", after=1.2)
    log.say("Script run successfully: atmo=OK ocean=OK", after=0.1)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(log.lines) + "\n")
    print(f"{out}: {len(log.lines):,} lines")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path, help="the log to write")
    main(parser.parse_args().out)
