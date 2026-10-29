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

    plan_meta = _load_plan_contract(config)
    data_meta = _load_data_inventory(config)
    svg = _generate_estimates_svg(estimates)
    report = _build_report(summary, config, plan_meta, data_meta, svg)
    return summary, report


def _load_plan_contract(config: Config) -> dict[str, Any]:
    path = Path(config.output.ai_work_dir) / "plan_contract.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _load_data_inventory(config: Config) -> dict[str, Any]:
    path = Path(config.output.ai_work_dir) / "data_inventory.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _generate_estimates_svg(estimates: list[float]) -> str:
    if not estimates:
        return "<p><em>No accepted estimates available to plot.</em></p>"

    width = 640
    height = 320
    margin = 50
    n_bins = min(max(3, len(estimates)), 10)
    min_val = min(estimates)
    max_val = max(estimates)

    if min_val == max_val:
        bins = [min_val - 0.5, min_val + 0.5]
        counts = [len(estimates)]
        n_bins = 1
        bin_width = 1.0
    else:
        bin_width = (max_val - min_val) / n_bins
        bins = [min_val + i * bin_width for i in range(n_bins + 1)]
        counts = [0] * n_bins
        for e in estimates:
            idx = min(int((e - min_val) / bin_width), n_bins - 1)
            counts[idx] += 1

    max_count = max(counts) if counts else 1
    plot_width = width - 2 * margin
    plot_height = height - 2 * margin
    bar_width = plot_width / n_bins

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Estimates distribution histogram">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
    ]

    for i in range(5):
        y = margin + i * plot_height / 4
        parts.append(f'<line x1="{margin}" y1="{y}" x2="{width - margin}" y2="{y}" stroke="#e0e0e0" stroke-width="1"/>')

    for i, count in enumerate(counts):
        bar_height = (count / max_count) * plot_height if max_count > 0 else 0
        x = margin + i * bar_width
        y = margin + plot_height - bar_height
        parts.append(f'<rect x="{x}" y="{y}" width="{max(bar_width - 2, 1)}" height="{bar_height}" fill="#4a90d9" rx="2"/>')
        if count > 0:
            parts.append(f'<text x="{x + bar_width/2}" y="{y - 8}" text-anchor="middle" font-size="12" fill="#333333" font-family="sans-serif">{count}</text>')

    parts.append(f'<line x1="{margin}" y1="{margin + plot_height}" x2="{width - margin}" y2="{margin + plot_height}" stroke="#333333" stroke-width="1"/>')
    parts.append(f'<line x1="{margin}" y1="{margin}" x2="{margin}" y2="{margin + plot_height}" stroke="#333333" stroke-width="1"/>')

    for i in range(n_bins + 1):
        x = margin + i * bar_width
        val = bins[i]
        parts.append(f'<text x="{x}" y="{margin + plot_height + 18}" text-anchor="middle" font-size="10" fill="#333333" font-family="sans-serif">{val:.3f}</text>')

    parts.append(f'<text x="{width/2}" y="{margin - 15}" text-anchor="middle" font-size="13" fill="#333333" font-family="sans-serif" font-weight="bold">Distribution of Accepted Estimates</text>')

    parts.append("</svg>")
    return "\n".join(parts)


def _build_report(summary: dict[str, Any], config: Config, plan_meta: dict[str, Any], data_meta: dict[str, Any], svg: str) -> str:
    plan_source = plan_meta.get("source_file", config.input.analysis_plan_dir)
    plan_id = plan_meta.get("plan_id", "N/A")

    data_files = []
    for f in data_meta.get("files", []):
        path = f.get("path", "")
        if path:
            data_files.append(path)
    if not data_files:
        data_files = [config.input.raw_data_dir]

    data_sources = "\n".join(f"- {Path(p).name}" for p in data_files) if data_files else "- None detected"

    llm_model = config.llm.spec_model or config.llm.model
    temperature = config.llm.temperature

    mean = summary.get("mean_estimate")
    std = summary.get("std_estimate")

    lines = [
        "# Synthesis Report",
        "",
        "## Overview",
        "",
        "The **Agentic Reanalysis Tool** automates reproducible research synthesis by executing multiple isolated analysis runs from a single pre-registered analysis plan and aggregating the results. Each run is executed in an isolated workspace with a randomly assigned researcher archetype to capture analyst uncertainty.",
        "",
        f"- **Project:** {config.project_name}",
        f"- **Analysis plan:** `{plan_source}` (ID: {plan_id})",
        f"- **Source data:**",
        data_sources,
        f"- **LLM:** {llm_model} (temperature: {temperature})",
        f"- **Runs executed:** {summary['total_runs']} ({summary['accepted_runs']} accepted, {summary['rejected_runs']} rejected, {summary['failed_runs']} failed)",
        "",
        "## Estimates Distribution",
        "",
        svg,
        "",
        "## Summary Statistics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
    ]

    if mean is not None:
        lines.append(f"| Mean estimate | {mean:.4f} |")
    else:
        lines.append("| Mean estimate | N/A |")

    if std is not None:
        lines.append(f"| Std estimate | {std:.4f} |")
    else:
        lines.append("| Std estimate | N/A |")

    lines.extend([
        f"| Total LLM tokens | {summary['total_llm_usage']['total_tokens']} |",
        f"| Estimated LLM cost | ${summary['total_llm_usage']['estimated_cost']:.4f} |",
        "",
        "## Rejection Reasons",
        "",
    ])

    if summary["rejection_reasons"]:
        for reason in summary["rejection_reasons"]:
            lines.append(f"- {reason}")
    else:
        lines.append("No rejection reasons.")

    return "\n".join(lines)
