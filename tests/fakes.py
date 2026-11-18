"""Independent in-memory storage adapters for shared behavior tests."""

from __future__ import annotations

import pandas as pd

from src.models import GOLD_COLUMNS, GROUP, ORDER_COLUMNS, OrderChange


class MemoryOrders:
    def __init__(self) -> None:
        self.snapshots: list[pd.DataFrame] = []
        self.feeds: list[pd.DataFrame] = []

    def first_load(self, rows: list[dict]) -> int:
        self.snapshots.append(pd.DataFrame(rows, columns=ORDER_COLUMNS))
        self.feeds.append(self.snapshots[0].assign(_change_type="insert", _commit_version=0))
        return 0

    def change(self, change: OrderChange) -> int:
        if not change.updates:
            return self.version()
        rows = self.read()
        selected = rows["order_id"] == change.order_id
        before = rows.loc[selected].copy()
        for column, value in change.updates.items():
            rows.loc[selected, column] = value
        version = self.version() + 1
        self.snapshots.append(rows)
        self.feeds.append(
            pd.concat(
                [
                    before.assign(_change_type="update_preimage", _commit_version=version),
                    rows.loc[selected].assign(_change_type="update_postimage", _commit_version=version),
                ],
                ignore_index=True,
            )
        )
        return version

    def version(self) -> int:
        return len(self.snapshots) - 1

    def read(self, version: int | None = None) -> pd.DataFrame:
        rows = self.snapshots[self.version() if version is None else version]
        return rows.copy(deep=True).sort_values("order_id").reset_index(drop=True)

    def changes(self, start: int, end: int | None = None) -> pd.DataFrame:
        stop = self.version() if end is None else end
        return pd.concat(self.feeds[start : stop + 1], ignore_index=True).copy(deep=True)


class MemoryTotals:
    def __init__(self) -> None:
        self.rows = pd.DataFrame(columns=GOLD_COLUMNS)
        self.released_version = -1

    @staticmethod
    def _validated(rows: pd.DataFrame) -> pd.DataFrame:
        rows = rows[GOLD_COLUMNS].copy(deep=True)
        if rows.duplicated(GROUP).any():
            raise ValueError("Duplicate Gold grain")
        for column in GROUP:
            rows[column] = rows[column].astype("str")
        for column in GOLD_COLUMNS[2:]:
            rows[column] = rows[column].astype("int64")
        return rows.sort_values(GROUP).reset_index(drop=True)

    def create(self, rows: pd.DataFrame, silver_version: int) -> None:
        self.rows = self._validated(rows)
        self.released_version = silver_version

    def read(self) -> pd.DataFrame:
        return self.rows.copy(deep=True)

    def upsert(self, rows: pd.DataFrame) -> None:
        incoming = self._validated(rows)
        keys = set(incoming[GROUP].itertuples(index=False, name=None))
        keep = [key not in keys for key in self.rows[GROUP].itertuples(index=False, name=None)]
        self.rows = self._validated(pd.concat([self.rows.loc[keep], incoming], ignore_index=True))

    def replace_groups(self, groups: frozenset[tuple[str, str]], rows: pd.DataFrame, silver_version: int) -> None:
        incoming = self._validated(rows)
        if not set(incoming[GROUP].itertuples(index=False, name=None)).issubset(groups):
            raise ValueError("Out-of-scope replacement")
        keep = [key not in groups for key in self.rows[GROUP].itertuples(index=False, name=None)]
        self.rows = self._validated(pd.concat([self.rows.loc[keep], incoming], ignore_index=True))
        self.released_version = silver_version

    def last_silver_version(self) -> int:
        return self.released_version
