"""Shared fixture: one full run of the article's example on a temporary Delta lake."""

from __future__ import annotations

from typing import Any

import pytest

from src.scenario import run


@pytest.fixture(scope="session")
def result(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return run(tmp_path_factory.mktemp("lake"))
