# Usage

## Recipes

| You want to | Run |
| --- | --- |
| Analyze everything in a directory | `runhealth /path/to/logs -o report/` |
| Analyze logs on a remote cluster from your laptop | `runhealth santis:/path/to/logs -o report/ --open` |
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

The recommended way to run `runhealth` is from your own machine, pointing at
logs that live on a cluster:

```bash
runhealth santis:/scratch/e1000/run -o report/ --open
```

Any path argument written as `host:/path` (or `user@host:/path`, or a path
relative to the remote home directory, `host:logs`) is treated as remote,
exactly as `scp` and `rsync` interpret it. This assumes that `ssh host` already
works without a prompt, since `runhealth` calls `rsync` over that same
connection to copy the matching logs into `<outdir>/.remote-cache/` before
reading them. Only files matching the active glob are transferred, and only
from that one directory, not from its subdirectories.

The result is a report on your local disk, so `--open` displays it immediately,
with no need for port forwarding or for `--serve` and `ssh -L`. It also
combines with `--watch`: each pass synchronizes first, so a report on your
laptop keeps following a job that is still writing its log on the cluster.

A local path and a remote one can be mixed freely in the same invocation:

```bash
runhealth santis:/scratch/e1000/run ./local-logs -o report/
```

Each run page still names the original `host:/path`, not the local copy under
`.remote-cache/` that was actually parsed, so a report built on your laptop
still states exactly where on the cluster a log resides.

## Running jobs

A log with no final status is reported as **RUNNING** while it is still being
written, and as **INCOMPLETE** once it has gone quiet. The silence check then
says where it stopped.

When `squeue` is available, `runhealth` asks it for the actual state, so a
queued job appears as **QUEUED** rather than as a broken run, and a job that
the scheduler still believes to be running while its log has gone quiet is
reported as **STALLED**, the one case in which intervening can still help.
`--no-squeue` disables this.

```bash
runhealth /path/to/logs --watch 60 -o report/
```

re-renders at a fixed interval. Each pass resumes where the previous one
stopped, so following a growing 100 MB log costs no more than the new lines.

## Output formats

`--format html`
: The default. `index.html` plus a page per run, with light and dark themes,
  [interactive figures](report.md#reading-them-in-a-browser) and a real print
  stylesheet. The browser's **Print to PDF** produces a clean document with
  sensible page breaks. The figures are written into the pages, so a single
  `.html` file is a complete report that can be attached to an email.

`--format md`
: `report.md` in GitHub-flavored Markdown. Markdown cannot hold an inline
  figure, so the figures are written to `images/*.svg` beside it.

`--format pdf`
: Uses [WeasyPrint](https://weasyprint.org/) if it is installed
  (`uv sync --extra pdf`). Without it, `runhealth` writes the HTML and asks for
  it to be printed instead of failing. WeasyPrint is not a hard dependency
  because it is large and the browser route is equally good.

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
otherwise arrive unreadable. Nothing is ever deleted at the destination: a
report directory is often one subdirectory of a document root that holds other
content as well.

Once the destination is set, the flag needs no argument:

```bash
export RUNHEALTH_PUBLISH=www-data@intranet:/var/www/runs
export RUNHEALTH_PUBLISH_URL=https://intranet.example/runs
runhealth /path/to/logs -o report/ --publish
```

Combined with `--watch`, every refresh is published, which turns a running job
into a page that colleagues can reload as it progresses.

**Or serve it yourself.** `--serve` starts a small read-only server bound to
`127.0.0.1`, which is what a login node without a web server can still offer.
The port is optional and defaults to 8000, and the server runs until it is
interrupted:

```bash
runhealth /path/to/logs -o report/ --serve 8080 --watch 60
```

Then, from your own machine, forward the port and open it:

```bash
ssh -L 8080:localhost:8080 login.cluster.example
```

Binding to localhost is deliberate. A directory of job logs should not be
exposed to everyone else logged into a shared node.

`--serve` is also the way to read a report wherever the shell cannot pass a
local file to a browser, which is the usual reason for `--open` appearing to do
nothing: a bare SSH session, WSL with its Windows interoperability switched
off, or a desktop with no application registered for `.html`. Given both flags,
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
