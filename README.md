# runhealth

**Analyze a directory of HPC batch job logs and obtain a report on the
outcome and the performance of each run.**

A batch log already records whether the job completed, whether and where it
hung, how fast it ran and whether it slowed down, how evenly the work was
distributed across ranks, and whether the underlying machine was healthy.
`runhealth` extracts that information and presents it as a report.

```bash
runhealth /path/to/logs -o report/ --open
```

It can be run on a local machine against logs that reside on a cluster. The
report is then written locally as well and can be opened in a browser without
an SSH tunnel:

```bash
runhealth santis:/scratch/e1000/run -o report/ --open
```

Any `host:/path` argument is accepted, provided that `ssh host` already works;
`runhealth` first copies the matching logs with `rsync`.

<p align="center">
  <img src="docs/images/timeline.svg" alt="A run timeline: one blue phase filling the whole allocation, with a red silence bar above it" width="820">
</p>

<p align="center"><em>A single figure is sufficient for the diagnosis: the job
spent its entire allocation in the coupling setup and wrote no further
output.</em></p>

`runhealth` is **model-agnostic**. The core interprets batch logs in general:
timestamps, SLURM records, silence and error signatures. Everything specific to
a code is defined in a **YAML profile**, so support for an additional model
requires a few regular expressions rather than Python code. Profiles for ICON
and Cray MPICH are included.

## Quick start

Two sample logs are included in the repository, so no cluster is required:

```bash
git clone https://github.com/C2SM/runhealth.git
cd runhealth
uv sync
uv run runhealth examples/ --glob '*.log' -o /tmp/demo --open
```

```
runhealth: scanning examples/
runhealth: 2 log(s) to read, 0.2 MB in total
runhealth: parsed 2 log(s) in 0.2s
runhealth: analyzed 2 run(s) in 0.1s
runhealth: drawing the overview
runhealth: writing the search index
runhealth: rendered 2 page(s) in 0.1s
  WARN  SUCCESS      26m 18s  demo.log       - 8 of 199 intervals took more than 3x the median
  FAIL  FAILED    1h 44m 10s  demo_hang.log  - CANCELLED AT 2026-03-17T22:48:18 DUE TO TIME LIMIT
runhealth: wrote /tmp/demo/index.html
```

If the shell cannot pass a local file to a browser, for example in a plain SSH
session or in WSL with Windows interoperability disabled, use `--serve` instead
of `--open` and open <http://127.0.0.1:8000/>.

## Documentation

The full documentation is published at **<https://c2sm.github.io/runhealth/>**:

- [Install](https://c2sm.github.io/runhealth/install.html)
- [Usage](https://c2sm.github.io/runhealth/usage.html): recipes, following a
  running job, output formats, sharing a report, performance
- [Reading the report](https://c2sm.github.io/runhealth/report.html): what each
  check means, how to read the figures
- [Profiles](https://c2sm.github.io/runhealth/profiles.html) and the
  [profile reference](https://c2sm.github.io/runhealth/profile-reference.html):
  adding support for a new code
- [Improving log quality](https://c2sm.github.io/runhealth/logging.html): two
  inexpensive changes to a job script that make its output considerably more
  informative
- [Troubleshooting](https://c2sm.github.io/runhealth/troubleshooting.html)
- [Command line reference](https://c2sm.github.io/runhealth/cli.html)
- [Development](https://c2sm.github.io/runhealth/development.html)

The sources are Markdown files under [`docs/`](docs/) and can be built locally
with

```bash
uv run --group docs sphinx-build -b html docs docs/_build/html
```

## License

BSD 3-Clause. See [LICENSE](LICENSE).
