# Running in a Sirocco workflow

In a [Sirocco](https://github.com/C2SM/Sirocco) workflow, `runhealth` runs as
a shell task after each ICON task. It writes a report for every cycle, and when
a run is graded as failed, it fails the task, which stops the workflow before
the next cycle builds on that run.

```{note}
Sirocco starts a task only after all of its predecessors have completed
successfully, and cancels the rest of the workflow as soon as one task fails.
A `runhealth` task therefore checks every ICON run that completed, but never
one that failed. To check a failed run, point `runhealth` at its run directory
by hand, or run it as a [SLURM job](slurm.md) outside the workflow.
```

## The workflow

The task needs the run directory of the ICON task. ICON's `finish_status`
output lies in that directory, so the task takes it as an input and passes its
directory to `runhealth`:

```yaml
cycles:
  - monthly:
      cycling:
        start_date: *root_start_date
        stop_date: *root_stop_date
        period: P1M
      tasks:
        - icon:
            components:
              atm:
                inputs:
                  # ...
                outputs:
                  finish_status: [finish]
                  restart_out: [restart]
                  output_streams: [atm_3d]
        - runhealth:
            inputs:
              status: [finish]
              stream: [atm_3d]

tasks:
  # ...
  - runhealth:
      plugin: shell
      walltime: 00:15:00
      nodes: 1
      procs_per_node: 1
      cores_per_proc: 4
      command: >-
        uv run --project $HOME/runhealth runhealth $(dirname {PORT::status})
        --output-dir {PORT::stream} --fail-on fail -o report

data:
  generated:
    - finish: {}
    - restart: {}
    - atm_3d: {}
```

- Sirocco places the input's path where `{PORT::status}` stands, and the
  command runs in a bash script, so `$(dirname ...)` yields the run directory
  of the ICON task of the same cycle.
- `runhealth` recognizes the log of the ICON task, `run_script.<job id>.o`, by
  its name, and takes the job id from it for the SLURM accounting record.
- The report is written to `report/` in the run directory of the `runhealth`
  task, for example `run/runhealth__date_2026-01-01T00-00-00/report/`. To
  collect the reports of all cycles in one place instead, use
  `-o /path/to/reports/$SIROCCO_START_DATE`; Sirocco sets that variable in
  every task of a cycle with dates.
- Sirocco writes each ICON output stream into its own subdirectory of the run
  directory, so `{PORT::stream}` is the directory of one stream and
  `--output-dir` reads exactly that stream; see
  [Diagnosing the model output](usage.md#diagnosing-the-model-output). Leave out
  the `stream` input and `--output-dir` to check the log alone.
- `uv run --project ...` starts a checkout installed as described in
  [Install](install.md); a `uenv` and `view` on the task may provide `runhealth`
  instead.

## How the report shows a workflow

A log in a Sirocco task directory, such as
`run/icon__date_2020-01-01T00-00-00/run_script.<job id>.o`, is read as one chunk
of the workflow whose root holds `sirocco.yaml`, `sirocco.resolved.yaml` or
`sirocco.log`. The report then

- names the run after its task and cycle, for example
  `icon · 2020-01-01 → 01-02 · chunk 1/2 · cold start`, with the period and the
  start and stop dates taken from `sirocco.resolved.yaml`;
- groups the runs of each workflow root in the run table and in the run
  switcher, in cycle order, with a dot per chunk, including chunks that have
  no run in the report yet;
- lists every workflow at the top of the index, with its task settings, what
  `state.yaml` and `sirocco.log` record for each chunk, and the events of
  `sirocco.log`; the paths given on the command line are folded away below;
- links each run page to the chunks before and after it, and notes when the
  workflow ran the chunk again as another job, or when the chunk it restarts
  from did not complete;
- adds the workflow, the chunk and the job the workflow last ran it as to
  `summary.json`, under `sirocco`;
- takes Sirocco's record of a job (completed, failed or canceled) as the
  run's outcome when the log ends without one and SLURM accounting no longer
  knows the job.

Workflows with the same name in different directories stay apart, each labeled
with its path. A copy of a workflow that kept only `sirocco.log` and
`state.yaml` beside its task directories is shown with the chunks those two
files know of; its configuration is not looked up elsewhere, since the original
may have changed since the copy was made.

## What the exit code does

With [`--fail-on fail`](cli.md#exit-codes), a run graded as failed makes
`runhealth` exit with code 3. The task then ends as `FAILED`, and Sirocco
cancels all remaining tasks of the workflow. Warnings, such as load imbalance
or a few slow intervals, leave the task successful, so that the workflow
continues and the warning remains in the report. Use `--fail-on warn` to stop
on warnings as well, or leave out `--fail-on` to never stop the workflow.

The `summary.json` beside each report holds the verdict in a form a later task
can read; see [Output formats](usage.md#output-formats).

This page describes Sirocco's standalone engine, its default. The AiiDA engine
names the job logs differently and is not covered yet.
