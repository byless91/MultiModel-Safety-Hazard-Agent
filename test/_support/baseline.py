"""Summarize executed test reports and the existing evaluation inputs."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


def junit_summary(path: Path) -> dict[str, int]:
    document = ET.parse(path).getroot()
    suites = list(document.iter("testsuite"))
    if not suites:
        raise ValueError("JUnit report has no test suite")
    result = {key: sum(int(suite.attrib[key]) for suite in suites)
              for key in ("tests", "failures", "errors", "skipped")}
    if result["tests"] <= result["skipped"] or result["failures"] or result["errors"]:
        raise ValueError("A baseline requires executed tests with no failures or errors")
    result["passed"] = result["tests"] - result["skipped"]
    return result


def junit_environment(path: Path) -> dict[str, str]:
    properties = {item.attrib["name"]: item.attrib["value"]
                  for item in ET.parse(path).getroot().iter("property")}
    return {key: properties[key] for key in ("database_backend", "provider_mode")}


def vitest_summary(path: Path) -> dict[str, int]:
    report = json.loads(path.read_text(encoding="utf-8"))
    result = {
        "tests": int(report["numTotalTests"]),
        "passed": int(report["numPassedTests"]),
        "failures": int(report["numFailedTests"]),
        "skipped": int(report["numPendingTests"]),
    }
    if not report["success"] or not result["passed"] or result["failures"]:
        raise ValueError("A baseline requires successful executed frontend tests")
    return result


def dataset_summary(path: Path) -> dict:
    content = path.read_bytes()
    cases = [json.loads(line) for line in content.decode("utf-8").splitlines() if line.strip()]
    return {
        "sha256": hashlib.sha256(content).hexdigest(),
        "cases": len(cases),
        "image_cases": sum(bool(case.get("image_paths")) for case in cases),
        "safe_negative_cases": sum(case.get("ground_truth_hazard_present") is False for case in cases),
        "evidence_labeled_cases": sum(case.get("expected_evidence_supported") is not None for case in cases),
        "source_type_counts": dict(Counter(case.get("source_type", "curated") for case in cases)),
        "category_counts": dict(Counter(case["expected_category"] for case in cases)),
    }


def product_source_digest(root: Path) -> str:
    files = [path for directory in (root / "backend/app", root / "frontend/src")
             for path in directory.rglob("*") if path.is_file() and path.suffix in {".py", ".ts", ".vue", ".css"}]
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()
