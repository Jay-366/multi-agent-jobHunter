"""Export — derived views of the tracker into data/outputs/ (ARCHITECTURE §8).

Exports are a *derived* layer (gitignored); the markdown files stay canonical. CSV and
JSON use only the standard library. XLSX is emitted too if openpyxl happens to be
installed, but it is optional — CSV is always produced.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from src.services.tracker import Tracker

_FIELDS = ["date", "company", "role", "score", "status", "report"]


def csv_bytes(data_dir: str | Path = "data") -> bytes:
    """Return the tracker as CSV bytes (for in-browser download, no disk write)."""
    rows = Tracker(data_dir)._load_rows()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_FIELDS)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in _FIELDS})
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel reads UTF-8 correctly


def json_bytes(data_dir: str | Path = "data") -> bytes:
    """Return the tracker as JSON bytes (for in-browser download, no disk write)."""
    rows = Tracker(data_dir)._load_rows()
    return json.dumps(rows, indent=2).encode("utf-8")


def export_csv(data_dir: str | Path = "data", out_path: str | Path | None = None) -> Path:
    rows = Tracker(data_dir)._load_rows()
    out = Path(out_path) if out_path else Path(data_dir) / "outputs" / "applications.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in _FIELDS})
    return out


def export_json(data_dir: str | Path = "data", out_path: str | Path | None = None) -> Path:
    rows = Tracker(data_dir)._load_rows()
    out = Path(out_path) if out_path else Path(data_dir) / "outputs" / "applications.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return out
