# Command line reference

```text
runhealth [PATH ...] [-o OUTDIR] [-f html|md|pdf]
          [--profile NAME[,NAME]] [--profile-dir DIR] [--list-profiles]
          [--glob PATTERN] [--last N] [--since 7d] [--list]
          [--watch SECONDS] [--stall-seconds N] [--jobs N]
          [--no-plots] [--no-cache] [--no-squeue] [--embed-logs]
          [--title TEXT] [--open] [--serve PORT]
          [--publish DEST] [--publish-url URL]
```

| Option | |
| --- | --- |
| `PATH ...` | files or directories, local or `host:/path` via ssh/rsync (see [Remote logs](usage.md#remote-logs)); defaults to the working directory |
| `-o, --outdir` | where the report is written (default `runhealth-report`) |
| `-f, --format` | `html` (default), `md` or `pdf` |
| `--glob` | file name pattern used when scanning directories |
| `--last N`, `--since` | keep the N most recent logs, or those newer than e.g. `7d`, `12h` |
| `--profile`, `--profile-dir` | pin profiles by name; add a directory of your own profiles |
| `--list`, `--list-profiles` | show which files would be read, or which profiles exist |
| `--watch N` | re-render every N seconds |
| `--stall-seconds N` | override the silence threshold |
| `--no-plots` | omit the figures |
| `--jobs N` | parallel parsers (default: one per core, capped) |
| `--no-cache`, `--no-squeue` | skip the parse cache; do not query SLURM for job states |
| `--embed-logs` | embed logs smaller than 8 MB as a page the figures can link into |
| `--open` | open the report when it is written |
| `--serve [PORT]` | serve the report on `127.0.0.1:PORT` (default 8000) until interrupted |
| `--publish [DEST]` | transfer the report to `DEST` with `rsync`; falls back to `$RUNHEALTH_PUBLISH` |
| `--publish-url URL` | the address at which the published report is reachable, printed after the transfer |

## Environment variables

| Variable | Meaning |
| --- | --- |
| `RUNHEALTH_PROFILE_DIR` | additional directory of profiles, equivalent to `--profile-dir` |
| `RUNHEALTH_PUBLISH` | default destination for `--publish` |
| `RUNHEALTH_PUBLISH_URL` | default value for `--publish-url` |
| `UV_PROJECT_ENVIRONMENT` | location in which `uv` creates the environment; see [Install](install.md) |
