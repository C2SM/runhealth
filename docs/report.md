# Reading the report

## The index

One row per run, sortable by any column and filterable by health grade, with
wall clock, throughput and longest silence side by side. This makes it easy to
identify the point at which a series of runs began to degrade. Above the
table, every directory the report was built from is listed as `machine:/path`,
with the machine set apart from the path and a button that copies the complete
string.

Grades are `ok`, `worth a look`, `warning` and `problem`. A run's grade is the
worst of its checks.

## The run page header

Below the run's name and its job id, a row names the `machine:/path` the log
was read from, next to the items that can be opened from it. For a
[remote log](usage.md#remote-logs) this is the original host and path, not the
local copy in `.remote-cache/` that `runhealth` actually parsed, so it is the
address to return to on the cluster; the button beside it copies the complete
`machine:/path` for pasting into a terminal.

**Run script** appears when the scheduler echoed the job script at the top of
the log. It opens the script that was submitted, shell-highlighted, with
`#SBATCH` directives picked out, and **download** saves it as a `.sh` file.
**Raw log** appears when the report was built with `--embed-logs`.

## The checks

Each run page opens with a list of checks. A check states what it found and
lists the supporting evidence, so nothing has to be taken on trust. The row of
buttons above the list filters by grade, in the same way the index filters
runs, which on a healthy-looking run with a single warning avoids reading
through the other twelve checks.

| Check | What it means |
| --- | --- |
| **Outcome** | Did the job report success or failure, or did it end without a statement? SLURM's own verdict is included while `squeue` still knows the job. |
| **Silence** | The longest stretch with no output. Silence *inside* the main loop, or in a run that never reached its loop, is a failure. Silence during setup is judged against a longer threshold, because reading input and compiling kernels legitimately take minutes. |
| **Wall time** | How much of the requested limit was used, and whether the scheduler cut the job off. |
| **Throughput** | Progress reached and the rate, in the unit the profile names (SYPD for a climate model). |
| **Throughput drift** | Whether the run slowed between its first and last quarter, which points at something degrading rather than a single bad moment. |
| **Slow intervals** | Individual progress intervals far above the median: output, checkpointing, or a transient stall. |
| **Where the time went** | The largest timers, as a share of the total. |
| **Load imbalance** | How much longer the slowest rank spent in each timer than the fastest. This never fails a run on its own; it is a performance observation, and spread on a *wait* timer is the symptom of imbalance created somewhere else. |
| **Checkpoint write / Output cost** | Volume and rate of restart writes, and the share of the run spent in output timers. |
| **Network** | Fabric counters and warnings. A burst of dropped flow-control messages means the network, not the code, was the limit. |
| **Suspect nodes** | Nodes named in step failures, or carrying a disproportionate share of the warnings. Ready to be pasted into an `--exclude=` list. |
| **Errors** | Error-looking lines collapsed by shape, with digits masked so the same message from a thousand ranks becomes one row. |

Checks for which a profile supplies no data simply do not appear. A completely
unknown log still yields outcome, silence, wall time and errors. Every
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
labeled with the last line before it, **load imbalance** per timer, and the
**network counter spread** between the least and the most loaded NIC.

A figure is omitted rather than approximated when the log does not contain what
it requires, and `--no-plots` leaves out all of them.

### Reading them in a browser

The figures are SVG written into the page, not images of figures, so they are
interactive without anything being downloaded:

- **Hover over, tap or tab onto any mark** to see the numbers behind it: the
  name of a phase and the share of the allocation it took, which rank was
  slowest in a timer, how many lines a node contributed. Everything a tooltip
  states is also the mark's accessible name, so a screen reader and the
  keyboard reach the same information.
- **Drag across the timeline or the progress rate** to zoom into a section of
  the run; the axis relabels itself and *reset zoom* restores the full view.
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

## Getting around a page

The header remains in place while scrolling, and on a run page it carries that
run's name and grade beside a link back to the index. The table of contents
marks the section being read and follows the scroll position; its first entry
returns to the top of the page. On a narrow screen it becomes a row of chips
below the header and scrolls to keep the current section in view.
