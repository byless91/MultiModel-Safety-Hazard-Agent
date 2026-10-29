"""Exercise the actual offline CLIs and immutable schema 2 archive paths."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def invoke(*arguments):
    return subprocess.run([sys.executable, *map(str, arguments)], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", timeout=60,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=False)


def test_mock_cli_archive_and_gate_fail_closed(tmp_path):
    output = tmp_path / "run"
    completed = invoke(ROOT / "test/evaluation/run_mock.py", "--output", output)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report_path = output / "report.json"
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    assert report["dataset_version"] == "r6-synthetic-v1"
    assert report["metrics_schema_version"] == "2.0"
    assert report["dataset_overview"]["declared_image_count"] == 12
    assert report["dataset_overview"]["loaded_image_count"] == 12
    assert report["dataset_overview"]["input_failed_count"] == 0
    assert report["source_partition_metrics"]["synthetic"]["total"] == 12
    assert report["call_statistics"]["http_attempt_count"] == 0
    assert report["independent_human_evidence_accuracy"] is None
    gate = ROOT / "scripts/check_eval_baseline.py"
    result = invoke(gate, "--current", report_path, "--baseline", report_path)
    assert result.returncode == 0, result.stderr
    del report["metrics"]["unsafe_auto_pass_rate"]
    invalid = tmp_path / "invalid-report.json"
    invalid.write_text(json.dumps(report), encoding="utf-8")
    result = invoke(gate, "--current", invalid, "--baseline", report_path)
    assert result.returncode == 1 and "unsafe_auto_pass_rate" in result.stderr
    result = invoke(ROOT / "test/evaluation/run_mock.py", "--output", output)
    assert result.returncode != 0 and report_path.read_bytes() == report_bytes
    result = invoke(ROOT / "test/evaluation/run_mock.py", "--output", output, "--ablation")
    assert result.returncode == 0, result.stdout + result.stderr
    ablation = json.loads((output / "ablation_report.json").read_text(encoding="utf-8"))
    assert ablation["evaluation_timestamp"]
    assert len(ablation["source_digest"]) == 64
    assert "report_identity" in ablation["variants"]["full"]
    archive = tmp_path / "archive"
    command = [ROOT / "scripts/build_eval_docs.py", "--eval-dir", output, "--docs-dir", archive,
               "--cases", ROOT / "test/evaluation/cases.jsonl"]
    result = invoke(*command)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (archive / "reports/evaluation_report.json").exists()
    assert (archive / "dataset/manifest-summary.json").exists()
    assert not list((archive / "dataset").glob("*.jsonl"))
    assert invoke(*command).returncode != 0
