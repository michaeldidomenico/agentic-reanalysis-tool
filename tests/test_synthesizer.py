"""Tests for synthesizer LLM usage aggregation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from reanalysis_tool.config import (
    Config,
    InputConfig,
    LLMConfig,
    OutputConfig,
    ResearcherSimulationConfig,
    ValidationConfig,
)
from reanalysis_tool.synthesizer import synthesize


@pytest.fixture()
def config(tmp_path: Path) -> Config:
    return Config(
        schema_version="1.0",
        project_name="test",
        input=InputConfig(
            analysis_plan_dir=str(tmp_path / "analysis_plan"),
            raw_data_dir=str(tmp_path / "raw_data"),
            metadata_dir=str(tmp_path / "metadata"),
        ),
        output=OutputConfig(ai_work_dir=str(tmp_path / "ai_work")),
        researcher_simulation=ResearcherSimulationConfig(),
        llm=LLMConfig(provider="openrouter", model="mock-model"),
        validation=ValidationConfig(),
    )


def _write_run(tmp_path: Path, run_id: str, status: str, usage: dict | None = None):
    run_dir = tmp_path / "ai_work" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "output").mkdir(parents=True, exist_ok=True)
    results = {
        "schema_version": "1.0",
        "run_id": run_id,
        "validation_status": status,
        "primary_results": [{"estimate": 1.0}] if status == "accepted" else [],
        "conclusion_classification": "null",
        "execution_time_seconds": 1.0,
        "error": "" if status == "accepted" else "bad",
    }
    (run_dir / "output" / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    audit = {
        "schema_version": "1.0",
        "run_id": run_id,
        "archetype": "archetype_0",
        "model": "mock-model",
        "temperature": 0.7,
        "prompt_version": "v1.0",
        "plan_contract_hash": "abc",
        "raw_data_manifest_hash": "",
        "files_accessed": [],
        "files_written": ["output/results.json"],
        "validation_status": status,
        "validation_warnings": [],
        "timestamp": "2026-10-23T00:00:00",
        "llm_usage": usage,
    }
    (run_dir / "output" / "audit_log.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")


class TestSynthesizerUsage:
    def test_aggregates_run_usage(self, tmp_path: Path, config: Config):
        _write_run(tmp_path, "run_0001", "accepted", {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "cost": 0.01})
        _write_run(tmp_path, "run_0002", "rejected", {"prompt_tokens": 200, "completion_tokens": 80, "total_tokens": 280, "cost": 0.02})

        summary, _report = synthesize(config)
        assert summary["total_runs"] == 2
        assert summary["accepted_runs"] == 1
        assert summary["rejected_runs"] == 1
        usage = summary["total_llm_usage"]
        assert usage["prompt_tokens"] == 300
        assert usage["completion_tokens"] == 130
        assert usage["total_tokens"] == 430
        assert usage["estimated_cost"] == 0.03

    def test_aggregates_plan_parse_usage(self, tmp_path: Path, config: Config):
        _write_run(tmp_path, "run_0001", "accepted", None)
        plan_usage = {
            "prompt_tokens": 500,
            "completion_tokens": 200,
            "total_tokens": 700,
            "cost": 0.05,
            "cost_currency": "USD",
            "model": "mock-model",
        }
        (tmp_path / "ai_work" / "plan_parse_usage.json").write_text(
            json.dumps(plan_usage, indent=2), encoding="utf-8"
        )

        summary, _ = synthesize(config)
        usage = summary["total_llm_usage"]
        assert usage["prompt_tokens"] == 500
        assert usage["completion_tokens"] == 200
        assert usage["total_tokens"] == 700
        assert usage["estimated_cost"] == 0.05

    def test_aggregates_plan_and_run_usage_together(self, tmp_path: Path, config: Config):
        _write_run(tmp_path, "run_0001", "accepted", {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "cost": 0.01})
        plan_usage = {
            "prompt_tokens": 500,
            "completion_tokens": 200,
            "total_tokens": 700,
            "cost": 0.05,
            "cost_currency": "USD",
            "model": "mock-model",
        }
        (tmp_path / "ai_work" / "plan_parse_usage.json").write_text(
            json.dumps(plan_usage, indent=2), encoding="utf-8"
        )

        summary, _ = synthesize(config)
        usage = summary["total_llm_usage"]
        assert usage["prompt_tokens"] == 600
        assert usage["completion_tokens"] == 250
        assert usage["total_tokens"] == 850
        assert usage["estimated_cost"] == pytest.approx(0.06)

    def test_handles_missing_usage_gracefully(self, tmp_path: Path, config: Config):
        _write_run(tmp_path, "run_0001", "accepted", None)
        summary, _ = synthesize(config)
        usage = summary["total_llm_usage"]
        assert usage["total_tokens"] == 0
        assert usage["estimated_cost"] == 0.0
