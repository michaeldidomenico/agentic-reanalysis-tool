"""Rule-based validation of analysis specs."""
from __future__ import annotations

from pathlib import Path

from reanalysis_tool.config import Config


class ValidationResult:
    def __init__(self, status: str, warnings: list[str], errors: list[str]) -> None:
        self.status = status
        self.warnings = warnings
        self.errors = errors

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"


def validate_spec(
    spec: dict[str, object],
    plan_contract: dict[str, object],
    data_inventory: dict[str, object],
    config: Config,
    workspace: Path,
) -> ValidationResult:
    warnings: list[str] = []
    errors: list[str] = []

    # Plan adherence
    if not spec.get("primary_outcome"):
        errors.append("Missing primary_outcome mapping.")
    if not spec.get("treatment_variable"):
        errors.append("Missing treatment_variable mapping.")
    if not spec.get("files_to_use"):
        errors.append("No files_to_use specified.")

    # Data validity
    allowed_extensions = {".csv", ".xlsx", ".xls", ".parquet"}
    for rel in spec.get("files_to_use", []):
        path = workspace / "input" / rel
        if not path.exists():
            errors.append(f"Referenced file missing in workspace: {rel}")
            continue
        if path.suffix.lower() not in allowed_extensions:
            errors.append(f"Referenced file has forbidden extension: {path.suffix}")

    # Statistical validity
    model = str(spec.get("model", ""))
    outcome_type = _infer_outcome_type(spec, data_inventory)
    if model == "logistic_regression" and outcome_type not in {"binary", "boolean"}:
        warnings.append("Logistic regression selected but outcome may not be binary.")
    if model == "linear_regression" and outcome_type not in {"continuous", "integer", "float"}:
        warnings.append("Linear regression selected but outcome may not be continuous.")

    if errors:
        return ValidationResult(status="rejected", warnings=warnings, errors=errors)
    return ValidationResult(status="accepted", warnings=warnings, errors=errors)


def _infer_outcome_type(spec: dict, data_inventory: dict) -> str:
    mapped = ((spec.get("primary_outcome") or {}).get("mapped_variable") or "").lower()
    for file_info in data_inventory.get("files", []):
        for col in file_info.get("columns", []):
            if col.get("name", "").lower() == mapped:
                return str(col.get("type", "continuous"))
    return "continuous"
