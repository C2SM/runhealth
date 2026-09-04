# Usage

## Recipes

| You want to | Run |
| --- | --- |
| Look at everything in a directory | `runhealth /path/to/logs -o report/` |
| Look at logs on a remote cluster, from your laptop | `runhealth santis:/path/to/logs -o report/ --open` |
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

## Remote logs

The recommended way to run `runhealth` is from your own machine, pointing at
logs that live on a cluster:

```bash
runhealth santis:/scratch/e1000/run -o report/ --open
```

Any path argument written as `host:/path` (or `user@host:/path`, or a path
relative to the remote home directory, `host:logs`) is treated as remote,
exactly like `scp` or `rsync` read it. This assumes `ssh host` already works
without a prompt, since `runhealth` shells out to `rsync` over that same
connection to pull the matching logs down into `<outdir>/.remote-cache/`
before reading them. Only files matching the active glob are transferred, and
only from that one directory, not its subdirectories.

The result is a report written to your local disk, so `--open` shows it
straight away with no port forwarding or `--serve`/`ssh -L` dance needed. It
also composes with `--watch`: each pass re-syncs first, so a report on your
laptop keeps following a job that is still writing its log on the cluster.

A local path and a remote one can be mixed freely in the same invocation:

```bash
runhealth santis:/scratch/e1000/run ./local-logs -o report/
```

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
: The default. `index.html` plus a page per run, with light and dark themes,
  [interactive figures](report.md#reading-them-in-a-browser) and a real print
  stylesheet. The browser's **Print to PDF** produces a clean document with
  sensible page breaks. The figures are written into the pages, so a single
  `.html` file is a complete report you can attach to a mail.

`--format md`
: `report.md` in GitHub-flavoured Markdown. Markdown cannot hold an inline
  figure, so these are written to `images/*.svg` beside it.

`--format pdf`
: Uses [WeasyPrint](https://weasyprint.org/) if it is installed
  (`uv sync --extra pdf`). Without it, `runhealth` writes the HTML and tells you
  to print it, rather than failing. WeasyPrint is not a hard dependency because
  it is large and the browser route is just as good.

## Sharing a report

A report is a directory of plain files with nothing to serve it, so there are
two ways to put it in front of someone else.

**Copy it to a web server.** `--publish` runs `rsync` on the output directory;
the destination is anything `rsync` accepts, so a path on a shared filesystem
works as well as a host:

```bash
runhealth /path/to/logs -o report/ \
    --publish www-data@intranet:/var/www/runs \
    --publish-url https://intranet.example/runs
```

```text
runhealth: wrote report/index.html
runhealth: published to https://intranet.example/runs/index.html
```

Files are synced with modes a web server can read (`755`/`644`), because a
report written under a restrictive umask on a shared filesystem otherwise
arrives unreadable. Nothing is ever deleted at the far end: a report directory
is often a subdirectory of a document root holding other things too.

Set the destination once and the flag needs no argument afterwards:

```bash
export RUNHEALTH_PUBLISH=www-data@intranet:/var/www/runs
export RUNHEALTH_PUBLISH_URL=https://intranet.example/runs
runhealth /path/to/logs -o report/ --publish
```

Combined with `--watch`, every refresh is published, which turns a running job
into a page colleagues can keep reloading.

**Or serve it yourself.** `--serve` starts a small read-only server bound to
`127.0.0.1` only, which is the case for a login node with no web server on it:

```bash
runhealth /path/to/logs -o report/ --serve 8080 --watch 60
```

Then, from your own machine, forward the port and open it:

```bash
ssh -L 8080:localhost:8080 login.cluster.example
```

Binding to localhost is deliberate. A directory of job logs is not something to
expose to everyone else logged into a shared node.

## Performance

Reading is strictly streaming, line by line, with counters and bounded
shortlists instead of stored lines. A 152 MB, 820k-line log parses in about
12 seconds; 443 MB across 31 logs takes about 30 seconds in parallel, with peak
resident memory in the tens of megabytes.

Results are cached under `<outdir>/.cache/`, keyed on file size and modification
time, so a second pass over the same folder takes well under a second.
`--no-cache` disables it.
