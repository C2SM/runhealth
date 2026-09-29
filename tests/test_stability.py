import math

import pytest

from runhealth import extract, health, plots
from runhealth.logfile import Line

HEALTHY = (
    "MAXABS VN, W in domain  1:  0.1611815346E+03 at level  18,   0.4905669340E+02 at level  37,"
)
BLOWN = (
    "MAXABS VN, W in domain  1:  0.2241437351+279 at level  32,   0.2069835235+166 at level   2,"
)


def _run(profiles, texts: list[str]) -> extract.RunLog:
    ex = extract.Extractor([profiles["slurm"], profiles["icon"]])
    for n, text in enumerate(texts):
        ex.feed(Line(wall=1000.0 + n, rank=0, text=text, offset=0, number=n + 1))
    return ex.finish()


@pytest.mark.parametrize(
    "raw, value",
    [
        ("0.1611815346E+03", 161.1815346),
        ("0.2241437351+279", 2.241437351e278),
        ("-0.5-123", -0.5e-123),
        ("1.5D+02", 150.0),
        ("*******", math.inf),
        ("garbage", None),
    ],
)
def test_fortran_floats(raw, value):
    assert extract._cast(raw, "float") == value


def test_nan_is_kept():
    assert math.isnan(extract._cast("NaN", "float"))


@pytest.mark.parametrize(
    "text, vn, w",
    [
        (HEALTHY, {"vn": 161.1815346, "level": 18}, {"w": 49.0566934, "level": 37}),
        (
            "MAXABS VN, W in domain  1:  0.1611815346E+03 (on proc #  481, level  18),"
            "   0.4905669340E+02 (on proc #   12, level  37), ",
            {"vn": 161.1815346, "rank": 481, "level": 18},
            {"w": 49.0566934, "rank": 12, "level": 37},
        ),
        (
            "MAXABS VN, W   0.1611815346E+03  0.4905669340E+02",
            {"vn": 161.1815346},
            {"w": 49.0566934},
        ),
    ],
)
def test_every_msg_level_format_of_the_wind_maxima(profiles, text, vn, w):
    log = _run(profiles, [text])
    for name, want in (("max_vn", vn), ("max_w", w)):
        got = {k: v for k, v in log.series[name][0].items() if k != "wall" and v is not None}
        assert got == pytest.approx(want)


def test_cfl_watch_mode_is_read(profiles):
    log = _run(
        profiles,
        [
            "High CFL number for horizontal or vertical advection in dynamical core, entering watch mode",
            "Maximum vertical CFL number in domain   1: 1.5116",
            "Number of dynamics substeps in domain   1 increased to   7",
            "Maximum vertical CFL number in domain   1:*******",
        ],
    )
    assert [r["cfl"] for r in log.series["vertical_cfl"]] == [1.5116, math.inf]
    assert log.series["substeps_increased"][0]["substeps"] == 7
    assert len(log.series["cfl_watch"]) == 1


def test_a_peak_series_is_binned_and_keeps_its_peaks(profiles, monkeypatch):
    monkeypatch.setattr(extract, "MAX_BINNED_EVENTS", 8)
    texts = [HEALTHY] * 40
    texts[13] = HEALTHY.replace("0.4905669340E+02", "0.9900000000E+02")
    log = _run(profiles, texts)
    records = log.series["max_w"]
    assert len(records) < 8
    assert log.series_stride["max_w"] > 1
    assert max(r["w"] for r in records) == pytest.approx(99.0)
    # A series without ``peak`` is not binned.
    assert "timestep" not in log.series_stride


def test_the_first_breach_is_kept_exactly_despite_binning(profiles, monkeypatch):
    monkeypatch.setattr(extract, "MAX_BINNED_EVENTS", 4)
    log = _run(profiles, [HEALTHY] * 20 + [BLOWN, BLOWN.replace("+279", "+300")])
    before, first = log.series_breach["max_vn"]
    assert before["vn"] == pytest.approx(161.1815346)
    assert first["vn"] == pytest.approx(2.241437351e278)
    assert first["level"] == 32


def test_a_blow_up_fails_the_run_and_names_the_first_report(profiles):
    log = _run(profiles, [HEALTHY] * 5 + [BLOWN])
    check = health.assess(log).check("stability")
    assert check.level == "fail"
    assert "horizontal wind |vn| blew up to 2.24e+278 m/s" in check.headline
    assert any("level 2" in e for e in check.evidence)
    assert any("report before: 49.06 m/s" in e for e in check.evidence)


def test_an_overflowing_cfl_number_fails_without_a_threshold(profiles):
    log = _run(profiles, ["Maximum vertical CFL number in domain   1:*******"])
    assert health.assess(log).check("stability").level == "fail"


def test_a_high_but_finite_wind_warns(profiles):
    log = _run(profiles, [HEALTHY.replace("0.4905669340E+02", "0.1500000000E+03")])
    check = health.assess(log).check("stability")
    assert check.level == "warn"
    assert "vertical wind |w| reached 150 m/s" in check.headline


def test_a_healthy_run_is_ok_and_counts_the_events(profiles):
    log = _run(
        profiles,
        [HEALTHY, "Number of dynamics substeps in domain   1 increased to   6", HEALTHY],
    )
    check = health.assess(log).check("stability")
    assert check.level == "ok"
    assert any(e.startswith("1 dynamics substep increases") for e in check.evidence)


def test_a_log_without_stability_output_has_no_check(assessed):
    assert assessed["slurm_generic"].check("stability") is None


def test_one_figure_per_group_with_the_blow_up_pinned_in_red(profiles):
    log = _run(
        profiles,
        [HEALTHY] * 5
        + [
            BLOWN,
            "Maximum vertical CFL number in domain   1: 1.2",
            "High CFL number for horizontal or vertical advection",
        ],
    )
    figures = plots.stability(log, health.assess(log), "t")
    assert [f.title for f in figures] == ["Maximum wind speed", "CFL number"]
    assert "lv-fail" in figures[0].svg
    assert "Infinity" not in figures[0].svg and "NaN" not in figures[0].svg
