# Agentic Reanalysis Tool — Workplan

## 1. Core Requirements

Build a **reusable Python CLI tool** that:
1. Ingests a pre-analysis plan and raw data.
2. Generates a reproducible analysis specification from the plan.
3. Executes the specification to produce estimates.
4. Repeats steps 2–3 many times to estimate researcher-decision uncertainty.

**End-user setup should be minimal:**
- Add secrets for a backend LLM endpoint.
- Specify file paths for the plan and raw data.
- Indicate the number of desired runs.

Everything else should be under the hood.

**Input format scope (PoC):**
- Analysis plans: PDF (DOCX may be added later).
- Raw data: CSV and Excel.

**Output format scope (PoC):**
- Treatment-control comparison.
- Basic regression adjustment.
- Missing data handling.
- Cross-run synthesis report.

**Usability constraint:**
- A person with basic programming knowledge should be able to clone the repo, read the README, and run it on their own data.

---

## 2. Non-Negotiable Approach Constraints

These are the approach-level rules that must hold regardless of implementation details.

### 2.1 Plan fidelity is binding
- The analysis plan is the source of truth.
- The agent fills gaps but never contradicts explicit commitments.
- Any unresolved ambiguity must be flagged, not silently resolved in a way that contradicts the plan.

### 2.2 Strict temporal isolation of plan parsing
- Plan parsing must be completed and cataloged before any raw data is read or inspected.
- The plan contract must contain **only** plan-derived information. No data-derived mappings may enter the plan contract.
- Technical enforcement: the plan parser module must not import or call any data-inventory or raw-data filesystem code.

### 2.3 Run isolation
- Each run’s LLM/agent sees only its own isolated workspace.
- The workspace contains: the plan contract, the data inventory, and copies of the allowed raw data files.
- The agent is blind to other runs and to any human work products.
- Technical enforcement: filesystem copies into per-run directories, with a hard-coded allowlist of source directories and file extensions.

### 2.4 Reproducibility is simulator uncertainty
- Fixed settings: temperature, model version, prompt version, archetype sequence, raw data hash, plan hash.
- Re-running with identical inputs and settings may produce different valid specifications due to LLM non-determinism.
- This variation is captured and reported, not hidden.
- Every run logs: model, temperature, prompt version, plan contract hash, and raw data manifest hash.

### 2.5 PoC validation is rule-based only
- Automated validation is limited to mechanical checks.
- No LLM-assisted or subjective validation gates.
- Rejected runs are logged but excluded from the output distribution.

### 2.6 Simplicity over flexibility
- Prefer deterministic templates over generated code where possible.
- Minimize moving parts.
- Avoid agent frameworks that add hidden sources of variation.

---

## 3. Planned Implementation

This section describes the current implementation plan. Details may change as we build and learn, but the output must always satisfy the core requirements and non-negotiables above.

### 3.1 High-Level Architecture

```
User Project
├── input/
│   ├── analysis_plan/   ← read only by plan parser
│   ├── raw_data/        ← read only by data inventory and run workspaces
│   └── metadata/        ← optional, read only by data inventory
└── ai_work/
    ├── plan_contract.json          ← output of stage 1
    ├── data_inventory.json         ← output of stage 2
    ├── runs/
    │   ├── run_0001/
    │   │   ├── input/              ← isolated copy of plan + raw data
    │   │   ├── work/
    │   │   └── output/
    │   └── run_0002/
    └── synthesis/
        └── final_report.md
```

**Stage flow (enforced by CLI state machine):**

1. `parse-plan` — reads only `input/analysis_plan/` → writes `ai_work/plan_contract.json`
2. `inventory` — reads `input/raw_data/` and `input/metadata/` → writes `ai_work/data_inventory.json`
3. `run` — for each run:
   - Creates isolated workspace `ai_work/runs/run_XXXX/`
   - Copies `plan_contract.json`, `data_inventory.json`, and allowed raw data into workspace `input/`
   - Generates `analysis_spec.json` (LLM sees only workspace contents)
   - Validates spec
   - Executes spec in workspace
   - Writes outputs to workspace `output/`
4. `synthesize` — aggregates outputs from all accepted runs

