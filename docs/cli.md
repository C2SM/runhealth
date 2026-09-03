# Command line reference

```text
runhealth [PATH ...] [-o OUTDIR] [-f html|md|pdf]
          [--profile NAME[,NAME]] [--profile-dir DIR] [--list-profiles]
          [--glob PATTERN] [--last N] [--since 7d] [--list]
          [--watch SECONDS] [--stall-seconds N] [--dpi N] [--jobs N]
          [--no-plots] [--no-cache] [--no-squeue] [--embed-logs]
          [--title TEXT] [--open]
```

| Option | |
| --- | --- |
| `PATH ...` | files or directories; defaults to the working directory |
| `-o, --outdir` | where the report is written (default `runhealth-report`) |
| `-f, --format` | `html` (default), `md` or `pdf` |
| `--glob` | filename pattern to scan directories with |
| `--last N`, `--since` | keep the N newest, or those newer than e.g. `7d`, `12h` |
| `--profile`, `--profile-dir` | pin profiles by name; add a directory of your own |
| `--list`, `--list-profiles` | show what would be read, or which profiles exist |
| `--watch N` | re-render every N seconds |
| `--stall-seconds N` | override the silence threshold |
| `--dpi`, `--no-plots` | figure resolution, or no figures at all |
| `--jobs N` | parallel parsers (default: one per core, capped) |
| `--no-cache`, `--no-squeue` | skip the parse cache; do not ask SLURM for job states |
| `--embed-logs` | copy logs under 8 MB into the report and link them |
| `--open` | open the report when it is written |

## Environment variables

| Variable | Meaning |
| --- | --- |
| `RUNHEALTH_PROFILE_DIR` | extra directory of profiles, equivalent to `--profile-dir` |
| `UV_PROJECT_ENVIRONMENT` | where `uv` puts the environment; see [Install](install.md) |
