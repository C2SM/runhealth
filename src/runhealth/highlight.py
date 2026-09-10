"""Colour a shell script for the report, without a JavaScript library.

A report has to work with no network, and the run script viewer is the only
place a page shows source code, so the markup is produced here rather than
by a highlighter downloaded at read time. One regular expression walks the
text once and every match becomes a span; anything unmatched is plain text.

The grammar is deliberately shallow. Heredocs and nested expansions are not
tracked, because the aim is a script a reader can skim, not a parser: the
worst a mistake costs is one span with the wrong colour.
"""

from __future__ import annotations

import html
import re

KEYWORDS = frozenset(
    "if then elif else fi for while until do done case esac in function "
    "select return break continue".split()
)
# Builtins plus the commands a batch script is mostly made of.
COMMANDS = frozenset(
    "echo export set unset source cd eval exec exit local read shift trap wait "
    "declare printf test module srun sbatch scancel squeue mpirun aprun python "
    "python3 mkdir rmdir rm cp mv ln cat sed awk grep ls date hostname env "
    "ulimit umask sleep touch chmod tar which nvidia-smi".split()
)

_VAR = r"\$(?:\{[^}\n]*\}?|[A-Za-z_]\w*|[-@*#?!$0-9])"
VAR_RE = re.compile(_VAR)

TOKEN_RE = re.compile(
    # A '#' opens a comment only at the start of a word, which keeps
    # ${var#trim} and colour#codes out of it.
    r"(?P<cmt>(?<![^\s])\#[^\n]*)"
    r"|(?P<sq>'[^'\n]*'?)"
    r"|(?P<dq>\"(?:\\.|[^\"\\\n])*\"?)"
    rf"|(?P<var>{_VAR})"
    r"|(?P<word>[A-Za-z_][A-Za-z0-9_-]*)",
    re.MULTILINE,
)


def _class_of(kind: str, text: str) -> str:
    if kind == "cmt":
        # Directives are what a reader opens a job script for.
        return "sy-dir" if text[:7].upper() == "#SBATCH" else "sy-cmt"
    if kind in ("sq", "dq"):
        return "sy-str"
    if kind == "var":
        return "sy-var"
    if text in KEYWORDS:
        return "sy-kw"
    return "sy-cmd" if text in COMMANDS else ""


def _with_vars(text: str) -> str:
    """Escaped ``text``, with the expansions inside it still marked up."""
    out: list[str] = []
    at = 0
    for m in VAR_RE.finditer(text):
        out.append(html.escape(text[at : m.start()]))
        out.append(f'<span class="sy-var">{html.escape(m.group())}</span>')
        at = m.end()
    out.append(html.escape(text[at:]))
    return "".join(out)


def bash_html(text: str) -> str:
    """``text`` as escaped HTML, with shell tokens wrapped in spans."""
    out: list[str] = []
    at = 0
    for m in TOKEN_RE.finditer(text):
        start, end = m.span()
        if start > at:
            out.append(html.escape(text[at:start]))
        chunk = m.group()
        kind = m.lastgroup or ""
        cls = _class_of(kind, chunk)
        # A double-quoted string still expands what is inside it.
        inner = _with_vars(chunk) if kind == "dq" else html.escape(chunk)
        out.append(f'<span class="{cls}">{inner}</span>' if cls else inner)
        at = end
    out.append(html.escape(text[at:]))
    return "".join(out)
