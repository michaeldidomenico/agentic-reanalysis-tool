"""Aggregate run results into a synthesis report."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reanalysis_tool.config import Config


def synthesize(config: Config) -> tuple[dict[str, Any], str]:
    runs_root = Path(config.output.ai_work_dir) / "runs"
    if not runs_root.exists():
        raise FileNotFoundError("No runs directory found. Run the pipeline before synthesis.")

    results = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_tokens = 0
    total_cost = 0.0

    for run_dir in sorted(runs_root.iterdir()):
        if not run_dir.is_dir():
            continue
        results_path = run_dir / "output" / "results.json"
        if not results_path.exists():
            continue
        try:
            data = json.loads(results_path.read_text(encoding="utf-8"))
            data["_run_dir"] = run_dir.name
            results.append(data)
        except json.JSONDecodeError:
            continue

        audit_path = run_dir / "output" / "audit_log.json"
        if audit_path.exists():
            try:
                audit = json.loads(audit_path.read_text(encoding="utf-8"))
                usage = audit.get("llm_usage") or {}
                total_prompt_tokens += usage.get("prompt_tokens", 0)
                total_completion_tokens += usage.get("completion_tokens", 0)
                total_tokens += usage.get("total_tokens", 0)
                total_cost += usage.get("cost", 0.0)
            except json.JSONDecodeError:
                continue

    plan_usage_path = Path(config.output.ai_work_dir) / "plan_parse_usage.json"
    if plan_usage_path.exists():
        try:
            plan_usage = json.loads(plan_usage_path.read_text(encoding="utf-8"))
            if isinstance(plan_usage, dict):
                total_prompt_tokens += plan_usage.get("prompt_tokens", 0)
                total_completion_tokens += plan_usage.get("completion_tokens", 0)
                total_tokens += plan_usage.get("total_tokens", 0)
                total_cost += plan_usage.get("cost", 0.0)
        except json.JSONDecodeError:
            pass

    accepted = [r for r in results if r.get("validation_status") == "accepted"]
    rejected = [r for r in results if r.get("validation_status") == "rejected"]
    failed = [r for r in results if r.get("validation_status") == "failed_execution"]

    estimates = [r["primary_results"][0]["estimate"] for r in accepted if r.get("primary_results")]
    mean_estimate = sum(estimates) / len(estimates) if estimates else None
    std_estimate = (
        sum((e - mean_estimate) ** 2 for e in estimates) / len(estimates)
    ) ** 0.5 if estimates else None

    summary = {
        "schema_version": "1.0",
        "total_runs": len(results),
        "accepted_runs": len(accepted),
        "rejected_runs": len(rejected),
        "failed_runs": len(failed),
        "rejection_reasons": [r.get("error", "unknown") for r in rejected + failed],
        "estimates": estimates,
        "mean_estimate": mean_estimate,
        "std_estimate": std_estimate,
        "total_llm_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "estimated_cost": total_cost,
            "currency": "USD",
        },
    }

    lines = [
        "# Synthesis Report",
        f"- Total runs: {summary['total_runs']}",
        f"- Accepted: {summary['accepted_runs']}",
        f"- Rejected: {summary['rejected_runs']}",
        f"- Failed: {summary['failed_runs']}",
    ]
    if estimates:
        lines.append(f"- Mean estimate: {summary['mean_estimate']:.4f}")
        lines.append(f"- Std estimate: {summary['std_estimate']:.4f}")
    usage = summary.get("total_llm_usage", {})
    if usage.get("total_tokens"):
        lines.append(f"- Total LLM tokens: {usage['total_tokens']}")
    if usage.get("estimated_cost"):
        lines.append(f"- Estimated LLM cost: ${usage['estimated_cost']:.4f}")
    if summary["rejection_reasons"]:
        lines.append("## Rejection Reasons")
        for reason in summary["rejection_reasons"]:
            lines.append(f"- {reason}")

    report = "\n".join(lines)
    return summary, report
