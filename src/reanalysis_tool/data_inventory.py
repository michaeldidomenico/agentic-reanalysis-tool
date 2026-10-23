"""Inspect raw data files and produce a deterministic data inventory."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel

from reanalysis_tool.config import Config

_ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".parquet", ".delta"}


class ColumnMetadata(BaseModel):
    name: str
    type: str
    missing_rate: float
    unique_values: int
    role_candidates: list[str] = []


class FileInventory(BaseModel):
    path: str
    format: str
    n_rows: int
    n_columns: int
    columns: list[dict[str, Any]]
    sheets: list[str] = []
    duplicate_records: int = 0
    warnings: list[str] = []


class DataInventory(BaseModel):
    schema_version: str = "1.0"
    inventory_id: str
    source_dirs: dict[str, str]
    files: list[dict[str, Any]]
    derived_insights: dict[str, list[str]] = {}


def _detect_role(name: str) -> list[str]:
    lower = name.lower()
    candidates = []
    if any(k in lower for k in ["id", "identifier", "subject", "apartment"]):
        candidates.append("id")
    if any(k in lower for k in ["treat", "arm", "assignment", "group", "random"]):
        candidates.append("treatment")
    if any(k in lower for k in ["outcome", "result", "score", "kwh", "y_", "endline"]):
        candidates.append("outcome")
    if any(k in lower for k in ["covariate", "baseline", "x_", "predictor"]):
        candidates.append("covariate")
    if any(k in lower for k in ["weight", "wt"]):
        candidates.append("weight")
    if any(k in lower for k in ["cluster", "site", "school", "site", "block"]):
        candidates.append("cluster")
    if any(k in lower for k in ["time", "date", "year", "month", "period", "week"]):
        candidates.append("time")
    if not candidates:
        candidates.append("covariate")
    return candidates


def _infer_type(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        return "float"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    return "string"


def _read_file(path: Path) -> tuple[pd.DataFrame, str, list[str]]:
    ext = path.suffix.lower()
    if ext == ".csv":
        df = pd.read_csv(path)
        return df, "csv", []
    elif ext in {".xlsx", ".xls"}:
        xl = pd.ExcelFile(path)
        sheet = xl.sheets[0]
        df = pd.read_excel(path, sheet_name=sheet)
        return df, "xlsx", xl.sheets
    elif ext == ".parquet":
        df = pd.read_parquet(path)
        return df, "parquet", []
    else:
        raise ValueError(f"Unsupported file format: {ext}")


def inspect_data(config: Config) -> DataInventory:
    raw_dir = Path(config.input.raw_data_dir)
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw data directory not found: {raw_dir}")

    files: list[FileInventory] = []
    derived: dict[str, list[str]] = {
        "candidate_id_variables": [],
        "candidate_treatment_variables": [],
        "candidate_outcome_variables": [],
        "candidate_cluster_variables": [],
        "date_like_variables": [],
    }

    for path in sorted(raw_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in _ALLOWED_EXTENSIONS:
            continue

        try:
            df, fmt, sheets = _read_file(path)
        except Exception as exc: # BLE001 allowed for file read errors
            files.append(
                FileInventory(
                    path=str(path),
                    format=path.suffix.lower().lstrip("."),
                    n_rows=0,
                    n_columns=0,
                    columns=[],
                    warnings=[f"Failed to read file: {exc}"],
                )
            )
            continue

        duplicates = int(df.duplicated().sum())
        cols = []
        for col in df.columns:
            series = df[col]
            missing_rate = float(series.isna().mean())
            unique_values = int(series.nunique())
            col_type = _infer_type(series)
            roles = _detect_role(str(col))
            cols.append(
                {
                    "name": str(col),
                    "type": col_type,
                    "missing_rate": round(missing_rate, 4),
                    "unique_values": unique_values,
                    "role_candidates": roles,
                }
            )
            if "id" in roles:
                derived["candidate_id_variables"].append(str(col))
            if "treatment" in roles:
                derived["candidate_treatment_variables"].append(str(col))
            if "outcome" in roles:
                derived["candidate_outcome_variables"].append(str(col))
            if "cluster" in roles:
                derived["candidate_cluster_variables"].append(str(col))
            if "time" in roles:
                derived["date_like_variables"].append(str(col))

        files.append(
            FileInventory(
                path=str(path.relative_to(Path.cwd())),
                format=fmt,
                n_rows=len(df),
                n_columns=len(df.columns),
                columns=cols,
                sheets=sheets,
                duplicate_records=duplicates,
                warnings=[],
            )
        )

    inventory = DataInventory(
        schema_version="1.0",
        inventory_id=raw_dir.name,
        source_dirs={"raw_data": str(raw_dir), "metadata": config.input.metadata_dir},
        files=[f.model_dump() for f in files],
        derived_insights=derived,
    )
    return inventory
