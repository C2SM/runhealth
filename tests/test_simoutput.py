import json
import os
from pathlib import Path

import pytest

from runhealth import cli, profile, simoutput, summary

np = pytest.importorskip("numpy")
xr = pytest.importorskip("xarray")

FIXTURES = Path(__file__).parent / "fixtures"
NLEV, NCELLS = 5, 8
ATM = "exp_atm_3d_pl_20200101.nc"  # a name the ICON profile reads


def icon_output(
    path: Path, days: list[float], temp=None, fill: bool = False, cmip: bool = False
) -> Path:
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
    if cmip:  # the names of an ICON output on pressure levels
        ds = ds.rename({"temp": "ta", "u": "ua", "v": "va", "w": "wa"}).drop_vars("pres")
    ds.to_netcdf(path)
    return path


def grid_file(path: Path) -> Path:
    # Two cells carry most of the area, so a weighted mean differs from a plain one.
    area = np.array([10.0, 10.0, 1, 1, 1, 1, 1, 1])
    xr.Dataset({"cell_area": (("cell",), area)}).to_netcdf(path)
    return path


def collect(out_dir: Path, grid: Path | None = None, prev=None) -> dict:
    icon = profile.load_all()["icon"]
    cfg = simoutput.config([icon], {"dir": out_dir, "grid": grid}, {})
    return simoutput.collect(cfg, prev)


def test_statistics_per_step_and_level(tmp_path):
    icon_output(tmp_path / "exp_atm_0001.nc", [20200101.0, 20200101.25])
    out = collect(tmp_path)
    s = simoutput.series(out)
    assert set(s) == {"temp", "pres", "wind", "w"}
    temp = s["temp"]
    assert [r["time"] for r in temp] == ["2020-01-01T00:00:00", "2020-01-01T06:00:00"]
    assert temp[0]["min"] == 250.0 and temp[0]["max"] == 254.0
    assert temp[0]["max_level"] == "height 5" and temp[0]["nonfinite"] == 0
    assert temp[0]["means"] == {"height 1": 250.0, "height 3": 252.0, "height 5": 254.0}
    assert s["wind"][0]["max"] == 5.0  # sqrt(3^2 + 4^2)
    assert out["files"]["exp_atm_0001.nc"]["vars"]["temp"]["weights"] == "unweighted"


def test_means_are_weighted_by_cell_area(tmp_path):
    t = np.full((1, NLEV, NCELLS), 250.0)
    t[:, :, :2] = 260.0  # the two large cells are warmer
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    icon_output(out_dir / ATM, [20200101.0], temp=t)
    out = collect(out_dir, grid=grid_file(tmp_path / "grid.nc"))
    mean = simoutput.series(out)["temp"][0]["means"]["height 1"]
    assert mean == pytest.approx((2 * 10 * 260 + 6 * 250) / 26)
    assert out["files"][ATM]["vars"]["temp"]["weights"] == "cell area"


def test_nonfinite_values_are_counted_but_fill_values_are_not(tmp_path):
    netcdf = pytest.importorskip("netCDF4")
    path = icon_output(tmp_path / ATM, [20200101.0], fill=True)
    # Written directly, since xarray would store a NaN as the fill value.
    with netcdf.Dataset(path, "r+") as nc:
        nc.set_auto_mask(False)
        nc["temp"][0, 0, 0] = -999.0
        nc["temp"][0, 3, 1] = np.nan
    rec = simoutput.series(collect(tmp_path))["temp"][0]
    assert rec["nonfinite"] == 1 and rec["bad_level"] == "height 4"
    assert rec["min"] == 250.0


def test_unchanged_files_are_not_read_again(tmp_path, monkeypatch):
    icon_output(tmp_path / ATM, [20200101.0])
    first = collect(tmp_path)
    icon_output(tmp_path / "exp_atm_b.nc", [20200102.0])
    read = []
    scan = simoutput._scan
    monkeypatch.setattr(simoutput, "_scan", lambda p, *a: read.append(p.name) or scan(p, *a))
    second = collect(tmp_path, prev=json.loads(json.dumps(first)))
    assert read == ["exp_atm_b.nc"]
    assert [t for t, _ in simoutput.steps(second)] == [1577836800.0, 1577923200.0]


def test_broken_and_empty_files_are_reported(tmp_path):
    (tmp_path / "exp_atm_empty.nc").write_bytes(b"")
    (tmp_path / "exp_atm_broken.nc").write_bytes(b"not netcdf")
    files = collect(tmp_path)["files"]
    assert files["exp_atm_empty.nc"]["error"] == "the file is empty"
    assert files["exp_atm_broken.nc"]["error"].startswith("cannot be read")


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
            "--no-submit",
            *extra,
        ]
    )
    data = json.loads((out / summary.SUMMARY_FILE).read_text())["runs"][0]
    return rc, data, out


