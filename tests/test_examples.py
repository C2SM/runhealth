"""The sample logs in examples/ are what the README promises, so keep them true."""

from pathlib import Path

import pytest

from runhealth import extract, health, profile

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module")
def demos(profiles):
    out = {}
    for path in sorted(EXAMPLES.glob("*.log")):
        log = extract.parse(path, profile.detect(path, profiles))
        out[path.stem] = (log, health.assess(log))
    return out


def test_both_sample_logs_are_present(demos):
    assert set(demos) == {"demo", "demo_hang"}


def test_the_healthy_sample_exercises_the_whole_report(demos):
    log, a = demos["demo"]
    assert a.status == "SUCCESS"
    assert [p.name for p in a.phases][:3] == ["job setup", "model init", "coupling setup"]
    assert a.stats["sypd"] > 0
    # Every figure needs its input to be present in this one.
    for key in ("throughput", "imbalance", "hotspots", "network", "restart_io"):
        assert a.check(key) is not None, key
    assert log.tables["timers"] and log.tables["cxi_counters"]


def test_the_hung_sample_is_diagnosed_from_its_silence(demos):
    log, a = demos["demo_hang"]
    assert a.status == "FAILED"
    assert a.grade == "fail"
    assert a.check("stall").level == "fail"
    assert "coupling frame" in a.check("stall").headline
    assert a.check("walltime").level == "fail"
    # The phase the run died in must be named, not guessed.
    longest = max(a.phases, key=lambda p: p.seconds)
    assert longest.name == "coupling setup"


def test_the_figures_shipped_in_the_readme_can_be_regenerated(tmp_path, demos):
    from runhealth import plots

    figs = {f.key for f in plots.render_run(*demos["demo"], tmp_path, "demo", dpi=60)}
    assert {"progress", "timers", "warnings"} <= figs
    hang = {f.key for f in plots.render_run(*demos["demo_hang"], tmp_path, "hang", dpi=60)}
    assert "timeline" in hang