**Temporal isolation guarantee:** `run` cannot execute unless both `plan_contract.json` and `data_inventory.json` exist. The plan parser has zero dependencies on raw data modules.

### 3.2 Data Contracts

#### 3.2.1 plan_contract.json
*Produced by: `parse-plan`. Contains ONLY plan-derived commitments. No data-derived mappings.*

```json
{
  "schema_version": "1.0",
  "plan_id": "string",
  "source_file": "input/analysis_plan/plan.pdf",
  "source_hash": "sha256:...",
  "primary_outcome": {
    "label": "string — exact plan language",
    "description": "string — plan's description of the outcome"
  },
  "estimand": "intent_to_treat | treatment_on_the_treated | average_treatment_effect | unspecified",
  "population": "string — exact plan language",
  "treatment_definition": "string — exact plan language",
  "comparison_definition": "string — exact plan language",
  "primary_method": "string — exact plan language",
  "secondary_outcomes": ["string"],
  "required_analyses": ["string"],
  "constraints": ["string — prohibitions or hard requirements"],
  "binding_commitments": {
    "primary_outcome": "string",
    "estimand": "string",
    "population": "string",
    "treatment_definition": "string",
    "comparison_definition": "string",
    "primary_method": "string"
  },
  "underspecified_elements": [
    "string — e.g., Missing data handling, Covariate set, Standard error adjustment"
  ],
  "ambiguities": [
    {
      "element": "string",
      "plan_language": "string",
      "resolution": "leave_to_evaluator | require_human_review"
    }
  ]
}
```

#### 3.2.2 data_inventory.json
*Produced by: `inventory`. Deterministic inspection of raw data and metadata.*

```json
{
  "schema_version": "1.0",
  "inventory_id": "string",
  "source_dirs": {
    "raw_data": "input/raw_data",
    "metadata": "input/metadata"
  },
  "files": [
    {
      "path": "raw_data/baseline.csv",
      "format": "csv | xlsx | parquet | delta",
      "n_rows": 1200,
      "n_columns": 6,
      "columns": [
        {
          "name": "employed_12m",
          "type": "string | integer | float | date | boolean",
          "missing_rate": 0.02,
          "unique_values": 2,
          "role_candidates": ["outcome", "treatment", "covariate", "id", "weight", "cluster"]
        }
      ],
      "sheets": ["Sheet1"],
      "duplicate_records": 0,
      "warnings": ["string"]
    }
  ],
  "derived_insights": {
    "candidate_id_variables": ["id"],
    "candidate_treatment_variables": ["assigned_treatment"],
    "candidate_outcome_variables": ["employed_12m", "earnings_12m"],
    "candidate_cluster_variables": ["site"],
    "date_like_variables": ["enrollment_date"]
  }
}
```

#### 3.2.3 analysis_spec.json
*Produced by: `spec_generator`. Combines plan contract and data inventory. This is the first data-aware artifact.*

```json
{
  "schema_version": "1.0",
  "run_id": "run_0001",
  "archetype": "conservative_plan_follower",
  "plan_contract_path": "input/plan_contract.json",
  "data_inventory_path": "input/data_inventory.json",
  "files_to_use": ["raw_data/baseline.csv", "raw_data/followup.xlsx"],
  "primary_outcome": {
    "plan_label": "Employment status at 12 months",
    "mapped_variable": "employed_12m",
    "file": "raw_data/followup.xlsx",
    "sheet": "employment",
    "rationale": "string — why this variable matches the plan"
  },
  "treatment_variable": {
    "mapped_variable": "assigned_treatment",
    "file": "raw_data/baseline.csv"
  },
  "estimand": "intent_to_treat",
  "analytic_population": "string — e.g., All randomized individuals with nonmissing treatment assignment",
  "missing_data_strategy": "complete_case | available_case | explicit_omission",
  "covariates": ["age", "gender", "baseline_employed"],
  "model": "difference_in_means | linear_regression | logistic_regression",
  "standard_errors": "classical | robust | clustered_by_site | clustered_by_site_state",
  "transformations": [],
  "hypothesis_test": "two-sided test of treatment coefficient equals zero",
  "assumptions": ["string"],
  "secondary_analyses": []
}
```

