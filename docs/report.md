# Reading the report

## The index

One row per run, sortable by any column and filterable by health grade, with
wall clock, throughput and longest silence side by side. This makes it easy to
identify the point at which a series of runs began to degrade. Above the table,
every directory the report was built from is listed as `machine:/path`,
with the machine set apart from the path and a button that copies the complete
string.

The grades are `healthy`, `worth a look`, `warning` and `problem`. The grade of
a run is the worst grade among its checks.

The tiles above the table count the runs twice: once by scheduler status
(`success`, `failed`, `stalled` and the other outcomes) and once by health
grade, so an ended-cleanly run that still shows warnings is visible in both.

Between the tiles and the table, the **All runs** comparison figure draws the
wall clock and the throughput of every run as one bar each. A bar is split into
two colors, the scheduler status on the left and the health grade on the right,
so a run whose two verdicts disagree is recognizable at a glance; a bar with a
single color means the two agree.

The last column, **script diff**, states how many lines of the run script were
added and removed relative to the previous run of the same kind, and opens the
comparison itself. See [Comparing run scripts](#comparing-run-scripts).

## The run page header

Below the run's name and its job id, a row names the `machine:/path` the log
was read from, next to the items that can be opened from it. For a
[remote log](usage.md#remote-logs) this is the original host and path, not the
local copy in `.remote-cache/` that `runhealth` actually parsed, so it is the
address to return to on the cluster; the button beside it copies the complete
`machine:/path` for pasting into a terminal.

**Run script** appears when the scheduler echoed the job script at the top of
the log. It opens the script that was submitted, shell-highlighted and
numbered, with `#SBATCH` directives picked out, and **download** saves it as a
`.sh` file.
**Script diff** appears when an earlier run of the same kind is part of the
same report. **Raw log** appears when the report was built with
`--embed-logs`.

## Comparing run scripts

A run that slowed down, or stopped finishing at all, is often explained by a
change to the script that submitted it. Both the index and a run page can
therefore open the run script beside the one the previous run used.

Two runs are the same kind of simulation when the name of their run script
matches, which is the name the script gives itself in `--job-name`; when the
log holds no SLURM metadata, the log file name without its job id is used
instead. The previous run is the most recent run of that kind that started
earlier and whose log contains a copy of its script. Only the runs in the same
report are considered, so the comparison reaches exactly as far back as the
directory that was read.

The comparison is a unified diff: the changed lines, a few lines of context
around each of them, and the line numbers on both sides. Removed lines are
marked `-` and added lines `+`. Scripts that are identical are reported as
such, which is itself an answer when a run behaved differently for no visible
reason.

## Searching the report

The field in the header searches every run in the report at once, from any of
its pages. It is reached with `/` or `Ctrl`/`Cmd`+`K`, and two characters are
enough to start.

The run scripts are the largest part of what it searches. Asking for
`--nodes=8`, for a module name or for an environment variable lists every run
whose script mentions it, with the matching line and its number under the name
of the run.
Selecting a line opens that run's script at that line, with every other
occurrence in the same script marked, so a setting can be traced across a
series of runs without opening each page in turn. The search also covers the
names of the runs, their job ids, the paths their logs were read from, the
facts listed under job and build provenance, and the text of every check, so a
node name or an error message finds the runs it occurred in. Selecting one of
those results opens the run page at the check, the provenance row or the
summary it matched rather than at the top of the page, marks the matching text
there, and expands the section first when the row sits inside a collapsed one.

Results are grouped by run, newest first, and each run contributes at most a
dozen lines; the remainder is counted, and selecting that count opens the
script with all of them marked. The arrow keys move through the results and
`Enter` follows the selected one.

The index behind this is written once per report, as `search.js` beside
`index.html`, and a page loads it the first time a reader searches. The two
files have to be kept together: a page copied on its own keeps working, but its
search field then reports that the index is missing.

## The checks

Each run page opens with a list of checks. A check states its finding and lists
the supporting evidence, so that every conclusion can be verified. The row of
buttons above the list filters by grade, in the same way as the index filters
runs, so that a run with a single warning does not require reading through the
remaining checks.

| Check | What it means |
| --- | --- |
| **Outcome** | Did the job report success or failure, or did it end without a statement? SLURM's own verdict is included while `squeue` still knows the job, and the accounting record settles a log that ends without one. |
| **SLURM accounting** | The scheduler's record from `sacct`: final state, exit code, elapsed time, nodes. It fails a job that SLURM ended as `TIMEOUT`, `NODE_FAIL`, `OUT_OF_MEMORY` or `CANCELLED`, and warns when a job printed its success message but still ended with a nonzero exit code, for example because the submission of the next job in a chain failed. |
| **Hang watchdog** | Whether the job script's own watchdog (see [Improving log quality](logging.md#3-leave-diagnostics-next-to-the-log)) fired, and when it sent SIGABRT and cancelled the step. |
| **Silence** | The longest stretch with no output. Silence *inside* the main loop, or in a run that never reached its loop, is a failure. Silence during setup is judged against a longer threshold, because reading input and compiling kernels legitimately take minutes. When the job script declares a watchdog, the silence it tolerates before the main loop is the limit until the loop starts, which also keeps a job that is still compiling from being reported as STALLED. |
| **Wall time** | How much of the requested limit was used, and whether the scheduler cut the job off. |
| **Throughput** | Progress reached and the rate, in the unit the profile names (SYPD and SDPD for a climate model), both overall and after warm-up. The first progress interval carries one-off costs such as kernel compilation and is left out of the steady-state rate and the outlier count. |
| **Throughput drift** | Whether the run slowed between its first and last quarter, which points at something degrading rather than a single bad moment. |
| **Slow intervals** | Individual progress intervals after warm-up far above the median: output, checkpointing, or a transient stall. |
| **Where the time went** | The largest timers, as a share of the total. |
| **Load imbalance** | How much longer the slowest rank spent in each timer than the fastest. This never fails a run on its own; it is a performance observation, and spread on a *wait* timer is the symptom of imbalance created somewhere else. |
| **Coupling cost** | The share of each component's time spent in the coupler. A coupled run prints one timer report per component, so the shares are comparable: when one component's share is much the larger, that component reaches the exchange first and waits for its partner, which usually means the ranks are split unevenly between them. Like load imbalance, this never fails a run on its own. |
| **Checkpoint write / Output cost** | Volume and rate of restart writes, and the share of the run spent in output timers. |
| **Output write cadence / Checkpoint write cadence** | The wall-clock gap between successive output or checkpoint writes. One gap far from the typical one usually means a transient file system stall. |
| **Network** | Fabric counters and warnings. A burst of dropped flow-control messages indicates that the network, not the code, was the limiting factor. Slingshot network timeouts are retransmissions the fabric recovered from, so a count is reported for information and only warns or fails above the `network_timeouts_warn` and `network_timeouts_fail` thresholds, or warns when the run itself failed. |
| **GPU health** | From the GPU monitor in the diagnostics directory: uncorrected ECC errors fail the run; hardware slowdown, thermal slowdown and power brake warn, because they make their node the slowest of the run. Peak temperature, power and memory are listed. |
| **GPU activity** | Mean GPU utilization in the main loop, with nodes far from the median, and during the longest silence. During a hang, the GPUs that are still busy point at the ranks the others are waiting for. |
| **Hang backtraces** | The gdb backtraces of the main thread taken during a hang, grouped by the innermost frame and the innermost frame with a source location. A rank in uninterruptible sleep, blocked in the kernel, warns. |
| **Kernel messages** | GPU Xid events and out-of-memory kills in the nodes' kernel logs. Xid codes that indicate a hardware fault, and out-of-memory kills, fail the run. |
| **Suspect nodes** | Nodes named in step failures, carrying a disproportionate share of the warnings, or implicated by the diagnostics directory (ECC errors, slowdown, a fatal Xid, GPUs busy while the rest waited). The list can be pasted directly into an `--exclude=` argument. |
| **Errors** | Lines that look like errors, collapsed by shape, with digits masked so the same message from a thousand ranks becomes one row. |

Checks for which a profile supplies no data do not appear. A completely unknown
log still yields outcome, silence, wall time and errors. Every
threshold a check compares against is
[adjustable per profile](#profile-thresholds).

## The figures

**Progress rate**, the wall time between successive progress reports. A flat
curve is healthy. The regular small spikes here are hourly output; the tall one
is a network stall that output alone does not explain.

```{image} images/progress.svg
:alt: Progress rate over the run, flat apart from regular output spikes and one tall stall
```

**Where the time went**, top-level timers, one panel per rank group. The bar is
the average across ranks and the whisker spans fastest to slowest rank, so a
long whisker indicates imbalance. `exch_data.wait` below accounts for 10% of
the run on average, but for about 25% on the slowest rank.

```{image} images/timers.svg
:alt: Timer breakdown per rank group, with whiskers spanning fastest to slowest rank
```

**Message rate**, message families per minute across the run, beside the nodes
producing them. A burst that coincides with a slow stretch in the progress plot
points to the fabric rather than to the code.

```{image} images/warnings.svg
:alt: Message families per minute across the run, beside the nodes producing them
```

In addition, on every page for which the log provides the input: the **run
timeline** shown on the [front page](index.md), the **longest silences**, each
labeled with the last line before it, the **output cadence** (wall time between
successive output or checkpoint writes, one line per kind of event),
**load imbalance** per timer, and the **network counter spread** between the
least and the most loaded NIC.

A figure is omitted rather than approximated when the log does not contain what
it requires, and `--no-plots` leaves out all of them.

### Reading the figures in a browser

The figures are SVG written into the page, not images of figures, so they are
interactive without anything being downloaded:

- **Hover over, tap or tab onto any mark** to see the numbers behind it: the
  name of a phase and the share of the allocation it took, which rank was
  slowest in a timer, how many lines a node contributed. Everything a tooltip
  states is also the mark's accessible name, so a screen reader and the
  keyboard reach the same information.
- **Drag across the timeline, the progress rate or the output cadence** to zoom
  into a section of the run; the axis relabels itself and *reset zoom* restores
  the full view. Brushing again zooms further into the section on screen.
  Double-clicking also resets.
- **Hovering over one time-based chart marks the same instant in the others**,
  which is how a burst of network messages is aligned with a slow section of
  the progress rate.
- **Click a legend entry** to hide that message family.
- **Click a silence** to open the log at the line where the run went quiet,
  provided the report was built with `--embed-logs`.

The page follows the system light or dark setting, and the switch in the header
overrides it for the individual reader. None of this is required in order to
read a figure: the markup is complete before any script runs, which is why the
same figure prints correctly and survives conversion to PDF.

## Navigating a page

The header remains in place while scrolling, and on a run page it carries that
run's name and grade beside a link back to the index. The table of contents
marks the section being read and follows the scroll position; its first entry
returns to the top of the page. On a narrow screen it becomes a row of chips
below the header and scrolls to keep the current section in view.

The header also carries the field that
[searches the whole report](#searching-the-report).