def test_end_to_end_checks_figures_and_summary(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    icon_output(out_dir / ATM, [20200101.0 + i / 96 for i in range(4)])  # every 15 minutes
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
    icon_output(tmp_path / ATM, [20200101.0, 20200101.25], temp=t)
    rc, run, _ = _run(tmp_path, tmp_path, "--fail-on", "fail")
    check = next(c for c in run["checks"] if c["key"] == "output_values")
    assert rc == cli.EXIT_GRADE and check["level"] == "fail"
    assert "2020-01-01 06:00:00" in check["headline"]


def test_a_gap_in_the_output_warns(tmp_path):
    days = [20200101.0 + i / 96 for i in (0, 1, 2, 5, 6)]
    icon_output(tmp_path / ATM, days)
    _, run, _ = _run(tmp_path, tmp_path)
    check = next(c for c in run["checks"] if c["key"] == "output_completeness")
    assert check["level"] == "warn" and "gap" in check["headline"]


def test_cmip_style_names_are_found(tmp_path):
    icon_output(tmp_path / ATM, [20200101.0], cmip=True)
    out = collect(tmp_path)
    found = simoutput.series(out)
    assert set(found) == {"temp", "wind", "w"}
    assert found["wind"][0]["max"] == 5.0
    assert out["files"][ATM]["vars"]["wind"]["source"] == "ua, va"
    assert out["files"][ATM]["vars"]["w"]["source"] == "wa"


def test_auto_takes_the_output_directory_from_the_log(tmp_path):
    out_dir = tmp_path / "exp"
    out_dir.mkdir()
    icon_output(out_dir / ATM, [20200101.0])
    log = tmp_path / "LOG.exp.12345.o"
    text = (FIXTURES / "icon_success.log").read_text()
    log.write_text(text + f"2026-01-05T10:01:01.600: + EXPDIR={out_dir}\n")
    report = tmp_path / "report"
    args = [str(log), "-o", str(report), "--no-squeue", "--output-dir", "auto", "--no-submit"]
    assert cli.main(args) == 0
    run = json.loads((report / summary.SUMMARY_FILE).read_text())["runs"][0]
    assert run["output"]["temp"]["max"] == [254.0]


def test_an_unreachable_output_directory_is_information(tmp_path):
    icon = profile.load_all()["icon"]
    log = {"settings": {"output_dir_field": "output_dir"}, "fields": {}}
    out = simoutput.collect(simoutput.config([icon], {"dir": "auto"}, log))
    assert out["error"] == "the log does not name an output directory"
    log["fields"]["output_dir"] = str(tmp_path / "elsewhere")
    out = simoutput.collect(simoutput.config([icon], {"dir": "auto"}, log))
    assert out["error"].endswith("is not reachable from this machine")


def test_the_icon_profile_leaves_out_ocean_output_and_input_files(tmp_path):
    icon_output(tmp_path / ATM, [20200101.0])
    icon_output(tmp_path / "exp_oce_3d_full_20200101.nc", [20200101.0])
    icon_output(tmp_path / "ifs2icon.nc", [20200101.0])
    assert list(collect(tmp_path)["files"]) == [ATM]


def test_a_directory_shared_by_several_runs_is_read_once(tmp_path, monkeypatch):
    monkeypatch.setenv("SLURM_JOB_ID", "1")  # inside a job, the output is read right away
    out_dir = tmp_path / "exp"
    out_dir.mkdir()
    icon_output(out_dir / ATM, [20200101.0])
    text = (FIXTURES / "icon_success.log").read_text()
    logs = []
    for job in ("12345", "12346"):
        logs.append(tmp_path / f"LOG.exp.{job}.o")
        logs[-1].write_text(text + f"2026-01-05T10:01:01.600: + EXPDIR={out_dir}\n")
    read = []
    scan = simoutput._scan
    monkeypatch.setattr(simoutput, "_scan", lambda p, *a: read.append(p.name) or scan(p, *a))
    report = tmp_path / "report"
    args = [
        *map(str, logs),
        "-o",
        str(report),
        "--no-squeue",
        "--output-dir",
        "auto",
        "--jobs",
        "1",
    ]
    assert cli.main(args) == 0
    runs = json.loads((report / summary.SUMMARY_FILE).read_text())["runs"]
    assert read == [ATM]
    assert [r["output"]["temp"]["max"] for r in runs] == [[254.0], [254.0]]
    assert cli.main(args) == 0
    assert read == [ATM]  # the second pass finds the summary in the cache


def test_outside_a_job_the_output_is_read_in_one(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sbatch = bin_dir / "sbatch"
    sbatch.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {tmp_path}/args\necho 4242\n')
    sbatch.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    monkeypatch.chdir(tmp_path)
    log = str(FIXTURES / "icon_success.log")
    args = [
        log,
        "-o",
        "report",
        "--output-dir",
        "out",
        "--sbatch",
        "--account=cwd01 --time=03:00:00",
    ]
    assert cli.main(args) == 0
    sent = (tmp_path / "args").read_text().splitlines()
    assert sent[-4:-2] == ["--account=cwd01", "--time=03:00:00"]
    assert sent[-2] == "--wrap" and sent[-1].endswith(
        f"-m runhealth {log} -o report --output-dir out "
        "--sbatch '--account=cwd01 --time=03:00:00'"
    )
    assert f"--output={tmp_path}/runhealth.%j.out" in sent
    assert not (tmp_path / "report").exists()  # the job writes it


def test_a_file_without_a_time_step_warns(tmp_path):
    icon_output(tmp_path / ATM, [20200101.0, 20200101.25])
    units = {"units": "minutes since 2020-1-1 00:00:00", "calendar": "gregorian"}
    hollow = xr.Dataset(
        {"temp": (("time", "ncells"), np.zeros((0, NCELLS)))},
        coords={"time": ("time", np.zeros(0), units)},
    )
    hollow.to_netcdf(tmp_path / "exp_atm_2d_20200102.nc")
    assert collect(tmp_path)["files"]["exp_atm_2d_20200102.nc"]["steps"] == []
    _, run, _ = _run(tmp_path, tmp_path)
    check = next(c for c in run["checks"] if c["key"] == "output_completeness")
    assert check["level"] == "warn" and "1 file(s) hold no output step" in check["headline"]


def test_a_file_that_failed_is_read_again(tmp_path):
    (tmp_path / ATM).write_bytes(b"not netcdf")
    first = collect(tmp_path)
    assert first["files"][ATM]["error"].startswith("cannot be read")
    _, todo = simoutput.plan(first, json.loads(json.dumps(first)))
    assert [p.name for p in todo] == [ATM]
