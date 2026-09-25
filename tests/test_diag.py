import json
from pathlib import Path

from runhealth import cli, diag, health
from test_watchdog import HUNG, parse_text

HEADER = (
    "timestamp, index, pstate, utilization.gpu [%], memory.used [MiB], power.draw [W], "
    "temperature.gpu, clocks.current.sm [MHz], clocks_event_reasons.active, "
    "ecc.errors.uncorrected.volatile.total\n"
)


def gpu_csv(busy_after_10_10: bool, ecc_on_gpu1: int = 0, slowdown: bool = False) -> str:
    """One node, two GPUs, one sample per minute from 10:00 to 10:47."""
    rows = [HEADER]
    for minute in range(48):
        clock = f"2026/09/24 10:{minute:02d}:30.000"
        for gpu in (0, 1):
            util = 100 if (minute < 10 or busy_after_10_10) else 0
            reasons = "0x0000000000000040" if slowdown and minute == 7 and gpu == 0 else "0x0"
            ecc = ecc_on_gpu1 if gpu == 1 else 0
            rows.append(
                f"{clock}, {gpu}, P0, {util} %, 40000 MiB, 350.5 W, 55, 1980 MHz, {reasons}, {ecc}\n"
            )
    return "".join(rows)


GDB_WAITING = """\
Thread 3 (Thread 0x4000 (LWP 12) "icon"):
#0  0x0000ffff in epoll_wait () from /lib64/libc.so.6
Thread 1 (Thread 0x4001 (LWP 11) "icon"):
#0  0x0000ffff in cxil_poll () from /usr/lib64/libcxi.so.1
#1  0x0000ffff in MPIDI_progress () from /opt/cray/libmpi.so
#2  0x0000ffff in yac_cget_ (field=(1, 2)) at /src/yac/yac_interface.c:321
#3  0x0000ffff in mo_coupling_MOD_get (x=1) at /src/mo_coupling.f90:88
"""
GDB_BUSY = """\
Thread 1 (Thread 0x4001 (LWP 11) "icon"):
#0  0x0000ffff in cuStreamSynchronize () from /usr/lib64/libcuda.so
#1  0x0000ffff in mo_dyn_MOD_run () at /src/mo_dyn.f90:12
"""


def make_run(tmp_path: Path) -> Path:
    """A hung run: node A keeps its GPUs busy, node B has a faulty GPU."""
    root = tmp_path / "diag.demo.12345"
    (root / "gpu").mkdir(parents=True)
    (root / "gpu" / "nidA.csv").write_text(gpu_csv(busy_after_10_10=True, slowdown=True))
    (root / "gpu" / "nidB.csv").write_text(gpu_csv(busy_after_10_10=False, ecc_on_gpu1=2))
    for node, rank, gdb, state in (
        ("nidA", 0, GDB_BUSY, "R (running)"),
        ("nidB", 1, GDB_WAITING, "D (disk sleep)"),
        ("nidB", 2, GDB_WAITING, "S (sleeping)"),
    ):
        (root / node).mkdir(exist_ok=True)
        (root / node / f"gdb_rank{rank}.txt").write_text(gdb)
        (root / node / f"proc_rank{rank}.txt").write_text(
            f"Name:\ticon\nState:\t{state}\nwchan: 0\n"
        )
    (root / "nidA" / "dmesg.txt").write_text("dmesg: read kernel buffer failed: not permitted\n")
    (root / "nidB" / "dmesg.txt").write_text(
        "[Thu Sep 24 10:40:00 2026] NVRM: Xid (PCI:0009:01:00): 79, GPU has fallen off the bus.\n"
    )
    return root


def hung_log(tmp_path: Path):
    make_run(tmp_path)
    log = parse_text(tmp_path, HUNG)
    log.diag = diag.collect(log)
    return log


def test_the_directory_is_found_by_job_id(tmp_path):
    root = make_run(tmp_path)
    log = parse_text(tmp_path, HUNG)
    assert diag.locate(log) == root  # the path the log names does not exist here


def test_no_directory_means_no_summary_and_no_checks(assessed):
    a = assessed["icon_success"]
    for key in ("gpu_health", "gpu_activity", "hang_dumps", "kernel"):
        assert a.check(key) is None


def test_gpu_monitor_is_summarized_per_gpu(tmp_path):
    log = hung_log(tmp_path)
    b1 = log.diag["gpu"]["nidB"]["gpus"]["1"]
    assert b1["samples"] == 48
    assert b1["ecc_max"] == 2
    assert b1["power_max"] == 350.5
    assert log.diag["gpu"]["nidA"]["gpus"]["0"]["slowdown"] == {"64": 1}
    assert diag.mean_util(b1, "loop") == 100
    assert diag.mean_util(b1, "silence") == 0


def test_ecc_errors_fail_and_slowdown_is_listed(tmp_path):
    check = health.assess(hung_log(tmp_path)).check("gpu_health")
    assert check.level == "fail"
    assert "nidB GPU 1: 2 uncorrected ECC error(s)" in check.evidence
    assert any("nidA GPU 0: hardware thermal slowdown" in e for e in check.evidence)


def test_gpus_busy_during_the_silence_are_named(tmp_path):
    a = health.assess(hung_log(tmp_path))
    check = a.check("gpu_activity")
    assert "2 of 4 GPU(s) stayed busy" in check.headline
    assert any("nidA GPU 0" in e for e in check.evidence)
    suspects = dict(a.suspect_nodes)
    assert "busy during the silence" in suspects["nidA"]
    assert "ECC" in suspects["nidB"]


def test_backtraces_are_grouped_by_place(tmp_path):
    check = health.assess(hung_log(tmp_path)).check("hang_dumps")
    assert check.level == "warn"  # one rank is in uninterruptible sleep
    assert "3 backtrace(s) in 2 distinct place(s)" in check.headline
    assert "cxil_poll <- yac_cget_ (yac_interface.c:321)" in check.headline
    assert any("[1-2]" in e for e in check.evidence)


def test_a_fatal_xid_fails_the_kernel_check(tmp_path):
    check = health.assess(hung_log(tmp_path)).check("kernel")
    assert check.level == "fail"
    assert check.evidence[0] == "nidB: Xid 79 (1x)"


def test_the_summary_is_refreshed_when_the_directory_changes(tmp_path):
    root = make_run(tmp_path)
    (tmp_path / "LOG.demo.12345.o").write_text(HUNG)
    out = tmp_path / "report"
    args = [str(tmp_path / "LOG.demo.12345.o"), "-o", str(out), "--no-squeue", "--no-plots"]
    cli.main(args)
    cache = next((out / ".cache").glob("*.json"))
    assert set(json.loads(cache.read_text())["state"]["diag"]["gpu"]) == {"nidA", "nidB"}
    (root / "gpu" / "nidC.csv").write_text(gpu_csv(busy_after_10_10=False))
    cli.main(args)
    assert set(json.loads(cache.read_text())["state"]["diag"]["gpu"]) == {"nidA", "nidB", "nidC"}
