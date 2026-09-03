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

:::{dropdown} Tight inode quota? Put the environment elsewhere
:icon: database

The environment holds a few thousand files, which some parallel file systems
count against you.

```bash
export UV_PROJECT_ENVIRONMENT=$SCRATCH/venvs/runhealth
uv sync
```

Keep that variable exported for `uv run` as well.
:::

:::{dropdown} Prefer pip?
:icon: package

```bash
pip install -e .
runhealth --help
```

Requirements: Python 3.11 or newer, `matplotlib` and `pyyaml`.
:::

PDF output needs one more package, and only if you want `runhealth` to write the
PDF itself rather than printing the HTML from a browser:

```bash
uv sync --extra pdf
```

See [Output formats](usage.md#output-formats).