#### 3.2.4 results.json
*Produced by: `executor`.*

```json
{
  "schema_version": "1.0",
  "run_id": "run_0001",
  "validation_status": "accepted | rejected | failed_execution",
  "primary_results": [
    {
      "outcome": "Employment status at 12 months",
      "estimate": 0.041,
      "standard_error": 0.015,
      "confidence_interval": [0.012, 0.070],
      "p_value": 0.006,
      "n": 1172,
      "n_analytic": 1145
    }
  ],
  "conclusion_classification": "positive_statistically_significant | negative_statistically_significant | null",
  "execution_time_seconds": 12.3,
  "error": "string — present only if validation_status is rejected or failed_execution"
}
```

#### 3.2.5 audit_log.json
*Produced by: `run` orchestration.*

```json
{
  "schema_version": "1.0",
  "run_id": "run_0001",
  "archetype": "conservative_plan_follower",
  "model": "provider/model-id",
  "temperature": 0.7,
  "prompt_version": "v1.0",
  "plan_contract_hash": "sha256:...",
  "raw_data_manifest_hash": "sha256:...",
  "files_accessed": ["raw_data/baseline.csv"],
  "files_written": ["output/results.json", "output/report.md"],
  "validation_status": "accepted",
  "validation_warnings": ["12 records dropped due to missing primary outcome"],
  "timestamp": "ISO8601"
}
```

#### 3.2.6 config.yaml
*User-editable configuration for a project.*

```yaml
schema_version: "1.0"
project_name: "my_evaluation"

input:
  analysis_plan_dir: "./input/analysis_plan"
  raw_data_dir: "./input/raw_data"
  metadata_dir: "./input/metadata"

output:
  ai_work_dir: "./ai_work"
  run_isolation: true

researcher_simulation:
  mode: "archetype_stochastic"
  number_of_runs: 60
  archetype_sampling:
    mode: "equal_allocation"
    # mode: "weighted_random"
    # weights:
    #   conservative_plan_follower: 0.25
    #   pragmatic_program_evaluator: 0.40
    #   frequentist_econometrician: 0.35
  force_diversity: false
  blind_runs: true

llm:
  provider: "openai"
  model: "gpt-4o"
  temperature: 0.7
  max_tokens: 4096
  log_prompts: true
  log_dir: "./ai_work/logs"

validation:
  reject_plan_contradictions: true
  reject_forbidden_file_access: true
  reject_missing_primary_outcome_mapping: true
  reject_empty_analytic_sample: true
  reject_incompatible_model: true
```

### 3.3 Component Specifications

#### 3.3.1 Plan Parser (`plan_parser.py`)
- **Input:** `input/analysis_plan/` (PDF or DOCX)
- **Output:** `ai_work/plan_contract.json`
- **Behavior:**
  - Extracts text from PDF/DOCX using deterministic libraries (`pypdf`, `python-docx`).
  - Uses an LLM to structure the text into `plan_contract.json`.
  - **Hard rule:** This module must not import or call any data-inventory or file-system traversal code for raw data.
  - Validates that required fields are present and non-empty.

#### 3.3.2 Data Inventory (`data_inventory.py`)
- **Input:** `input/raw_data/`, `input/metadata/`
- **Output:** `ai_work/data_inventory.json`
- **Behavior:**
  - Deterministically inspects files (CSV via `pandas`, Excel via `openpyxl`, Parquet via `pyarrow`).
  - Produces column-level metadata: types, missingness, uniqueness.
  - Generates candidate variable roles based on name heuristics and metadata.
  - Writes warnings for data quality issues.

#### 3.3.3 Workspace Manager (`workspace.py`)
- **Responsibility:** Create and populate isolated run directories.
- **Behavior:**
  - Creates `ai_work/runs/run_XXXX/input/`, `work/`, `output/`.
  - Copies `plan_contract.json` and `data_inventory.json` into `input/`.
  - Copies allowed raw data files (filtered by extension allowlist) into `input/`.
  - Does NOT copy anything from `human_work/`, `intermediate_data/`, or other forbidden paths.
  - Returns absolute path to workspace root.

