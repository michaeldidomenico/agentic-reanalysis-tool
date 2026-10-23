"""Execute validated analysis specs."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pandas as pd
import statsmodels.api as sm
from scipy import stats


def execute_spec(
    spec: dict[str, Any],
    workspace: Path,
) -> dict[str, Any]:
    start = time.time()
    model_type = spec.get("model", "difference_in_means")
    outcome = ((spec.get("primary_outcome") or {}).get("mapped_variable") or "").lower()
    treatment = ((spec.get("treatment_variable") or {}).get("mapped_variable") or "").lower()
    file_rel = (((spec.get("primary_outcome") or {}).get("file")) or (((spec.get("treatment_variable") or {}).get("file")) or "")).lower()

    # Load data
    candidates = [
        workspace / "input" / file_rel,
        workspace / "input" / (file_rel.replace(".xlsx", ".csv") if file_rel.endswith(".xlsx") else file_rel + ".csv"),
    ]
    data_path = next((p for p in candidates if p.exists()), None)
    if data_path is None:
        return _error_result(spec, f"Data file not found: {file_rel}", start)

    if data_path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(data_path)
    else:
        df = pd.read_csv(data_path)

    # Normalize column names for lookup
    col_map = {c.lower().strip(): c for c in df.columns}

    outcome_col = col_map.get(outcome)
    treatment_col = col_map.get(treatment)
    if not outcome_col or not treatment_col:
        return _error_result(
            spec, f"Mapped variables not found in data. outcome={outcome}, treatment={treatment}", start
        )

    # Filter analytic sample
    valid = df[[outcome_col, treatment_col]].dropna()
    if len(valid) == 0:
        return _error_result(spec, "Empty analytic sample after dropping missing values.", start)

    y = valid[outcome_col].astype(float)
    x = valid[treatment_col].astype(int)

    results = _run_model(model_type, y, x, spec)
    elapsed = round(time.time() - start, 3)

    output = {
        "schema_version": "1.0",
        "run_id": str(spec.get("run_id", "unknown")),
        "validation_status": "accepted",
        "primary_results": [
            {
                "outcome": str(spec.get("primary_outcome", {}).get("plan_label", outcome_col)),
                "estimate": round(float(results["estimate"]), 6),
                "standard_error": round(float(results["se"]), 6),
                "confidence_interval": [
                    round(float(results["estimate"]) - 1.96 * float(results["se"]), 6),
                    round(float(results["estimate"]) + 1.96 * float(results["se"]), 6),
                ],
                "p_value": round(float(results["p_value"]), 6),
                "n": len(df),
                "n_analytic": len(valid),
            }
        ],
        "conclusion_classification": _classify(results["p_value"], results["estimate"], results["se"]),
        "execution_time_seconds": elapsed,
    }
    return output


def _run_model(model_type: str, y: pd.Series, x: pd.Series, spec: dict[str, Any]) -> dict[str, Any]:
    if model_type == "difference_in_means":
        treat = x == 1
        control = x == 0
        mean_t = y[treat].mean()
        mean_c = y[control].mean()
        estimate = mean_t - mean_c
        se = float(y[treat].std() / (treat.sum() ** 0.5) + y[control].std() / (control.sum() ** 0.5))
        if se == 0:
            se = 1e-9
        t_stat = estimate / se
        p_value = float(2 * (1 - stats.norm.cdf(abs(t_stat))))
        return {"estimate": estimate, "se": se, "p_value": p_value}

    if model_type == "linear_regression":
        X = sm.add_constant(x)
        model = sm.OLS(y, X).fit()
        coef = model.params.iloc[1]
        se = model.bse.iloc[1]
        p = model.pvalues.iloc[1]
        return {"estimate": float(coef), "se": float(se), "p_value": float(p)}

    if model_type == "logistic_regression":
        y_bin = (y > y.median()).astype(int)
        X = sm.add_constant(x)
        try:
            model = sm.Logit(y_bin, X).fit(disp=False)
            coef = model.params.iloc[1]
            se = model.bse.iloc[1]
            p = model.pvalues.iloc[1]
            return {"estimate": float(coef), "se": float(se), "p_value": float(p)}
        except Exception: # BLE001 allowed for model fallback
            # Fallback to linear probability model
            model = sm.OLS(y_bin, X).fit()
            coef = model.params.iloc[1]
            se = model.bse.iloc[1]
            p = model.pvalues.iloc[1]
            return {"estimate": float(coef), "se": float(se), "p_value": float(p)}

    raise ValueError(f"Unsupported model type: {model_type}")


def _classify(p_value: float, estimate: float, se: float) -> str:
    if float(p_value) < 0.05:
        if float(estimate) > 0:
            return "positive_statistically_significant"
        return "negative_statistically_significant"
    return "null"


def _error_result(spec: dict[str, Any], message: str, start: float) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "run_id": str(spec.get("run_id", "unknown")),
        "validation_status": "failed_execution",
        "primary_results": [],
        "conclusion_classification": "null",
        "execution_time_seconds": round(time.time() - start, 3),
        "error": message,
    }
