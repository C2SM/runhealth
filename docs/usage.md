# Usage

## Recipes

| You want to | Run |
| --- | --- |
| Look at everything in a directory | `runhealth /path/to/logs -o report/` |
| Look at one log and open it | `runhealth LOG.myjob.12345.o -o report/ --open` |
| Only the recent ones | `runhealth /path/to/logs --last 5 --since 7d -o report/` |
| Follow a job that is running now | `runhealth /path/to/logs --watch 60 -o report/` |
| A Markdown report instead | `runhealth /path/to/logs -f md -o report/` |
| Just a terminal summary, fast | `runhealth /path/to/logs -o report/ --no-plots` |
| See which logs would be read | `runhealth /path/to/logs --list` |
| Logs with an unusual name | `runhealth /path/to/logs --glob 'job-*.txt' -o report/` |
| Ignore what the model profile knows | `runhealth /path/to/logs --profile slurm -o report/` |
| Use your own profile | `runhealth /path/to/logs --profile-dir ./my-profiles -o report/` |

Everything is written under `-o`, and re-running over the same directory reuses
the cache, so it costs about a second. Every flag is listed in the
[command line reference](cli.md).

## Running jobs

A log with no final status is reported as **RUNNING** while it is still being
written, and as **INCOMPLETE** once it has gone quiet. The silence check then
says where it stopped.

When `squeue` is available, `runhealth` asks it for the real state, so a queued
job shows as **QUEUED** rather than as a broken run, and a job the scheduler
still believes is running while its log has gone quiet is reported as
**STALLED**, the one case where intervening is still worth something.
`--no-squeue` turns that off.

```bash
runhealth /path/to/logs --watch 60 -o report/
```

re-renders on an interval. Each pass resumes from where the last one stopped, so
following a growing 100 MB log costs no more than the new lines.

## Output formats

`--format html`
: The default. `index.html` plus a page per run, with light and dark themes and
  a real print stylesheet. The browser's **Print to PDF** produces a clean
  document with sensible page breaks.

`--format md`
: `report.md` with the same figures, in GitHub-flavoured Markdown.

`--format pdf`
: Uses [WeasyPrint](https://weasyprint.org/) if it is installed
  (`uv sync --extra pdf`). Without it, `runhealth` writes the HTML and tells you
  to print it, rather than failing. WeasyPrint is not a hard dependency because
  it is large and the browser route is just as good.

## Performance

Reading is strictly streaming, line by line, with counters and bounded
shortlists instead of stored lines. A 152 MB, 820k-line log parses in about
12 seconds; 443 MB across 31 logs takes about 30 seconds in parallel, with peak
resident memory in the tens of megabytes.

Results are cached under `<outdir>/.cache/`, keyed on file size and modification
time, so a second pass over the same folder takes well under a second.
`--no-cache` disables it.
