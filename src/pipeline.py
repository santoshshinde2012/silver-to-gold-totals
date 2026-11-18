"""Releasing a repair, and closing a month. Depends only on the protocols."""

from __future__ import annotations

import pandas as pd

from .models import Adjustment, Release
from .protocols import OrderTable, TotalsTable
from .totals import full_rebuild, old_and_new_groups, restrict


def build_release(silver: OrderTable, start: int, end: int) -> Release:
    """Read Silver at `end` and compute the groups touched by changes `start..end`."""
    groups = old_and_new_groups(silver.changes(start, end))
    rows = restrict(full_rebuild(silver.read(end)), groups)
    return Release(groups=groups, rows=rows.to_dict("records"), silver_version=end)


def publish(gold: TotalsTable, release: Release, guard: bool) -> str:
    """Replace the release's groups. With the guard, a release older than the last one is refused."""
    if guard and release.silver_version <= gold.last_silver_version():
        return "rejected"
    gold.replace_groups(release.groups, pd.DataFrame(release.rows), release.silver_version)
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
