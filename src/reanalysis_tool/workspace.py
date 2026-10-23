"""Create and manage isolated per-run workspaces."""
from pathlib import Path

from reanalysis_tool.config import Config


def create_run_workspace(config: Config, run_id: str) -> Path:
    base = Path(config.output.ai_work_dir)
    run_dir = base / "runs" / run_id
    input_dir = run_dir / "input"
    work_dir = run_dir / "work"
    output_dir = run_dir / "output"

    for d in (input_dir, work_dir, output_dir):
        d.mkdir(parents=True, exist_ok=True)

    _copy_allowed_inputs(config, input_dir)
    return run_dir


def _copy_allowed_inputs(config: Config, dest: Path) -> None:
    allowed_sources = [
        Path(config.input.analysis_plan_dir),
        Path(config.input.raw_data_dir),
        Path(config.input.metadata_dir),
    ]
    allowed_extensions = {".csv", ".xlsx", ".xls", ".parquet", ".pdf", ".docx", ".json", ".yaml", ".yml", ".txt", ".md"}

    for src_dir in allowed_sources:
        if not src_dir.exists() or not src_dir.is_dir():
            continue
        for src_path in src_dir.rglob("*"):
            if not src_path.is_file():
                continue
            if src_path.suffix.lower() not in allowed_extensions:
                continue
            rel = src_path.relative_to(src_dir)
            dst_path = dest / src_dir.name / rel
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            dst_path.write_bytes(src_path.read_bytes())
