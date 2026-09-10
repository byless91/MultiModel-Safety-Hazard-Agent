from app.services.rectification_assessment import (
    RESOLVED_THRESHOLD,
    RULE_VERSION,
    assess_rectification_completion,
)


def _pair_counts(original: int = 1, rectification: int = 1) -> dict:
    pair_count = min(original, rectification)
    return {
        "original_count": original,
        "rectification_count": rectification,
        "pair_count": pair_count,
        "unmatched_original_count": original - pair_count,
        "unmatched_rectification_count": rectification - pair_count,
    }


def test_no_after_photos_is_insufficient_evidence():
    result = assess_rectification_completion(
        comparison=_pair_counts(original=1, rectification=0)
    )
    assert result.verdict == "insufficient_evidence"
    assert result.completion_score is None
    assert result.review_required is True
    assert "missing_after_photos" in result.triggered_rules


def test_low_score_is_not_resolved():
    result = assess_rectification_completion(
        provider_result={"completion_score": 0.4, "issues": []},
        comparison=_pair_counts(),
    )
    assert result.verdict == "not_resolved"
    assert result.completion_score == 0.4
    assert "score_below_threshold" in result.triggered_rules


def test_high_score_without_issues_is_resolved_recommended():
    result = assess_rectification_completion(
        provider_result={
            "completion_score": RESOLVED_THRESHOLD + 0.1,
            "issues": [],
        },
        comparison=_pair_counts(),
    )
    assert result.verdict == "resolved_recommended"
    assert result.review_required is False
    assert "score_above_threshold" in result.triggered_rules
    assert result.rule_version == RULE_VERSION


def test_high_score_with_issues_needs_review():
    result = assess_rectification_completion(
        provider_result={
            "completion_score": 0.9,
            "issues": ["仍有纸箱堆放在通道"],
        },
        comparison=_pair_counts(),
    )
    assert result.verdict == "needs_review"
    assert result.review_required is True
    assert any("结论冲突" in item for item in result.reasons)


def test_missing_before_photos_requires_review():
    result = assess_rectification_completion(
        provider_result={"completion_score": 0.9, "issues": []},
        comparison=_pair_counts(original=0, rectification=1),
    )
    assert result.verdict == "needs_review"
    assert "missing_before_photos" in result.triggered_rules
    assert result.completion_confidence < 0.9


def test_unmatched_images_requires_review():
    result = assess_rectification_completion(
        provider_result={"completion_score": 0.9, "issues": []},
        comparison=_pair_counts(original=2, rectification=1),
    )
    assert result.verdict == "needs_review"
    assert "unmatched_image_counts" in result.triggered_rules


def test_provider_failure_is_insufficient_evidence():
    result = assess_rectification_completion(
        provider_result=None,
        comparison=_pair_counts(),
        provider_failed=True,
    )
    assert result.verdict == "insufficient_evidence"
    assert result.provider_ok is False
    assert result.review_required is True
