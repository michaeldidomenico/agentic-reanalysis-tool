"""Researcher archetypes and allocation logic."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Archetype:
    id: str
    label: str
    missing_data: str
    covariates: str
    standard_errors: str
    guidance: str


ARCHETYPES: dict[str, Archetype] = {
    "conservative_plan_follower": Archetype(
        id="conservative_plan_follower",
        label="Conservative Plan Follower",
        missing_data="complete_case",
        covariates="none_unless_explicitly_required",
        standard_errors="classical",
        guidance=(
            "Implement the simplest defensible analysis consistent with the plan. "
            "Use complete-case analysis. Do not adjust for covariates unless the plan explicitly requires it. "
            "Use classical standard errors unless the design explicitly requires clustering. "
            "State assumptions; avoid exploratory analysis."
        ),
    ),
    "pragmatic_program_evaluator": Archetype(
        id="pragmatic_program_evaluator",
        label="Pragmatic Program Evaluator",
        missing_data="available_case",
        covariates="basic_adjustment_for_observed_differences",
        standard_errors="clustered_if_design_suggests",
        guidance=(
            "Implement the plan faithfully with practical analytic choices. "
            "Use available-case analysis with justification. "
            "Adjust for baseline covariates if there are observed differences. "
            "Use clustered standard errors if the design suggests clustering. "
            "Include transparent summary statistics."
        ),
    ),
    "frequentist_econometrician": Archetype(
        id="frequentist_econometrician",
        label="Frequentist Econometrician",
        missing_data="available_case_or_model_based",
        covariates="active_adjustment_for_precision",
        standard_errors="robust_or_clustered",
        guidance=(
            "Focus on causal identification and precise estimation. "
            "Actively adjust for covariates to improve precision. "
            "Use robust or clustered standard errors as appropriate. "
            "Clearly distinguish confirmatory from exploratory analyses."
        ),
    ),
}


def allocate_archetypes(n_runs: int) -> list[str]:
    archetype_ids = list(ARCHETYPES.keys())
    if n_runs <= len(archetype_ids):
        return archetype_ids[:n_runs]
    base = [archetype_ids[i % len(archetype_ids)] for i in range(n_runs)]
    return base
