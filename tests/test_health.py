from datetime import datetime, timedelta

import pytest

from runhealth import health
from runhealth.extract import RunLog
from runhealth.tables import Row, Table


def _io_log(gaps: list[float]) -> RunLog:
    """A synthetic run whose only content is a series of I/O events."""
    walls = [0.0]
    for g in gaps:
        walls.append(walls[-1] + g)
    return RunLog(
        first_wall=walls[0],
        last_wall=walls[-1],
        series={"output_write": [{"wall": w} for w in walls]},
        series_roles={"output_write": "io"},
    )


def test_healthy_run_is_not_flagged_as_failed(assessed):
    a = assessed["icon_success"]
    assert a.status == "SUCCESS"
    assert a.grade in {"ok", "info", "warn"}
    assert a.check("outcome").level == "ok"


def test_hang_is_diagnosed_from_the_silence(assessed):
    a = assessed["icon_hang"]
    assert a.status == "FAILED"
    assert a.grade == "fail"
    stall = a.check("stall")
    assert stall.level == "fail"
    assert "coupling frame" in stall.headline
    assert a.check("walltime").level == "fail"


def test_setup_silence_is_judged_more_leniently_than_loop_silence(assessed):
    """A run that reached its loop is not failed for a slow start."""
    a = assessed["icon_success"]
    assert a.check("stall").level == "ok"


def test_phases_are_named_from_the_markers(assessed):
    names = [p.name for p in assessed["icon_success"].phases]
    assert "model init" in names and "time loop" in names


def test_throughput_and_rate(assessed):
    a = assessed["icon_success"]
    assert a.stats["progress_last"] == 100
    assert a.stats["sypd"] == pytest.approx(0.137, abs=0.01)


def test_simulated_time_is_counted_from_one_step_before_the_first_report(parsed, assessed):
    # Step 1 is reported at 00:00:20, one 20 s step after the job's start.
    clock = health.model_clock(parsed["icon_success"])
    assert clock.per_step == pytest.approx(20.0)
    assert clock.start == datetime(2020, 1, 1)
    assert clock.at_step(100) == pytest.approx(2000.0)
    assert assessed["icon_success"].stats["sim_seconds"] == pytest.approx(2000.0)


def test_simulated_time_is_interpolated_between_reports(parsed):
    clock = health.model_clock(parsed["icon_success"])
    (w0, s0), (w1, s1) = clock.points[:2]
    assert clock.at_wall(w0 - 1) is None
    assert clock.at_wall((w0 + w1) / 2) == pytest.approx((s0 + s1) / 2)
    assert clock.at_wall(clock.points[-1][0] + 60) == clock.points[-1][1]


def test_a_log_without_model_time_has_no_simulated_time(parsed, assessed):
    assert health.model_clock(parsed["slurm_generic"]) is None
    assert "sim_seconds" not in assessed["slurm_generic"].stats


def test_imbalance_never_fails_a_run_on_its_own(assessed):
    check = assessed["icon_success"].check("imbalance")
    assert check is not None
    assert check.level in {"ok", "info", "warn"}
    assert "8.00x" in check.headline


def test_io_cadence_is_measured_between_output_files():
    log = _io_log([150.0] * 6)
    gaps = health.io_cadence(log)["output_write"]
    assert [g["seconds"] for g in gaps] == pytest.approx([150.0] * 6)


def test_io_cadence_flags_a_gap_far_from_the_typical_one():
    log = _io_log([150.0] * 6 + [1200.0])
    a = health.assess(log, now=log.last_wall + 1)
    check = a.check("io_cadence_output_write")
    assert check is not None
    assert check.level in {"warn", "info"}
    assert "1200" not in check.headline  # human-formatted, not raw seconds
    assert any("8x" in e for e in check.evidence)


def test_io_cadence_is_ok_when_regular():
    log = _io_log([150.0] * 6)
    a = health.assess(log, now=log.last_wall + 1)
    check = a.check("io_cadence_output_write")
    assert check is not None
    assert check.level == "ok"


def test_io_cadence_needs_a_few_events_before_judging():
    log = _io_log([150.0, 9000.0])
    a = health.assess(log, now=log.last_wall + 1)
    assert a.check("io_cadence_output_write") is None


def test_generic_profile_still_produces_useful_checks(assessed):
    a = assessed["slurm_generic"]
    assert a.status == "FAILED"
    assert a.check("outcome").level == "fail"
    assert a.check("stall").level == "fail"
    # No model profile, so no throughput or timer analysis.
    assert a.check("throughput") is None
    assert a.check("imbalance") is None


def test_missing_timestamps_are_reported_rather_than_guessed(assessed):
    check = assessed["icon_no_timestamps"].check("stall")
    assert check.level == "info"
    assert "timestamp" in check.detail.lower() or "timestamp" in check.headline.lower()


