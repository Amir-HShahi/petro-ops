from typing import Any

import pytest

from offline_rag.organization.domain.errors import (
    EmptyTransferRuleFieldError,
    InvalidPackageLengthError,
    TransferTopicRequiredAndExcludedError,
)
from offline_rag.organization.domain.transfer_rule import TransferRule
from offline_rag.shared_kernel.judge_threshold import JudgeThreshold


def _rule(**changes: Any) -> TransferRule:
    values: dict[str, Any] = {
        "required_topics": ("key risks", "unresolved issues"),
        "excluded_topics": ("shift rosters",),
        "output_format": "markdown",
        "min_judge_score": JudgeThreshold(18),
        "max_package_length_tokens": 1500,
        "source_reference_level": "document",
    }
    return TransferRule(**(values | changes))


def test_rule_keeps_its_values_when_valid():
    rule = _rule()

    assert rule.required_topics == ("key risks", "unresolved issues")
    assert rule.excluded_topics == ("shift rosters",)
    assert rule.min_judge_score == JudgeThreshold(18)
    assert rule.max_package_length_tokens == 1500


def test_rule_is_valid_when_it_names_no_topics():
    assert _rule(required_topics=(), excluded_topics=()).required_topics == ()


def test_rule_is_rejected_when_a_topic_is_required_and_excluded():
    with pytest.raises(TransferTopicRequiredAndExcludedError) as caught:
        _rule(excluded_topics=("unresolved issues", "key risks"))

    assert caught.value.code == "ORGANIZATION_TRANSFER_TOPIC_REQUIRED_AND_EXCLUDED"
    assert caught.value.details == {"topics": ["key risks", "unresolved issues"]}


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"output_format": "  "}, "output_format"),
        ({"source_reference_level": ""}, "source_reference_level"),
        ({"required_topics": ("key risks", " ")}, "required_topics"),
        ({"excluded_topics": ("",)}, "excluded_topics"),
    ],
)
def test_rule_is_rejected_when_a_field_is_blank(changes: dict[str, Any], field: str):
    with pytest.raises(EmptyTransferRuleFieldError) as caught:
        _rule(**changes)

    assert caught.value.code == "ORGANIZATION_TRANSFER_RULE_FIELD_EMPTY"
    assert caught.value.details == {"field": field}


@pytest.mark.parametrize("length", [0, -100, True, 1500.0])
def test_rule_is_rejected_when_length_is_not_a_positive_whole_number(length: object):
    with pytest.raises(InvalidPackageLengthError) as caught:
        _rule(max_package_length_tokens=length)

    assert caught.value.code == "ORGANIZATION_INVALID_PACKAGE_LENGTH"
    assert caught.value.details == {"value": length}
