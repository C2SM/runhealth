"""A progress indicator for the command line.

A report over a directory of large logs takes a while, so every stage that
runs once per log reports how far it has come. On a terminal this is a bar
that rewrites itself in place; when the output is redirected it degrades to
one line per stage, so a log file stays readable.
"""

from __future__ import annotations

import shutil
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from types import TracebackType
from typing import Self

FILLED = "━"  # heavy horizontal
HEAD = "╸"  # heavy left half, the leading edge of the bar
EMPTY = "─"  # light horizontal
MIN_BAR = 8
MAX_BAR = 28

_active: Progress | None = None


def clear_active() -> None:
    """Erase the bar currently on screen, if any, so a message can be printed."""
    if _active is not None:
        _active.clear()


def _short(text: str, width: int) -> str:
    if width <= 1 or len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _seconds(value: float) -> str:
    if value < 60:
        return f"{value:.0f}s"
    return f"{int(value // 60)}m{int(value % 60):02d}s"


def megabytes(n: float, total: float) -> str:
    """``180/620 MB``, the shape a byte count takes in the bar."""
    return f"{n / 1e6:.0f}/{total / 1e6:.0f} MB" if total else f"{n / 1e6:.0f} MB"


class Progress:
    """Counts completed units of one stage and draws them as a bar.

    A unit is whatever the stage counts: one log file, one page, or one byte
    of a file being read. ``total`` of zero means the count is unknown, in
    which case only the elapsed time and the current item are shown.

    ``done`` is the closing message, with ``{n}`` the number of units and
    ``{t}`` the time they took; ``counter`` formats the counts shown in the
    bar itself, which is how a byte count becomes megabytes.
    """

    def __init__(
        self,
        label: str,
        total: float = 0,
        done: str = "",
        counter: Callable[[float, float], str] | None = None,
        stream=None,
        enabled: bool | None = None,
    ):
        self.label = label
        self.done = done or f"{label} {{n}} in {{t}}"
        self.counter = counter or (lambda n, total: f"{n:g}/{total:g}" if total else f"{n:g}")
        self.total = max(0, total)
        self.stream = stream if stream is not None else sys.stderr
        self.enabled = self.stream.isatty() if enabled is None else enabled
        self.count = 0
        self.start = time.time()
        self._width = 0

    def __enter__(self) -> Self:
        global _active
        _active = self
        if self.enabled:
            self._draw("")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        global _active
        self.clear()
        _active = None
        if exc is None:
            self._summarise()

    def advance(self, item: str = "", n: float = 1) -> None:
        """Record ``n`` finished units, naming the last one. ``n`` of zero redraws."""
        self.count += n
        if self.enabled:
            self._draw(item)

    def wrap(self, items: Iterable, name: Callable | None = None) -> Iterator:
        """Iterate ``items`` as one stage, advancing after each one is handled."""
        with self:
            for item in items:
                yield item
                self.advance(name(item) if name else "")

    # -- rendering --------------------------------------------------------

    @property
    def elapsed(self) -> float:
        return time.time() - self.start

    def clear(self) -> None:
        if self.enabled and self._width:
            self.stream.write("\r\x1b[K")
            self.stream.flush()
            self._width = 0

    def _summarise(self) -> None:
        note = self.done.format(n=self.count or self.total, t=f"{self.elapsed:.1f}s")
        print(f"runhealth: {note}", file=self.stream, flush=True)

    def _bar(self, width: int) -> str:
        if not self.total:
            return ""
        fraction = min(1.0, self.count / self.total)
        filled = int(fraction * width)
        if filled >= width:
            return FILLED * width
        return FILLED * filled + HEAD + EMPTY * (width - filled - 1)

    def _eta(self) -> str:
        left = self.total - self.count
        if not self.total or left <= 0 or not self.count:
            return _seconds(self.elapsed)
        eta = self.elapsed / self.count * left
        return (
            f"{_seconds(self.elapsed)}, {_seconds(eta)} left"
            if eta >= 1
            else _seconds(self.elapsed)
        )

    def _draw(self, item: str) -> None:
        columns = shutil.get_terminal_size((80, 24)).columns
        counter = self.counter(self.count, self.total)
        head = f"runhealth: {self.label} "
        tail = f" {counter}  {self._eta()}"
        bar = self._bar(max(MIN_BAR, min(MAX_BAR, columns - len(head) - len(tail) - 20)))
        line = f"{head}{bar}{tail}"
        room = columns - len(line) - 3
        if item and room >= 6:
            line += f"  {_short(item, room)}"
        line = line[: columns - 1]
        self.stream.write("\r" + line + "\x1b[K")  # erase whatever the last line left
        self.stream.flush()
        self._width = len(line)
