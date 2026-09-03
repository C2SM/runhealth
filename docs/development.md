# Development

```bash
uv sync
uv run pytest
uv run python tests/make_fixtures.py     # regenerate the test logs
uv run python examples/make_demo.py      # regenerate the sample logs
```

The test fixtures are small hand-built logs, one per shape: a healthy run, a run
that hangs in its coupling setup, two attempts in one file, a generic SLURM job
from an unknown code, output with no timestamps, and the degenerate cases
(empty, truncated, not a log at all). No real log is committed; they are far too
large, and the figures in this documentation come from `examples/demo.log`.

## The layout

| Module | |
| --- | --- |
| `logfile.py` | line grammar: timestamps, rank labels, streaming reads |
| `profile.py` | loading, composing and detecting YAML profiles |
| `extract.py` | one streaming pass over a log, producing a `RunLog` |
| `tables.py` | the two table shapes models and MPI stacks print |
| `health.py` | `RunLog` to checks and a grade |
| `plots.py` | the figures |
| `report.py` | HTML, Markdown and PDF rendering |
| `cli.py` | discovery, cache, parallelism, the watch loop |

Formatting is [black](https://black.readthedocs.io/) via `pre-commit`:

```bash
pre-commit install
```

## Building this documentation

The documentation is Sphinx with [MyST](https://myst-parser.readthedocs.io/)
Markdown sources under `docs/`:

```bash
uv run --group docs sphinx-build -b html docs docs/_build/html
```

Open `docs/_build/html/index.html`. Add `-W` to turn warnings into errors, which
is what the [GitHub Actions workflow](https://github.com/C2SM/runhealth/blob/main/.github/workflows/docs.yml)
does before publishing to GitHub Pages on every push to `main`.

## Licence

BSD 3-Clause. See [LICENSE](https://github.com/C2SM/runhealth/blob/main/LICENSE).
