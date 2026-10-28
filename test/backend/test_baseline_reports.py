"""A green baseline must come from executed reports, including all failures."""

import json

import pytest

from _support.baseline import dataset_summary, junit_environment, junit_summary, vitest_summary


def test_junit_counts_executed_and_skipped_tests(tmp_path):
    report = tmp_path / "report.xml"
    report.write_text('<testsuites><testsuite tests="4" failures="0" errors="0" skipped="1"/></testsuites>')
    assert junit_summary(report) == {"tests": 4, "failures": 0, "errors": 0, "skipped": 1, "passed": 3}


@pytest.mark.parametrize("attributes", [
    'tests="0" failures="0" errors="0" skipped="0"',
    'tests="4" failures="1" errors="0" skipped="0"',
    'tests="4" failures="0" errors="1" skipped="0"',
    'tests="4" failures="0" errors="0" skipped="4"',
])
def test_junit_rejects_collection_only_or_failed_runs(tmp_path, attributes):
    report = tmp_path / "report.xml"
    report.write_text(f'<testsuites><testsuite {attributes}/></testsuites>')
    with pytest.raises(ValueError):
        junit_summary(report)


def test_vitest_uses_executed_report_counts(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"numTotalTests": 10, "numPassedTests": 10, "numFailedTests": 0,
                                 "numPendingTests": 0, "success": True}))
    assert vitest_summary(report)["passed"] == 10
    report.write_text(json.dumps({"numTotalTests": 10, "numPassedTests": 10, "numFailedTests": 0,
                                 "numPendingTests": 0, "success": False}))
    with pytest.raises(ValueError):
        vitest_summary(report)


def test_missing_report_metrics_are_not_treated_as_zero(tmp_path):
    report = tmp_path / "report.json"
    report.write_text('{}')
    with pytest.raises(KeyError):
        vitest_summary(report)


def test_junit_environment_only_reads_allowlisted_properties(tmp_path):
    report = tmp_path / "report.xml"
    report.write_text('<testsuites><testsuite><properties>'
                      '<property name="database_backend" value="sqlite"/>'
                      '<property name="provider_mode" value="mock"/>'
                      '<property name="unrelated" value="must-not-be-exported"/>'
                      '</properties></testsuite></testsuites>')
    assert junit_environment(report) == {"database_backend": "sqlite", "provider_mode": "mock"}


def test_junit_requires_actual_environment_metadata(tmp_path):
    report = tmp_path / "report.xml"
    report.write_text('<testsuites><testsuite/></testsuites>')
    with pytest.raises(KeyError):
        junit_environment(report)


def test_dataset_summary_does_not_invent_images_or_negative_labels(tmp_path):
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(json.dumps({"expected_category": "fire"}) + "\n", encoding="utf-8")
    result = dataset_summary(dataset)
    assert result["cases"] == 1
    assert result["image_cases"] == result["safe_negative_cases"] == result["evidence_labeled_cases"] == 0
    assert len(result["sha256"]) == 64
