# runhealth

**Analyze a directory of HPC batch job logs and obtain a report on how the
runs went.**

A batch log already records whether the job completed, whether and where it
hung, how fast it ran and whether it slowed down, how evenly the work was
distributed across ranks, and whether the underlying machine was healthy.
`runhealth` extracts that information and presents it as a report.

```bash
runhealth /path/to/logs -o report/ --open
```

```{figure} images/timeline.svg
:alt: A run timeline: one blue phase filling the whole allocation, with a red silence bar above it
:width: 820px
:align: center

A single figure is sufficient for the diagnosis: the job spent its entire
allocation in the coupling setup and wrote no further output.
```

`runhealth` is **model-agnostic**. The core interprets batch logs in general:
timestamps, SLURM records, silence and error signatures. Everything specific to
a code is defined in a [YAML profile](profiles.md), so support for an additional
model requires a few regular expressions rather than Python code. Profiles for
ICON and Cray MPICH are included.

## Example

Two sample logs are included in the repository, so no cluster is required:

```bash
runhealth examples/ --glob '*.log' -o /tmp/demo --open
```

```text
runhealth: parsed 2 log(s) in 0.2s
  WARN  SUCCESS      26m 18s  demo.log       - 8 of 199 intervals took more than 3x the median
  FAIL  FAILED    1h 44m 10s  demo_hang.log  - CANCELLED AT 2026-03-17T22:48:18 DUE TO TIME LIMIT
runhealth: wrote /tmp/demo/index.html
```

Open `/tmp/demo/index.html`. `demo.log` is a run that completed despite a
transient fabric problem in the middle of the run; `demo_hang.log` is the same
job, which remained in its coupling setup until the scheduler terminated it.

If `--open` does nothing, the shell has no browser registered for a local file.
Use `--serve` instead and browse to <http://127.0.0.1:8000/>; see
[serving a report](usage.md#sharing-a-report).

The summary reads the same way for production logs. The following example
covers one afternoon of a coupled climate model:

```text
runhealth: parsed 11 log(s) in 12.6s
  WARN  SUCCESS      19m 52s  LOG.jcp_r2b8_icon4py.839444.o   - Worst timer runs 11.57x slower on the slowest rank
  FAIL  SUCCESS      53m 49s  LOG.jcp_r2b10_icon4py.832847.o  - 640.9k dropped flow-control messages, 641.1k in one minute
  FAIL  FAILED            19s  LOG.jcp_r2b10_icon4py.831673.o - srun exit status 143, finish_atmo.status missing
  WARN  SUCCESS   2h 40m 00s  LOG.jcp_r2b8_icon4py.831554.o   - 23m 44s of silence during setup
  FAIL  FAILED    2h 15m 20s  LOG.jcp_r2b8_icon4py.828160.o   - CANCELLED DUE to SIGNAL Terminated
```

The second line is the important one: the run *succeeded* and would otherwise
not have been examined again, although for one minute it was saturated by a
network retry storm.

## Contents of a report

```text
report/
  index.html                  every run, one row each, sortable and filterable
  LOG.myjob.12345.html        one page per run: checks, figures, tables
  .cache/                     parsed state, so the next pass is instant
```

## Next steps

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} {octicon}`download` Install
:link: install
:link-type: doc

`uv sync`, and two alternatives for a restrictive inode quota or a plain pip
environment.
:::

:::{grid-item-card} {octicon}`terminal` Usage
:link: usage
:link-type: doc

One recipe per question, following a running job, output formats and the cost
of parsing.
:::

:::{grid-item-card} {octicon}`graph` Reading the report
:link: report
:link-type: doc

What each check means and how to read the figures.
:::

:::{grid-item-card} {octicon}`file-code` Profiles
:link: profiles
:link-type: doc

Adding support for a new code with a YAML file, and the complete profile
schema.
:::

::::

```{toctree}
:maxdepth: 2
:hidden:

install
usage
report
profiles
logging
troubleshooting
cli
development
```
