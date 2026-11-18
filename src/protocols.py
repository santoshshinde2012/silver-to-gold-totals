"""Interfaces the pipeline depends on."""

from __future__ import annotations

from typing import Protocol

import pandas as pd


class OrderTable(Protocol):
    """Silver orders as a Delta table with a change data feed."""

    def version(self) -> int: ...

    def read(self, version: int | None = None) -> pd.DataFrame: ...

    def changes(self, start: int, end: int | None = None) -> pd.DataFrame: ...


class TotalsTable(Protocol):
    """Gold daily totals as a Delta table."""

    def read(self) -> pd.DataFrame: ...

    def upsert(self, rows: pd.DataFrame) -> None: ...

    def replace_groups(self, groups: frozenset[tuple[str, str]], rows: pd.DataFrame, silver_version: int) -> None: ...

    def last_silver_version(self) -> int: ...


class GoldRepair(Protocol):
    """One way of bringing Gold up to date with Silver's changes. Each strategy is one class."""

    @property
    def name(self) -> str: ...

    def apply(self, silver: OrderTable, gold: TotalsTable, start: int, end: int) -> None: ...