#### 3.3.4 Archetype Manager (`archetypes.py`)
- **Responsibility:** Define archetypes and sample archetypes for runs.
- **Archetypes (PoC):**
  1. `conservative_plan_follower`
     - Simplest defensible implementation.
     - Complete-case missing data handling.
     - No covariate adjustment unless explicitly required by plan.
     - Classical standard errors unless design explicitly requires clustering.
     - Flags assumptions; avoids exploratory analysis.
  2. `pragmatic_program_evaluator`
     - Faithful plan implementation.
     - Practical missing data handling (e.g., available-case with justification).
     - Basic covariate adjustment for observed baseline differences.
     - Clustered standard errors if design features suggest it.
     - Transparent summary statistics.
  3. `frequentist_econometrician`
     - Causal identification focus.
     - Active covariate adjustment for precision.
     - Robust or clustered standard errors.
     - Clear confirmatory vs. exploratory distinction.
- **Sampling (PoC):** Equal allocation (20 runs per archetype × 3 = 60). Weighted random sampling deferred to post-PoC.

#### 3.3.5 Spec Generator (`spec_generator.py`)
- **Input:** Plan contract, data inventory, archetype.
- **Output:** `analysis_spec.json`
- **Behavior:**
  - Constructs an LLM prompt containing the plan contract, data inventory, and archetype defaults.
  - Instructs the LLM to return a structured JSON spec.
  - The LLM sees only the contents of the run workspace (plan contract, data inventory, and copied raw data paths).
  - Parses LLM response into `analysis_spec.json`.
  - If LLM returns malformed JSON, retry once with stricter instructions; reject run on second failure.

#### 3.3.6 Validator (`validator.py`)
- **Input:** `analysis_spec.json`, `plan_contract.json`, `data_inventory.json`
- **Output:** Validation decision + warnings
- **Behavior:** Rule-based checks only (no LLM judgment) for PoC.
  - **Plan adherence:**
    - Primary outcome variable exists in data inventory.
    - Estimand matches plan contract.
    - Treatment variable exists.
    - No forbidden files referenced.
    - No post-treatment variables used as covariates (checked against variable names containing outcome-like terms, flagged for manual review if ambiguous).
  - **Data validity:**
    - All referenced files exist in the copied workspace.
    - All referenced variables exist in the data inventory.
    - Analytic sample is non-empty (check against row counts after filtering).
  - **Statistical validity:**
    - Model is compatible with outcome type (binary → logistic, continuous → linear).
    - Standard error type is allowed by config.
  - **Audit validity:**
    - Spec includes rationale for all mappings.
    - Spec lists all files used.

#### 3.3.7 Executor (`executor.py`)
- **Input:** Accepted `analysis_spec.json`, run workspace
- **Output:** `results.json`, `report.md`, `diagnostics.json`
- **Behavior:**
  - Uses deterministic analysis templates for supported models.
  - **Templates (PoC):**
    - `difference_in_means`: two-sample t-test.
    - `linear_regression`: OLS via `statsmodels`, with optional robust/clustered SE.
    - `logistic_regression`: GLM via `statsmodels`.
  - For data wrangling (filtering, merging, missing-data handling), generates a small Python script executed in the run workspace.
  - All file I/O is relative to the run workspace.
  - Captures stdout/stderr and execution time.
  - Writes `diagnostics.json` with convergence warnings, dropped observations, etc.

#### 3.3.8 Synthesizer (`synthesizer.py`)
- **Input:** `ai_work/runs/*/output/results.json`
- **Output:** `ai_work/synthesis/final_report.md`, `ai_work/synthesis/summary.json`
- **Behavior:**
  - Reads only accepted runs.
  - Computes:
    - Counts: proposed, accepted, rejected, failed.
    - Rejection reasons.
    - Distribution of estimates, standard errors, confidence intervals, p-values.
    - Archetype-specific distributions.
    - Share of runs supporting each conclusion.
  - Writes human-readable markdown report and machine-readable summary JSON.

