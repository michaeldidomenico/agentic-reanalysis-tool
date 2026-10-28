"""Generate analysis specs from plan contract, data inventory, and archetype."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI

from reanalysis_tool.config import Config
from reanalysis_tool.prompts import spec_generation_prompt


def generate_spec(
    config: Config,
    workspace: Path,
    run_id: str,
    archetype_id: str,
    plan_contract: dict[str, Any],
    data_inventory: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    spec: dict[str, Any] = {}
    usage: dict[str, Any] | None = None
    try:
        prompt = spec_generation_prompt(plan_contract, data_inventory, archetype_id)

        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise OSError(
                "OPENROUTER_API_KEY is not set. Cannot generate analysis spec."
            )

        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )

        model = config.llm.spec_model or config.llm.model
        response = client.chat.completions.create(
            model=model,
            temperature=config.llm.temperature,
            max_tokens=config.llm.max_tokens,
            messages=[
                {"role": "system", "content": "You are a research methods assistant. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
        )
        raw_usage = response.usage or {}
        if isinstance(raw_usage, dict):
            usage = {
                "prompt_tokens": raw_usage.get("prompt_tokens", 0) or 0,
                "completion_tokens": raw_usage.get("completion_tokens", 0) or 0,
                "total_tokens": raw_usage.get("total_tokens", 0) or 0,
                "cost": raw_usage.get("cost", 0.0) or 0.0,
                "cost_currency": "USD",
                "model": model,
            }
        else:
            usage = {
                "prompt_tokens": getattr(raw_usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(raw_usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(raw_usage, "total_tokens", 0) or 0,
                "cost": getattr(raw_usage, "cost", 0.0) or 0.0,
                "cost_currency": "USD",
                "model": model,
            }
        content = response.choices[0].message.content or "{}"
        content = content.strip()
        if content.startswith("```"):
            content = "\n".join(content.splitlines()[1:])
        if content.endswith("```"):
            content = "\n".join(content.splitlines()[:-1])

        try:
            spec = json.loads(content.strip())
        except json.JSONDecodeError:
            spec = {}
    except Exception: # BLE001 allowed for LLM fallback
        spec = {}

    spec.setdefault("run_id", run_id)
    spec.setdefault("archetype", archetype_id)
    spec = _normalize_paths(spec, workspace)
    return _apply_fallback(spec, plan_contract, data_inventory, workspace), usage


def _normalize_paths(spec: dict[str, Any], workspace: Path) -> dict[str, Any]:
    input_dir = workspace / "input"
    known_files = {p.name: str(p.relative_to(input_dir)) for p in input_dir.rglob("*") if p.is_file()}

    def normalize(value: Any) -> Any:
        if isinstance(value, str):
            name = Path(value).name
            return known_files.get(name, value)
        if isinstance(value, dict):
            return {k: normalize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [normalize(v) for v in value]
        return value

    return normalize(spec)


def _apply_fallback(
    spec: dict[str, Any],
    plan_contract: dict[str, Any],
    data_inventory: dict[str, Any],
    workspace: Path,
) -> dict[str, Any]:
    files = _available_files(workspace)
    data_files = [f for f in files if f["suffix"] in {".csv", ".xlsx", ".xls", ".parquet"}]
    primary_outcome = spec.get("primary_outcome") or {}
    treatment_variable = spec.get("treatment_variable") or {}

    if not primary_outcome.get("mapped_variable"):
        primary_outcome = _fallback_primary_outcome(plan_contract, data_inventory, data_files)
        spec["primary_outcome"] = primary_outcome

    if not treatment_variable.get("mapped_variable"):
        treatment_variable = _fallback_treatment_variable(data_inventory, data_files)
        spec["treatment_variable"] = treatment_variable

    spec.setdefault("files_to_use", _fallback_files(data_files, primary_outcome, treatment_variable))
    spec.setdefault("estimand", _first(plan_contract.get("estimand"), "intent_to_treat"))
    spec.setdefault("analytic_population", _first(plan_contract.get("population"), "All units with nonmissing outcomes"))
    spec.setdefault("missing_data_strategy", "complete_case")
    spec.setdefault("covariates", [])
    spec.setdefault("model", "difference_in_means")
    spec.setdefault("standard_errors", "classical")
    spec.setdefault("transformations", [])
    spec.setdefault("hypothesis_test", "Two-sided test of no treatment effect")
    spec.setdefault("assumptions", [])
    spec.setdefault("secondary_analyses", [])
    return spec


def _first(value: Any, default: Any) -> Any:
    return value if value else default


def _available_files(workspace: Path) -> list[dict[str, Any]]:
    input_dir = workspace / "input"
    files = []
    for path in sorted(input_dir.rglob("*")):
        if path.is_file():
            files.append({
                "path": str(path.relative_to(input_dir)),
                "name": path.name,
                "suffix": path.suffix.lower(),
            })
    return files


def _fallback_primary_outcome(
    plan_contract: dict[str, Any],
    data_inventory: dict[str, Any],
    data_files: list[dict[str, Any]],
) -> dict[str, Any]:
    label = plan_contract.get("primary_outcome", {}).get("label", "Primary outcome")
    candidates = [
        col.get("name")
        for f in data_inventory.get("files", [])
        for col in f.get("columns", [])
        if any(role == "outcome" for role in col.get("role_candidates", []))
    ]
    mapped = candidates[0] if candidates else ""
    file_path = data_files[0]["path"] if data_files else ""
    return {
        "plan_label": label,
        "mapped_variable": mapped,
        "file": file_path,
        "sheet": "",
        "rationale": "Selected first outcome-like variable detected in data inventory.",
    }


def _fallback_treatment_variable(
    data_inventory: dict[str, Any],
    data_files: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates = [
        col.get("name")
        for f in data_inventory.get("files", [])
        for col in f.get("columns", [])
        if any(role == "treatment" for role in col.get("role_candidates", []))
    ]
    mapped = candidates[0] if candidates else ""
    file_path = data_files[0]["path"] if data_files else ""
    return {
        "mapped_variable": mapped,
        "file": file_path,
    }


def _fallback_files(
    data_files: list[dict[str, Any]],
    primary_outcome: dict[str, Any],
    treatment_variable: dict[str, Any],
) -> list[str]:
    return [f["path"] for f in data_files]
