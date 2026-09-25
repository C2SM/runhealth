# Usage

## Recipes

| Task | Command |
| --- | --- |
| Analyze everything in a directory | `runhealth /path/to/logs -o report/` |
| Analyze logs on a remote cluster from a local machine | `runhealth santis:/path/to/logs -o report/ --open` |
| Analyze a single log and open the report | `runhealth LOG.myjob.12345.o -o report/ --open` |
| Read it in a browser from a login node | `runhealth /path/to/logs -o report/ --serve` |
| Only the most recent logs | `runhealth /path/to/logs --last 5 --since 7d -o report/` |
| Follow a job that is running now | `runhealth /path/to/logs --watch 60 -o report/` |
| Write a Markdown report instead | `runhealth /path/to/logs -f md -o report/` |
| A fast terminal summary only | `runhealth /path/to/logs -o report/ --no-plots` |
| See which logs would be read | `runhealth /path/to/logs --list` |
| Logs with an unusual file name | `runhealth /path/to/logs --glob 'job-*.txt' -o report/` |
| Ignore the model-specific profile | `runhealth /path/to/logs --profile slurm -o report/` |
| Use your own profile | `runhealth /path/to/logs --profile-dir ./my-profiles -o report/` |

Everything is written under `-o`, and a repeated run over the same directory
reuses the cache, so it takes about a second. Every flag is listed in the
[command line reference](cli.md).

## Remote logs

The recommended way to run `runhealth` is from a local machine, pointing at
logs that reside on a cluster:

```bash
runhealth santis:/scratch/e1000/run -o report/ --open
```

