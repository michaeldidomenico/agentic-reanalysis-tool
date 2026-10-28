"""Parse analysis plans from PDF into a structured plan contract."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from pypdf import PdfReader

from reanalysis_tool.config import Config


class PlanContract(BaseModel):
    schema_version: str = "1.0"
    plan_id: str
    source_file: str
    source_hash: str
    primary_outcome: dict[str, str]
    estimand: str
    population: str
    treatment_definition: str
    comparison_definition: str
    primary_method: str
    secondary_outcomes: list[str] = []
    required_analyses: list[str] = []
    constraints: list[str] = []
    binding_commitments: dict[str, str] = {}
    underspecified_elements: list[str] = []
    ambiguities: list[dict[str, str]] = []
    raw_text: str = ""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def _extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            txt = page.extract_text() or ""
            pages.append(txt)
        return "\n".join(pages)
    raise ValueError(f"Unsupported plan format: {path.suffix}")


def _extract_json(text: str) -> str:
    """Pull a JSON object out of likely LLM return patterns.

    Order of preference:
    1. First ```json ... ``` or ``` ... ``` fenced block.
    2. First top-level {...} object in the text.
    3. The stripped raw text as a last resort.
    """
    text = text.strip()
    # 1) Markdown code fence with or without language tag
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if match:
        return match.group(1).strip()
    # 2) First top-level JSON object
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        return match.group(0).strip()
    # 3) Fallback to whatever is left
    return text


def _structure_with_llm(text: str, config: Config) -> dict[str, Any]:
    from openai import OpenAI

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise OSError(
            "OPENROUTER_API_KEY is not set. Set it to use LLM-assisted plan parsing."
        )

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    system = (
        "You are a research methods assistant. Extract a structured analysis plan contract "
        "from the provided text. Return ONLY valid JSON matching the schema: "
        '{"plan_id":"string","primary_outcome":{"label":"string","description":"string"},'
        '"estimand":"intent_to_treat|treatment_on_the_treated|average_treatment_effect|unspecified",'
        '"population":"string","treatment_definition":"string","comparison_definition":"string",'
        '"primary_method":"string","secondary_outcomes":["string"],"required_analyses":["string"],'
        '"constraints":["string"],"binding_commitments":{"primary_outcome":"string","estimand":"string",'
        '"population":"string","treatment_definition":"string","comparison_definition":"string","primary_method":"string"},'
        '"underspecified_elements":["string"],"ambiguities":[{"element":"string","plan_language":"string","resolution":"leave_to_evaluator|require_human_review"}]}. '
        "Use exact plan language where possible. Do not invent details."
    )
    user = f"PLAN TEXT:\n{text}\n\nJSON:"

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=config.llm.model,
                temperature=0.0,
                max_tokens=config.llm.max_tokens,
                messages=[
                    {"role": "system", "content": system if attempt == 0 else "Return ONLY valid JSON. No commentary."},
                    {"role": "user", "content": user},
                ],
            )
            content = response.choices[0].message.content or ""
            content = _extract_json(content)
            return json.loads(content)
        except Exception:
            if attempt == 0:
                continue
            raise
    raise OSError("LLM plan parsing failed after retries.")


def _fallback_contract(text: str, source_file: str, source_hash: str) -> dict[str, Any]:
    return {
        "plan_id": Path(source_file).stem,
        "primary_outcome": {"label": "Unknown", "description": "Extracted from plan text."},
        "estimand": "unspecified",
        "population": "",
        "treatment_definition": "",
        "comparison_definition": "",
        "primary_method": "",
        "secondary_outcomes": [],
        "required_analyses": [],
        "constraints": [],
        "binding_commitments": {},
        "underspecified_elements": ["full plan parsing requires LLM configuration"],
        "ambiguities": [],
    }


def parse_plan(config: Config) -> PlanContract:
    plan_dir = Path(config.input.analysis_plan_dir)
    if not plan_dir.exists() or not plan_dir.is_dir():
        raise FileNotFoundError(f"Analysis plan directory not found: {plan_dir}")

    files = [p for p in plan_dir.iterdir() if p.suffix.lower() == ".pdf"]
    if not files:
        raise FileNotFoundError("No PDF plan files found in analysis_plan_dir.")
    if len(files) > 1:
        raise ValueError(f"Multiple plan files found: {files}. Expected exactly one.")

    plan_path = files[0]
    text = _extract_text(plan_path)
    source_hash = _sha256(plan_path)

    try:
        data = _structure_with_llm(text, config)
    except Exception:  # noqa: BLE001
        data = _fallback_contract(text, str(plan_path), source_hash)

    data["plan_id"] = data.get("plan_id", plan_path.stem)
    data["source_file"] = str(plan_path)
    data["source_hash"] = source_hash

    try:
        return PlanContract.model_validate(data)
    except ValidationError:
        data = _fallback_contract(text, str(plan_path), source_hash)
        data["source_file"] = str(plan_path)
        data["source_hash"] = source_hash
        return PlanContract.model_validate(data)
