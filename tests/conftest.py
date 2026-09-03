from pathlib import Path

import pytest

from runhealth import extract, health, profile

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def profiles():
    return profile.load_all()


@pytest.fixture(scope="session")
def parsed(profiles):
    """Every fixture log, parsed once and shared by the tests."""
    out = {}
    for path in sorted(FIXTURES.glob("*.log")):
        picked = profile.detect(path, profiles)
        out[path.stem] = extract.parse(path, picked)
    return out


@pytest.fixture(scope="session")
def assessed(parsed):
    return {name: health.assess(log) for name, log in parsed.items()}
