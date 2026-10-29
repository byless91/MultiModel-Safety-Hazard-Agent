"""M1 human values must be explicit and belong to a recorded taxonomy."""

import pytest
from app.schemas.classification import ClassificationSaveIn
from pydantic import ValidationError


@pytest.mark.parametrize("level", [None, 1, 2, 3])
def test_human_risk_is_optional(level):
    value = ClassificationSaveIn(category="其他隐患", risk_level=level, revision=0)
    assert value.risk_level == level
    assert value.taxonomy_version == "m1-v1"


@pytest.mark.parametrize("changes", [
    {"risk_level": True}, {"risk_level": "2"}, {"risk_level": 0}, {"risk_level": 4},
    {"category": "模型臆造类别"}, {"tags": ["无此标签"]}, {"taxonomy_version": "future"},
    {"revision": -1}, {"confirmed": True},
])
def test_invalid_human_values_are_rejected(changes):
    with pytest.raises(ValidationError):
        ClassificationSaveIn.model_validate({"category": "其他隐患", "revision": 0, **changes})
