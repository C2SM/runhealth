from pathlib import Path

import pytest

from runhealth.logfile import (
    Line,
    format_duration,
    iter_lines,
    parse_stamp,
    parse_walltime,
    sniff,
)

FIXTURES = Path(__file__).parent / "fixtures"


def decode(text: str) -> Line:
    return next(iter(_lines(text)))


def _lines(text: str):
    from runhealth.logfile import _decode

    return [_decode(line, 0, i) for i, line in enumerate(text.splitlines(True))]


def test_stamp_matches_datetime():
    from datetime import datetime, timezone

    got = parse_stamp("2026-09-01T13:45:57.628")
    want = datetime(2026, 9, 1, 13, 45, 57, 628000, tzinfo=timezone.utc).timestamp()
    assert got == pytest.approx(want)


def test_stamp_rejects_rubbish():
    assert parse_stamp("not a date") is None
    assert parse_stamp("") is None


def test_decode_stamped_with_rank():
    line = decode("2026-09-01T13:45:57.628:   74:  total   1576\n")
    assert line.rank == 74
    assert line.text.strip().startswith("total")


def test_decode_stamped_without_rank():
    line = decode("2026-09-01T13:46:12.140: + srun_status=0\n")
    assert line.rank is None
    assert line.text == "+ srun_status=0"


def test_decode_bracketed_slurmd_stamp():
    line = decode("[2026-08-21T23:50:06.031] error: *** JOB 1 CANCELLED ***\n")
    assert line.wall is not None
    assert "CANCELLED" in line.text


def test_decode_plain_line():
    line = decode("#SBATCH --nodes=16\n")
    assert line.wall is None and line.rank is None


@pytest.mark.parametrize(
    "name,want",
    [
        ("icon_success", "timestamped"),
        ("icon_no_timestamps", "plain"),
        ("empty", "plain"),
    ],
)
def test_sniff(name, want):
    assert sniff(FIXTURES / f"{name}.log") == want


def test_sniff_looks_past_a_long_preamble():
    # The job script copy at the top of icon_success.log is unstamped.
    assert sniff(FIXTURES / "icon_success.log") == "timestamped"


@pytest.mark.parametrize(
    "text,want",
    [("03:00:00", 10800), ("1-12:00:00", 129600), ("45", 2700), ("12:30", 45000)],
)
def test_parse_walltime(text, want):
    assert parse_walltime(text) == want


def test_parse_walltime_rejects_rubbish():
    assert parse_walltime("soon") is None


@pytest.mark.parametrize(
    "seconds,want",
    [(0.35, "0.35s"), (46, "46s"), (95, "1m 35s"), (7987, "2h 13m 07s"), (None, "")],
)
def test_format_duration(seconds, want):
    assert format_duration(seconds) == want


def test_iter_lines_resumes_from_an_offset():
    path = FIXTURES / "icon_success.log"
    everything = list(iter_lines(path))
    half = everything[len(everything) // 2]
    rest = list(iter_lines(path, half.offset))
    assert rest[0].text == half.text