#### 3.3.9 Access Control & State Machine (`access_control.py`)
- **Responsibility:** Enforce temporal ordering and path restrictions.
- **State machine:**
  - `UNINITIALIZED` → `PLAN_PARSED` → `DATA_INVENTORIED` → `RUNS_COMPLETE` → `SYNTHESIZED`
  - Each state transition requires the previous artifact to exist and pass schema validation.
- **Path enforcement:**
  - Plan parser: allowlist `[input/analysis_plan/]`.
  - Data inventory: allowlist `[input/raw_data/, input/metadata/]`.
  - Run workspace: copies only from allowlisted source dirs. No traversal to parent directories.

### 3.4 Detailed Execution Flow

#### Command: `reanalysis parse-plan config.yaml`
1. Load config.
2. Verify `input/analysis_plan/` exists and contains exactly one PDF or DOCX.
3. Call `plan_parser.parse()`.
4. Write `ai_work/plan_contract.json`.
5. Compute and store `source_hash`.
6. Transition state to `PLAN_PARSED`.

#### Command: `reanalysis inventory config.yaml`
1. Load config.
2. Verify `ai_work/plan_contract.json` exists and is valid.
3. Call `data_inventory.inspect()`.
4. Write `ai_work/data_inventory.json`.
5. Transition state to `DATA_INVENTORIED`.

#### Command: `reanalysis run config.yaml --n-runs 60`
1. Load config.
2. Verify `ai_work/plan_contract.json` and `ai_work/data_inventory.json` exist.
3. Determine archetype sequence (e.g., 20 conservative, 20 pragmatic, 20 econometrician).
4. For each run:
   - Create workspace via `workspace.create_run(run_id)`.
   - Copy allowed inputs into workspace `input/`.
   - Call `spec_generator.generate(run_id, archetype, workspace)` → `analysis_spec.json`.
   - Call `validator.validate(spec, plan_contract, data_inventory)`.
   - If accepted:
     - Call `executor.execute(spec, workspace)` → `results.json`, `report.md`, `diagnostics.json`.
   - If rejected:
     - Write `results.json` with `validation_status: rejected` and reason.
   - Write `audit_log.json`.
   - Archive workspace (do not delete; retained for audit).
5. Transition state to `RUNS_COMPLETE`.

#### Command: `reanalysis synthesize config.yaml`
1. Load config.
2. Verify state is `RUNS_COMPLETE`.
3. Call `synthesizer.aggregate()`.
4. Write `ai_work/synthesis/summary.json` and `final_report.md`.
5. Transition state to `SYNTHESIZED`.

#### Command: `reanalysis run-all config.yaml`
- Executes `parse-plan` → `inventory` → `run` → `synthesize` in sequence.

### 3.5 CLI Interface

```
reanalysis init <project_dir>                # scaffold example project structure
reanalysis validate-config <config.yaml>      # check config and input structure
reanalysis parse-plan <config.yaml>           # stage 1: plan → plan_contract.json
reanalysis inventory <config.yaml>            # stage 2: data → data_inventory.json
reanalysis run <config.yaml> [--n-runs 60]    # stage 3: simulations
reanalysis synthesize <config.yaml>           # stage 4: aggregation
reanalysis run-all <config.yaml>              # execute all stages in order
```

### 3.6 Project Structure

```
agentic-reanalysis-tool/
├── workplan.md
├── README.md
├── pyproject.toml
├── src/
│   └── reanalysis_tool/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── access_control.py
│       ├── plan_parser.py
│       ├── data_inventory.py
│       ├── workspace.py
│       ├── archetypes.py
│       ├── prompts.py
│       ├── spec_generator.py
│       ├── validator.py
│       ├── executor.py
│       ├── synthesizer.py
│       ├── report.py
│       └── templates/
│           ├── __init__.py
│           ├── difference_in_means.py
│           ├── linear_regression.py
│           └── logistic_regression.py
├── tests/
│   ├── __init__.py
│   ├── test_plan_parser.py
│   ├── test_data_inventory.py
│   ├── test_validator.py
│   └── test_executor.py
└── examples/
    └── demo_project/
        ├── input/
        │   ├── analysis_plan/
        │   │   └── plan.pdf
        │   └── raw_data/
        │       ├── baseline.csv
        │       └── followup.csv
        └── config.yaml
```

