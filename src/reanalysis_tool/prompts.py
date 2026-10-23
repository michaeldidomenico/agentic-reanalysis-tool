"""Prompt fragments for spec generation."""
from __future__ import annotations

from reanalysis_tool.archetypes import ARCHETYPES


def spec_generation_prompt(plan_contract: dict, data_inventory: dict, archetype_id: str) -> str:
    archetype = ARCHETYPES[archetype_id]
    return f"""You are a research analyst following the {archetype.label} approach.

## Analysis Plan Contract
{plan_contract}

## Data Inventory
{data_inventory}

## Archetype Guidance
{archetype.guidance}

## Task
Produce an analysis specification JSON with exactly these keys:
{{
  "run_id": "string",
  "archetype": "{archetype_id}",
  "plan_contract_path": "input/plan_contract.json",
  "data_inventory_path": "input/data_inventory.json",
  "files_to_use": ["string"],
  "primary_outcome": {{
    "plan_label": "string",
    "mapped_variable": "string",
    "file": "string",
    "sheet": "string",
    "rationale": "string"
  }},
  "treatment_variable": {{
    "mapped_variable": "string",
    "file": "string"
  }},
  "estimand": "string",
  "analytic_population": "string",
  "missing_data_strategy": "complete_case | available_case | explicit_omission",
  "covariates": ["string"],
  "model": "difference_in_means | linear_regression | logistic_regression",
  "standard_errors": "classical | robust | clustered_by_site | clustered_by_site_state",
  "transformations": [],
  "hypothesis_test": "string",
  "assumptions": ["string"],
  "secondary_analyses": []
}}

Rules:
- Use ONLY the plan contract and data inventory provided above.
- Do not reference files outside the workspace input directory.
- Map variables to files and sheets explicitly.
- If any mapping is ambiguous, leave it to the evaluator and note it in assumptions.
- Return ONLY valid JSON. No markdown fences, no commentary.
"""
