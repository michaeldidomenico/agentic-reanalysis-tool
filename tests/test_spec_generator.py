"""Tests for spec_generator LLM usage tracking."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from reanalysis_tool.config import (
    Config,
    InputConfig,
    LLMConfig,
    OutputConfig,
    ResearcherSimulationConfig,
    ValidationConfig,
)
from reanalysis_tool.spec_generator import generate_spec


@pytest.fixture()
def config() -> Config:
    return Config(
        schema_version="1.0",
        project_name="test",
        input=InputConfig(
            analysis_plan_dir="examples/demo_project/input/analysis_plan",
            raw_data_dir="examples/demo_project/input/raw_data",
            metadata_dir="examples/demo_project/input/metadata",
        ),
        output=OutputConfig(ai_work_dir="/tmp/ai_work_test"),
        researcher_simulation=ResearcherSimulationConfig(),
        llm=LLMConfig(provider="openrouter", model="mock-model"),
        validation=ValidationConfig(),
    )


def _make_response(content: str, usage: dict | None = None):
    response = MagicMock()
    response.choices[0].message.content = content
    if usage is None:
        usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "cost": 0.01}
    response.usage = usage
    return response


class TestGenerateSpecUsage:
    def test_returns_usage_with_tokens(self, tmp_path, config):
        client = MagicMock()
        client.chat.completions.create.return_value = _make_response(
            '{"run_id": "run_0001", "primary_outcome": {"mapped_variable": "y"}, "treatment_variable": {"mapped_variable": "t"}, "files_to_use": ["data.csv"], "model": "difference_in_means"}'
        )
        with patch("reanalysis_tool.spec_generator.OpenAI", return_value=client):
            spec, usage = generate_spec(
                config,
                tmp_path,
                "run_0001",
                "conservative_plan_follower",
                {"estimand": "intent_to_treat", "population": "pop", "primary_outcome": {"label": "x"}},
                {"files": []},
            )
        assert spec["run_id"] == "run_0001"
        assert usage["prompt_tokens"] == 100
        assert usage["completion_tokens"] == 50
        assert usage["total_tokens"] == 150
        assert usage["cost"] == 0.01
        assert usage["model"] == "mock-model"

    def test_returns_none_usage_on_fallback(self, tmp_path, config):
        with patch("reanalysis_tool.spec_generator.OpenAI", side_effect=OSError("no key")):
            spec, usage = generate_spec(
                config,
                tmp_path,
                "run_0001",
                "conservative_plan_follower",
                {"estimand": "intent_to_treat", "population": "pop", "primary_outcome": {"label": "x"}},
                {"files": []},
            )
        assert spec["run_id"] == "run_0001"
        assert usage is None

    def test_returns_usage_even_on_malformed_json(self, tmp_path, config):
        client = MagicMock()
        client.chat.completions.create.return_value = _make_response("not json")
        with patch("reanalysis_tool.spec_generator.OpenAI", return_value=client):
            spec, usage = generate_spec(
                config,
                tmp_path,
                "run_0001",
                "conservative_plan_follower",
                {"estimand": "intent_to_treat", "population": "pop", "primary_outcome": {"label": "x"}},
                {"files": []},
            )
        assert spec["run_id"] == "run_0001"
        assert usage is not None
        assert usage["total_tokens"] == 150
