"""Small storage capabilities used by the domain; adapters supply their implementation."""

from __future__ import annotations

from typing import Protocol

import pandas as pd


class OrderReader(Protocol):
    """Versioned order snapshots and inclusive change-feed ranges."""

    def read(self, version: int | None = None) -> pd.DataFrame: ...

    def changes(self, start: int, end: int | None = None) -> pd.DataFrame: ...


class OrderTable(OrderReader, Protocol):
    """Order reader with a discoverable current version."""

    def version(self) -> int: ...


class TotalsReader(Protocol):
    """Read one row per (business date, region)."""

    def read(self) -> pd.DataFrame: ...


class TotalsUpsert(Protocol):
    """Insert or update supplied groups, retaining groups absent from the input."""

    def upsert(self, rows: pd.DataFrame) -> None: ...


class GroupReplacement(Protocol):
    """Atomically replace exactly the scope; omitted groups disappear, outside rows are rejected."""

    def replace_groups(self, groups: frozenset[tuple[str, str]], rows: pd.DataFrame, silver_version: int) -> None: ...


class ReleaseHistory(Protocol):
    """The input version recorded by the most recent versioned write, or -1 if none exists."""

    def last_silver_version(self) -> int: ...


class ArithmeticStore(TotalsReader, GroupReplacement, Protocol):
    """Capabilities needed by the changed-row arithmetic experiment."""


class ReleaseStore(GroupReplacement, ReleaseHistory, Protocol):
    """Capabilities needed by the release publisher; the check and write are separate operations."""


class TotalsTable(TotalsReader, TotalsUpsert, ReleaseStore, Protocol):
    """Composite store for the comparison harness; consumers use narrower capabilities."""


class GoldRepair(Protocol):
    """An experiment invoked by the comparison harness, not a guarantee of correct totals.

    Deliberately incorrect candidates satisfy this invocation contract. Their business
    correctness is assessed separately against the full-rebuild oracle.
    """

    @property
    def name(self) -> str: ...

    def apply(self, silver: OrderReader, gold: TotalsTable, start: int, end: int) -> None: ...
