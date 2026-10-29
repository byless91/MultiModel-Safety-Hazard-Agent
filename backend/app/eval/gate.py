"""Fail closed when a report is missing metrics or belongs to another experiment."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from app.eval.contracts import digest

IDENTITY_FIELDS = (
    "report_schema_version",
    "metrics_schema_version",
    "dataset_schema_version",
    "dataset_version",
    "dataset_digest",
    "sample_digest",
    "sample_ids",
    "evaluation_mode",
    "configuration_digest",
    "variant_ids",
    "prompt_version",
    "prompt_digest",
    "rule_versions",
    "rules_digest",
    "gate_policy_digest",
    "model_identifiers",
)


def compare_reports(baseline: dict[str, Any], current: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    failures = []
    for key in IDENTITY_FIELDS:
        if key not in baseline or key not in current or baseline[key] in (None, "", []):
            failures.append(f"missing identity field: {key}")
        elif baseline[key] != current[key]:
            failures.append(f"incomparable identity: {key}")
    if policy.get("tolerance") != 0.02:
        failures.append("policy must retain registered 2pp tolerance")
    for report in (baseline, current):
        if report.get("report_schema_version") != policy.get("report_schema_version"):
            failures.append("report schema does not match policy")
        if report.get("metrics_schema_version") != policy.get("metrics_schema_version"):
            failures.append("metric schema does not match policy")
        if report.get("gate_policy_digest") != digest(policy):
            failures.append("policy digest mismatch")
        try:
            if datetime.fromisoformat(policy["registered_at"]) > datetime.fromisoformat(report["evaluation_timestamp"]):
                failures.append("threshold policy was registered after evaluation")
        except (KeyError, ValueError, TypeError):
            failures.append("missing/invalid registration or evaluation time")
    if failures:
        return failures
    metrics = policy.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        return ["policy requires explicit metrics"]
    for name, direction in metrics.items():
        numbers = []
        for label, report in (("baseline", baseline), ("current", current)):
            value = report.get("metrics", {}).get(name)
            basis = report.get("metrics", {}).get("metric_basis", {}).get(name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or not isinstance(basis, dict)
                or not isinstance(basis.get("denominator"), (int, float))
                or basis["denominator"] <= 0
            ):
                failures.append(f"{label}: missing/non-numeric metric or denominator: {name}")
                break
            numbers.append(value)
        if len(numbers) != 2:
            continue
        base, value = numbers
        if direction not in {"higher", "lower"}:
            failures.append(f"unknown direction: {name}")
        elif (
            direction == "higher"
            and value < base - policy["tolerance"] - 1e-9
            or direction == "lower"
            and value > base + policy["tolerance"] + 1e-9
        ):
            failures.append(f"regression {name}: {base} -> {value}")
        ceiling = policy.get("ceilings", {}).get(name)
        if ceiling is not None and value > ceiling:
            failures.append(f"absolute ceiling {name}: {value} > {ceiling}")
    return failures
