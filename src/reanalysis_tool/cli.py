"""CLI entrypoint for the reanalysis tool."""
from __future__ import annotations

import click

from reanalysis_tool.config import load_config
from reanalysis_tool.access_control import (
    AccessControl,
    State,
    StateTransitionError,
)


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
    load_config(config_path)
    click.echo("Config loaded successfully.")


@main.command()
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
def parse_plan(config_path: str) -> None:
    """Stage 1: parse analysis plan into plan_contract.json."""
    config = load_config(config_path)
    access = AccessControl(config)
    access.ensure_state(State.UNINITIALIZED)
    click.echo("Plan parsing is not implemented in the PoC scaffold.")
    access.transition_to(State.PLAN_PARSED)


@main.command()
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
def inventory(config_path: str) -> None:
    """Stage 2: inspect raw data into data_inventory.json."""
    config = load_config(config_path)
    access = AccessControl(config)
    access.ensure_state(State.PLAN_PARSED)
    click.echo("Data inventory is not implemented in the PoC scaffold.")
    access.transition_to(State.DATA_INVENTORIED)


@main.command()
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--n-runs", default=60, show_default=True, type=int)
def run(config_path: str, n_runs: int) -> None:
    """Stage 3: execute isolated analysis runs."""
    config = load_config(config_path)
    access = AccessControl(config)
    access.ensure_state(State.DATA_INVENTORIED)
    click.echo(f"Run orchestration is not implemented in the PoC scaffold. Requested runs: {n_runs}")
    access.transition_to(State.RUNS_COMPLETE)


@main.command()
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
def synthesize(config_path: str) -> None:
    """Stage 4: aggregate run outputs into final report."""
    config = load_config(config_path)
    access = AccessControl(config)
    access.ensure_state(State.RUNS_COMPLETE)
    click.echo("Synthesis is not implemented in the PoC scaffold.")
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
