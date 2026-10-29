"""R6/T17: provenance, annotation state, image coverage and content identity."""

import json
import shutil
from pathlib import Path

import pytest
from app.eval.contracts import sample_identity
from app.eval.dataset import EvalCase, load_dataset

HERE = Path(__file__).resolve().parents[1] / "evaluation"


def test_boundary_coverage_and_real_acceptance_remain_explicit():
    dataset = load_dataset(HERE / "cases.jsonl", fail_on_issues=True)
    assert dataset.version == "r6-synthetic-v1"
    assert dataset.manifest.schema_version == "2.0"
    assert len(dataset.cases) == 12
    assert {c.scenario for c in dataset.cases} == {"消防", "生产安全", "社区", "林区"}
    tags = {tag for case in dataset.cases for tag in case.coverage_tags}
    assert {"safe_negative", "low_quality", "multiple_hazards", "image_text_conflict", "insufficient_evidence"} <= tags
    assert sum(not c.ground_truth_hazard_present for c in dataset.cases) == 4
    assert all(c.source_type.value == "synthetic" and c.review_status == "synthetic_spec" for c in dataset.cases)
    assert all(c.source_reference and c.usage_authorization and c.annotator for c in dataset.cases)
    assert not load_dataset(HERE / "cases.jsonl", include_synthetic=False).cases


@pytest.mark.parametrize(
    "key", ["source_reference", "usage_authorization", "annotator", "image_paths", "annotation_method", "review_status"]
)
def test_schema_two_rejects_missing_provenance(key):
    row = json.loads((HERE / "cases.jsonl").read_text(encoding="utf-8").splitlines()[0])
    del row[key]
    with pytest.raises(ValueError):
        EvalCase.model_validate(row)


def test_real_acceptance_requires_human_review():
    row = json.loads((HERE / "cases.jsonl").read_text(encoding="utf-8").splitlines()[0])
    row["source_type"] = "donated"
    with pytest.raises(ValueError, match="human"):
        EvalCase.model_validate(row)


@pytest.mark.parametrize("mutation", ["label", "version", "count", "missing_image", "corrupt_image", "traversal"])
def test_invalid_manifest_labels_and_images_fail(tmp_path, mutation):
    shutil.copytree(HERE, tmp_path / "dataset")
    directory = tmp_path / "dataset"
    rows = [json.loads(line) for line in (directory / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
    meta = json.loads((directory / "dataset_meta.json").read_text(encoding="utf-8"))
    if mutation == "label":
        del rows[0]["ground_truth_hazard_present"]
    elif mutation == "version":
        from app.eval.dataset import validate_case_row

        missing_version = dict(rows[0])
        del missing_version["dataset_version"]
        assert validate_case_row(missing_version, line=1, dataset_version="r6-synthetic-v1", issues=[]) is None
        rows[0]["dataset_version"] = "different"
    elif mutation == "count":
        meta["case_count"] = 999
    elif mutation == "missing_image":
        rows[0]["image_paths"] = ["images/absent.png"]
    elif mutation == "corrupt_image":
        (directory / "images/fire-hazard.png").write_bytes(b"broken image")
    else:
        rows[0]["image_paths"] = ["../outside.png"]
    (directory / "cases.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    (directory / "dataset_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ValueError, match="校验失败"):
        load_dataset(directory / "cases.jsonl", fail_on_issues=True)


def test_digest_changes_on_image_or_label_but_not_absolute_location(tmp_path):
    original = load_dataset(HERE / "cases.jsonl", fail_on_issues=True)
    shutil.copytree(HERE, tmp_path / "copy")
    copied = load_dataset(tmp_path / "copy/cases.jsonl", fail_on_issues=True)
    assert sample_identity(original.cases) == sample_identity(copied.cases)
    copied.cases[0].severity = 3
    assert sample_identity(original.cases) != sample_identity(copied.cases)
    copied.cases[0].severity = original.cases[0].severity
    target = tmp_path / "copy/images/fire-hazard.png"
    target.write_bytes(target.read_bytes() + b"changed")
    assert sample_identity(original.cases) != sample_identity(copied.cases)


def test_schema_two_requires_manifest(tmp_path):
    shutil.copytree(HERE, tmp_path / "dataset")
    (tmp_path / "dataset/dataset_meta.json").unlink()
    with pytest.raises(ValueError, match="校验失败"):
        load_dataset(tmp_path / "dataset/cases.jsonl", dataset_version="r6-synthetic-v1", fail_on_issues=True)