def test_suspect_nodes_name_the_reason(assessed):
    check = assessed["icon_hang"].check("suspect_nodes")
    assert check is not None
    assert any("nid000001" in e for e in check.evidence)


def test_grade_is_the_worst_check(assessed):
    for a in assessed.values():
        assert a.grade == max((c.level for c in a.checks), key=lambda x: health.LEVEL_RANK[x])


def test_empty_log_does_not_raise(assessed):
    a = assessed["empty"]
    assert a.grade in {"ok", "info", "warn", "fail"}


@pytest.mark.parametrize(
    "text,want", [("2020-01-01 00:00:20.000", 2020), ("2020-01-01T00:00:20Z", 2020)]
)
def test_parse_model_time(text, want):
    assert health.parse_model_time(text).year == want


def test_parse_model_time_rejects_rubbish():
    assert health.parse_model_time("whenever") is None


def test_status_uses_the_scheduler_when_it_can(parsed):
    log = parsed["truncated"]  # no final status of its own
    assert health.assess(log, now=1e12, slurm_state="PENDING").status == "QUEUED"
    assert health.assess(log, now=1e12, slurm_state="RUNNING").status == "STALLED"
    assert health.assess(log, now=1e12).status == "INCOMPLETE"


def _coupled_log(atmo: float, ocean: float, ranks: int = 8) -> RunLog:
    """A synthetic coupled run: one timer report per component, ``coupling`` in each."""

    def table(title: str, coupling: float) -> Table:
        return Table(
            name="timers",
            title=title,
            rows=[
                Row("total", 0, values={"total avg (s)": 100.0}),
                Row("integrate", 1, values={"total avg (s)": 100.0 - coupling}),
                Row("coupling", 1, values={"total avg (s)": coupling}),
                Row("cpl_get", 2, values={"total avg (s)": coupling * 0.9}),
            ],
        )

    return RunLog(
        fields={"atmo_ranks": ranks, "ocean_ranks": ranks},
        tables={
            "timers": [
                table(f"Timer report, ranks 0-{ranks - 1}", atmo),
                table(f"Timer report, ranks {ranks}-{2 * ranks - 1}", ocean),
            ]
        },
        settings={
            "timer_table": "timers",
            "timer_root": "total",
            "coupling_timers": ["coupling"],
            "coupling_wait_timers": ["cpl_get"],
            "timer_group_ranks": r"ranks\s+(\d+)\s*-\s*(\d+)",
        },
    )


def test_coupling_names_the_component_that_waits():
    a = health.assess(_coupled_log(atmo=40.0, ocean=5.0), now=1e12)
    check = a.check("coupling")
    assert check.level == "warn"
    assert "atmo is waiting for ocean" in check.headline
    assert any(e.startswith("atmo: 40%") for e in check.evidence)


def test_coupling_is_quiet_when_the_components_are_balanced():
    check = health.assess(_coupled_log(atmo=8.0, ocean=6.0), now=1e12).check("coupling")
    assert check.level == "ok"
    assert "waiting" not in check.headline


def test_coupling_check_is_absent_without_coupling_timers(assessed):
    """The bundled fixtures are single-component, so nothing is attributed."""
    assert assessed["slurm_generic"].check("coupling") is None


def _progress_log(gaps: list[float], model_step: float = 60.0, **fields) -> RunLog:
    """A synthetic run that reports progress after each wall-time gap."""
    walls = [0.0]
    for g in gaps:
        walls.append(walls[-1] + g)
    start = datetime(2020, 1, 1)
    series = [
        {"wall": w, "step": n, "model_time": f"{start + timedelta(seconds=n * model_step)}"}
        for n, w in enumerate(walls)
    ]
    return RunLog(
        first_wall=walls[0],
        last_wall=walls[-1],
        series={"timestep": series},
        series_roles={"timestep": "progress"},
        fields=fields,
    )


def test_first_interval_is_warm_up():
    a = health.assess(_progress_log([100.0] + [10.0] * 8))
    assert a.intervals[0]["warmup"] and not any(i.get("warmup") for i in a.intervals[1:])
    assert a.stats["sypd_steady"] > a.stats["sypd"]
    assert a.check("outliers") is None
    assert "after warm-up" in a.check("throughput").headline
    assert "SDPD" in a.check("throughput").headline


def test_rate_text_gives_days_per_day():
    assert health.rate_text(0.1) == "0.10 SYPD (36.5 SDPD)"


@pytest.mark.parametrize(
    "count,want", [(0, "ok"), (1041, "info"), (20000, "warn"), (200000, "fail")]
)
def test_network_timeouts_are_graded_by_count(count, want):
    log = _progress_log([10.0] * 6, network_timeouts=count)
    assert health.assess(log, now=log.last_wall + 1).check("network").level == want
