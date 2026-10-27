"""Pfade und Fixtures für die Tests des Sprachmoduls (offline, ohne Audiogeräte)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HIER = Path(__file__).resolve().parent
KERN = HIER.parents[1]
for pfad in (KERN, HIER):
    if str(pfad) not in sys.path:
        sys.path.insert(0, str(pfad))

from stimme_hilfen import Protokoll  # noqa: E402


@pytest.fixture
def protokoll():
    return Protokoll()
