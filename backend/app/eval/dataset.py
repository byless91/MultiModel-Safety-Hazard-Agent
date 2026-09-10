"""Unified evaluation dataset schema and versioned JSONL loader.

Ground truth fields are kept separate from model output: model results live in
the evaluation run result records, never in this dataset. Existing 30 cases use
the short field names ``id`` / ``expected_category`` / ``expected_level`` and
remain loadable through aliases.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

KNOWN_SCENARIOS = ("消防", "生产安全", "社区", "林区", "交通", "其他")

CASE_ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")


class EvalSourceType(str, Enum):
    """Explicit provenance for evaluation cases.

    ``curated`` covers real manually annotated cases, including private
    field-survey data and publicly documented incidents that have been
    human-reviewed. Synthetic rows must always be marked as ``synthetic`` and
    are never labeled as real benchmarks.
    """

    curated = "curated"
    donated = "donated"
    official = "official"
    synthetic = "synthetic"


class EvalCase(BaseModel):
    """One labeled evaluation case.

    Severity uses the project convention 1 = highest risk, 2 = medium,
    3 = lower risk.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        json_schema_extra={
            "note": "expected_* 与 ground_truth_* 均为标注真值；预测结果写入评测结果文件，不写入数据集。"
        },
    )

    case_id: str = Field(alias="id")
    category: str = Field(alias="expected_category")
    severity: int = Field(alias="expected_level", ge=1, le=3)
    description: str
    scenario: str = "其他"
    source_type: EvalSourceType = Field(default=EvalSourceType.curated)
    dataset_version: str = "v1"
    ground_truth_hazard_present: bool = True
    expected_hazard: str | None = None
    user_text: str | None = None
    image_paths: list[str] = Field(default_factory=list)
    expected_clause_terms: list[str] = Field(default_factory=list)
    expected_regulation_refs: list[str] = Field(default_factory=list)
    expected_source: str = ""
    expected_evidence_supported: bool | None = None
    expected_review_required: bool | None = None
    notes: str = ""

    @field_validator("case_id")
    @classmethod
    def _case_id_shape(cls, value: str) -> str:
        if not CASE_ID_RE.match(value):
            raise ValueError(f"case_id 只能包含字母/数字/_/-，长度 1-64，当前值：{value!r}")
        return value

    @field_validator("scenario")
    @classmethod
    def _known_scenario(cls, value: str) -> str:
        if value not in KNOWN_SCENARIOS:
            raise ValueError(f"scenario 不在已知列表 {list(KNOWN_SCENARIOS)}，当前值：{value!r}")
        return value

    @field_validator("source_type", mode="before")
    @classmethod
    def _parse_source_type(cls, value: Any) -> Any:
        if isinstance(value, str) and not isinstance(value, EvalSourceType):
            try:
                return EvalSourceType(value)
            except ValueError:
                raise ValueError(f"source_type 非法：{value!r}") from None
        return value

    @model_validator(mode="after")
    def _review_default_for_hazard(self) -> "EvalCase":
        if self.expected_review_required is None:
            self.expected_review_required = self.ground_truth_hazard_present
        return self

    def legacy_dict(self) -> dict[str, Any]:
        """Backward-compatible dict for existing evaluate/ablation scripts."""
        return {
            "id": self.case_id,
            "scenario": self.scenario,
            "description": self.description,
            "expected_category": self.category,
            "expected_level": self.severity,
            "expected_clause_terms": list(self.expected_clause_terms),
            "expected_source": self.expected_source,
        }


class EvalDatasetManifest(BaseModel):
    dataset_version: str
    title: str
    case_count: int
    schema_version: str = "1.0"
    created_at: str
    category_counts: dict[str, int] = Field(default_factory=dict)
    severity_counts: dict[int, int] = Field(default_factory=dict)
    source_type_counts: dict[str, int] = Field(default_factory=dict)
    expected_review_counts: dict[bool, int] = Field(default_factory=dict)
    known_category_set: list[str] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    line: int
    case_id: str | None
    message: str


class EvalDataset(BaseModel):
    version: str
    cases: list[EvalCase]
    manifest: EvalDatasetManifest
    issues: list[ValidationIssue] = Field(default_factory=list)

    def to_legacy(self) -> list[dict[str, Any]]:
        return [case.legacy_dict() for case in self.cases]


