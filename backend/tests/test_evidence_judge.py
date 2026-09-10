from app.services.evidence import judge_evidence


def _finding(finding_id: str, category: str, facts: list[str]) -> dict:
    return {
        "finding_id": finding_id,
        "category": category,
        "observed_facts": facts,
    }


def _law(text: str, score: float = 0.8, article: str = "第二十八条") -> dict:
    return {
        "id": f"law-{article}",
        "source": "官方",
        "article": article,
        "text": text,
        "score": score,
    }


def test_evidence_judge_accepts_supported_finding():
    findings = [
        _finding("f1", "占用疏散通道", ["疏散通道被纸箱堵塞", "通行受阻"])
    ]
    evidence = [_law("不得占用、堵塞、封闭疏散通道、安全出口、消防车通道")]
    result = judge_evidence(findings, evidence)
    assert result.supported is True
    assert result.support_score > 0.5
    assert result.evidence_ids
    assert result.findings[0].evidence_ids
    assert result.findings[0].evidence_ids == ["law-第二十八条"]
    assert result.findings[0].visual_evidence_ok is True
    assert result.findings[0].needs_human_review is False
    assert result.retrieval_evidence_count == 1


def test_evidence_judge_marks_missing_regulation_as_insufficient():
    findings = [_finding("f1", "电气线路隐患", ["电线裸露"])]
    result = judge_evidence(findings, [])
    assert result.supported is False
    assert result.needs_human_review is True
    assert result.findings[0].unsupported_claims
    assert result.findings[0].evidence_ids == []


def test_hint_finding_without_visual_facts_requires_review():
    findings = [
        {
            "finding_id": "f2",
            "category": "野外用火风险",
            "observed_facts": [],
        }
    ]
    evidence = [_law("森林防火期内，禁止在森林防火区野外用火", article="第二十五条")]
    result = judge_evidence(findings, evidence)
    assert result.findings[0].visual_evidence_ok is False
    assert result.findings[0].needs_human_review is True
    assert any("缺少视觉事实描述" in item for item in result.findings[0].unsupported_claims)


def test_partial_support_fails_overall():
    findings = [
        _finding("f1", "占用疏散通道", ["疏散通道被占"]),
        _finding("f2", "电气线路隐患", ["电线裸露"]),
    ]
    evidence = [_law("不得占用疏散通道、安全出口")]
    result = judge_evidence(findings, evidence)
    assert result.supported is False
    assert [item.finding_id for item in result.findings] == ["f1", "f2"]
    assert result.findings[0].supported is True
    assert result.findings[1].supported is False


def test_evidence_judge_ignores_demo_entries():
    findings = [
        _finding("f1", "占用疏散通道", ["疏散通道被纸箱堵塞"])
    ]
    evidence = [
        {
            "id": "demo-fire-001",
            "source": "示例知识库（演示用，非法律条文）",
            "version": "demo",
            "text": "演示条目：疏散通道不得堆放物品。",
            "score": 0.9,
        }
    ]
    result = judge_evidence(findings, evidence)
    assert result.supported is False
    assert result.retrieval_evidence_count == 0
    assert result.findings[0].evidence_ids == []
    assert result.findings[0].unsupported_claims
    assert result.needs_human_review is True


def test_evidence_judge_rejects_placeholder_visual_facts():
    findings = [
        {
            "finding_id": "f1",
            "category": "占用疏散通道",
            "observed_facts": ["照片特征待人工确认"],
        }
    ]
    evidence = [_law("不得占用疏散通道、安全出口")]
    result = judge_evidence(findings, evidence)
    assert result.findings[0].visual_evidence_ok is False
    assert result.findings[0].needs_human_review is True
    assert any("占位" in item for item in result.findings[0].unsupported_claims)
    assert result.visual_evidence_count == 0


def test_neutral_regulation_does_not_support_finding():
    findings = [
        _finding("f1", "占用疏散通道", ["疏散通道被纸箱堵塞"])
    ]
    evidence = [
        {
            "id": "law-neutral",
            "source": "官方",
            "article": "第二十八条",
            "text": "疏散通道和安全出口应设置清晰标识。",
            "score": 0.8,
        }
    ]
    result = judge_evidence(findings, evidence)
    assert result.findings[0].supported is False
    assert any("法规文本未覆盖" in item for item in result.findings[0].unsupported_claims)
    assert result.needs_human_review is True


def test_evidence_judge_has_version():
    result = judge_evidence([], [])
    assert result.version == "v1"


def test_workflow_writes_evidence_back_to_findings():
    from app.services.workflow import run_workflow

    state = run_workflow(description="小区楼道堆放纸箱杂物，堵塞疏散通道", images=[])
    assert state["evidence_judge"]["supported"] is True
    assert state["evidence_guard"]["supported"] is True
    finding = state["ensemble_judge"]["final_findings"][0]
    assert finding["evidence_status"] == "supported"
    assert finding["support_score"] is not None
    assert finding["evidence_ids"]
    assert finding["unsupported_claims"] == []
