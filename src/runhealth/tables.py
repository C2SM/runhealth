"""Parsers for the tabular blocks that models and MPI stacks print at exit.

Two shapes cover everything seen so far, and both are selected by a profile
rather than hard-coded, so a new model needs a YAML entry and no Python:

``ruled``
    Columns are delimited by a rule row of dash runs separated by blanks, the
    row above or below it naming them. ICON's timer report is of this kind, and
    the rule row is a gift: it gives exact column spans, so a name containing
    spaces or a right-aligned number never has to be guessed at.
``trailing-numbers``
    No rules; each row is a label followed by a fixed count of numeric fields.
    Cray MPICH's Slingshot counter summary and its ratio block are of this
    kind, and the label there does contain spaces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

RULE_RE = re.compile(r"^[\s-]*-{3,}[\s-]*$")
GAPPED_RULE_RE = re.compile(r"^\s*-{3,}(?:\s{2,}-{2,})+\s*$")
NUM_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
# ICON writes elapsed times as 0.05847s, 16m43s, 02m46s or 01h02m.
DUR_RE = re.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?$")
RANK_TAG_RE = re.compile(r"^\[(\d+)\]$")


def parse_duration(text: str) -> float | None:
    """Seconds from a compact duration such as ``16m43s`` or ``0.05847s``."""
    text = text.strip()
    if not text:
        return None
    m = DUR_RE.match(text)
    if not m or not any(m.groups()):
        return float(text) if NUM_RE.match(text) else None
    d, h, mi, s = m.groups()
    return int(d or 0) * 86400 + int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0)


def parse_number(text: str) -> float | None:
    text = text.strip()
    return float(text) if NUM_RE.match(text) else None


@dataclass
class Row:
    """One table row: an ordered label plus its cells, keyed by column name."""

    label: str
    depth: int = 0
    cells: dict[str, str] = field(default_factory=dict)
    values: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "depth": self.depth,
            "cells": self.cells,
            "values": self.values,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Row":
        return cls(d["label"], d.get("depth", 0), d.get("cells", {}), d.get("values", {}))


@dataclass
class Table:
    """A parsed block: its title, column names and rows."""

    name: str
    title: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    wall: float | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "columns": self.columns,
            "wall": self.wall,
            "rows": [r.to_dict() for r in self.rows],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Table":
        return cls(
            d["name"],
            d.get("title", ""),
            d.get("columns", []),
            [Row.from_dict(r) for r in d.get("rows", [])],
            d.get("wall"),
        )


def _unique(names: list[str]) -> list[str]:
    """Disambiguate repeated headers by qualifying them with the one before.

    Cray's counter summary heads three pairs of columns ``Min (/s) Mean (/s)
    Max (/s)``, so the bare names would collide.
    """
    out: list[str] = []
    for i, name in enumerate(names):
        if name in out:
            name = f"{names[i - 1]} {name}" if i else f"{name} 2"
        while name in out:
            name += "'"
        out.append(name)
    return out


def _spans(rule: str) -> list[tuple[int, int]]:
    """Column spans of a gapped dash rule, each span open-ended to the right."""
    out = []
    for m in re.finditer(r"-+", rule):
        out.append((m.start(), m.end()))
    if out:
        # The last column is padded, not truncated, so let it run to the end.
        out[-1] = (out[-1][0], 10_000)
    return out


class TableReader:
    """Incremental reader for one table block.

    Fed line by line while the enclosing extractor is inside a block. Returns
    True from :meth:`feed` while it wants more lines.
    """

    def __init__(self, name: str, spec: dict, title: str = "", wall: float | None = None):
        self.spec = spec
        self.kind = spec.get("kind", "ruled")
        self.table = Table(name=name, title=title, wall=wall)
        self.nesting = re.compile(spec["nesting"]) if spec.get("nesting") else None
        self.durations = set(spec.get("durations", []))
        self.numbers = set(spec.get("numbers", []))
        self.max_lines = int(spec.get("max_lines", 4000))
        self.include_start = bool(spec.get("include_start"))
        self._spans: list[tuple[int, int]] = []
        self._seen = 0
        self._blanks = 0
        self._done = False

    @property
    def done(self) -> bool:
        return self._done

    def feed(self, text: str) -> bool:
        self._seen += 1
        if self._seen > self.max_lines:
            self._done = True
            return False
        handler = self._feed_ruled if self.kind == "ruled" else self._feed_trailing
        handler(text)
        return not self._done

    # -- ruled ------------------------------------------------------------

    def _feed_ruled(self, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            # Blank lines separate header from body; two in a row after rows
            # have started mean the block is over.
            self._blanks += 1
            if self.table.rows and self._blanks >= 2:
                self._done = True
            return
        self._blanks = 0
        if GAPPED_RULE_RE.match(text):
            if not self._spans:
                self._spans = _spans(text)
            return
        if RULE_RE.match(text):
            # A rule without gaps closes the table.
            if self.table.rows:
                self._done = True
            return
        if not self._spans:
            # No column rule in sight: this is not the table we thought it was.
            if self._seen > 20:
                self._done = True
            return
        if not self.table.columns:
            self.table.columns = _unique(
                [text[a:b].strip() or f"col{i}" for i, (a, b) in enumerate(self._spans)]
            )
            return
        self._add_row(self._slice(text))

    def _slice(self, text: str) -> list[str]:
        # The first column keeps its indentation, which carries the nesting.
        return [
            text[a:b].rstrip() if i == 0 else text[a:b].strip()
            for i, (a, b) in enumerate(self._spans)
        ]

    # -- trailing-numbers -------------------------------------------------

    def _feed_trailing(self, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            self._blanks += 1
            if self.table.rows and self._blanks >= 1:
                self._done = True
            return
        self._blanks = 0
        if not self.table.columns:
            self.table.columns = _unique(re.split(r"\s{2,}", stripped))
            return
        parts = stripped.split()
        ncols = len(self.table.columns)
        # Peel the numeric tail off the right; whatever is left is the label.
        nums: list[str] = []
        while parts and len(nums) < ncols - 1 and NUM_RE.match(parts[-1]):
            nums.insert(0, parts.pop())
        if not parts or len(nums) < ncols - 1:
            self._done = True
            return
        self._add_row([" ".join(parts), *nums])

    # -- shared -----------------------------------------------------------

    def _add_row(self, cells: list[str]) -> None:
        if not cells or not cells[0]:
            return
        label, depth = cells[0], 0
        if self.nesting:
            m = self.nesting.match(label)
            if m:
                # One nesting marker per level, indented by a fixed step.
                depth = 1 + len(m.group(1)) // 3
                label = label[m.end() :]
        row = Row(label=label.strip(), depth=depth)
        for name, cell in zip(self.table.columns, cells):
            row.cells[name] = cell
            tag = RANK_TAG_RE.match(cell)
            if tag:
                row.values[name] = float(tag.group(1))
                continue
            value = parse_duration(cell) if name in self.durations else parse_number(cell)
            if value is not None:
                row.values[name] = value
        self.table.rows.append(row)
