"""Dataset schema, provenance and version validation for the eval suite."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.eval.dataset import (
    EvalCase,
    EvalSourceType,
    load_dataset,
    validate_case_row,
)


EXISTING_ROWS = [
    {
        "id": "eval-fire-001",
        "scenario": "消防",
        "description": "小区楼道堆放纸箱杂物，堵塞疏散通道",
        "expected_category": "占用疏散通道",
        "expected_level": 1,
        "expected_clause_terms": ["疏散通道", "安全出口"],
        "expected_source": "消防法第二十八条",
    },
    {
        "id": "eval-forest-001",
        "scenario": "林区",
        "description": "林区边缘存在烧荒明火",
        "expected_category": "野外用火风险",
        "expected_level": 1,
        "expected_clause_terms": ["野外用火", "森林防火"],
    },
]


def _write_cases(tmp_path, rows, name="cases.jsonl"):
    path = tmp_path / name
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def test_legacy_case_aliases_validate():
    case = EvalCase.model_validate(EXISTING_ROWS[0])
    assert case.case_id == "eval-fire-001"
    assert case.category == "占用疏散通道"
    assert case.severity == 1
    assert case.source_type == EvalSourceType.curated
    assert case.expected_review_required is True


def test_legacy_dict_roundtrip_preserves_runner_fields():
    case = EvalCase.model_validate(EXISTING_ROWS[1])
    payload = case.legacy_dict()
    assert payload == {
        "id": "eval-forest-001",
        "scenario": "林区",
        "description": "林区边缘存在烧荒明火",
        "expected_category": "野外用火风险",
        "expected_level": 1,
        "expected_clause_terms": ["野外用火", "森林防火"],
        "expected_source": "",
    }


def test_safe_case_requires_explicit_hazard_flag():
    case = EvalCase.model_validate(
        {
            "id": "eval-safe-001",
            "scenario": "社区",
            "description": "小区出入口路面平整，未见异常",
            "expected_category": "无隐患",
            "expected_level": 3,
            "ground_truth_hazard_present": False,
            "expected_review_required": False,
        }
    )
    assert case.ground_truth_hazard_present is False
    assert case.expected_review_required is False


def test_extended_fields_are_kept_separate_from_prediction():
    case = EvalCase.model_validate(
        {
            "id": "eval-community-101",
            "scenario": "社区",
            "description": "入口限高杆锈蚀倾斜",
            "expected_category": "公共区域安全隐患",
            "expected_level": 3,
            "ground_truth_hazard_present": True,
            "expected_hazard": "限高杆锈蚀倾斜，存在倾倒伤人风险",
            "expected_evidence_supported": True,
            "user_text": "入口处有儿童经过",
            "image_paths": ["photos/a.jpg", "photos/b.jpg"],
            "expected_regulation_refs": ["公共设施维护规范-设施检查"],
            "source_type": "official",
            "dataset_version": "v1",
            "notes": "夜间拍摄、存在遮挡",
        }
    )
    assert case.expected_hazard == "限高杆锈蚀倾斜，存在倾倒伤人风险"
    assert case.user_text == "入口处有儿童经过"
    assert case.image_paths == ["photos/a.jpg", "photos/b.jpg"]
    assert case.expected_evidence_supported is True
    assert case.source_type == EvalSourceType.official
    assert case.notes.startswith("夜间拍摄")


def test_unknown_source_type_rejected():
    with pytest.raises((ValidationError, ValueError)):
        EvalCase.model_validate(
            {
                **EXISTING_ROWS[0],
                "source_type": "generated_by_ai",
            }
        )


def test_unknown_scenario_rejected():
    with pytest.raises((ValidationError, ValueError)):
        EvalCase.model_validate({**EXISTING_ROWS[0], "scenario": "未知场景"})


def test_missing_required_field_reported_with_line_number(tmp_path):
    missing_category = {
        **EXISTING_ROWS[0],
        "id": "eval-fire-002",
        "description": "缺失类别字段的行",
    }
    missing_category.pop("expected_category")
    path = _write_cases(
        tmp_path,
        [
            missing_category,
            {"id": "bad-row", "scenario": "消防"},
        ],
    )
    dataset = load_dataset(path)
    assert len(dataset.cases) == 0
    assert any(issue.line == 2 for issue in dataset.issues)
    assert any("expected_category" in issue.message for issue in dataset.issues)


def test_duplicate_case_id_reported(tmp_path):
    path = _write_cases(tmp_path, [EXISTING_ROWS[0], EXISTING_ROWS[0]])
    dataset = load_dataset(path)
    assert len(dataset.cases) == 1
    assert any(issue.message == "case_id 重复" for issue in dataset.issues)
    with pytest.raises(ValueError):
        load_dataset(path, fail_on_issues=True)


def test_synthetic_cases_marked_and_filterable(tmp_path):
    synthetic = {
        **EXISTING_ROWS[0],
        "id": "eval-synthetic-001",
        "source_type": "synthetic",
    }
    path = _write_cases(tmp_path, [EXISTING_ROWS[0], synthetic])
    all_rows = load_dataset(path)
    assert len(all_rows.cases) == 2
    assert all_rows.manifest.source_type_counts["synthetic"] == 1
    filtered = load_dataset(path, include_synthetic=False)
    assert len(filtered.cases) == 1
    assert filtered.cases[0].case_id == "eval-fire-001"


def test_expected_count_verifies_manifest_size(tmp_path):
    path = _write_cases(tmp_path, EXISTING_ROWS)
    dataset = load_dataset(path, expected_count=2)
    assert dataset.manifest.case_count == 2
    mismatch = load_dataset(path, expected_count=200)
    assert any(issue.line == 0 for issue in mismatch.issues)
    assert "实际 2 条" in mismatch.issues[0].message


def test_empty_dataset_is_valid_with_counts(tmp_path):
    path = _write_cases(tmp_path, [])
    dataset = load_dataset(path)
    assert dataset.manifest.case_count == 0
    assert dataset.manifest.category_counts == {}
    assert dataset.cases == []


def test_dataset_version_field_normalized_to_loader_version(tmp_path):
    path = _write_cases(tmp_path, EXISTING_ROWS)
    dataset = load_dataset(path, dataset_version="v1")
    assert all(case.dataset_version == "v1" for case in dataset.cases)


def test_manifest_derives_distributions(tmp_path):
    rows = [
        EXISTING_ROWS[0],
        {
            **EXISTING_ROWS[1],
            "id": "eval-forest-101",
            "description": "林区防火检查站灭火器过期",
            "expected_category": "消防器材失效",
            "expected_level": 2,
            "source_type": "synthetic",
        },
        EXISTING_ROWS[1],
    ]
    path = _write_cases(tmp_path, rows)
    dataset = load_dataset(path)
    manifest = dataset.manifest
    assert manifest.dataset_version == "v1"
    assert manifest.category_counts["野外用火风险"] == 1
    assert manifest.category_counts["消防器材失效"] == 1
    assert manifest.severity_counts[1] == 2
    assert manifest.severity_counts[2] == 1
    assert manifest.source_type_counts["curated"] == 2
    assert manifest.source_type_counts["synthetic"] == 1
    assert manifest.expected_review_counts[True] == 3
    assert "野外用火风险" in manifest.known_category_set


def test_validate_case_row_writes_issue_for_bad_case():
    issues = []
    result = validate_case_row(
        {"id": "bad", "scenario": "消防"},
        line=7,
        dataset_version="v1",
        issues=issues,
    )
    assert result is None
    assert issues[0].line == 7
    assert issues[0].case_id == "bad"


def test_real_dataset_v1_loads_30_cases_without_issues():
    path = Path(__file__).resolve().parents[1] / "data" / "eval_cases" / "cases.jsonl"
    dataset = load_dataset(path, dataset_version="v1", expected_count=30)
    assert len(dataset.cases) == 30
    assert dataset.issues == []
    assert dataset.manifest.case_count == 30
    assert sum(dataset.manifest.category_counts.values()) == 30
