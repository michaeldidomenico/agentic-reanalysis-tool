"""CLI entrypoint for the reanalysis tool."""
from __future__ import annotations

import json
from pathlib import Path

import click

from reanalysis_tool.access_control import (
    AccessControl,
    State,
)
from reanalysis_tool.archetypes import allocate_archetypes
from reanalysis_tool.config import load_config
from reanalysis_tool.data_inventory import inspect_data
from reanalysis_tool.executor import execute_spec
from reanalysis_tool.plan_parser import parse_plan as run_parse_plan
from reanalysis_tool.spec_generator import generate_spec
from reanalysis_tool.synthesizer import synthesize as run_synthesize
from reanalysis_tool.validator import ValidationResult, validate_spec
from reanalysis_tool.workspace import create_run_workspace


@click.group()
@click.version_option(package_name="reanalysis_tool")
def main() -> None:
    """Agentic Reanalysis Tool."""


@main.command()
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
def init(config_path: str) -> None:
    """Scaffold an example project structure."""
    click.echo("Project initialization is not implemented in the PoC scaffold.")
    raise click.ClickException("Not implemented")


@main.command()
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
def validate_config(config_path: str) -> None:
    """Check config and input structure."""
    config = load_config(config_path)
    click.echo("Config loaded successfully.")
    click.echo(f"Project: {config.project_name}")
    click.echo(f"Plan dir: {config.input.analysis_plan_dir}")
    click.echo(f"Raw data dir: {config.input.raw_data_dir}")


@main.command()
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
def parse_plan(config_path: str) -> None:
    """Stage 1: parse analysis plan into plan_contract.json."""
    config = load_config(config_path)
    access = AccessControl(config)
    access.ensure_state(State.UNINITIALIZED)

    contract = run_parse_plan(config)
    out_path = Path(config.output.ai_work_dir) / "plan_contract.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(contract.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"Wrote plan contract to {out_path}")

    usage_path = Path(config.output.ai_work_dir) / "plan_parse_usage.json"
    if usage_path.exists():
        try:
            usage = json.loads(usage_path.read_text(encoding="utf-8"))
            tokens = usage.get("total_tokens")
            cost = usage.get("cost")
            parts = []
            if tokens is not None:
                parts.append(f"{tokens} tokens")
            if cost is not None:
                parts.append(f"${cost:.4f}")
            if parts:
                click.echo(f"Plan parse LLM usage: {', '.join(parts)}")
        except json.JSONDecodeError:
            pass

    access.transition_to(State.PLAN_PARSED)


@main.command()
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
def inventory(config_path: str) -> None:
    """Stage 2: inspect raw data into data_inventory.json."""
    config = load_config(config_path)
    access = AccessControl(config)
    access.ensure_state(State.PLAN_PARSED)

    inventory = inspect_data(config)
    out_path = Path(config.output.ai_work_dir) / "data_inventory.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(inventory.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"Wrote data inventory to {out_path}")
    access.transition_to(State.DATA_INVENTORIED)


@main.command()
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--n-runs", default=60, show_default=True, type=int)
def run(config_path: str, n_runs: int) -> None:
    """Stage 3: execute isolated analysis runs."""
    config = load_config(config_path)
    access = AccessControl(config)
    access.ensure_state(State.DATA_INVENTORIED)

    plan_path = Path(config.output.ai_work_dir) / "plan_contract.json"
    inventory_path = Path(config.output.ai_work_dir) / "data_inventory.json"
    plan_contract = json.loads(plan_path.read_text(encoding="utf-8"))
    data_inventory = json.loads(inventory_path.read_text(encoding="utf-8"))

    archetype_ids = allocate_archetypes(n_runs)
    for i, archetype_id in enumerate(archetype_ids, start=1):
        run_id = f"run_{i:04d}"
        click.echo(f"Running {run_id} ({archetype_id})...")
        workspace = create_run_workspace(config, run_id)
        spec = {}
        validation = None
        llm_usage = None
        try:
            spec, llm_usage = generate_spec(config, workspace, run_id, archetype_id, plan_contract, data_inventory)
            validation = validate_spec(spec, plan_contract, data_inventory, config, workspace)
            spec_path = workspace / "work" / "analysis_spec.json"
            spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")

            if validation.accepted:
                results = execute_spec(spec, workspace)
                results["validation_status"] = "accepted"
            else:
                results = {
                    "schema_version": "1.0",
                    "run_id": run_id,
                    "validation_status": "rejected",
                    "primary_results": [],
                    "conclusion_classification": "null",
                    "execution_time_seconds": 0.0,
                    "error": "; ".join(validation.errors),
                }
        except Exception as exc: # BLE001 allowed for orchestration
            results = {
                "schema_version": "1.0",
                "run_id": run_id,
                "validation_status": "failed_execution",
                "primary_results": [],
                "conclusion_classification": "null",
                "execution_time_seconds": 0.0,
                "error": str(exc),
            }

        (workspace / "output" / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        audit = {
            "schema_version": "1.0",
            "run_id": run_id,
            "archetype": archetype_id,
            "model": config.llm.model,
            "temperature": config.llm.temperature,
            "prompt_version": "v1.0",
            "plan_contract_hash": plan_contract.get("source_hash", ""),
            "raw_data_manifest_hash": "",
            "files_accessed": spec.get("files_to_use", []) if isinstance(spec, dict) else [],
            "files_written": ["output/results.json"],
            "validation_status": results.get("validation_status", "unknown"),
            "validation_warnings": validation.warnings if isinstance(validation, ValidationResult) else [],
            "timestamp": "2026-10-23T00:00:00",
            "llm_usage": llm_usage,
        }
        (workspace / "output" / "audit_log.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")

    click.echo(f"Completed {n_runs} runs.")
    access.transition_to(State.RUNS_COMPLETE)


@main.command()
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
def synthesize(config_path: str) -> None:
    """Stage 4: aggregate run outputs into final report."""
    config = load_config(config_path)
    access = AccessControl(config)
    access.ensure_state(State.RUNS_COMPLETE)

    summary, report = run_synthesize(config)
    out_dir = Path(config.output.ai_work_dir) / "synthesis"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "final_report.md").write_text(report, encoding="utf-8")
    click.echo(f"Wrote synthesis report to {out_dir / 'final_report.md'}")
    access.transition_to(State.SYNTHESIZED)


@main.command()
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--n-runs", default=60, show_default=True, type=int)
def run_all(config_path: str, n_runs: int) -> None:
    """Execute all stages in order."""
    ctx = click.get_current_context()
    ctx.invoke(parse_plan, config_path=config_path)
    ctx.invoke(inventory, config_path=config_path)
    ctx.invoke(run, config_path=config_path, n_runs=n_runs)
    ctx.invoke(synthesize, config_path=config_path)


if __name__ == "__main__":
    main()
