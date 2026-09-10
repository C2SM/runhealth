# Install

Only [uv](https://docs.astral.sh/uv/) is needed; it fetches a suitable Python
itself.

```bash
git clone https://github.com/C2SM/runhealth.git
cd runhealth
uv sync
uv run runhealth --help
```

Add `uv run` in front of `runhealth` in every example in this documentation, or
activate the environment once with `source .venv/bin/activate`.

:::{dropdown} Placing the environment elsewhere under a tight inode quota
:icon: database

The environment holds a few thousand files, which counts against the inode
quota of some parallel file systems.

```bash
export UV_PROJECT_ENVIRONMENT=$SCRATCH/venvs/runhealth
uv sync
```

Keep that variable exported for `uv run` as well.
:::

:::{dropdown} Installing with pip instead
:icon: package

```bash
pip install -e .
runhealth --help
```

Requirements: Python 3.11 or newer and `pyyaml`. The figures are drawn as SVG
by `runhealth` itself, so no plotting library has to be installed.
:::

PDF output requires one additional package, and only if `runhealth` should
write the PDF itself rather than the HTML being printed from a browser:

```bash
uv sync --extra pdf
```

See [Output formats](usage.md#output-formats).
