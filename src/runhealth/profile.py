"""Declarative profiles: what a given model or MPI stack prints, in YAML.

The core of ``runhealth`` knows only about batch logs. Everything specific to
a code -- how it announces progress, what its timer table looks like, which
line means success -- lives in a profile, so adding support for another model
means writing YAML, not Python. See ``docs/profile-reference.md`` for the schema.

Profiles compose. A run of ICON on a Cray machine is described by ``slurm``
plus ``icon`` plus ``cray-mpich``, each contributing its own rules, and all
three are detected from the content of the log itself.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

BUNDLED = Path(__file__).parent / "profiles"
DETECT_BYTES = 8 << 20  # how much of a log to sniff for profile detection
_LITERAL_OK = re.compile(r"[A-Za-z0-9 _:,./#=-]")


def literal_hint(pattern: str) -> str:
    """Longest literal substring every match of ``pattern`` must contain.

    Used as a cheap ``in`` test before the regex, which matters when a rule set
    is applied to a million lines. Conservative by design: anything that could
    make a literal optional (alternation, quantifiers, groups) makes the
    function give up and return ``""``, and the caller then always runs the
    regex.
    """
    best = ""
    buf = ""
    depth = 0
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "\\":
            if depth == 0 and len(buf) > len(best):
                best = buf
            buf = ""
            i += 2
            continue
        if c == "|":
            return ""  # an alternation can bypass any literal we collected
        if c in "([":
            depth += 1
            if depth == 1 and len(buf) > len(best):
                best = buf
            buf = ""
        elif c in ")]":
            depth = max(0, depth - 1)
        elif c in "?*+{":
            # The preceding character is optional or repeated: drop it.
            buf = buf[:-1]
            if depth == 0 and len(buf) > len(best):
                best = buf
            buf = ""
        elif c in "^$.":
            if depth == 0 and len(buf) > len(best):
                best = buf
            buf = ""
        elif depth == 0 and _LITERAL_OK.match(c):
            buf += c
        else:
            if depth == 0 and len(buf) > len(best):
                best = buf
            buf = ""
        i += 1
    if depth == 0 and len(buf) > len(best):
        best = buf
    best = best.strip()
    return best if len(best) >= 4 else ""


@dataclass
class Rule:
    """One named pattern plus whatever the section attaches to it."""

    name: str
    regex: re.Pattern
    literal: str
    spec: dict[str, Any] = field(default_factory=dict)
    profile: str = ""

    def search(self, text: str):
        if self.literal and self.literal not in text:
            return None
        return self.regex.search(text)


def _rule(name: str, spec: Any, profile: str) -> Rule:
    if isinstance(spec, str):
        spec = {"re": spec}
    # ``tables`` name their opening pattern ``start``; everything else ``re``.
    pattern = spec.get("re") or spec["start"]
    hint = spec.get("contains")
    if hint is None:
        hint = literal_hint(pattern)
    flags = re.IGNORECASE if spec.get("ignorecase") else 0
    return Rule(name, re.compile(pattern, flags), hint, spec, profile)


@dataclass
class Profile:
    name: str
    description: str = ""
    priority: int = 0
    detect: list[Rule] = field(default_factory=list)
    fields: list[Rule] = field(default_factory=list)
    keyvalues: list[Rule] = field(default_factory=list)
    series: list[Rule] = field(default_factory=list)
    markers: list[Rule] = field(default_factory=list)
    groups: list[Rule] = field(default_factory=list)
    tables: list[Rule] = field(default_factory=list)
    outcome: list[Rule] = field(default_factory=list)
    boundary: list[Rule] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    thresholds: dict[str, Any] = field(default_factory=dict)
    always: bool = False

    @classmethod
    def from_dict(cls, data: dict, fallback_name: str) -> "Profile":
        name = data.get("name", fallback_name)
        p = cls(
            name=name,
            description=data.get("description", ""),
            priority=int(data.get("priority", 0)),
            settings=data.get("settings", {}) or {},
            thresholds=data.get("thresholds", {}) or {},
            always=bool(data.get("always", False)),
        )
        p.detect = [
            _rule(f"detect{i}", s, name) for i, s in enumerate(data.get("detect", []) or [])
        ]
        p.boundary = [
            _rule(f"boundary{i}", s, name)
            for i, s in enumerate(data.get("attempt_boundary", []) or [])
        ]
        p.outcome = [
            _rule(f"outcome{i}", s, name) for i, s in enumerate(data.get("outcome", []) or [])
        ]
        for section in ("fields", "keyvalues", "series", "markers", "groups", "tables"):
            rules = [_rule(k, v, name) for k, v in (data.get(section) or {}).items()]
            setattr(p, section, rules)
        return p


def load_dir(path: Path) -> dict[str, Profile]:
    out: dict[str, Profile] = {}
    if not path.is_dir():
        return out
    for f in sorted(path.glob("*.yaml")) + sorted(path.glob("*.yml")):
        data = yaml.safe_load(f.read_text()) or {}
        p = Profile.from_dict(data, f.stem)
        out[p.name] = p
    return out


def load_all(extra_dirs: Iterable[Path] = ()) -> dict[str, Profile]:
    """Bundled profiles, then ``$RUNHEALTH_PROFILE_DIR``, then explicit dirs."""
    profiles = load_dir(BUNDLED)
    env = os.environ.get("RUNHEALTH_PROFILE_DIR")
    for d in ([Path(env)] if env else []) + [Path(d) for d in extra_dirs]:
        profiles.update(load_dir(d))
    return profiles


def detect(path: Path, profiles: dict[str, Profile], limit: int = DETECT_BYTES) -> list[Profile]:
    """Profiles whose detect patterns appear in the head of ``path``.

    Profiles marked ``always`` (the generic SLURM one) are included
    unconditionally, so even a completely unknown log gets a report.
    """
    chosen = {name: p for name, p in profiles.items() if p.always}
    candidates = [p for p in profiles.values() if not p.always and p.detect]
    if candidates:
        try:
            with path.open("rb") as fh:
                blob = fh.read(limit).decode("utf-8", "replace")
        except OSError:
            blob = ""
        for p in candidates:
            if any(r.search(blob) for r in p.detect):
                chosen[p.name] = p
    return sorted(chosen.values(), key=lambda p: p.priority)


def select(names: Iterable[str], profiles: dict[str, Profile]) -> list[Profile]:
    picked = []
    for name in names:
        if name not in profiles:
            raise KeyError(f"unknown profile {name!r}; have {', '.join(sorted(profiles))}")
        picked.append(profiles[name])
    return sorted(picked, key=lambda p: p.priority)
