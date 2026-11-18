"""Four ways of bringing Gold up to date after Silver changed. Each one is a class."""

from __future__ import annotations

import pandas as pd

from .models import GOLD_COLUMNS, GROUP
from .protocols import OrderTable, TotalsTable
from .totals import full_rebuild, groups_of, new_groups, old_and_new_groups, restrict, tidy


class NewGroupsUpsert:
    """Recompute the groups the new rows name, then upsert them."""

    name = "new groups, upsert"

    def apply(self, silver: OrderTable, gold: TotalsTable, start: int, end: int) -> None:
        groups = new_groups(silver.changes(start, end))
        gold.upsert(restrict(full_rebuild(silver.read(end)), groups))


class OldAndNewUpsert:
    """Recompute the groups the old and new rows name, then upsert them."""

    name = "old and new groups, upsert"

    def apply(self, silver: OrderTable, gold: TotalsTable, start: int, end: int) -> None:
        groups = old_and_new_groups(silver.changes(start, end))
        gold.upsert(restrict(full_rebuild(silver.read(end)), groups))


class ReplaceAffectedGroups:
    """Recompute the groups the old and new rows name, then replace exactly those groups."""

    name = "old and new groups, replace"

    def apply(self, silver: OrderTable, gold: TotalsTable, start: int, end: int) -> None:
        groups = old_and_new_groups(silver.changes(start, end))
        gold.replace_groups(groups, restrict(full_rebuild(silver.read(end)), groups), end)


class ChangedRowArithmetic:
    """Add each new row's contribution and subtract each old row's, without reading the group again."""

    name = "add and subtract changed rows"

    def apply(self, silver: OrderTable, gold: TotalsTable, start: int, end: int) -> None:
        feed = silver.changes(start, end)
        feed = feed[feed["status"] == "accepted"]
        sign = feed["_change_type"].map({"insert": 1, "update_postimage": 1, "update_preimage": -1, "delete": -1})
        delta = (
            feed.assign(net_amount=feed["amount"] * sign, order_count=sign, customers=sign)
            .groupby(GROUP, as_index=False)[["net_amount", "order_count", "customers"]]
            .sum()
        )
        current = gold.read()
        merged = pd.concat([current, delta]).groupby(GROUP, as_index=False)[GOLD_COLUMNS[2:]].sum()
        groups = groups_of(delta)
        gold.replace_groups(groups, tidy(restrict(merged, groups)), end)
