"""Configuration loading and validation."""
from __future__ import annotations

from pathlib import Path

import pydantic
import yaml



class InputConfig(pydantic.BaseModel):
    analysis_plan_dir: str
    raw_data_dir: str
    metadata_dir: str


class OutputConfig(pydantic.BaseModel):
    ai_work_dir: str
    run_isolation: bool = True


class LLMConfig(pydantic.BaseModel):
    provider: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    log_prompts: bool = True
    log_dir: str = "./ai_work/logs"


class ValidationConfig(pydantic.BaseModel):
    reject_plan_contradictions: bool = True
    reject_forbidden_file_access: bool = True
    reject_missing_primary_outcome_mapping: bool = True
    reject_empty_analytic_sample: bool = True
    reject_incompatible_model: bool = True


class ResearcherSimulationConfig(pydantic.BaseModel):
    mode: str = "archetype_stochastic"
    number_of_runs: int = 60
    archetype_sampling: dict = pydantic.Field(default_factory=lambda: {"mode": "equal_allocation"})
    force_diversity: bool = False
    blind_runs: bool = True


class Config(pydantic.BaseModel):
    schema_version: str
    project_name: str
    input: InputConfig
    output: OutputConfig
    researcher_simulation: ResearcherSimulationConfig
    llm: LLMConfig
    validation: ValidationConfig

    model_config = {"extra": "forbid"}


def load_config(config_path: str | Path) -> Config:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        raise ValueError("Config file must contain a YAML mapping.")

    config = Config.model_validate(raw)
    _validate_paths(config)
    return config


def _validate_paths(config: Config) -> None:
    base = Path(".").resolve()
    for name, rel in [
        ("analysis_plan_dir", config.input.analysis_plan_dir),
        ("raw_data_dir", config.input.raw_data_dir),
        ("metadata_dir", config.input.metadata_dir),
        ("ai_work_dir", config.output.ai_work_dir),
        ("log_dir", config.llm.log_dir),
    ]:
        target = (base / rel).resolve()
        if not str(target).startswith(str(base)):
            raise ValueError(f"Config path escapes project root: {name}={rel}")
