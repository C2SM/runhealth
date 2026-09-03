import pytest

from runhealth import profile


@pytest.mark.parametrize(
    "pattern,want",
    [
        (r"Time step:\s+(\d+) model time", "model time"),
        (r"^\s*version: (\S+)", "version:"),
        (r"atmo runs on\s+(\d+) mpi processes", "mpi processes"),
        (r"WARNING PE:\s+(\d+)\s+(\S+)", "WARNING PE:"),
        # An alternation could bypass any literal, so no hint may be offered.
        (r"Constructing the (atmosphere|ocean) coupling frame", ""),
        (r"(alternative_long_thing|x) ab", ""),
        # Quantified characters are optional, so they must not end up in a hint.
        (r"colou?r report", "r report"),
        ("ab", ""),
    ],
)
def test_literal_hint_is_conservative(pattern, want):
    assert profile.literal_hint(pattern) == want


def test_literal_hint_never_lies():
    """Whatever hint we derive must appear in a string the pattern matches."""
    import re

    cases = [
        (r"Time step:\s+(\d+) model", "Time step:      7 model"),
        (r"^\s*revision: (\S+)", "  revision: abc"),
        (
            r"srun: error: (\S+): tasks? ([\d,\-]+): (.+)",
            "srun: error: nid1: tasks 1-2: Terminated",
        ),
    ]
    for pattern, sample in cases:
        hint = profile.literal_hint(pattern)
        assert re.search(pattern, sample), sample
        assert hint in sample


def test_bundled_profiles_load(profiles):
    assert {"slurm", "icon", "cray-mpich"} <= set(profiles)
    assert profiles["slurm"].always


def test_detection_composes_profiles(profiles):
    from pathlib import Path

    path = Path(__file__).parent / "fixtures" / "icon_success.log"
    names = [p.name for p in profile.detect(path, profiles)]
    assert names == ["slurm", "icon", "cray-mpich"]


def test_unknown_log_still_gets_the_generic_profile(profiles):
    from pathlib import Path

    path = Path(__file__).parent / "fixtures" / "not_a_log.log"
    assert [p.name for p in profile.detect(path, profiles)] == ["slurm"]


def test_select_rejects_unknown_names(profiles):
    with pytest.raises(KeyError):
        profile.select(["nope"], profiles)


def test_extra_profile_directory_is_picked_up(tmp_path):
    (tmp_path / "mine.yaml").write_text(
        "name: mine\ndescription: test\ndetect: ['hello world']\n"
        "fields:\n  greeting: {re: 'hello (\\w+)'}\n"
    )
    loaded = profile.load_all([tmp_path])
    assert "mine" in loaded
    assert loaded["mine"].fields[0].name == "greeting"
