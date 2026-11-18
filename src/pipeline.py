"""Releasing a repair, and closing a month. Depends only on the protocols."""

from __future__ import annotations

import pandas as pd

from .models import GOLD_COLUMNS, Adjustment, Release
from .protocols import OrderReader, ReleaseStore
from .totals import full_rebuild, old_and_new_groups, restrict


def build_release(silver: OrderReader, start: int, end: int) -> Release:
    """Read Silver at `end` and compute the groups touched by changes `start..end`."""
    groups = old_and_new_groups(silver.changes(start, end))
    rows = restrict(full_rebuild(silver.read(end)), groups)
    return Release(groups=groups, rows=rows.to_dict("records"), silver_version=end)


def publish(gold: ReleaseStore, release: Release, guard: bool) -> str:
    """Replace the release's groups, optionally refusing older or equal input versions.

    This table-wide guard assumes releases cover all changes since the prior release.
    It is a read followed by a write, not an atomic concurrency control mechanism.
    """
    if guard and release.silver_version <= gold.last_silver_version():
        return "rejected"
    gold.replace_groups(release.groups, pd.DataFrame(release.rows, columns=GOLD_COLUMNS), release.silver_version)
    return "released"


def adjustments(
    approved: dict[str, int], current: dict[str, int], closed: list[str], booked_in: str
) -> list[Adjustment]:
    """For each closed month whose current total differs from the approved one, book the difference later."""
    return [
        Adjustment(booked_in=booked_in, for_month=m, amount=current.get(m, 0) - approved.get(m, 0))
        for m in closed
        if current.get(m, 0) != approved.get(m, 0)
    ]
