"""Write examples/demo.log: a synthetic run with something interesting in it.

Real logs cannot be committed -- they are hundreds of megabytes and full of a
particular site's detail. This builds a small stand-in that still exercises
every part of the report: phases, an output cadence, a mid-run stall with a
fabric burst behind it, an uneven timer table and a network counter summary.

    python examples/make_demo.py
    runhealth examples/ -o /tmp/demo --glob '*.log' --open

Two logs are written: demo.log, a run that finishes with a fabric hiccup in
the middle of it, and demo_hang.log, the same job stuck in its coupling setup
until the scheduler cuts it off.
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
START = datetime(2026, 3, 17, 21, 4, 12)
NODES = [f"nid{5000 + i:06d}" for i in range(4)]
RANKS = 32

HEADER = """#! /usr/bin/bash
#SBATCH --account=demo01
#SBATCH --job-name=demo_r2b6
#SBATCH --partition=normal
#SBATCH --nodes=4
#SBATCH --gpus-per-node=4
#SBATCH --time=02:00:00
#SBATCH --output=LOG.%x.%j.o
#
#=============================================================================
# ICON run script:
# first created by make_target_runscript for a demonstration machine
#=============================================================================
export ICON_THREADS=1
export FI_LOG_LEVEL=warn
export MPICH_OFI_CXI_COUNTER_REPORT=3
#
# Output is piped through a wall-clock stamping filter, which is what makes
# silence measurable. See the runhealth README.
#
  echo "Script run successfully: atmo=${finish_atmo} ocean=${finish_ocean}"
  echo "Script FAILED: srun exit status ${srun_status}"
