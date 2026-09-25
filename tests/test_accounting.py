import os

from runhealth import accounting, cli, health
from runhealth.extract import Outcome, RunLog
from runhealth.logfile import parse_stamp

SACCT = """\
123|123|CANCELLED by 0|0:0|03:43:04|12:00:00|200|nid[001-200]|2026-09-24T07:01:25|2026-09-24T10:44:29
124_1|124_1|TIMEOUT|0:0|1-00:00:10|1-00:00:00|2|nid[1-2]|2026-09-23T10:00:00|2026-09-24T10:00:10
125|125|NODE_FAIL|1:0|00:10:00|01:00:00|1|nid1|2026-09-24T09:00:00|2026-09-24T09:10:00
125|125|RUNNING|0:0|00:01:00|01:00:00|1|nid2|2026-09-24T09:20:00|Unknown
not a record
"""


def record(state: str, exit_code: str = "0:0", **extra) -> dict:
    rec = {"state": state, "exit_code": exit_code, "elapsed": 3600.0, "timelimit": 7200.0}
    rec.update(extra)
    return rec


def test_records_are_keyed_by_job_id_and_the_last_run_wins():
    out = accounting.parse(SACCT)
    assert set(out) == {"123", "124_1", "125"}
    assert out["123"]["state"] == "CANCELLED by root"  # the uid is resolved to a name
    assert out["124_1"]["elapsed"] == 86410
    assert out["125"]["state"] == "RUNNING"
    assert out["125"]["end"] is None
    assert out["123"]["start"] == parse_stamp("2026-09-24T07:01:25")


def test_query_without_sacct_returns_nothing(monkeypatch):
    monkeypatch.setattr(accounting.shutil, "which", lambda _: None)
    assert accounting.query(["123"]) == {}


def test_query_runs_sacct_with_absolute_timestamps(tmp_path, monkeypatch):
    fake = tmp_path / "sacct"
    fake.write_text(
        '#!/bin/sh\necho "123|123|COMPLETED|0:0|00:10:00|01:00:00|1|nid1|$SLURM_TIME_FORMAT|x"\n'
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    out = accounting.query(["123", ""])
    assert out["123"]["state"] == "COMPLETED"
    assert out["123"]["start"] is None  # the format string itself, not a date


def test_query_on_a_host_runs_sacct_over_ssh(tmp_path, monkeypatch):
    # Stands in for ssh: skips "-o BatchMode=yes host" and runs the command here.
    (tmp_path / "ssh").write_text('#!/bin/sh\nshift 3\nexec sh -c "$1"\n')
    (tmp_path / "sacct").write_text(
        '#!/bin/sh\necho "7|7|CANCELLED by 0|0:0|00:10:00|01:00:00|1|nid1|$SLURM_TIME_FORMAT|x"\n'
    )
    for f in ("ssh", "sacct"):
        (tmp_path / f).chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("SLURM_TIME_FORMAT", raising=False)
    out = accounting.query(["7"], host="santis")
    assert out["7"]["state"] == "CANCELLED by 0"  # a remote uid is not resolved locally


def test_the_cli_asks_the_remote_host_about_synced_logs(tmp_path, monkeypatch):
    from test_cli import FIXTURES, _fake_ssh

    monkeypatch.setenv("RSYNC_RSH", str(_fake_ssh(tmp_path)))
    monkeypatch.setattr(cli.shutil, "which", lambda n: None if n == "squeue" else "/bin/" + n)
    asked = {}
    monkeypatch.setattr(
        accounting,
        "query",
        lambda ids, host=None: asked.setdefault(host, sorted(set(ids) - {""})) and {},
    )
    local = str(FIXTURES / "icon_success.log")
    out = tmp_path / "report"
    cli.main(
        [f"fakehost:{FIXTURES}", local, "--glob", "icon_success.log", "--no-plots", "-o", str(out)]
    )
    assert asked == {"fakehost": ["4242"], None: ["4242"]}


def test_a_log_without_verdict_takes_the_accounting_verdict():
    log = RunLog(first_wall=0.0, last_wall=600.0)
    a = health.assess(log, now=10**6, accounting=record("TIMEOUT"))
    assert a.status == "FAILED"
    assert a.check("outcome").headline == "SLURM recorded the job as TIMEOUT"
    assert a.check("walltime").level == "fail"
    assert a.check("accounting").level == "fail"


def test_a_completed_job_without_verdict_is_a_success():
    a = health.assess(RunLog(), now=10**6, accounting=record("COMPLETED"))
    assert a.status == "SUCCESS"
    assert a.check("accounting").level == "ok"


def test_a_failed_job_that_reported_success_is_a_warning():
    log = RunLog(outcome=Outcome("ok", "atmo=RESTART ocean=RESTART"))
    a = health.assess(log, accounting=record("FAILED", "1:0"))
    assert a.status == "SUCCESS"
    check = a.check("accounting")
    assert check.level == "warn"
    assert "although the job script reported success" in check.headline


def test_a_pending_job_is_queued():
    assert health.assess(RunLog(), accounting=record("PENDING")).status == "QUEUED"


def test_the_elapsed_time_stands_in_for_a_log_without_timestamps():
    log = RunLog(line_format="plain", first_wall=1000.0, last_wall=1000.0)
    accounting.fill_times(log, record("CANCELLED by x", start=100.0, end=1000.0))
    assert log.first_wall == 100.0
    a = health.assess(log, accounting=record("CANCELLED by x"))
    assert a.stats["wall_seconds"] == 900.0


def test_timestamped_logs_keep_their_own_times():
    log = RunLog(line_format="timestamped", first_wall=500.0, last_wall=900.0)
    accounting.fill_times(log, record("COMPLETED", start=100.0, end=1000.0))
    assert (log.first_wall, log.last_wall) == (500.0, 900.0)


def test_the_cli_reads_accounting_unless_told_not_to(tmp_path, monkeypatch):
    from test_cli import FIXTURES

    asked = []
    monkeypatch.setattr(
        accounting,
        "query",
        lambda ids, host=None: asked.append(sorted(ids)) or {"4242": record("FAILED")},
    )
    base = [str(FIXTURES / "icon_success.log"), "--no-plots", "--no-squeue"]
    cli.main([*base, "-o", str(tmp_path / "a")])
    assert asked == []  # --no-squeue keeps runhealth away from SLURM altogether
    base.remove("--no-squeue")
    cli.main([*base, "--no-sacct", "-o", str(tmp_path / "b")])
    assert asked == []
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)  # no squeue
    cli.main([*base, "-o", str(tmp_path / "c")])
    assert asked == [["4242"]]
    assert "SLURM accounting" in (tmp_path / "c" / "icon_success.html").read_text()
