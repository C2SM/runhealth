from pathlib import Path

from runhealth import extract, health, profile

SCRIPT = """\
#! /usr/bin/bash
#SBATCH --job-name=demo
#SBATCH --time=01:00:00
# ICON run script
watchdog_timeout=${watchdog_timeout:=1800}            # after the first time step
watchdog_init_timeout=${watchdog_init_timeout:=7200}  # before it
hang_watchdog()
{
  echo "WATCHDOG: no log output for ${idle} s, assuming a hang."
}
end_of_job_script
"""


def stamped(lines: list[tuple[str, str]]) -> str:
    return "".join(f"2026-09-24T{clock}.000: {text}\n" for clock, text in lines)


HUNG = SCRIPT + stamped(
    [
        ("10:00:00", "+ export EXPNAME=demo"),
        ("10:00:01", "    0:  master_control: start model initialization"),
        ("10:05:00", "    0:  Time step:        1 model time 2020-01-01 00:00:20.000"),
        ("10:06:00", "    0:  Time step:        2 model time 2020-01-01 00:00:40.000"),
        ("10:07:00", "    0:  Time step:        3 model time 2020-01-01 00:01:00.000"),
        ("10:08:00", "    0:  Time step:        4 model time 2020-01-01 00:01:20.000"),
        ("10:09:00", "    0:  Time step:        5 model time 2020-01-01 00:01:40.000"),
        ("10:10:00", "    0:  Time step:        6 model time 2020-01-01 00:02:00.000"),
        (
            "10:41:00",
            "WATCHDOG: no log output for 1860 s, assuming a hang. "
            "Collecting diagnostics in /nowhere/diag.demo.12345",
        ),
        ("10:45:00", "WATCHDOG: diagnostics done, sending SIGABRT to step 12345.0"),
        ("10:45:01", "    3: Fatal Python error: Aborted"),
        ("10:45:01", '    3:   File "/opt/icon4py/dycore.py", line 12 in run_step'),
        ("10:45:01", '    4:   File "/opt/icon4py/dycore.py", line 12 in run_step'),
        ("10:47:00", "WATCHDOG: cancelling step 12345.0"),
        ("10:47:05", "Script FAILED: srun exit status 143, finish_atmo.status missing"),
    ]
)


def parse_text(tmp_path: Path, text: str, name: str = "LOG.demo.12345.o"):
    path = tmp_path / name
    path.write_text(text)
    return extract.parse(path, profile.detect(path, profile.load_all()))


def test_the_profile_is_detected_from_the_echoed_script(tmp_path):
    log = parse_text(tmp_path, HUNG)
    assert "watchdog" in log.profiles
    assert log.fields["watchdog_timeout"] == 1800
    assert log.fields["watchdog_init_timeout"] == 7200


def test_a_fired_watchdog_fails_the_run_and_marks_the_timeline(tmp_path):
    log = parse_text(tmp_path, HUNG)
    assert log.fields["watchdog_idle"] == 1860
    assert log.fields["diag_dir"] == "/nowhere/diag.demo.12345"
    a = health.assess(log)
    check = a.check("watchdog")
    assert check.level == "fail"
    assert "31m 00s" in check.headline
    assert "hang diagnostics" in [p.name for p in a.phases]
    assert "SIGABRT tracebacks" in [p.name for p in a.phases]


def test_python_frames_at_the_signal_are_counted(tmp_path):
    log = parse_text(tmp_path, HUNG)
    assert log.groups["python_frames"].total == 2
    assert log.groups["python_frames"].keys == {"run_step": 2}


def test_an_armed_watchdog_that_did_not_fire_is_ok(tmp_path):
    lines = HUNG.split("2026-09-24T10:41:00")[0]
    check = health.assess(parse_text(tmp_path, lines)).check("watchdog")
    assert check.level == "ok"
    assert "30m 00s in the main loop" in check.evidence[0]


def test_logs_without_a_watchdog_get_no_watchdog_check(assessed):
    assert assessed["icon_success"].check("watchdog") is None


def test_setup_silence_is_judged_against_the_watchdog_allowance(tmp_path):
    compiling = stamped(
        [
            ("10:00:00", "+ export EXPNAME=demo"),
            ("10:00:01", "    0:  master_control: start model initialization"),
            ("10:40:00", "    0:  Icon4py: Diffusion granule initialization"),
        ]
    )
    with_watchdog = health.assess(parse_text(tmp_path, SCRIPT + compiling), now=0)
    assert with_watchdog.check("stall").level == "ok"
    plain = SCRIPT.replace("watchdog_init_timeout", "unrelated").replace("hang_watchdog", "x")
    without = health.assess(parse_text(tmp_path, plain + compiling, "LOG.demo.2.o"), now=0)
    assert without.check("stall").level == "fail"


def test_a_running_job_is_not_stalled_while_the_allowance_lasts(tmp_path):
    text = SCRIPT + stamped(
        [
            ("10:00:00", "+ export EXPNAME=demo"),
            ("10:00:01", "    0:  master_control: start model initialization"),
        ]
    )
    log = parse_text(tmp_path, text)
    a = health.assess(log, now=log.last_wall + 3600, slurm_state="RUNNING")
    assert a.status == "RUNNING"
    a = health.assess(log, now=log.last_wall + 8000, slurm_state="RUNNING")
    assert a.status == "STALLED"


def test_a_stamping_helper_that_failed_to_start_is_the_outcome(tmp_path):
    text = SCRIPT + "ERROR: timewarp failed to start, aborting\n"
    log = parse_text(tmp_path, text)
    assert log.outcome.level == "fail"
    assert "timewarp failed to start" in log.outcome.text