end_of_job_script"""

TIMER_COLS = [
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

# label, calls, min, avg, max, min rank, max rank
TIMERS = [
    ("total", 32, 1148, 1151, 1154, 9, 21),
    (" L integrate_nh", 4000, 902, 934, 961, 9, 21),
    ("    L transport", 4000, 214, 221, 229, 3, 17),
    ("       L adv_horiz", 4000, 151, 156, 162, 3, 28),
    ("       L adv_vert", 4000, 58, 61, 65, 11, 17),
    ("    L nh_solve", 20000, 448, 461, 474, 9, 21),
    ("       L nh_solve.exch", 20000, 96, 128, 171, 9, 21),
    ("    L physics", 4000, 188, 196, 205, 14, 6),
    ("       L radiation", 334, 96, 101, 107, 14, 6),
    ("       L microphysics", 4000, 44, 46, 48, 2, 19),
    (" L exch_data.wait", 84000, 31, 118, 287, 9, 21),
    (" L wrt_output", 24, 38, 52, 71, 0, 4),
    ("    L wait_for_async_io", 24, 12, 21, 34, 0, 4),
    (" L coupling", 400, 47, 51, 56, 30, 12),
    ("model_init", 32, 96, 97, 98, 5, 26),
]


def dur(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.5f}s"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}h{m:02d}m" if h else f"{m:02d}m{s:02d}s"


class Log:
    def __init__(self) -> None:
        self.t = START
        self.lines: list[str] = []

    def raw(self, text: str) -> None:
        self.lines.append(text)

    def say(self, text: str, rank: int | None = None, after: float = 0.4) -> None:
        self.t += timedelta(seconds=after)
        stamp = self.t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{self.t.microsecond // 1000:03d}"
        self.lines.append(f"{stamp}: " + (f"{rank:>5}: " if rank is not None else "") + text)

    def fabric(self, node: str, after: float = 0.002) -> None:
        self.say(
            f"libfabric:{random.randint(10000, 99999)}:{int(self.t.timestamp())}::cxi:"
            f"ep_data:cxip_fc_notify_cb():{random.randint(1000, 9999)}<warn> {node}: "
            f"TXC (0x{random.randint(0x1000, 0xffff):x}:1): dropped FC message: "
            f"retry_delay_usecs=1000 retry_count={random.randint(1, 8)}",
            random.randrange(RANKS),
            after,
        )


def timer_report(log: Log) -> None:
    rows = [
        (
            label,
            calls,
            dur(lo / calls * 32),
            f"[{lo_r}]",
            dur(av / calls * 32),
            dur(hi / calls * 32),
            f"[{hi_r}]",
            f"{lo:.3f}",
            f"[{lo_r}]",
            f"{hi:.3f}",
            f"[{hi_r}]",
            f"{av:.3f}",
            str(RANKS),
        )
        for label, calls, lo, av, hi, lo_r, hi_r in TIMERS
    ]
    widths = [
        max(len(str(c)) for c in (col, *(r[i] for r in rows))) + 4
        for i, col in enumerate(TIMER_COLS)
    ]
    line = (
        lambda cells: "  "
        + "".join(f"{str(c):<{w}}" for c, w in zip(cells, widths)).rstrip()  # noqa: E731
        + "    "
    )
    rule = "  " + "   ".join("-" * (w - 3) for w in widths) + "    "
    log.say("", 0, 0.01)
    log.say("Timer report, ranks 0-31", 0, 0.01)
    log.say("", 0, 0.01)
    log.say(rule, 0, 0.01)
    log.say(line(TIMER_COLS), 0, 0.01)
    log.say(rule, 0, 0.01)
    log.say("", 0, 0.01)
    for row in rows:
        log.say(line(row), 0, 0.01)
    log.say("  " + "-" * (sum(widths) + 6) + "    ", 0, 0.01)
    log.say("", 0, 0.01)


COUNTERS = [
    ("atu_cache_evictions", 512, 4110, 61240),
    ("atu_cache_hit_base_page_size_0", 812340991, 1188402699, 1774109056),
    ("lpe_net_match_priority_0", 904695, 1960940, 2979960),
    ("lpe_rndzv_puts_0", 536681, 1465215, 2409976),
    ("hni_rx_paused_0", 371553, 1960270, 5466732),
    ("hni_rx_paused_1", 585581, 10845694, 198910058),
    ("hni_tx_paused_0", 4267, 93516, 682011),
    ("rh:nacks", 5, 25, 85),
    ("rh:nack_sequence_error", 4, 24, 84),
]


def counter_report(log: Log) -> None:
    log.say("", 0, 0.05)
    log.say("MPICH Slingshot Network Summary: 0 network timeouts", 0, 0.01)
    log.say("", 0, 0.01)
    log.say("MPICH Slingshot CXI Counter Summary:", 0, 0.01)
    head = ("Counter", "Samples", "Min", "(/s)", "Mean", "(/s)", "Max", "(/s)")
    widths = [38, 9, 13, 13, 13, 13, 13, 13]
    fmt = lambda cells: "".join(  # noqa: E731
        f"{c:<{widths[0]}}" if i == 0 else f"{c:>{widths[i]}}" for i, c in enumerate(cells)
    )
    log.say(fmt(head), 0, 0.01)
    for name, lo, mean, hi in COUNTERS:
        log.say(
            fmt(
                (
                    name,
                    "16",
                    str(lo),
                    f"{lo / 1150:.1f}",
                    str(mean),
                    f"{mean / 1150:.1f}",
                    str(hi),
                    f"{hi / 1150:.1f}",
                )
            ),
            0,
            0.01,
        )
    log.say("", 0, 0.01)
    log.say("Computed Ratios                              Min   Mean    Max", 0, 0.01)
    log.say("PCIe posted (write) blocked cycles/pkt       0.4    0.9    2.1", 0, 0.01)
    log.say("PCIe non-posted (read) blocked cycles/pkt    0.0    0.1    0.3", 0, 0.01)


def main(hang: bool = False) -> None:
    random.seed(20260317)
    log = Log()
    for line in HEADER.splitlines():
        log.raw(line)

    for key, value in [
        ("SLURM_JOB_ID", "774112"),
        ("SLURM_JOB_NAME", "demo_r2b6"),
        ("SLURM_JOB_NUM_NODES", "4"),
        ("SLURM_NTASKS", "32"),
        ("SLURM_JOB_NODELIST", f"nid[{NODES[0][3:]}-{NODES[-1][3:]}]"),
        ("SLURM_GPUS_ON_NODE", "4"),
        ("SLURM_CPUS_ON_NODE", "288"),
        ("SLURMD_NODENAME", NODES[0]),
    ]:
        log.say(f"{key}={value}", after=0.05)
    for i in range(RANKS):
        log.say(f"Atmo compute process {i % 8} on {NODES[i // 8]}", i, 0.03)

    for text in [
        " version: 2026.04",
        " revision: demo-2026.04-7-g0a1b2c3",
        " local branch: main",
        " compilers:",
        "   Fortran: NVHPC 26.1.0",
    ]:
        log.say(text, 0, 0.2)
    log.say("   MPI: MPI VERSION    : CRAY MPICH version 9.1.0.794 ...", 0, 0.1)
    log.say(" master_control: start model initialization.", 0, 1.4)
    log.say(" atmo runs on 32 mpi processes.", 0, 0.6)
    log.say(" set_nproma_nblocks: Using namelist nproma=       32", 0, 0.3)
    for i in range(6):
        log.say(f" mo_read_netcdf_distributed_base::distrib_nf_open_base: input_{i}.nc", 0, 6.0)
    for i in range(RANKS):
        log.say(
            f"    WARNING PE:   {i:2d} mo_load_restart:readData: variable not "
            f"found: tracer_{i % 4}",
            i,
            0.02,
        )
    log.say(" Running ICON atmo in coupled mode with YAC version: v3.17.0", 0, 3.0)
    log.say(" mo_atmo_coupling_frame: Constructing the atmosphere coupling frame.", 0, 4.0)
    log.say(
        " mo_atmo_coupling_frame: Constructing the coupling frame " "atmosphere-ocean.", 0, 18.0
    )
    if hang:
        # The coupler never returns. Nothing is written for the rest of the
        # allocation, which is the whole diagnosis.
        log.say(
            "srun: Job step aborted: Waiting up to 32 seconds for job step " "to finish.",
            after=6180.0,
        )
        killed = log.t.strftime("%Y-%m-%dT%H:%M:%S")
        log.raw(
            f"[{killed}.061] error: *** JOB 774113 ON {NODES[0]} CANCELLED AT "
            f"{killed} DUE TO TIME LIMIT ***"
        )
        log.say(
            f"[{killed}.058] error: *** STEP 774113.0 ON {NODES[0]} CANCELLED "
            f"AT {killed} DUE TO TIME LIMIT ***",
            0,
            0.4,
        )
        log.say("++ rm -f ICON_run_9931.pipe", after=3.0)
        out = HERE / "demo_hang.log"
        out.write_text("\n".join(log.lines).replace("774112", "774113") + "\n")
        print(f"{out}: {len(log.lines):,} lines, {out.stat().st_size / 1024:.0f} kB")
        return
    log.say(" normal exit from read_restart_files", 0, 4.0)

    # 200 reports of 25 steps: about 6 s each, plus hourly output and one stall.
    model = datetime(2020, 6, 1)
    for n in range(200):
        step = 1 if n == 0 else n * 25
        model = datetime(2020, 6, 1) + timedelta(seconds=step * 36)
        gap = 41.0 if n == 0 else random.uniform(5.6, 6.4)
        if n == 118:
            # A fabric storm: the run goes quiet while the network retries.
            for _ in range(900):
                log.fabric(NODES[2], random.uniform(0.05, 0.3))
            gap = 12.0
        log.say(
            f" Time step: {step:8d} model time " f"{model.strftime('%Y-%m-%d %H:%M:%S')}.000",
            0,
            gap,
        )
        if n and n % 25 == 0:
            log.say(
                f" mo_name_list_output: Write output at:" f"{model.strftime('%Y-%m-%d %H:%M:%S')}",
                4,
                14.0,
            )
        if n == 150:
            log.say(
                " :writeRestartInternal: restart: finished: 46.20000GB of data "
                "in 1.9400000s (23.814433GB/s)",
                4,
                2.0,
            )

    log.say(" mo_atmo_coupling_frame: Destructing the coupling frame.", 0, 2.0)
    timer_report(log)
    counter_report(log)
    log.say(" clean-up finished", 0, 0.4)
    log.say("+ srun_status=0", after=1.2)
    log.say("Script run successfully: atmo=OK ocean=OK", after=0.1)

    out = HERE / "demo.log"
    out.write_text("\n".join(log.lines) + "\n")
    print(f"{out}: {len(log.lines):,} lines, {out.stat().st_size / 1024:.0f} kB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["ok", "hang"], help="write just one of them")
    args = parser.parse_args()
    if args.only != "hang":
        main()
    if args.only != "ok":
        main(hang=True)
