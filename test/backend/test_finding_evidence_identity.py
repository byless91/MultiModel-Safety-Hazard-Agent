"""R2/T06: each concrete location keeps its own evidence result."""

import json
from copy import deepcopy

import pytest
from app.core.db import SessionLocal
from app.models import Assessment
from app.services.ensemble import StandardizedFinding, StandardizedModelResult, detect_disagreement, judge_ensemble
from app.services.evidence import judge_evidence
from app.services.finding_identity import LEGACY_IDENTITY_WARNING, ensure_unique_finding_ids
from app.services.workflow_nodes import step_evidence

CATEGORY = "占用疏散通道"
LAW = [{"id": "law-1", "document": "测试法规", "article": "第二十八条", "source": "test",
        "text": "不得占用、堵塞、封闭疏散通道、安全出口、消防车通道", "score": 0.95, "version": "test"}]


def finding_pair():
    return [
        StandardizedFinding(finding_id=CATEGORY, canonical_category=CATEGORY, raw_hazard_type=CATEGORY,
                            severity=2, confidence=0.9, description="第一项待核查", observed_facts=[],
                            location={"image_id": "img-1", "location_text": "待人工确认"}),
        StandardizedFinding(finding_id=CATEGORY, canonical_category=CATEGORY, raw_hazard_type=CATEGORY,
                            severity=2, confidence=0.9, description="第二项纸箱堵塞通道",
                            observed_facts=["纸箱堵塞疏散通道"],
                            location={"image_id": "img-1", "bbox": [20, 20, 30, 30]}),
    ]


def model(findings, family="qwen"):
    return StandardizedModelResult(provider=family, family=family, model=family, status="success",
                                   vision_confidence=0.9, findings=findings)


def aggregate(models):
    disagreement = detect_disagreement(models, ensemble_mode="full")
    return judge_ensemble(models, disagreement, evidence=LAW)


def test_ensemble_keeps_independent_statuses_for_same_category():
    result = aggregate([model(finding_pair())])
    first, second = result.final_findings
    assert first.finding_id != second.finding_id
    assert first.evidence_status == "insufficient"
    assert first.unsupported_claims
    assert second.evidence_status == "supported"
    assert second.unsupported_claims == []


def test_ids_are_stable_across_finding_order_and_model_order():
    qwen = model(finding_pair())
    glm = model(list(reversed(finding_pair())), family="glm")
    first = aggregate([qwen, glm])
    qwen.findings.reverse()
    second = aggregate([glm, qwen])
    def keyed(result):
        return {json.dumps(item.locations[0], sort_keys=True): item.finding_id
                for item in result.final_findings}
    assert keyed(first) == keyed(second)
    assert len(set(keyed(first).values())) == 2


def test_numeric_coordinate_representation_does_not_change_group_or_id():
    one = finding_pair()[1]
    two = one.model_copy(deep=True)
    two.location = {"image_id": "img-1", "bbox": [20.0, 20.0, 30.0, 30.0]}
    forward = aggregate([model([one]), model([two], "glm")])
    reverse = aggregate([model([two], "glm"), model([one])])
    assert len(forward.final_findings) == len(reverse.final_findings) == 1
    assert forward.final_findings[0].finding_id == reverse.final_findings[0].finding_id


def test_evidence_node_returns_explicit_state_update_without_mutating_input():
    initial = aggregate([model(finding_pair())]).model_dump()
    state = {"ensemble_judge": initial, "retrieval": LAW}
    before = deepcopy(state)
    update = step_evidence(state)
    assert state == before
    results = update["ensemble_judge"]["final_findings"]
    assert [item["evidence_status"] for item in results] == ["insufficient", "supported"]
    assert {item["finding_id"] for item in update["evidence_judge"]["findings"]} == {
        item["finding_id"] for item in results}
    restored = json.loads(json.dumps(update))
    again = step_evidence({"ensemble_judge": restored["ensemble_judge"], "retrieval": LAW})
    assert again["ensemble_judge"] == update["ensemble_judge"]


def test_legacy_checkpoint_ids_are_repaired_before_evidence_writeback():
    rows = aggregate([model(finding_pair())]).model_dump()["final_findings"]
    for row in rows:
        row["finding_id"] = CATEGORY
    before = deepcopy(rows)
    update = step_evidence({"ensemble_judge": {"final_findings": rows}, "retrieval": LAW})
    assert rows == before
    repaired = update["ensemble_judge"]["final_findings"]
    assert len({item["finding_id"] for item in repaired}) == 2
    assert [item["evidence_status"] for item in repaired] == ["insufficient", "supported"]
    reversed_ids = {item["description"]: item["finding_id"] for item in ensure_unique_finding_ids(list(reversed(rows)))}
    assert reversed_ids == {item["description"]: item["finding_id"] for item in repaired}


