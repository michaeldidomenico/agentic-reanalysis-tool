"""Tests for plan_parser JSON extraction and fallback behavior."""
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
from reanalysis_tool.plan_parser import (
    _extract_json,
    _fallback_contract,
    _structure_with_llm,
    parse_plan,
)


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


class TestExtractJson:
    def test_clean_json(self):
        assert _extract_json('{"a": 1}') == '{"a": 1}'

    def test_json_with_leading_and_trailing_whitespace(self):
        assert _extract_json('  \n{"a": 1}\n  ') == '{"a": 1}'

    def test_json_in_fenced_block_with_language_tag(self):
        raw = 'Here you go:\n```json\n{"a": 1}\n```'
        assert _extract_json(raw) == '{"a": 1}'

    def test_json_in_fenced_block_without_language_tag(self):
        raw = '```\n{"a": 1}\n```'
        assert _extract_json(raw) == '{"a": 1}'

    def test_trailing_text_after_closing_fence(self):
        raw = '{"a": 1}\n```\n\nHope this helps!'
        assert _extract_json(raw) == '{"a": 1}'

    def test_text_before_and_after_fenced_block(self):
        raw = 'Some intro\n```json\n{"a": 1}\n```\nOutro text'
        assert _extract_json(raw) == '{"a": 1}'

    def test_first_object_when_no_fences(self):
        raw = 'Sure thing: {"a": 1} and more text'
        assert _extract_json(raw) == '{"a": 1}'

    def test_nested_objects_with_fence(self):
        raw = '```json\n{"x": {"y": 1}}\n```'
        assert _extract_json(raw) == '{"x": {"y": 1}}'

    def test_plain_json_returns_unchanged(self):
        payload = '{"key": "value", "nested": {"a": 1}}'
        assert _extract_json(payload) == payload

    def test_no_json_falls_back_to_text(self):
        raw = "No JSON here, just prose."
        assert _extract_json(raw) == "No JSON here, just prose."


class TestFallbackContract:
    def test_uses_pdf_stem_as_plan_id(self):
        result = _fallback_contract("text", "/path/to/my_plan.pdf", "sha256:abc")
        assert result["plan_id"] == "my_plan"

    def test_has_expected_defaults(self):
        result = _fallback_contract("some text", "test.pdf", "sha256:123")
        assert result["estimand"] == "unspecified"
        assert result["primary_outcome"] == {"label": "Unknown", "description": "Extracted from plan text."}
        assert result["underspecified_elements"] == ["full plan parsing requires LLM configuration"]
        assert "raw_text" not in result

    def test_no_raw_text_in_fallback(self):
        result = _fallback_contract("sensitive plan text", "test.pdf", "sha256:123")
        assert "raw_text" not in result


class TestStructureWithLlm:
    def _make_response(self, content: str):
        response = MagicMock()
        response.choices[0].message.content = content
        return response

    def test_successful_json_extraction(self, config):
        client = MagicMock()
        client.chat.completions.create.return_value = self._make_response(
            '```json\n{"plan_id": "p1", "primary_outcome": {"label": "x", "description": "y"}, "estimand": "intent_to_treat", "population": "pop", "treatment_definition": "t", "comparison_definition": "c", "primary_method": "m"}\n```'
        )
        with patch("openai.OpenAI", return_value=client):
            result = _structure_with_llm("plan text", config)
        assert result["plan_id"] == "p1"
        assert result["estimand"] == "intent_to_treat"

    def test_trailing_text_after_fence(self, config):
        client = MagicMock()
        client.chat.completions.create.return_value = self._make_response(
            '{"plan_id": "p1", "primary_outcome": {"label": "x", "description": "y"}, "estimand": "intent_to_treat", "population": "pop", "treatment_definition": "t", "comparison_definition": "c", "primary_method": "m"}\n```\n\nLet me know if you need anything else.'
        )
        with patch("openai.OpenAI", return_value=client):
            result = _structure_with_llm("plan text", config)
        assert result["plan_id"] == "p1"

    def test_retry_on_first_malformed_response(self, config):
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            self._make_response("This is not JSON."),
            self._make_response('{"plan_id": "p1", "primary_outcome": {"label": "x", "description": "y"}, "estimand": "intent_to_treat", "population": "pop", "treatment_definition": "t", "comparison_definition": "c", "primary_method": "m"}'),
        ]
        with patch("openai.OpenAI", return_value=client):
            result = _structure_with_llm("plan text", config)
        assert result["plan_id"] == "p1"
        assert client.chat.completions.create.call_count == 2

    def test_raises_after_two_failures(self, config):
        client = MagicMock()
        client.chat.completions.create.return_value = self._make_response("not json")
        with patch("openai.OpenAI", return_value=client), pytest.raises(Exception):  # noqa: B017
            _structure_with_llm("plan text", config)

    def test_raises_when_api_key_missing(self, config):
        with patch.dict("os.environ", {}, clear=True), pytest.raises(
            OSError, match="OPENROUTER_API_KEY is not set"
        ):
            _structure_with_llm("plan text", config)


class TestParsePlan:
    def test_returns_fallback_when_llm_fails(self, config):
        with patch("reanalysis_tool.plan_parser._structure_with_llm", side_effect=OSError("boom")):
            contract = parse_plan(config)
        assert contract.plan_id == "1808-energy-use-feedback"
        assert contract.estimand == "unspecified"
        assert contract.source_file.endswith("1808-energy-use-feedback.pdf")
        assert contract.source_hash.startswith("sha256:")

    def test_validates_malformed_llm_output_to_fallback(self, config):
        bad_data = {"plan_id": "p1"}
        with patch("reanalysis_tool.plan_parser._structure_with_llm", return_value=bad_data):
            contract = parse_plan(config)
        assert contract.plan_id == "1808-energy-use-feedback"
        assert contract.estimand == "unspecified"
