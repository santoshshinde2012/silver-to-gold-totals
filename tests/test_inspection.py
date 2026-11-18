"""Evidence exports use real table snapshots and never rewrite the source lake."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pytest
from deltalake import write_deltalake

from src.inspection import export_report, inspect_lake
from src.scenario import run


def _files(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_report_reconciles_stage_snapshots_and_preserves_lake(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    run(lake)
    before = _files(lake)
    output = tmp_path / "report"
    output.mkdir()
    (output / "keep.txt").write_text("keep", encoding="utf-8")
    snapshot = export_report(lake, output)
    assert _files(lake) == before
    assert (output / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert json.loads((output / "tables.json").read_text(encoding="utf-8")) == json.loads(json.dumps(snapshot))
    assert snapshot["references"]["latest"]["silver_version"] == 4
    assert sum(r["net_amount"] for r in snapshot["references"]["latest"]["records"]) == 365
    checks = {c["table"]: c for c in snapshot["checks"]}
    correct = checks["gold_old_and_new_groups_replace"]
    assert correct["reference_silver_version"] == 2
    assert correct["matches_full_rebuild"]
    assert not checks["gold_new_groups_upsert"]["matches_full_rebuild"]
    assert checks["gold_race_guard_true"]["reference_silver_version"] == 3
    assert checks["gold_race_guard_true"]["matches_full_rebuild"]
    assert not checks["gold_race_guard_false"]["matches_full_rebuild"]
    html = (output / "index.html").read_text(encoding="utf-8")
    assert "each stage has its own baseline" in html
    assert "365" in html


def test_unavailable_historical_version_is_reported(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    run(lake)
    snapshot = inspect_lake(lake, repair_version=999)
    assert not snapshot["references"]["repair"]["available"]
    assert not snapshot["checks"][0]["available"]
    assert snapshot["references"]["race"]["available"]


def test_external_schema_is_exported_without_business_rule_mapping(tmp_path: Path) -> None:
    lake = tmp_path / "external"
    write_deltalake(
        str(lake / "silver_orders"),
        pa.Table.from_pylist([{"order_id": 1, "order_date": "2026-11-01", "status": "canceled"}]),
    )
    write_deltalake(str(lake / "gold<&"), pa.Table.from_pylist([{"orders": 1}]))
    before = _files(lake)
    snapshot = export_report(lake, tmp_path / "report")
    assert _files(lake) == before
    assert snapshot["schema"] == "external"
    assert snapshot["checks"] == []
    assert snapshot["tables"]["silver_orders"]["records"] == [
        {"order_id": 1, "order_date": "2026-11-01", "status": "canceled"}
    ]
    document = (tmp_path / "report" / "index.html").read_text(encoding="utf-8")
    assert "different schema" in document
    assert "gold&lt;&amp;" in document
    assert "gold<&" not in document


def test_missing_lake_does_not_create_evidence(tmp_path: Path) -> None:
    output = tmp_path / "report"
    with pytest.raises(ValueError, match="does not exist"):
        export_report(tmp_path / "missing", output)
    assert not output.exists()


def test_output_cannot_be_inside_lake(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    lake.mkdir()
    output = lake / "report"
    with pytest.raises(ValueError, match="outside the source lake"):
        export_report(lake, output)
    assert not output.exists()
