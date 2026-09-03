import pytest

from runhealth import health


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


def test_imbalance_never_fails_a_run_on_its_own(assessed):
    check = assessed["icon_success"].check("imbalance")
    assert check is not None
    assert check.level in {"ok", "info", "warn"}
    assert "8.00x" in check.headline


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
