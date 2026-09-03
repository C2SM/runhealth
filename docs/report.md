# Reading the report

## The index

One row per run, sortable by any column and filterable by health grade, with
wall clock, throughput and longest silence side by side. Useful for spotting the
point at which a series of runs started to degrade.

Grades are `ok`, `worth a look`, `warning` and `problem`. A run's grade is the
worst of its checks.

## The checks

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
still gets outcome, silence, wall time and errors. Every threshold a check
compares against is [adjustable per profile](#profile-thresholds).

## The figures

**Progress rate**, the wall time between successive progress reports. Flat is
healthy. The regular small spikes here are hourly output; the tall one is a
network stall that output alone does not explain.

```{image} images/progress.png
:alt: Progress rate over the run, flat apart from regular output spikes and one tall stall
```

**Where the time went**, top-level timers, one panel per rank group. The bar is
the average across ranks and the whisker spans fastest to slowest, so a long
whisker is imbalance. `exch_data.wait` below is 10 % of the run on average but
about 25 % on the slowest rank.

```{image} images/timers.png
:alt: Timer breakdown per rank group, with whiskers spanning fastest to slowest rank
```

**Message rate**, message families per minute across the run, beside the nodes
producing them. A burst that lines up with a slow stretch in the progress plot
points at the fabric rather than the code.

```{image} images/warnings.png
:alt: Message families per minute across the run, beside the nodes producing them
```

Plus, on every page that has the input for them: the **run timeline** shown on
the [front page](index.md), the **longest silences** each labelled with the last
line before it, **load imbalance** per timer, and the **network counter spread**
between the least and most loaded NIC.

Every figure is skipped rather than faked when the log does not contain what it
needs. `--no-plots` skips all of them, and `--dpi` sets their resolution.