@pytest.mark.parametrize("field", ["location", "locations"])
@pytest.mark.parametrize("location,expected", [
    ({}, False), ({"image_id": "img-1"}, False), ({"bbox": [0, 0, 10, 10]}, False),
    ({"location_text": "待人工确认"}, False), ({"location_text": "楼道中部"}, True),
    ({"image_id": "img-1", "bbox": [0, 0, 10, 10]}, True),
    ({"image_id": "img-1", "bbox": [10, 10, 0, 0]}, False),
    ({"image_id": "img-1", "bbox": [-1, 0, 10, 10]}, False),
    ({"image_id": "img-1", "bbox": [False, 0, 10, 10]}, False),
    ({"image_id": "img-1", "bbox": [float("nan"), 0, 10, 10]}, False),
])
def test_singular_and_plural_locations_share_reliability_rules(field, location, expected):
    finding = {"finding_id": "existing-unique", "category": CATEGORY, "observed_facts": [],
               field: [location] if field == "locations" else location}
    result = judge_evidence([finding], LAW)
    assert result.findings[0].visual_evidence_ok is expected
    assert result.visual_evidence_count == int(expected)
    assert result.needs_human_review is not expected


def test_direct_evidence_judge_repairs_duplicate_ids_without_mutating_callers():
    findings = [{"finding_id": "old", "category": CATEGORY, "observed_facts": []},
                {"finding_id": "old", "category": CATEGORY, "observed_facts": ["纸箱堵塞疏散通道"]}]
    before = deepcopy(findings)
    result = judge_evidence(findings, LAW)
    assert findings == before
    assert len({item.finding_id for item in result.findings}) == 2
    assert result.findings[0].visual_evidence_ok is False
    assert result.findings[1].visual_evidence_ok is True


def test_identical_legacy_rows_still_receive_unique_runtime_keys():
    row = {"finding_id": "old", "category": CATEGORY, "observed_facts": []}
    result = ensure_unique_finding_ids([row, deepcopy(row), {**row, "finding_id": ""}])
    assert len({item["finding_id"] for item in result}) == 3
    assert ensure_unique_finding_ids(result) == result


def test_historical_duplicate_ids_are_only_rendered_conservatively(review_client, assessment_factory):
    findings = aggregate([model(finding_pair())]).model_dump()["final_findings"]
    for row in findings:
        row.update(finding_id=CATEGORY, evidence_status="supported", evidence_ids=["law-1"], unsupported_claims=[])
    assessment_id = assessment_factory("confirmed", ensemble_judge_json=json.dumps({"final_findings": findings}),
                                       evidence_judge_json=json.dumps({"supported": True, "findings": [],
                                                                       "unsupported_claims": []}))
    with SessionLocal() as db:
        item = db.get(Assessment, assessment_id)
        before = {column.name: getattr(item, column.name) for column in Assessment.__table__.columns}
    detail = review_client.get(f"/api/v1/assessments/{assessment_id}").json()
    assert detail["status"] == "confirmed" and detail["confirmed"] is True
    assert len({row["finding_id"] for row in detail["findings"]}) == 2
    assert all(row["evidence_status"] == "pending" and row["evidence_ids"] == [] for row in detail["findings"])
    assert detail["evidence_judge"]["supported"] is False
    assert detail["evidence_judge"]["identity_ambiguous"] is True
    assert LEGACY_IDENTITY_WARNING in detail["review_reasons"]
    listed = review_client.get("/api/v1/assessments", params={"status": "confirmed", "limit": 200}).json()
    assert next(row for row in listed if row["id"] == assessment_id)["findings"] == detail["findings"]
    with SessionLocal() as db:
        item = db.get(Assessment, assessment_id)
        assert {column.name: getattr(item, column.name) for column in Assessment.__table__.columns} == before


def test_existing_unique_legacy_id_is_not_rewritten(review_client, assessment_factory):
    row = {"finding_id": CATEGORY, "category": CATEGORY, "evidence_status": "supported", "evidence_ids": ["law-1"]}
    assessment_id = assessment_factory(ensemble_judge_json=json.dumps({"final_findings": [row]}))
    detail = review_client.get(f"/api/v1/assessments/{assessment_id}").json()
    assert detail["findings"] == [row]
    assert LEGACY_IDENTITY_WARNING not in detail["review_reasons"]
