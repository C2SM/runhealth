"""Command line entry point: ``runhealth [PATH ...]``.

Scans directories for job logs, parses each one, assesses it, and writes a
report: an index page listing every run plus one detail page per run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import __version__, plots, profile, report
from .extract import RunLog, parse
from .health import assess
from .logfile import format_duration
from .report import RunView

CACHE_VERSION = 3
DEFAULT_GLOB = "LOG.*.o"
LOG_GLOBS = [DEFAULT_GLOB, "slurm-*.out", "*.log", "*.out", "*.o[0-9]*"]
SINCE_RE = re.compile(r"^(\d+(?:\.\d+)?)([smhdw])$")
SINCE_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
MAX_EMBED_LOG = 8 << 20  # copy the raw log next to the report below this size
# Reports are written with the user's umask, which on a shared filesystem is
# often too tight for a web server to read, so the sync sets the modes it needs.
RSYNC_FLAGS = ["-rlptz", "--chmod=D755,F644"]


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "run"


def parse_since(text: str) -> float | None:
    m = SINCE_RE.match(text.strip().lower())
    return float(m.group(1)) * SINCE_UNITS[m.group(2)] if m else None


# -- discovery ------------------------------------------------------------


def discover(paths: list[Path], pattern: str | None) -> list[Path]:
    """Files to analyse, newest first."""
    found: list[Path] = []
    for p in paths:
        if p.is_file():
            found.append(p)
        elif p.is_dir():
            globs = [pattern] if pattern else LOG_GLOBS
            hits: list[Path] = []
            for g in globs:
                hits = sorted(f for f in p.glob(g) if f.is_file() and f.stat().st_size)
                # Without an explicit pattern, take the first shape that matches
                # rather than every text file in the directory.
                if hits and not pattern:
                    break
            found += hits
        else:
            log(f"runhealth: no such path: {p}")
    seen, out = set(), []
    for f in sorted(found, key=lambda f: f.stat().st_mtime, reverse=True):
        if f.resolve() not in seen:
            seen.add(f.resolve())
            out.append(f)
    return out


def slurm_states() -> dict[str, str]:
    """Job id to state for the current user, or empty if SLURM is unreachable."""
    try:
        r = subprocess.run(
            ["squeue", "--me", "-h", "-o", "%i %T"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if r.returncode != 0:
        return {}
    out = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            out[parts[0].split(".")[0].split("_")[0]] = parts[1]
    return out


# -- parsing with a cache -------------------------------------------------


def _cache_file(cache_dir: Path, path: Path) -> Path:
    return cache_dir / f"{slug(path.name)}.json"


def parse_cached(path: Path, names: list[str], dirs: list[str], cache_dir: str | None) -> dict:
    """Parse one log, reusing and updating an on-disk cache. Runs in a worker."""
    profiles = profile.load_all([Path(d) for d in dirs])
    picked = profile.select(names, profiles) if names else profile.detect(path, profiles)
    cache = Path(cache_dir) / f"{slug(path.name)}.json" if cache_dir else None
    state, start = None, 0
    stat = path.stat()
    if cache and cache.is_file():
        try:
            blob = json.loads(cache.read_text())
        except (OSError, ValueError):
            blob = {}
        same = (
            blob.get("version") == CACHE_VERSION
            and blob.get("profiles") == [p.name for p in picked]
            and blob.get("size", -1) <= stat.st_size
        )
        if same and blob.get("size") == stat.st_size and blob.get("mtime") == stat.st_mtime:
            return blob["state"]
        if same and blob.get("offset"):
            # Job logs only ever grow, so continue where the last pass stopped.
            state, start = blob["state"], int(blob["offset"])
    result = parse(path, picked, start=start, state=state)
    payload = RunLog.to_dict(result)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json.dumps(
                {
                    "version": CACHE_VERSION,
                    "profiles": [p.name for p in picked],
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "offset": result.offset,
                    "state": payload,
                }
            )
        )
    return payload


def parse_all(
    files: list[Path], names: list[str], dirs: list[Path], cache_dir: Path | None, jobs: int
) -> list[RunLog]:
    args = [
        (f, names, [str(d) for d in dirs], str(cache_dir) if cache_dir else None) for f in files
    ]
    if len(files) == 1 or jobs == 1:
        blobs = [parse_cached(*a) for a in args]
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            blobs = list(pool.map(_worker, args))
    return [RunLog.from_dict(b) for b in blobs]


def _worker(args) -> dict:
    return parse_cached(*args)


# -- rendering ------------------------------------------------------------


def build(args, files: list[Path], outdir: Path, states: dict[str, str]) -> list[RunView]:
    profile_dirs = [Path(d) for d in (args.profile_dir or [])]
    names = [n.strip() for n in (args.profile or "").split(",") if n.strip()]
    cache = None if args.no_cache else outdir / ".cache"
    jobs = max(1, min(len(files), args.jobs or (os.cpu_count() or 4), 16))
    t0 = time.time()
    logs = parse_all(files, names, profile_dirs, cache, jobs)
    log(f"runhealth: parsed {len(logs)} log(s) in {time.time() - t0:.1f}s")

    views: list[RunView] = []
    for rl in logs:
        if args.stall_seconds:
            rl.thresholds["stall_seconds"] = args.stall_seconds
        state = states.get(str(rl.fields.get("job_id") or ""), "")
        a = assess(rl, slurm_state=state)
        v = RunView(log=rl, assessment=a)
        v.page = f"{slug(Path(rl.path).stem)}.html"
        if not args.no_plots:
            # Markdown needs a figure it can point at; HTML inlines the same
            # markup and writes no image files at all.
            v.figures = plots.render_run(
                rl, a, outdir, slug(Path(rl.path).stem), standalone=args.format == "md"
            )
        if args.embed_logs:
            v.log_href = report.copy_log(rl, outdir, MAX_EMBED_LOG)
        views.append(v)
    return views


def write_report(args, views: list[RunView], outdir: Path, sources: list[str]) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    overview = None
    if not args.no_plots:
        overview = plots.render_index(
            [(v.log, v.assessment, v.page) for v in views],
            outdir,
            standalone=args.format == "md",
        )
    title = args.title or "Run health"
    if args.format == "md":
        path = outdir / "report.md"
        path.write_text(report.render_markdown(views, sources, title))
        return path
    for v in views:
        (outdir / v.page).write_text(report.render_run(v))
    index = outdir / "index.html"
    index.write_text(report.render_index(views, sources, overview, title))
    if args.format == "pdf":
        log(report.to_pdf(index, outdir / "report.pdf"))
        pdf = outdir / "report.pdf"
        if pdf.is_file():
            return pdf
    return index


def summarise(views: list[RunView]) -> None:
    for v in sorted(views, key=lambda v: v.log.first_wall or 0, reverse=True):
        a = v.assessment
        worst = next((c for c in a.checks if c.level == a.grade), None)
        log(
            f"  {a.grade.upper():<5} {a.status:<10} "
            f"{format_duration(a.stats.get('wall_seconds')):>12}  "
            f"{v.log.name}" + (f"  - {worst.headline[:70]}" if worst and a.grade != "ok" else "")
        )


# -- publishing -----------------------------------------------------------


def publish(outdir: Path, dest: str, url: str) -> bool:
    """Copy the report to a web server with rsync.

    ``dest`` is anything rsync understands, so a plain directory on a shared
    filesystem works as well as ``user@host:/var/www/runs``. Nothing is
    deleted at the far end: a report directory is frequently a subdirectory
    of a document root that holds other things too.
    """
    if shutil.which("rsync") is None:
        log("runhealth: rsync is not on PATH, cannot publish")
        return False
    command = ["rsync", *RSYNC_FLAGS, f"{outdir}/", dest]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"runhealth: publishing failed: {exc}")
        return False
    if result.returncode != 0:
        log(f"runhealth: rsync exited {result.returncode}: {result.stderr.strip()[:400]}")
        return False
    where = url.rstrip("/") + "/index.html" if url else dest
    log(f"runhealth: published to {where}")
    return True


def make_server(outdir: Path, port: int):
    """A read-only server bound to the loopback interface.

    Binding to localhost only is deliberate. Reports are generated on shared
    login nodes, and a directory of job logs is not something to expose to
    everyone else on the machine; reach it with ``ssh -L``.
    """
    from functools import partial  # noqa: PLC0415
    from http.server import (  # noqa: PLC0415
        SimpleHTTPRequestHandler,
        ThreadingHTTPServer,
    )

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

    handler = partial(Quiet, directory=str(outdir))
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


# -- entry point ----------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="runhealth",
        description="Read HPC batch job logs and write a system-health report.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("paths", nargs="*", default=["."], help="log files or directories to scan")
    p.add_argument("-o", "--outdir", default="runhealth-report", help="where to write the report")
    p.add_argument("-f", "--format", choices=["html", "md", "pdf"], default="html")
    p.add_argument("--glob", default=None, help=f"filename pattern (default: {DEFAULT_GLOB} etc.)")
    p.add_argument("--last", type=int, default=0, help="keep only the N newest logs (0 = all)")
    p.add_argument("--since", default="", help="skip logs older than this, e.g. 7d or 12h")
    p.add_argument("--profile", default="", help="profiles to apply, comma separated")
    p.add_argument("--profile-dir", action="append", help="extra directory of profiles")
    p.add_argument("--list-profiles", action="store_true", help="show known profiles and exit")
    p.add_argument("--list", action="store_true", help="show matching logs and exit")
    p.add_argument("--watch", type=float, default=0, help="re-render every N seconds")
    p.add_argument("--stall-seconds", type=float, default=0, help="override the stall threshold")
    p.add_argument("--jobs", type=int, default=0, help="parallel parsers (0 = auto)")
    p.add_argument("--no-plots", action="store_true", help="skip the figures")
    p.add_argument("--no-cache", action="store_true", help="ignore and do not write the cache")
    p.add_argument("--no-squeue", action="store_true", help="do not ask SLURM for job states")
    p.add_argument(
        "--embed-logs",
        action="store_true",
        help="embed logs under 8 MB as a linkable page the figures can jump into",
    )
    p.add_argument("--title", default="", help="report title")
    p.add_argument("--open", action="store_true", help="open the report when it is written")
    p.add_argument(
        "--publish",
        nargs="?",
        const="",
        default=None,
        metavar="DEST",
        help="rsync the report to DEST, e.g. user@host:/var/www/runs "
        "(default: $RUNHEALTH_PUBLISH)",
    )
    p.add_argument(
        "--publish-url",
        default=os.environ.get("RUNHEALTH_PUBLISH_URL", ""),
        metavar="URL",
        help="address the published report is reachable at, printed when it is synced",
    )
    p.add_argument(
        "--serve",
        nargs="?",
        const=8000,
        type=int,
        default=None,
        metavar="PORT",
        help="serve the report on 127.0.0.1:PORT until interrupted (default 8000)",
    )
    p.add_argument("--version", action="version", version=f"runhealth {__version__}")
    return p


def _select(args) -> list[Path]:
    files = discover([Path(p) for p in args.paths], args.glob)
    if args.since:
        window = parse_since(args.since)
        if window is None:
            log(f"runhealth: cannot read --since {args.since!r}, ignoring")
        else:
            cutoff = time.time() - window
            files = [f for f in files if f.stat().st_mtime >= cutoff]
    return files[: args.last] if args.last else files


def _publish_dest(args) -> str:
    if args.publish is None:
        return ""
    return args.publish or os.environ.get("RUNHEALTH_PUBLISH", "")


def _once(args, outdir: Path) -> Path | None:
    files = _select(args)
    if not files:
        log("runhealth: no logs matched")
        return None
    states = {} if args.no_squeue else slurm_states()
    views = build(args, files, outdir, states)
    path = write_report(args, views, outdir, [str(Path(p).resolve()) for p in args.paths])
    summarise(views)
    log(f"runhealth: wrote {path}")
    dest = _publish_dest(args)
    if dest:
        publish(outdir, dest, args.publish_url)
    return path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_profiles:
        profiles = profile.load_all([Path(d) for d in (args.profile_dir or [])])
        for name, p in sorted(profiles.items()):
            flag = " (always applied)" if p.always else ""
            print(f"{name:<14} {p.description}{flag}")
        return 0
    if args.list:
        for f in _select(args):
            print(f"{f}  ({f.stat().st_size / 1e6:.1f} MB)")
        return 0

    if args.publish is not None and not _publish_dest(args):
        log("runhealth: --publish needs a destination, or $RUNHEALTH_PUBLISH set")
        return 2

    outdir = Path(args.outdir)
    path = _once(args, outdir)
    if path is None:
        return 1

    server = None
    if args.serve is not None:
        try:
            server = make_server(outdir, args.serve)
        except OSError as exc:
            log(f"runhealth: cannot serve on port {args.serve}: {exc}")
            return 1
        threading.Thread(target=server.serve_forever, daemon=True).start()
        log(f"runhealth: serving http://127.0.0.1:{args.serve}/ (Ctrl-C to stop)")

    if args.open:
        target = f"http://127.0.0.1:{args.serve}/{path.name}" if server else path.resolve().as_uri()
        webbrowser.open(target)

    try:
        if args.watch:
            log(f"runhealth: watching, refreshing every {args.watch:g}s (Ctrl-C to stop)")
            while True:
                time.sleep(args.watch)
                _once(args, outdir)
        elif server:
            threading.Event().wait()
    except KeyboardInterrupt:
        log("runhealth: stopped")
    finally:
        if server:
            server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