### 3.7 Proof-of-Concept Scope

#### In Scope
- Input formats: PDF plans, CSV and Excel raw data.
- Designs: Treatment-control comparison with OLS or logistic regression.
- Archetypes: Conservative, Pragmatic, Frequentist (equal allocation).
- Templates: Difference in means, linear regression, logistic regression.
- Validation: Rule-based mechanical checks only.
- Outputs: `plan_contract.json`, `data_inventory.json`, per-run `analysis_spec.json`, `results.json`, `audit_log.json`, synthesis report.

#### Out of Scope (Post-PoC)
- DOCX plan parsing.
- Delta/Parquet data formats.
- Complex survey designs, weighting, multilevel models.
- LLM-assisted or subjective validation.
- Bayesian analysis templates.
- Weighted archetype sampling.
- Containerization or OS-level mount enforcement.

### 3.8 Implementation Phases

#### Phase 1: Scaffolding and Core Infrastructure
- Initialize `pyproject.toml` with dependencies.
- Implement `cli.py` with command structure and state machine.
- Implement `config.py` with `config.yaml` loading and validation.
- Implement `access_control.py` with path allowlists and state transitions.
- Create `examples/demo_project/` with sample data and config.

#### Phase 2: Plan Parsing and Data Inventory
- Implement `plan_parser.py` with PDF extraction and LLM structuring.
- Implement `data_inventory.py` with deterministic file inspection.
- Write JSON schema validators for `plan_contract.json` and `data_inventory.json`.

#### Phase 3: Run Isolation and Spec Generation
- Implement `workspace.py` for run directory creation and file copying.
- Implement `archetypes.py` with three archetypes and equal allocation.
- Implement `prompts.py` with base and archetype-specific prompt fragments.
- Implement `spec_generator.py` with LLM call, JSON parsing, and retry logic.

#### Phase 4: Validation and Execution
- Implement `validator.py` with rule-based checks.
- Implement `executor.py` with three analysis templates and code generation for wrangling.
- Implement failure handling (timeouts, exceptions).

#### Phase 5: Synthesis and Reporting
- Implement `synthesizer.py` with aggregation logic.
- Implement `report.py` for markdown generation.

#### Phase 6: Testing and Documentation
- Unit tests for config loading, plan parsing (mocked LLM), data inventory, validator, executor templates.
- Integration test using `examples/demo_project`.
- Write `README.md` with installation, quickstart, and project structure.
- Run `ruff check --fix` and `pytest`.

### 3.9 Technology Stack

- **Language:** Python 3.14
- **CLI:** `click`
- **Contracts/validation:** `pydantic`
- **LLM client:** `openai` SDK (OpenAI-compatible; works with Ollama, vLLM, etc.)
- **Data:** `pandas`, `openpyxl`, `pyarrow`
- **Plan parsing:** `pypdf`, `python-docx`
- **Execution:** `statsmodels`
- **Config:** `pyyaml`
- **Lint/test:** `ruff`, `pytest`

### 3.10 Key Design Decisions

| Decision | Current Choice | Rationale |
|----------|----------------|-----------|
| Plan parsing before data access | Enforced by CLI state machine + module boundaries | Meets strict temporal isolation requirement |
| Run isolation mechanism | Filesystem copy into per-run directories | Simple, robust, cross-platform, no symlink escape risk |
| Validation approach | Rule-based only for PoC | Keeps PoC simple; LLM validation deferred |
| Execution approach | Hybrid: templates for models, generated code for wrangling | Balances reliability and flexibility |
| Archetype sampling | Equal allocation for PoC | Simplest valid approach; weighted sampling deferred |
| Reproducibility | Fixed settings + logged simulator uncertainty | Honest about LLM non-determinism |
| Data visibility during spec generation | Agent sees complete raw data in its isolated workspace | Required for accurate variable mapping; isolation prevents cross-run contamination |
| Agent framework | None — direct LLM API calls | Minimizes hidden variation; keeps dependencies minimal; maximizes reproducibility |

---

## 4. Current State and Lessons Learned

