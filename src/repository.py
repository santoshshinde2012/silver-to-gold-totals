"""Silver orders and Gold totals as local Delta tables (open-source `deltalake`)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
from deltalake import CommitProperties, DeltaTable, write_deltalake

from .models import GOLD_COLUMNS, GROUP, ORDER_COLUMNS, OrderChange
from .totals import groups_of, tidy

ORDERS = pa.schema(
    [
        ("order_id", pa.int64()),
        ("business_date", pa.string()),
        ("region", pa.string()),
        ("customer", pa.string()),
        ("amount", pa.int64()),
        ("status", pa.string()),
    ]
)
TOTALS = pa.schema(
    [
        ("business_date", pa.string()),
        ("region", pa.string()),
        ("net_amount", pa.int64()),
        ("order_count", pa.int64()),
        ("customers", pa.int64()),
    ]
)


def _sql_string(value: str) -> str:
    """Quote a SQL string literal, including embedded apostrophes."""
    return "'" + value.replace("'", "''") + "'"


def group_predicate(groups: frozenset[tuple[str, str]]) -> str:
    parts = [f"(business_date = {_sql_string(d)} AND region = {_sql_string(r)})" for d, r in sorted(groups)]
    return " OR ".join(parts) if parts else "false"


class SilverOrders:
    """The latest accepted state of each order. Every change is one commit."""

    def __init__(self, root: Path) -> None:
        self.path = str(root / "silver_orders")

    def first_load(self, rows: list[dict]) -> int:
        write_deltalake(
            self.path, pa.Table.from_pylist(rows, schema=ORDERS), configuration={"delta.enableChangeDataFeed": "true"}
        )
        return self.version()

    def change(self, c: OrderChange) -> int:
        if type(c.order_id) is not int:
            raise ValueError("order_id must be an integer")
        for column, value in c.updates.items():
            if column not in ORDER_COLUMNS or column == "order_id":
                raise ValueError(f"Cannot update order column: {column}")
            expected = int if column == "amount" else str
            if type(value) is not expected:
                raise ValueError(f"{column} must be {expected.__name__}")
        if c.updates:
            # delta-rs 1.6.6's new_values also formats strings without escaping.
            # Validate columns/types above and build literals explicitly instead.
            updates = {
                key: _sql_string(value) if isinstance(value, str) else str(value) for key, value in c.updates.items()
            }
            DeltaTable(self.path).update(predicate=f"order_id = {c.order_id}", updates=updates)
        return self.version()

    def version(self) -> int:
        return DeltaTable(self.path).version()

    def read(self, version: int | None = None) -> pd.DataFrame:
        df = DeltaTable(self.path, version=version).to_pandas()[ORDER_COLUMNS]
        return df.sort_values("order_id").reset_index(drop=True)

    def changes(self, start: int, end: int | None = None) -> pd.DataFrame:
        end = self.version() if end is None else end
        feed = pa.table(DeltaTable(self.path).load_cdf(starting_version=start, ending_version=end).read_all())
        order = {"update_preimage": 0, "update_postimage": 1, "delete": 2, "insert": 3}
        df = feed.to_pandas()
        df["_order"] = df["_change_type"].map(order)
        return df.sort_values(["_commit_version", "order_id", "_order"]).drop(columns="_order").reset_index(drop=True)


class GoldTotals:
    """Daily totals. Each release records the Silver version it read, in the commit metadata."""

    def __init__(self, root: Path, name: str = "gold_daily_totals") -> None:
        self.path = str(root / name)

    def create(self, rows: pd.DataFrame, silver_version: int) -> None:
        write_deltalake(self.path, self._arrow(rows), mode="overwrite", commit_properties=self._meta(silver_version))

    def read(self) -> pd.DataFrame:
        return tidy(DeltaTable(self.path).to_pandas())

    def upsert(self, rows: pd.DataFrame) -> None:
        """Update groups that are present in `rows` and insert new ones. Nothing is removed."""
        if rows.empty:
            return
        cond = " AND ".join(f"t.{c} = s.{c}" for c in GROUP)
        (
            DeltaTable(self.path)
            .merge(self._arrow(rows), predicate=cond, source_alias="s", target_alias="t")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute()
        )

    def replace_groups(self, groups: frozenset[tuple[str, str]], rows: pd.DataFrame, silver_version: int) -> None:
        """Replace every row in `groups` in one commit. A group missing from `rows` is removed."""
        if not groups_of(rows).issubset(groups):
            raise ValueError("Replacement rows must belong to the requested groups")
        write_deltalake(
            self.path,
            self._arrow(rows),
            mode="overwrite",
            predicate=group_predicate(groups),
            commit_properties=self._meta(silver_version),
        )

    def last_silver_version(self) -> int:
        for commit in DeltaTable(self.path).history():
            if "silver_version" in commit:
                return int(commit["silver_version"])
        return -1

    @staticmethod
    def _arrow(rows: pd.DataFrame) -> pa.Table:
        if rows.duplicated(GROUP).any():
            raise ValueError("Gold must contain at most one row per business date and region")
        return pa.Table.from_pandas(rows[GOLD_COLUMNS].reset_index(drop=True), schema=TOTALS, preserve_index=False)

    @staticmethod
    def _meta(silver_version: int) -> CommitProperties:
        return CommitProperties(custom_metadata={"silver_version": json.dumps(silver_version)})