Any path argument written as `host:/path` (or `user@host:/path`, or a path
relative to the remote home directory, `host:logs`) is treated as remote,
exactly as `scp` and `rsync` interpret it. This assumes that `ssh host` already
works without a prompt, since `runhealth` calls `rsync` over that same
connection to copy the matching logs into `<outdir>/.remote-cache/` before
reading them. Only files matching the active glob are transferred, and only
from that one directory, not from its subdirectories. The one exception is a
[diagnostics directory](logging.md#3-leave-diagnostics-next-to-the-log)
`diag.*/` beside the logs, which is transferred whole so that its checks
appear in a locally built report as well.

The result is a report on the local disk, so `--open` displays it immediately,
without port forwarding or a combination of `--serve` and `ssh -L`. It also
combines with `--watch`: each pass synchronizes first, so a local report
continues to follow a job that is still writing its log on the cluster.

A local path and a remote one can be mixed freely in the same invocation:

```bash
runhealth santis:/scratch/e1000/run ./local-logs -o report/
```

Each run page still names the original `host:/path`, not the local copy under
`.remote-cache/` that was actually parsed, so a locally built report still
states exactly where on the cluster a log resides.

## Running jobs

A log with no final status is reported as **RUNNING** while it is still being
written, and as **INCOMPLETE** once it has gone quiet. The silence check then
says where it stopped.

When `squeue` is available, `runhealth` asks it for the actual state, so a
queued job appears as **QUEUED** rather than as a broken run, and a job that
the scheduler still believes to be running while its log has gone quiet is
reported as **STALLED**, the one case in which intervention can still help.
`--no-squeue` disables this.

When `sacct` is available, `runhealth` also reads the SLURM accounting record
of every job, in one call per machine: locally for logs read on this machine,
and through `ssh host sacct` for logs synced from `host`. The record
settles the verdict of a log that stops without one (`TIMEOUT`, `NODE_FAIL`,
`OUT_OF_MEMORY`, `CANCELLED by <user>`), supplies the start and the duration
of a log without timestamps, and reveals a job that printed its success
message but still ended with a nonzero exit code. `squeue`, in contrast, is
only asked about logs read on this machine.
`--no-sacct` disables this, and `--no-squeue` disables both queries.

```bash
runhealth /path/to/logs --watch 60 -o report/
```

re-renders at a fixed interval. Each pass resumes where the previous one
stopped, so following a growing 100 MB log costs no more than the new lines.

## Output formats

`--format html`
: The default. `index.html` plus a page per run, with light and dark themes,
  [interactive figures](report.md#reading-the-figures-in-a-browser) and a real
  print stylesheet. The browser's **Print to PDF** produces a well-formatted
  document with sensible page breaks. The figures are written into the pages, so
  a single `.html` file is a complete report that can be attached to an email.

`--format md`
: `report.md` in GitHub-flavored Markdown. Markdown cannot hold an inline
  figure, so the figures are written to `images/*.svg` beside it.

`--format pdf`
: Uses [WeasyPrint](https://weasyprint.org/) if it is installed
  (`uv sync --extra pdf`). Without it, `runhealth` writes the HTML and asks for
  it to be printed instead of failing. WeasyPrint is not a hard dependency
  because it is large and printing from a browser is equally suitable.

## Sharing a report

A report is a directory of plain files with no server behind it, so there are
two ways to make it available to someone else.

**Copy it to a web server.** `--publish` runs `rsync` on the output directory;
the destination is anything `rsync` accepts, so a path on a shared file system
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

Files are transferred with modes a web server can read (`755`/`644`), because a
report written under a restrictive umask on a shared file system would
otherwise arrive unreadable. The parse cache `.cache/` and the logs synced from
a cluster in `.remote-cache/` stay behind, since they are working state rather
than part of the report. Nothing is ever deleted at the destination: a
report directory is often one subdirectory of a document root that holds other
content as well.

Once the destination is set, the flag needs no argument:

```bash
export RUNHEALTH_PUBLISH=www-data@intranet:/var/www/runs
export RUNHEALTH_PUBLISH_URL=https://intranet.example/runs
runhealth /path/to/logs -o report/ --publish
```

Combined with `--watch`, every refresh is published, so that a running job is
presented as a page that colleagues can reload as it progresses.

**Serve it directly.** `--serve` starts a small read-only server bound to
`127.0.0.1`, which is what a login node without a web server can still provide.
The port is optional and defaults to 8000, and the server runs until it is
interrupted:

```bash
runhealth /path/to/logs -o report/ --serve 8080 --watch 60
```

Then, from the local machine, forward the port and open it:

```bash
ssh -L 8080:localhost:8080 login.cluster.example
```

Binding to localhost is deliberate. A directory of job logs should not be
exposed to the other users of a shared node.

`--serve` is also the way to read a report wherever the shell cannot pass a
local file to a browser, which is the usual reason for `--open` appearing to do
nothing: a plain SSH session, WSL with Windows interoperability disabled, or a
desktop with no application registered for `.html`. Given both flags,
`--open` directs the browser to the served address rather than to a `file://`
path, and any browser can be pointed at `http://127.0.0.1:8000/` manually:

```bash
runhealth /path/to/logs -o report/ --serve --open
```

## Performance

Reading is strictly streaming, line by line, using counters and bounded
shortlists instead of stored lines. A 152 MB log with 820k lines is parsed in
about 12 seconds; 443 MB across 31 logs takes about 30 seconds in parallel,
with a peak resident memory in the tens of megabytes.

Results are cached under `<outdir>/.cache/`, keyed on file size and
modification time, so a second pass over the same directory takes well under a
second. `--no-cache` disables the cache.

## Following a long report

A pass over several hundred megabytes takes a while, so every stage reports
what it is doing. On a terminal the three stages that run once per log draw a
bar; parsing counts the megabytes read, and therefore advances within a single
large file rather than only when the file is finished:

```text
runhealth: scanning /scratch/e1000/run
runhealth: 11 log(s) to read, 443.2 MB in total
runhealth: parsing on 8 core(s) ━━━━━━━━━━━━╸──────────── 194/443 MB  13s, 17s left  LOG.831673.o
```

When the output is not a terminal, for example in a job script or a pipe, the
bars are left out and each stage prints one line as it finishes, so the log
stays readable.
