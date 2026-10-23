# Running as a SLURM job

`runhealth` can check every model job automatically by running as a small
SLURM job of its own once the model job has ended. The report is then ready
when the run is over, and its exit code can decide whether a job chain goes on.

## The job script

[`examples/runhealth.sbatch`](https://github.com/C2SM/runhealth/blob/main/examples/runhealth.sbatch)
is a complete job script. It takes the id of the model job, the directory of
its log and, optionally, where to write the report (by default
`<log directory>/runhealth/<job id>/`):

```bash
sbatch --dependency=afterany:12345 runhealth.sbatch 12345 /scratch/run/logs
```

- It requests one task with four cores for 15 minutes, which is ample for a
  single log; add the `--account` and `--partition` your site requires.
- It selects the log with [`--job-id`](cli.md), so a directory full of earlier
  logs costs nothing.
- It reads no model output. With
  [`--output-dir`](usage.md#diagnosing-the-model-output) added, raise the time
  and cores to suit the size of the output, which at kilometer scale takes
  hours rather than minutes.
- It runs with [`--fail-on fail`](cli.md#exit-codes), so the job itself fails
  when the model run failed, while warnings such as load imbalance leave it
  successful.
- `$RUNHEALTH` names the command that starts `runhealth`, for example
  `uv run --project $HOME/runhealth runhealth` for a checkout installed as
  described in [Install](install.md). When `$RUNHEALTH_PUBLISH` is set, the
  report is also [published](usage.md#sharing-a-report).

The dependency must be `afterany`, not `afterok`: the check is most valuable
when the model job failed, timed out or was cancelled, and `afterok` would
never start it in exactly those cases.

## Submitting the check

From wherever the model job is submitted:

```bash
jobid=$(sbatch --parsable model.sh)
sbatch --dependency=afterany:$jobid runhealth.sbatch $jobid "$PWD"
```

Alternatively, the model job submits its own check as its first action, which
needs no change to how it is submitted. Inside the job, `$SLURM_JOB_ID` is the
id of the model job:

```bash
sbatch --dependency=afterany:$SLURM_JOB_ID runhealth.sbatch $SLURM_JOB_ID "$PWD"
```

The other way round does not work: inside the `runhealth` job,
`$SLURM_JOB_ID` is the id of the check, which is why the script takes the id of
the model job as an argument.

## Gating a job chain

Because the check fails with the model run, a dependency on the check holds
back the next segment of a chain until the previous one has been found healthy:

```bash
model=$(sbatch --parsable model.sh)
check=$(sbatch --parsable --dependency=afterany:$model runhealth.sbatch $model "$PWD")
sbatch --dependency=afterok:$check --kill-on-invalid-dep=yes model_next.sh
```

Without `--kill-on-invalid-dep=yes`, the next segment would remain pending
with the reason `DependencyNeverSatisfied` after a failed check, rather than
being removed from the queue.

The `summary.json` beside the report holds the verdict in a form that a script
can read, for example to decide on a restart; see
[Output formats](usage.md#output-formats).
