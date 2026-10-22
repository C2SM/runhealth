import json
from pathlib import Path

import pytest

from runhealth import cli, profile, simoutput, summary

np = pytest.importorskip("numpy")
xr = pytest.importorskip("xarray")

FIXTURES = Path(__file__).parent / "fixtures"
NLEV, NCELLS = 5, 8


def icon_output(path: Path, days: list[float], temp=None, fill: bool = False) -> Path:
    """A small file shaped like ICON output on the native grid, with ICON's time axis."""
    nt = len(days)
    t = np.full((nt, NLEV, NCELLS), 250.0) if temp is None else temp
    t = t + np.arange(NLEV)[None, :, None]  # warmer towards the lowest level
    ds = xr.Dataset(
        {
            "temp": (("time", "height", "ncells"), t),
            "pres": (("time", "height", "ncells"), np.full((nt, NLEV, NCELLS), 5e4)),
            "u": (("time", "height", "ncells"), np.full((nt, NLEV, NCELLS), 3.0)),
            "v": (("time", "height", "ncells"), np.full((nt, NLEV, NCELLS), 4.0)),
            "w": (("time", "height_2", "ncells"), np.zeros((nt, NLEV + 1, NCELLS))),
        },
        coords={
            "time": (
                "time",
                days,
                {"units": "day as %Y%m%d.%f", "calendar": "proleptic_gregorian"},
            ),
            "height": ("height", np.arange(1.0, NLEV + 1)),
            "height_2": ("height_2", np.arange(1.0, NLEV + 2)),
        },
    )
    if fill:
        ds["temp"].encoding["_FillValue"] = -999.0
    ds.to_netcdf(path)
    return path


def grid_file(path: Path) -> Path:
    # Two cells carry most of the area, so a weighted mean differs from a plain one.
    area = np.array([10.0, 10.0, 1, 1, 1, 1, 1, 1])
    xr.Dataset({"cell_area": (("cell",), area)}).to_netcdf(path)
    return path


def collect(out_dir: Path, grid: Path | None = None, prev=None) -> dict:
    icon = profile.load_all()["icon"]
    cfg = simoutput.config([icon], {"dir": out_dir, "grid": grid})
    return simoutput.collect(cfg, prev)


def test_statistics_per_step_and_level(tmp_path):
    icon_output(tmp_path / "out_0001.nc", [20200101.0, 20200101.25])
    out = collect(tmp_path)
    s = simoutput.series(out)
    assert set(s) == {"temp", "pres", "wind", "w"}
    temp = s["temp"]
    assert [r["time"] for r in temp] == ["2020-01-01T00:00:00", "2020-01-01T06:00:00"]
    assert temp[0]["min"] == 250.0 and temp[0]["max"] == 254.0
    assert temp[0]["max_level"] == "height 5" and temp[0]["nonfinite"] == 0
    assert temp[0]["means"] == {"height 1": 250.0, "height 3": 252.0, "height 5": 254.0}
    assert s["wind"][0]["max"] == 5.0  # sqrt(3^2 + 4^2)
    assert out["files"]["out_0001.nc"]["vars"]["temp"]["weights"] == "unweighted"


def test_means_are_weighted_by_cell_area(tmp_path):
    t = np.full((1, NLEV, NCELLS), 250.0)
    t[:, :, :2] = 260.0  # the two large cells are warmer
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    icon_output(out_dir / "a.nc", [20200101.0], temp=t)
    out = collect(out_dir, grid=grid_file(tmp_path / "grid.nc"))
    mean = simoutput.series(out)["temp"][0]["means"]["height 1"]
    assert mean == pytest.approx((2 * 10 * 260 + 6 * 250) / 26)
    assert out["files"]["a.nc"]["vars"]["temp"]["weights"] == "cell area"


def test_nonfinite_values_are_counted_but_fill_values_are_not(tmp_path):
    netcdf = pytest.importorskip("netCDF4")
    path = icon_output(tmp_path / "a.nc", [20200101.0], fill=True)
    # Written directly, since xarray would store a NaN as the fill value.
    with netcdf.Dataset(path, "r+") as nc:
        nc.set_auto_mask(False)
        nc["temp"][0, 0, 0] = -999.0
        nc["temp"][0, 3, 1] = np.nan
    rec = simoutput.series(collect(tmp_path))["temp"][0]
    assert rec["nonfinite"] == 1 and rec["bad_level"] == "height 4"
    assert rec["min"] == 250.0


def test_unchanged_files_are_not_read_again(tmp_path, monkeypatch):
    icon_output(tmp_path / "a.nc", [20200101.0])
    first = collect(tmp_path)
    icon_output(tmp_path / "b.nc", [20200102.0])
    read = []
    scan = simoutput._scan
    monkeypatch.setattr(simoutput, "_scan", lambda p, *a: read.append(p.name) or scan(p, *a))
    second = collect(tmp_path, prev=json.loads(json.dumps(first)))
    assert read == ["b.nc"]
    assert [t for t, _ in simoutput.steps(second)] == [1577836800.0, 1577923200.0]


def test_broken_and_empty_files_are_reported(tmp_path):
    (tmp_path / "empty.nc").write_bytes(b"")
    (tmp_path / "broken.nc").write_bytes(b"not netcdf")
    files = collect(tmp_path)["files"]
    assert files["empty.nc"]["error"] == "the file is empty"
    assert files["broken.nc"]["error"].startswith("cannot be read")


def _run(tmp_path, out_dir, *extra):
    out = tmp_path / "report"
    rc = cli.main(
        [
            str(FIXTURES / "icon_success.log"),
            "-o",
            str(out),
            "--no-squeue",
            "--output-dir",
            str(out_dir),
            *extra,
        ]
    )
    data = json.loads((out / summary.SUMMARY_FILE).read_text())["runs"][0]
    return rc, data, out


def test_end_to_end_checks_figures_and_summary(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    icon_output(out_dir / "a.nc", [20200101.0 + i / 96 for i in range(4)])  # every 15 minutes
    rc, run, report = _run(tmp_path, out_dir)
    assert rc == 0
    checks = {c["key"]: c for c in run["checks"]}
    assert checks["output_values"]["level"] == "ok"
    assert run["output"]["temp"]["max"][0] == 254.0
    page = (report / "icon_success.html").read_text()
    assert "Output: Temperature" in page


def test_a_blown_up_field_fails_the_run(tmp_path):
    t = np.full((2, NLEV, NCELLS), 250.0)
    t[1, 2, 5] = np.inf
    icon_output(tmp_path / "a.nc", [20200101.0, 20200101.25], temp=t)
    rc, run, _ = _run(tmp_path, tmp_path, "--fail-on", "fail")
    check = next(c for c in run["checks"] if c["key"] == "output_values")
    assert rc == cli.EXIT_GRADE and check["level"] == "fail"
    assert "2020-01-01 06:00:00" in check["headline"]


def test_a_gap_in_the_output_warns(tmp_path):
    days = [20200101.0 + i / 96 for i in (0, 1, 2, 5, 6)]
    icon_output(tmp_path / "a.nc", days)
    _, run, _ = _run(tmp_path, tmp_path)
    check = next(c for c in run["checks"] if c["key"] == "output_completeness")
    assert check["level"] == "warn" and "gap" in check["headline"]
