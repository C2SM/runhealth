"""Diagnostics of the simulation output: what the model wrote, not what it logged.

For every variable a profile names under ``output``, each output time step
yields the minimum, the maximum and the number of non-finite values over the
whole three-dimensional field, and the area-weighted mean on the top, middle
and lowest level. Fields are read one level at a time, so that a global field
at kilometer scale never has to fit into memory at once.

Reading NetCDF needs the optional dependencies ``runhealth[output]``. The
summary of each file is kept with the parsed log and read again only when the
file changes, which makes a repeated pass over a growing run cheap. :func:`plan` and
:func:`read` split :func:`collect` so that a caller can read the files of
several directories in parallel and follow its progress.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

AUTO = "auto"  # --output-dir value that reads each run's directory from its log
DEFAULT_GLOB = "*.nc"
EPOCH = "seconds since 1970-01-01 00:00:00"
LATLON = ("lat", "lon")
MISSING = "the output diagnostics need the optional dependencies: pip install 'runhealth[output]'"


def config(profiles, options: dict, log: dict) -> dict:
    """The output section of the selected profiles, completed by the command line.

    ``options["dir"]`` set to ``auto`` takes each run's directory from the field
    of its log that the ``output_dir_field`` setting names.
    """
    spec: dict[str, Any] = {"variables": {}}
    for p in profiles:
        section = getattr(p, "output", None) or {}
        spec.update({k: v for k, v in section.items() if k != "variables"})
        spec["variables"].update(section.get("variables") or {})
    where = options["dir"]
    if where == AUTO:
        field = (log.get("settings") or {}).get("output_dir_field", "")
        where = (log.get("fields") or {}).get(field)
    return {
        "dir": str(Path(where).resolve()) if where else None,
        "glob": options.get("glob") or spec.get("files") or DEFAULT_GLOB,
        "grid": str(Path(options["grid"]).resolve()) if options.get("grid") else None,
        "variables": spec["variables"],
    }


def collect(cfg: dict, prev: dict | None = None) -> dict:
    """Summarize every output file, reusing the summary of a file that has not changed."""
    out, todo = plan(cfg, prev)
    for path in todo:
        out["files"][path.name] = read(path, cfg)
    return out


def plan(cfg: dict, prev: dict | None = None) -> tuple[dict, list[Path]]:
    """The summary of every file unchanged since ``prev``, and the files still to read."""
    try:
        import numpy  # noqa: F401
        import xarray  # noqa: F401
    except ImportError:
        return {**cfg, "error": MISSING, "files": {}}, []
    if not cfg["dir"]:
        return {**cfg, "error": "the log does not name an output directory", "files": {}}, []
    if not Path(cfg["dir"]).is_dir():
        return {**cfg, "error": f"{cfg['dir']} is not reachable from this machine", "files": {}}, []
    key = json.dumps([cfg["variables"], cfg["grid"]], sort_keys=True)
    old = (prev or {}).get("files", {}) if (prev or {}).get("key") == key else {}
    files: dict[str, dict] = {}
    todo: list[Path] = []
    for path in sorted(Path(cfg["dir"]).glob(cfg["glob"])):
        if not path.is_file():
            continue
        st = path.stat()
        rec = old.get(path.name)
        if rec and rec["size"] == st.st_size and rec["mtime"] == st.st_mtime:
            files[path.name] = rec
        elif not st.st_size:
            files[path.name] = {"size": 0, "mtime": st.st_mtime, "error": "the file is empty"}
        else:
            todo.append(path)
    return {**cfg, "key": key, "files": files}, todo


def read(path: Path, cfg: dict) -> dict:
    """The summary of one file; a file that cannot be read yields an error, not an exception."""
    st = path.stat()
    rec: dict[str, Any] = {"size": st.st_size, "mtime": st.st_mtime}
    try:
        rec.update(_scan(path, cfg["variables"], _area(cfg["grid"])))
    except Exception as exc:  # one broken file must not hide the others
        rec["error"] = f"cannot be read: {exc}"
    return rec


def series(output: dict) -> dict[str, list[dict]]:
    """Each variable's statistics per output time step, across all files, in time order."""
    out: dict[str, list[dict]] = {}
    for name, rec in sorted((output or {}).get("files", {}).items()):
        steps = rec.get("steps") or []
        for var, stats in (rec.get("vars") or {}).items():
            for i, (time, seconds) in enumerate(steps):
                out.setdefault(var, []).append(
                    {
                        "time": time,
                        "t": seconds,
                        "file": name,
                        **{k: v[i] for k, v in stats.items() if isinstance(v, list)},
                        "means": {label: v[i] for label, v in stats["means"].items()},
                    }
                )
    for records in out.values():
        records.sort(key=lambda r: r["t"])
    return out


def steps(output: dict) -> list[tuple[float, str]]:
    """Every distinct output time, in order."""
    seen = {
        t: time
        for rec in (output or {}).get("files", {}).values()
        for time, t in rec.get("steps") or []
    }
    return sorted(seen.items())


# -- reading --------------------------------------------------------------


class _Area:
    """Cell areas from an ICON grid file, read once and only when a field needs them."""

    def __init__(self, grid: str | None):
        self.grid, self._values = grid, None

    def values(self):
        if self.grid and self._values is None:
            import xarray as xr

            with xr.open_dataset(self.grid, decode_times=False) as ds:
                self._values = ds["cell_area"].values.astype("float64")
        return self._values


_AREAS: dict[str | None, _Area] = {}  # per process, so a worker reads each grid once


def _area(grid: str | None) -> _Area:
    return _AREAS.setdefault(grid, _Area(grid))