### 4.1 Completed Implementation

The following components are implemented and verified end-to-end against the demo project:

- **Project scaffolding**: `pyproject.toml`, `src/reanalysis_tool/`, `examples/demo_project/`
- **CLI & state machine**: `validate-config`, `parse-plan`, `inventory`, `run`, `synthesize`, `run-all`
- **Config loading**: resolves paths relative to the config file location; validates project root containment
- **Plan parser**: extracts text from PDF via `pypdf`, structures into `plan_contract.json` via OpenRouter LLM; falls back to extraction-only contract on invalid LLM output
- **Data inventory**: deterministic inspection of CSV and Excel files; produces column metadata and candidate variable roles
- **Workspace isolation**: creates per-run directories and copies allowed inputs (`pdf`, `docx`, `csv`, `xlsx`, etc.)
- **Spec generator**: sends plan contract + data inventory + archetype guidance to LLM; normalizes returned paths to workspace-relative; applies deterministic fallback mappings when LLM output is incomplete
- **Validator**: rule-based checks for plan adherence, data validity, and statistical compatibility
- **Executor**: supports `difference_in_means`, `linear_regression`, and `logistic_regression` via `statsmodels`; computes estimates, SEs, CIs, and p-values
- **Synthesizer**: aggregates accepted/rejected/failed runs into `summary.json` and `final_report.md`

### 4.2 Demo Artifacts

- **Analysis plan**: `examples/demo_project/input/analysis_plan/1808-energy-use-feedback.pdf`
- **Synthetic dataset**: 
  - `examples/demo_project/input/raw_data/hud_energy.csv`
  - `examples/demo_project/input/raw_data/hud_energy.xlsx`
- **Config**: `examples/demo_project/config.yaml`

The synthetic dataset reproduces the published HUD study summary statistics:
- Week 1 control mean ≈ 19.4 kWh; treatment difference ≈ –0.04 kWh; valid n ≈ 2981
- Week 8 control mean ≈ 16.0 kWh; treatment difference ≈ +0.12 kWh; valid n ≈ 3029

### 4.3 Confirmed Test Run

Running `run --n-runs 1` against the demo project produced:
- `estimate`: –0.04
- `n_analytic`: 2981
- `p_value`: 0.863
- `conclusion_classification`: `null`

This matches the published point estimate and sample size for the week-1 outcome.

### 4.4 Key Lessons and Required Updates

| Lesson | Impact on Plan | Action Taken / Needed |
|--------|----------------|----------------------|
| Free OpenRouter models have intermittent availability and rate limits. | LLM-dependent stages can fail with 404/429 errors. | Added graceful fallback in `plan_parser` and `spec_generator`; recommend a paid buffer model for reliable testing. |
| LLMs frequently return absolute paths instead of workspace-relative paths. | Validator/rejector flags false positives for forbidden file access. | Added `_normalize_paths()` in `spec_generator` to remap paths to workspace-relative form. |
| LLMs sometimes return empty or malformed JSON. | `run` stage fails before validation/execution. | `spec_generator` now falls back to deterministic variable mapping when JSON is invalid or empty. |
| State detector must use `ai_work_dir` from config, not CWD. | Running from wrong directory broke state gating. | Fixed `AccessControl._detect_state()` to use `config.output.ai_work_dir`. |
| Click command functions can shadow imported module names. | `parse_plan` CLI command caused recursion into Click internals. | Renamed imports to `run_parse_plan` / `run_synthesize`. |
| `statsmodels.stats.norm` is not available in newer versions. | Executor crashes on p-value calculation. | Switched to `scipy.stats.norm`. |
| `pyproject.toml` testpaths needs explicit `tests/` dir. | `pytest` exits with code 5 when no tests exist yet. | Already set; will create tests in Phase 6. |

### 4.5 Testing Status

- ✅ CLI plumbing and state transitions validated
- ✅ `parse-plan`, `inventory`, `run`, `synthesize` executed end-to-end
- ⬜ Unit tests not yet written
- ⬜ README not yet written
- ⬜ Lint passes with 5 remaining intentional `Exception` catches for orchestration/fallback


---

## 5. Next Steps

