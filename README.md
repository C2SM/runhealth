# runhealth

**A system-health report for HPC batch job logs.**

A batch log records far more about how a job actually behaved than anyone reads
by hand. `runhealth` scans a folder of them and writes a report that answers, at
a glance: did the run finish, did it hang, how fast was it, was the work spread
evenly, and was the machine underneath it healthy.

It is model-agnostic. The core understands batch logs -- timestamps, SLURM
records, silence, error signatures -- and everything specific to a code lives in
a **YAML profile**, so supporting your own model means writing a few regular
expressions, not Python. ICON and Cray MPICH profiles ship with it.

```
runhealth /path/to/logs -o report/
```

```
runhealth: parsed 11 log(s) in 12.6s
  WARN  SUCCESS      19m 52s  LOG.jcp_r2b8_icon4py.839444.o   - Worst timer runs 11.57x slower on the slowest rank
  FAIL  SUCCESS      53m 49s  LOG.jcp_r2b10_icon4py.832847.o  - 640.9k dropped flow-control messages, 641.1k in one minute
  FAIL  FAILED           19s  LOG.jcp_r2b10_icon4py.831673.o  - srun exit status 143, finish_atmo.status missing
  WARN  SUCCESS   2h 40m 00s  LOG.jcp_r2b8_icon4py.831554.o   - 23m 44s of silence during setup
  FAIL  FAILED    2h 15m 20s  LOG.jcp_r2b8_icon4py.828160.o   - CANCELLED DUE to SIGNAL Terminated
runhealth: wrote report/index.html
```

Every one of those lines came out of a file nobody had time to read.

## Why

A hung job looks exactly like a healthy one in every respect except one: it goes
quiet. If the job output carries a wall clock on each line -- and it costs almost
nothing to arrange -- then the longest silence in the file, together with the
last thing written before it, is usually the whole diagnosis.

The rest of a log is similar. The scheduler says why it killed the job. The
model's own timer table says where the time went and how unevenly. The MPI stack
says whether the fabric was retrying. `runhealth` reads all of it, in one
streaming pass, and puts the answers on one page.

## Install

