# runhealth

**Read a folder of HPC batch job logs. Get a report that says how the runs went.**

Did it finish? Did it hang, and where? How fast was it, and did it slow down?
Was the work spread evenly across ranks? Was the machine underneath it healthy?
Those answers are all in the log already. `runhealth` reads them out.

```bash
runhealth /path/to/logs -o report/ --open
```

```{figure} images/timeline.svg
:alt: A run timeline: one blue phase filling the whole allocation, with a red silence bar above it
:width: 820px
:align: center

One picture, one diagnosis: the job spent its entire allocation in the coupling
setup and never wrote another line.
```

It is **model-agnostic**. The core understands batch logs, meaning timestamps,
SLURM records, silence and error signatures, and everything specific to a code
lives in a [YAML profile](profiles.md), so supporting your own model means
writing a few regular expressions, not Python. ICON and Cray MPICH profiles ship
with it.

## See it work

Two sample logs ship with the repository. No cluster needed:

```bash
runhealth examples/ --glob '*.log' -o /tmp/demo --open
```

```text
runhealth: parsed 2 log(s) in 0.2s
  WARN  SUCCESS      26m 18s  demo.log       - 8 of 199 intervals took more than 3x the median
  FAIL  FAILED    1h 44m 10s  demo_hang.log  - CANCELLED AT 2026-03-17T22:48:18 DUE TO TIME LIMIT
runhealth: wrote /tmp/demo/index.html
```

Open `/tmp/demo/index.html`. `demo.log` is a run that finished but hit a fabric
hiccup halfway through; `demo_hang.log` is the same job stuck in its coupling
setup until the scheduler cut it off.

On real logs the summary reads the same way. This is one afternoon of a coupled
climate model:

```text
runhealth: parsed 11 log(s) in 12.6s
  WARN  SUCCESS      19m 52s  LOG.jcp_r2b8_icon4py.839444.o   - Worst timer runs 11.57x slower on the slowest rank
  FAIL  SUCCESS      53m 49s  LOG.jcp_r2b10_icon4py.832847.o  - 640.9k dropped flow-control messages, 641.1k in one minute
  FAIL  FAILED            19s  LOG.jcp_r2b10_icon4py.831673.o - srun exit status 143, finish_atmo.status missing
  WARN  SUCCESS   2h 40m 00s  LOG.jcp_r2b8_icon4py.831554.o   - 23m 44s of silence during setup
  FAIL  FAILED    2h 15m 20s  LOG.jcp_r2b8_icon4py.828160.o   - CANCELLED DUE to SIGNAL Terminated
```

The second line is the one worth having: that run *succeeded*, and would never
have been looked at again. It was also, for one minute, drowning in a network
retry storm.

## What you get

```text
report/
  index.html                  every run, one row each, sortable and filterable
  LOG.myjob.12345.html        one page per run: checks, figures, tables
  .cache/                     parsed state, so the next pass is instant
```

## Where to go next

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} {octicon}`download` Install
:link: install
:link-type: doc

`uv sync`, and the two alternatives for a tight inode quota or a plain pip
environment.
:::

:::{grid-item-card} {octicon}`terminal` Usage
:link: usage
:link-type: doc

A recipe per question, following a running job, output formats and what the
parser costs.
:::

:::{grid-item-card} {octicon}`graph` Reading the report
:link: report
:link-type: doc

What each check means and how to read the figures.
:::

:::{grid-item-card} {octicon}`file-code` Profiles
:link: profiles
:link-type: doc

Teach `runhealth` a new code with a YAML file, and the full profile schema.
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
