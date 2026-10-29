"""R6/T17: absent fields and incomparable experiments must fail closed."""

import copy
import json
from pathlib import Path

import pytest
from app.eval.contracts import digest
from app.eval.gate import IDENTITY_FIELDS, compare_reports

ROOT = Path(__file__).resolve().parents[2]
POLICY = json.loads((ROOT / "test/evaluation/gate-policy-v2.json").read_text(encoding="utf-8"))


def report():
    identity = dict.fromkeys(IDENTITY_FIELDS, "identity")
    identity.update(
        report_schema_version="2.0",
        metrics_schema_version="2.0",
        gate_policy_digest=digest(POLICY),
        evaluation_timestamp="2026-10-29T01:00:00+08:00",
    )
    identity["metrics"] = {key: 0.9 if direction == "higher" else 0 for key, direction in POLICY["metrics"].items()}
    identity["metrics"]["metric_basis"] = {
        key: {"numerator": 9, "denominator": 10, "missing": 0} for key in POLICY["metrics"]
    }
    return identity


def test_identical_valid_reports_pass():
    assert compare_reports(report(), report(), POLICY) == []


@pytest.mark.parametrize("name", IDENTITY_FIELDS)
def test_missing_identity_fails(name):
    current = report()
    del current[name]
    assert any(name in reason for reason in compare_reports(report(), current, POLICY))


@pytest.mark.parametrize("name", IDENTITY_FIELDS)
def test_incomparable_identity_fails(name):
    current = report()
    current[name] = "different"
    assert any(name in reason for reason in compare_reports(report(), current, POLICY))


@pytest.mark.parametrize("value", [None, "0", float("nan"), float("inf"), True])
def test_missing_or_invalid_metric_does_not_default_zero(value):
    current = report()
    current["metrics"]["unsafe_auto_pass_rate"] = value
    assert compare_reports(report(), current, POLICY)


def test_absent_metric_and_zero_denominator_fail():
    current = report()
    del current["metrics"]["unsafe_auto_pass_rate"]
    assert compare_reports(report(), current, POLICY)
    current = report()
    current["metrics"]["metric_basis"]["detection_precision"]["denominator"] = 0
    assert compare_reports(report(), current, POLICY)


def test_deliberately_degraded_detection_and_unsafe_pass_fail():
    current = report()
    current["metrics"]["detection_recall"] -= 0.03
    current["metrics"]["unsafe_auto_pass_rate"] = 0.01
    failures = compare_reports(report(), current, POLICY)
    assert any("detection_recall" in reason for reason in failures)
    assert any("absolute ceiling unsafe_auto_pass" in reason for reason in failures)


def test_overall_review_cannot_replace_high_risk_review():
    current = report()
    del current["metrics"]["high_risk_review_rate"]
    current["metrics"]["human_review_rate"] = 1
    assert any("high_risk_review_rate" in reason for reason in compare_reports(report(), current, POLICY))


def test_thresholds_registered_after_run_rejected():
    policy = copy.deepcopy(POLICY)
    policy["registered_at"] = "2026-10-30T00:00:00+08:00"
    current = report()
    current["gate_policy_digest"] = digest(policy)
    assert any("after evaluation" in reason for reason in compare_reports(current, current, policy))
