# Command line reference

```text
runhealth [PATH ...] [-o OUTDIR] [-f html|md|pdf]
          [--profile NAME[,NAME]] [--profile-dir DIR] [--list-profiles]
          [--glob PATTERN] [--last N] [--since 7d] [--job-id ID[,ID]] [--list]
          [--watch SECONDS] [--stall-seconds N] [--jobs N]
          [--no-plots] [--no-cache] [--no-squeue] [--no-sacct] [--embed-logs]
          [--output-dir DIR] [--output-glob PATTERN] [--grid FILE]
          [--sbatch OPTIONS] [--no-submit]
          [--fail-on never|warn|fail] [--title TEXT] [--open] [--serve PORT]
          [--publish DEST] [--publish-url URL]
```

| Option | |
| --- | --- |
| `PATH ...` | files or directories, local or `host:/path` via ssh/rsync (see [Remote logs](usage.md#remote-logs)); defaults to the working directory |
| `-o, --outdir` | where the report is written (default `runhealth-report`) |
| `-f, --format` | `html` (default), `md` or `pdf` |
| `--glob` | file name pattern used when scanning directories |
| `--last N`, `--since` | keep the N most recent logs, or those newer than e.g. `7d`, `12h` |
| `--job-id ID[,ID]` | analyze only the logs of these SLURM jobs, recognized by the job id in the file name or, failing that, in the log |
| `--profile`, `--profile-dir` | pin profiles by name; add a directory of your own profiles |
| `--list`, `--list-profiles` | show which files would be read, or which profiles exist |
| `--watch N` | re-render every N seconds |
| `--stall-seconds N` | override the silence threshold |
| `--no-plots` | omit the figures |
| `--jobs N` | parallel processes for parsing logs and reading output (default: one per core, capped) |
| `--no-cache`, `--no-squeue` | skip the parse cache; do not query SLURM (`squeue` or `sacct`) at all |
| `--no-sacct` | do not read the SLURM accounting records of the jobs |
| `--embed-logs` | embed logs smaller than 8 MB as a page the figures can link into |
| `--output-dir DIR` | read the model output in `DIR` as well, or with `auto` in the directory each run's log names; see [Diagnosing the model output](usage.md#diagnosing-the-model-output) |
| `--output-glob` | which files in `--output-dir` to read (default from the profile, else `*.nc`) |
| `--grid FILE` | grid file whose `cell_area` weights the means of output on the native grid |
| `--sbatch OPTIONS` | extra `sbatch` options for the job that reads the output, such as `--account` or `--time` |
| `--no-submit` | read the output on this machine rather than in a SLURM job |
| `--fail-on` | `never` (default), `warn` or `fail`: exit with code 3 when any run is graded at or above this level; see [Exit codes](#exit-codes) |
| `--open` | open the report when it is written |
| `--serve [PORT]` | serve the report on `127.0.0.1:PORT` (default 8000) until interrupted |
| `--publish [DEST]` | transfer the report to `DEST` with `rsync`; falls back to `$RUNHEALTH_PUBLISH` |
| `--publish-url URL` | the address at which the published report is reachable, printed after the transfer |

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | the report was written, and no run reached the `--fail-on` level |
| `1` | no report was written, for example because no log matched, or the server could not start |
| `2` | invalid arguments |
| `3` | the report was written, and at least one run is graded at or above the `--fail-on` level |

A workflow manager can thus distinguish a failed simulation (`3`) from a failure
of `runhealth` itself (`1`, `2`). With `--watch`, the code reflects the last
report written before the interruption.

## Environment variables

| Variable | Meaning |
| --- | --- |
| `RUNHEALTH_PROFILE_DIR` | additional directory of profiles, equivalent to `--profile-dir` |
| `RUNHEALTH_PUBLISH` | default destination for `--publish` |
| `RUNHEALTH_PUBLISH_URL` | default value for `--publish-url` |
| `UV_PROJECT_ENVIRONMENT` | location in which `uv` creates the environment; see [Install](install.md) |
