from pathlib import Path

from runhealth import extract, profile

FIXTURES = Path(__file__).parent / "fixtures"


def test_job_metadata(parsed):
    log = parsed["icon_success"]
    assert log.fields["job_id"] == "4242"
    assert log.fields["node_count"] == 2
    assert log.keyvalues["sbatch"]["time"] == "01:00:00"
    assert log.keyvalues["sbatch"]["nodes"] == "2"


def test_model_provenance(parsed):
    log = parsed["icon_success"]
    assert log.fields["model_version"] == "2026.04"
    assert log.fields["model_branch"] == "main"
    assert log.fields["atmo_ranks"] == 8


def test_the_echoed_job_script_does_not_set_the_outcome(parsed):
    """The header contains both status strings; only the real one counts."""
    assert parsed["icon_success"].outcome.level == "ok"
    assert parsed["icon_hang"].outcome.level == "fail"
    assert "TIME LIMIT" in parsed["icon_hang"].outcome.text


def test_progress_series(parsed):
    steps = parsed["icon_success"].series["timestep"]
    assert [s["step"] for s in steps] == [1, 25, 50, 75, 100]
    assert steps[0]["model_time"] == "2020-01-01 00:00:20.000"


def test_io_series(parsed):
    restart = parsed["icon_success"].series["restart_write"]
    assert restart[0]["gigabytes"] == 12.5
    assert restart[0]["gb_per_s"] == 25.0


def test_gaps_are_ranked_and_carry_context(parsed):
    gaps = parsed["icon_hang"].gaps
    assert gaps[0].seconds == 3300
    assert "coupling frame" in gaps[0].before


def test_groups_aggregate_rather_than_store(parsed):
    warn = parsed["icon_success"].groups["icon_warning"]
    assert warn.total == 1
    assert list(warn.keys) == ["mo_demo:some_routine:"]


def test_claimed_lines_stay_out_of_the_generic_error_list(parsed):
    """srun task failures have their own group, so they are not double counted."""
    log = parsed["slurm_generic"]
    assert log.groups["srun_task_failure"].total == 1
    assert not any("tasks 12-15" in e.sample for e in log.errors.values())


def test_error_signatures_collapse_by_shape(parsed):
    errors = parsed["icon_hang"].errors
    assert len(errors) == 1
    assert "nid000001" in next(iter(errors.values())).nodes


def test_only_the_last_attempt_is_analysed(parsed):
    log = parsed["icon_two_attempts"]
    assert log.attempts == 2
    assert log.outcome.level == "ok"
    # Six hours separate the attempts; the surviving one is under a minute.
    assert log.wall_seconds < 120
    assert log.notes


def test_tables(parsed):
    log = parsed["icon_success"]
    timers = log.tables["timers"][0]
    assert "total avg (s)" in timers.columns
    assert [r.label for r in timers.rows][:2] == ["total", "integrate_nh"]
    assert log.tables["cxi_counters"][0].rows[0].label == "rh:nacks"


def test_nodes_are_collected(parsed):
    assert "nid000007" in parsed["slurm_generic"].nodes


def test_empty_and_garbage_files_do_not_raise(parsed):
    assert parsed["empty"].n_lines == 0
    assert parsed["not_a_log"].outcome is None


def test_truncated_file_parses(parsed):
    log = parsed["truncated"]
    assert log.n_lines > 0
    assert log.outcome is None


def test_state_round_trips_through_json(parsed):
    import json

    from runhealth.extract import RunLog

    log = parsed["icon_success"]
    again = RunLog.from_dict(json.loads(json.dumps(log.to_dict())))
    assert again.fields == log.fields
    assert [g.seconds for g in again.gaps] == [g.seconds for g in log.gaps]
    assert again.tables["timers"][0].columns == log.tables["timers"][0].columns


def test_resuming_from_an_offset_matches_a_full_pass(profiles):
    path = FIXTURES / "icon_success.log"
    picked = profile.detect(path, profiles)
    whole = extract.parse(path, picked)

    half = path.stat().st_size // 2
    with path.open("rb") as fh:
        fh.seek(half)
        fh.readline()
        cut = fh.tell()
    partial = extract.parse(path, picked, start=0)
    # Re-run the tail on top of the state the first pass left behind.
    partial_state = partial.to_dict()
    resumed = extract.parse(path, picked, start=cut, state=partial_state)
    assert resumed.outcome.text == whole.outcome.text