Only [uv](https://docs.astral.sh/uv/) is needed; it fetches a suitable Python
itself.

```bash
git clone <this repo> runhealth
cd runhealth
uv sync
uv run runhealth --help
```

The virtual environment holds a few thousand files. On a file system with a
tight inode quota, put it elsewhere:

```bash
export UV_PROJECT_ENVIRONMENT=$SCRATCH/venvs/runhealth
uv sync
```

Plain pip works too: `pip install -e .`, then `runhealth --help`.

## Quickstart

```bash
# Everything in a directory, written to report/
runhealth /path/to/logs -o report/

# One file, opened in a browser when it is ready
runhealth LOG.myjob.12345.o -o report/ --open

# The five newest logs from the past week
runhealth /path/to/logs --last 5 --since 7d -o report/

# Follow a job that is running now, refreshing every minute
runhealth /path/to/logs --watch 60 -o report/

# Markdown instead of a web page
runhealth /path/to/logs -f md -o report/
```

`runhealth` writes `index.html` (one row per run) plus one page per run, with
the figures under `images/`. Open `index.html` in a browser.

## What the report tells you

### The index

One row per run, sortable and filterable by health grade, with wall clock,
throughput and longest silence side by side, plus a chart comparing the runs.
Useful for spotting the moment a series of runs started to degrade.

### The checks

Each run page opens with a list of checks. A check states what it found and
lists the evidence behind it, so nothing has to be taken on trust.

| Check | What it means |
| --- | --- |
| **Outcome** | Did the job report success, fail, or end without saying? SLURM's own verdict is included when `squeue` still knows the job. |
| **Silence** | The longest stretch with no output. Silence *inside* the main loop, or in a run that never reached its loop, is a failure. Silence during setup is judged against a longer threshold, because reading input and compiling kernels legitimately take minutes. |
| **Wall time** | How much of the requested limit was used, and whether the scheduler cut the job off. |
| **Throughput** | Progress reached and the rate, in the unit the profile names (SYPD for a climate model). |
| **Throughput drift** | Whether the run slowed between its first and last quarter, which points at something degrading rather than a single bad moment. |
| **Slow intervals** | Individual progress intervals far above the median: output, checkpointing, or a transient stall. |
| **Where the time went** | The largest timers, as a share of the total. |
| **Load imbalance** | How much longer the slowest rank spent in each timer than the fastest. This never fails a run on its own; it is a performance observation, and spread on a *wait* timer is the symptom of imbalance created somewhere else. |
| **Checkpoint write / Output cost** | Volume and rate of restart writes, and the share of the run spent in output timers. |
| **Network** | Fabric counters and warnings. A burst of dropped flow-control messages means the network, not the code, was the limit. |
| **Suspect nodes** | Nodes named in step failures, or carrying a disproportionate share of the warnings. Ready to paste into an `--exclude=` list. |
| **Errors** | Error-looking lines collapsed by shape, with digits masked so the same message from a thousand ranks becomes one row. |

Checks a profile cannot feed simply do not appear. A completely unknown log
still gets outcome, silence, wall time and errors.

### The figures

| Figure | Reads out |
| --- | --- |
| **Run timeline** | The wall clock split into phases, with silences overlaid in red and output writes ticked below. A wide red bar is where the run hung. |
| **Progress rate** | Wall seconds per progress report. Flat is healthy; spikes are output or stalls; a rising trend is degradation. Switches to a log scale when one slow first step would otherwise flatten everything. |
| **Longest silences** | Each silence labelled with the last line written before it. |
| **Where the time went** | Top-level timers per rank group; the bar is the average across ranks and the whisker spans fastest to slowest. |
| **Load imbalance** | Slowest rank divided by fastest, per timer. |
| **Message rate** | Message families per minute across the run, beside the nodes producing them. A burst that lines up with a slow stretch in the progress plot points at the fabric. |
| **Network counters** | The span between the least and most loaded NIC for each counter, on a log scale. A wide span means the load is concentrated rather than shared. |

## Output formats

- `--format html` (default): `index.html` plus a page per run. Light and dark
  themes, and a real print stylesheet -- the browser's **Print to PDF** produces
  a clean document with sensible page breaks.
- `--format md`: `report.md` with the same figures, in GitHub-flavoured
  Markdown.
- `--format pdf`: uses [WeasyPrint](https://weasyprint.org/) if it is installed
  (`uv sync --extra pdf`). Without it, `runhealth` writes the HTML and tells you
  to print it, rather than failing. WeasyPrint is not a hard dependency because
  it is large and the browser route is just as good.

## Profiles

A profile is a YAML file describing what a code prints. Profiles compose:
`slurm` (always applied) plus `icon` plus `cray-mpich` describe an ICON run on a
Cray machine, and each is detected from the content of the log itself.

```bash
runhealth --list-profiles
# cray-mpich     Cray MPICH / Slingshot: CXI counters, libfabric warnings
# icon           ICON atmosphere/ocean model: progress, timer report, coupling
# slurm          SLURM batch job metadata, step failures and cancellations. (always applied)
```

| Profile | Detects | Contributes |
| --- | --- | --- |
| `slurm` | always | `#SBATCH` directives, the SLURM environment, `srun` step failures, cancellations, wall-clock limits |
| `icon` | ICON output or a generated ICON runscript | time steps and SYPD, the timer report, coupling and I/O phases, `WARNING PE` families, the success/failure protocol |
| `cray-mpich` | Slingshot or libfabric output | the CXI counter summary, libfabric flow-control warnings, MPICH aborts |

To add your own, drop a YAML file in a directory and point `runhealth` at it:

```bash
runhealth /path/to/logs --profile-dir ./my-profiles
export RUNHEALTH_PROFILE_DIR=$HOME/.runhealth   # or set it once
```

A minimal profile for a code that prints `iteration 42, residual 1.0e-6`:

```yaml
name: mysolver
description: "Iterative solver: progress and convergence"
detect:
  - 'mysolver v[0-9]'

settings:
  progress_label: iterations
  progress_series: iteration

series:
  iteration:
    re: 'iteration (\d+), residual (\S+)'
    fields: [step, residual]
    cast: {step: int}
    role: progress

markers:
  solve_start: {re: 'entering solve', label: solve}

outcome:
  - {re: '^converged in (\d+) iterations', level: ok}
  - {re: '^diverged after (\d+) iterations', level: fail}
```

`--profile mysolver` pins it; without that flag it is detected automatically.
The full schema, including timer tables and message families, is in
[docs/profiles.md](docs/profiles.md).

## Running jobs

A log with no final status is reported as **RUNNING** while it is still being
written, and as **INCOMPLETE** once it has gone quiet -- the silence check then
says where it stopped.

When `squeue` is available, `runhealth` asks it for the real state, so a queued
job shows as **QUEUED** rather than as a broken run, and a job the scheduler
still believes is running while its log has gone quiet is reported as
**STALLED** -- the one case where intervening is still worth something.
`--no-squeue` turns that off.

`--watch 60` re-renders on an interval. Each pass resumes from where the last
one stopped, so following a growing 100 MB log costs no more than the new lines.

## Performance

Reading is strictly streaming, line by line, with counters and bounded
shortlists instead of stored lines. A 152 MB, 820k-line log parses in about
12 seconds; 443 MB across 31 logs takes about 30 seconds in parallel, with peak
resident memory in the tens of megabytes.

Results are cached under `<outdir>/.cache/`, keyed on file size and modification
time, so a second pass over the same folder takes well under a second.
`--no-cache` disables it.

## Getting more out of your logs

`runhealth` reports what a log contains. Two cheap changes to a job script make
it contain much more:

1. **Stamp every line with the wall clock.** Without it, silence -- the single
   most valuable signal -- cannot be measured, and `runhealth` says so rather
   than guessing. Any line-buffered filter will do; ICON ships
   `utils/timewarp` for exactly this.
2. **Turn on the MPI stack's counters.** On Cray MPICH,
   `MPICH_OFI_CXI_COUNTER_REPORT=3` and `FI_LOG_LEVEL=warn` cost nothing and
   turn "the run was slow" into "the fabric dropped 640k flow-control messages
   in one minute".

## Limitations

- Without line timestamps there is no silence detection, no phase timeline and
  no progress rate. The report says which of the three line shapes it found.
- Throughput needs a profile that names a progress line. The generic profile
  reports outcome, silence and errors only.
- Load imbalance is read from the model's own timer table. A code that does not
  print one gets no imbalance analysis.
- A file holding several job attempts (a resubmission appending to the same
  name) is analysed as its **last** attempt, and the report says so.

## Command line

```
runhealth [PATH ...] [-o OUTDIR] [-f html|md|pdf]
          [--profile NAME[,NAME]] [--profile-dir DIR] [--list-profiles]
          [--glob PATTERN] [--last N] [--since 7d] [--list]
          [--watch SECONDS] [--stall-seconds N] [--dpi N] [--jobs N]
          [--no-plots] [--no-cache] [--no-squeue] [--embed-logs]
          [--title TEXT] [--open]
```

`PATH` may be files or directories. Directories are scanned for `LOG.*.o`,
`slurm-*.out`, `*.log` and `*.out` in that order, taking the first shape that
matches; `--glob` overrides this.

## Development

```bash
uv sync
uv run pytest
uv run python tests/make_fixtures.py   # regenerate the sample logs
```

The test fixtures are small hand-built logs, one per shape: a healthy ICON run,
a run that hangs in its coupling setup, two attempts in one file, a generic
SLURM job from an unknown code, ICON output with no timestamps, and the
degenerate cases (empty, truncated, not a log at all). No real log is committed;
they are far too large.

Formatting is [black](https://black.readthedocs.io/) via `pre-commit`:

```bash
pre-commit install
```

## Licence

BSD 3-Clause. See [LICENSE](LICENSE).