def _read_json(path: Path, model: type[BaseModel]) -> Any | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return model.model_validate(payload)
    except Exception:
        return None


def _manifest_for_directory(
    cases_dir: Path,
    version: str,
    cases: list[EvalCase],
) -> EvalDatasetManifest:
    categories: dict[str, int] = {}
    severities: dict[int, int] = {}
    sources: dict[str, int] = {}
    reviews: dict[bool, int] = {}
    known: list[str] = []
    for case in cases:
        categories[case.category] = categories.get(case.category, 0) + 1
        severities[case.severity] = severities.get(case.severity, 0) + 1
        key = case.source_type.value
        sources[key] = sources.get(key, 0) + 1
        review = bool(case.expected_review_required)
        reviews[review] = reviews.get(review, 0) + 1
        if case.category not in known:
            known.append(case.category)
    meta = cases_dir / "dataset_meta.json"
    created_at = ""
    declared: dict[str, Any] = {}
    try:
        declared = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    created_at = str(declared.get("created_at") or "")
    return EvalDatasetManifest(
        dataset_version=version,
        title=str(declared.get("title") or f"安全隐患评测集 {version}"),
        case_count=len(cases),
        created_at=created_at,
        category_counts=categories,
        severity_counts=severities,
        source_type_counts=sources,
        expected_review_counts=reviews,
        known_category_set=known,
    )


def validate_case_row(
    row: dict[str, Any],
    *,
    line: int,
    dataset_version: str,
    issues: list[ValidationIssue],
) -> EvalCase | None:
    """Validate one parsed JSONL row through the unified schema."""
    payload = dict(row)
    payload["dataset_version"] = payload.get("dataset_version") or dataset_version
    try:
        return EvalCase.model_validate(payload)
    except Exception as exc:
        issues.append(
            ValidationIssue(
                line=line,
                case_id=str(row.get("id") or row.get("case_id") or ""),
                message=str(exc),
            )
        )
        return None


def load_dataset(
    cases_path: Path | str,
    *,
    dataset_version: str = "v1",
    fail_on_issues: bool = False,
    include_synthetic: bool = True,
    expected_count: int | None = None,
) -> EvalDataset:
    """Load and validate a versioned evaluation dataset from a JSONL file.

    - The existing 30 cases keep working through the aliases in ``EvalCase``.
    - Rows may carry optional ``source_type`` / ``expected_*`` fields; missing
      metadata does not invalidate an otherwise valid row.
    - Synthetic rows are dropped when ``include_synthetic=False``.
    - ``expected_count`` supports dataset version manifests (30/100/200) without
      hard-coding special cases.
    """
    path = Path(cases_path)
    found_issues: list[ValidationIssue] = []
    cases: list[EvalCase] = []
    seen: set[str] = set()
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            found_issues.append(
                ValidationIssue(
                    line=line_index,
                    case_id=None,
                    message=f"JSON 解析失败：{exc}",
                )
            )
            continue
        if not isinstance(row, dict):
            found_issues.append(
                ValidationIssue(line=line_index, case_id=None, message="数据行必须是 JSON 对象")
            )
            continue
        case = validate_case_row(
            row,
            line=line_index,
            dataset_version=dataset_version,
            issues=found_issues,
        )
        if case is None:
            continue
        if case.case_id in seen:
            found_issues.append(
                ValidationIssue(line=line_index, case_id=case.case_id, message="case_id 重复")
            )
            continue
        if not include_synthetic and case.source_type == EvalSourceType.synthetic:
            continue
        seen.add(case.case_id)
        cases.append(case)
    if expected_count is not None and len(cases) != expected_count:
        found_issues.append(
            ValidationIssue(
                line=0,
                case_id=None,
                message=f"数据集版本 {dataset_version} 应有 {expected_count} 条，实际 {len(cases)} 条",
            )
        )
    if fail_on_issues and found_issues:
        raise ValueError(
            "评测数据集校验失败："
            + "; ".join(f"L{item.line}: {item.message}" for item in found_issues[:5])
        )
    manifest = _manifest_for_directory(path.parent, dataset_version, cases)
    return EvalDataset(
        version=dataset_version,
        cases=cases,
        manifest=manifest,
        issues=found_issues,
    )