Pick up from here in the next conversation thread.

### Immediate Priorities

1. **Write unit tests for non-LLM components**
   - `tests/test_config.py`: loading, path resolution, rejection of escaped paths
   - `tests/test_access_control.py`: state transitions, guards, detection from artifacts
   - `tests/test_data_inventory.py`: CSV/XLSX inspection, missing files, derived insights
   - `tests/test_validator.py`: accepted/rejected cases for rule-based checks
   - `tests/test_executor.py`: difference-in-means, linear regression, logistic regression templates

2. **Add an integration test**
   - Run `parse-plan` → `inventory` → `run --n-runs 1` → `synthesize` against `examples/demo_project`
   - Assert `results.json` contains accepted run with expected outcome mapping and non-null estimate

3. **Improve spec generation quality**
   - Add retry logic with backoff for free-model 429s
   - Add a small paid fallback model config option (e.g., `z-ai/glm-5.3-flash`)
   - Strengthen prompt to enforce strict JSON schema and workspace-relative paths

4. **Write README.md**
   - Installation, quickstart, project structure, config reference, example run command

5. **Resolve remaining ruff warnings**
   - Decide whether to keep broad `Exception` catches in orchestration/fallback code or add more granular handling
   - Fix or explicitly exclude the remaining lint findings

### Suggested Order for Next Session

1. Unit tests for config, access control, data inventory, validator, executor
2. Integration test
3. README
4. Spec generator robustness improvements
5. Paid fallback model option

---

## 6. Outstanding Issues and Required Fixes

### 6.1 Plan parser fallback contamination

**Observed:** `plan_contract.json` can end up with fallback default values when the LLM fails. In that state, the spec generator's fallback path maps outcomes from data column-name heuristics instead of the plan contract.

**Impact:** This violates the binding requirement that the analysis plan is the source of truth.

**Required fix:**
- Make `spec_generator` fallback conservative: if the plan contract's required fields are empty, do not invent variable mappings from data heuristics. Reject the run or leave mappings empty so the validator catches it.
- Remove `raw_text` from the fallback contract, or strip it before passing the contract to `spec_generator`, to prevent accidental reliance on partial plan text.

### 6.2 Spec generator reliance on raw_text / plan PDF absence

**Observed:** The execution-plan LLM prompt receives `plan_contract`, `data_inventory`, and `archetype_id`. The PDF itself is not attached. When `plan_contract` is a fallback object, the only plan-derived content is a partial `raw_text` excerpt.

**Impact:** Spec generation is not reliably grounded in the actual analysis plan.

**Required fix:**
- Ensure `parse-plan` succeeds against a reliable LLM endpoint so the contract is populated from structured extraction, not fallback.
- If the plan parser fails, fail loudly and stop the pipeline rather than silently using a degraded contract.

### 6.3 Unreliable free-model endpoints

**Observed:** Free OpenRouter models intermittently return 404, 429, empty responses, or safety-filtered outputs like "User Safety: safe".

**Impact:** LLM-dependent stages fail nondeterministically, making debugging and validation difficult.

**Required fix:**
- Add a configurable paid fallback model option in `config.yaml` (for example, `z-ai/glm-5.3-flash`).
- Add retry logic with backoff for transient 429s.
- Keep free models available, but document that they are for smoke testing only.

### 6.4 Synthetic dataset calibration

**Observed:** The demo dataset was calibrated to reproduce the published HUD study point estimates and sample sizes.

**Impact:** This is not a fair validation of the workflow. It tests whether the system can recover known answers rather than whether it faithfully executes an analysis plan on unknown data.

**Required fix:**
- Regenerate `hud_energy.csv` and `hud_energy.xlsx` without anchoring to the published –0.04 / +0.12 outcomes.
- Use the same structural features (blocking, missingness, covariate set) but with random effect sizes.
- Treat the regenerated dataset as the canonical demo fixture going forward.

### 6.5 Lint warnings

**Observed:** `ruff check` reports 5 remaining findings, mostly around broad `except Exception` usage in orchestration/fallback code.

**Decision needed:** Keep these broad catches intentionally for robustness, or refactor to more granular exception handling.