def _scan(path: Path, variables: dict, area: _Area) -> dict:
    import xarray as xr

    # Fill values are handled here rather than turned into NaN, so that a NaN
    # left in the field is one the model wrote.
    with xr.open_dataset(path, decode_times=False, mask_and_scale=False, cache=False) as ds:
        tname = "time" if "time" in ds.variables else None
        rec: dict[str, Any] = {"steps": _times(ds[tname]) if tname else [], "vars": {}}
        for name, spec in variables.items():
            sources = _sources(spec.get("names") or [name], ds)
            if sources:
                rec["vars"][name] = _stats([ds[s] for s in sources], ds, tname, area)
                rec["vars"][name]["source"] = ", ".join(sources)
        return rec


def _sources(names: list, ds) -> list[str]:
    """The first alternative a file holds; a list of names is the components of a magnitude."""
    for alt in names:
        parts = alt if isinstance(alt, list) else [alt]
        if all(p in ds.data_vars for p in parts):
            return parts
    return []


def _times(var) -> list[tuple[str, float]]:
    """ISO model time and seconds since 1970 of each step, in the file's calendar."""
    import numpy as np

    units = var.attrs.get("units", "")
    values = np.atleast_1d(var.values).astype("float64")
    if units.startswith("day as %Y%m%d"):
        # ICON's absolute time axis: the date as digits, the time of day as a fraction.
        out = []
        for v in values:
            day = int(v)
            d = datetime.strptime(str(day), "%Y%m%d") + timedelta(seconds=round((v - day) * 86400))
            out.append((d.isoformat(), (d - datetime(1970, 1, 1)).total_seconds()))
        return out
    import cftime

    calendar = var.attrs.get("calendar", "standard")
    dates = cftime.num2date(values, units, calendar)
    seconds = cftime.date2num(dates, EPOCH, calendar)
    return [(d.isoformat(), float(s)) for d, s in zip(dates, np.atleast_1d(seconds))]


def _stats(arrays, ds, tname: str | None, area: _Area) -> dict:
    import numpy as np

    da = arrays[0]
    dims = list(da.dims)
    hdims = list(LATLON) if all(d in dims for d in LATLON) else dims[-1:]
    vdims = [d for d in dims if d != tname and d not in hdims]
    vdim = vdims[0] if vdims else None
    nt = da.sizes[tname] if tname in dims else 1
    nlev = da.sizes[vdim] if vdim else 1
    weights, kind = _weights(da, ds, hdims, area)
    picks = sorted({0, nlev // 2, nlev - 1})
    labels = [_level(ds, vdim, k) for k in picks]
    out: dict[str, Any] = {
        "min": [], "max": [], "nonfinite": [], "min_level": [], "max_level": [], "bad_level": [],
        "means": {label: [] for label in labels}, "weights": kind,
    }  # fmt: skip
    for t in range(nt):
        lo, hi, bad = math.inf, -math.inf, 0
        lo_k = hi_k = bad_k = None
        for k in range(nlev):
            sel = {d: i for d, i in ((tname, t), (vdim, k)) if d in dims}
            field, valid = _field(arrays, sel)
            finite = valid & np.isfinite(field)
            n_bad = int(valid.sum() - finite.sum())
            if n_bad:
                bad += n_bad
                bad_k = bad_k if bad_k is not None else _level(ds, vdim, k)
            if finite.any():
                vals = field[finite]
                mn, mx = float(vals.min()), float(vals.max())
                if mn < lo:
                    lo, lo_k = mn, _level(ds, vdim, k)
                if mx > hi:
                    hi, hi_k = mx, _level(ds, vdim, k)
            if k in picks:
                w = weights[finite] if weights is not None else None
                total = float(w.sum()) if w is not None else float(finite.sum())
                mean = (
                    float(
                        (field[finite] * w).sum() / total if w is not None else field[finite].mean()
                    )
                    if total
                    else None
                )
                out["means"][labels[picks.index(k)]].append(mean)
        out["min"].append(lo if lo_k is not None else None)
        out["max"].append(hi if hi_k is not None else None)
        out["nonfinite"].append(bad)
        out["min_level"].append(lo_k)
        out["max_level"].append(hi_k)
        out["bad_level"].append(bad_k)
    return out


def _field(arrays, sel: dict):
    """One horizontal slice, as values and a mask of the points that hold data."""
    import numpy as np

    parts, valid = [], None
    for a in arrays:
        raw = np.asarray(a.isel(sel).values, dtype="float64")
        ok = np.ones(raw.shape, dtype=bool)
        for key in ("_FillValue", "missing_value"):
            if key in a.attrs:
                ok &= raw != float(a.attrs[key])
        raw = raw * float(a.attrs.get("scale_factor", 1.0)) + float(a.attrs.get("add_offset", 0.0))
        parts.append(raw.ravel())
        valid = ok.ravel() if valid is None else valid & ok.ravel()
    field = parts[0] if len(parts) == 1 else np.sqrt(sum(p * p for p in parts))
    return field, valid


def _weights(da, ds, hdims: list[str], area: _Area):
    """Cell areas on the native grid, cos(latitude) on a regular one, else none, and which."""
    import numpy as np

    if hdims == list(LATLON) and "lat" in ds.variables:
        lat = np.deg2rad(ds["lat"].values.astype("float64"))
        return np.repeat(np.cos(lat), da.sizes["lon"]), "cos(latitude)"
    cells = area.values()
    if cells is not None and cells.size == da.sizes[hdims[0]]:
        return cells, "cell area"
    return None, "unweighted"


def _level(ds, vdim: str | None, k: int) -> str:
    if vdim is None:
        return "surface"
    if vdim in ds.variables:
        return f"{vdim} {float(ds[vdim].values[k]):g}"
    return f"{vdim} {k + 1}"
