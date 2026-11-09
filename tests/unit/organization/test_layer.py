from datetime import UTC, datetime

import pytest

from offline_rag.organization.domain.errors import (
    InvalidLayerDetailLevelError,
    LayerReceivesNoTransferPackageError,
)
from offline_rag.organization.domain.events import LayerTransferRuleDefined
from offline_rag.organization.domain.layer import Layer
from offline_rag.organization.domain.transfer_detail_level import TransferDetailLevel
from offline_rag.organization.domain.transfer_rule import TransferRule
from offline_rag.shared_kernel.judge_threshold import JudgeThreshold
from offline_rag.shared_kernel.layer_index import LayerIndex


def _layer(index: int, detail_level: TransferDetailLevel | None) -> Layer:
    return Layer(
        layer_index=LayerIndex(index),
        name="Parent organizations",
        role="Regional operators",
        received_detail_level=detail_level,
    )


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_layer_receives_a_package_when_it_has_a_detail_level(index: int):
    layer = _layer(index, TransferDetailLevel.MANAGERIAL)

    assert layer.receives_transfer_package
    assert layer.received_detail_level == TransferDetailLevel.MANAGERIAL


def test_layer_four_receives_no_package_when_it_has_no_detail_level():
    assert not _layer(4, None).receives_transfer_package


def test_layer_four_is_rejected_when_given_a_detail_level():
    with pytest.raises(InvalidLayerDetailLevelError) as caught:
        _layer(4, TransferDetailLevel.DETAILED_TECHNICAL)

    assert caught.value.code == "ORGANIZATION_INVALID_LAYER_DETAIL_LEVEL"
    assert caught.value.details == {"layer_index": 4, "detail_level": "detailed_technical"}


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_layer_is_rejected_when_it_lacks_a_detail_level(index: int):
    with pytest.raises(InvalidLayerDetailLevelError) as caught:
        _layer(index, None)

    assert caught.value.details == {"layer_index": index, "detail_level": None}


def test_detail_levels_match_the_registry_when_listed():
    assert [level.value for level in TransferDetailLevel] == [
        "top_executive",
        "managerial",
        "technical_summary",
        "detailed_technical",
    ]


DEFINED_AT = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
RULE = TransferRule(
    required_topics=("key risks",),
    excluded_topics=("shift rosters",),
    output_format="markdown",
    min_judge_score=JudgeThreshold(18),
    max_package_length_tokens=1500,
    source_reference_level="document",
)


def test_layer_has_no_transfer_rule_when_none_is_defined():
    assert _layer(1, TransferDetailLevel.MANAGERIAL).transfer_rule is None


def test_layer_keeps_rule_and_detail_level_when_rule_is_defined():
    layer = _layer(1, TransferDetailLevel.MANAGERIAL)

    layer.define_transfer_rule(
        received_detail_level=TransferDetailLevel.TOP_EXECUTIVE,
        transfer_rule=RULE,
        defined_at=DEFINED_AT,
    )

    assert layer.transfer_rule == RULE
    assert layer.received_detail_level == TransferDetailLevel.TOP_EXECUTIVE
    assert layer.pull_events() == (
        LayerTransferRuleDefined(
            occurred_at=DEFINED_AT,
            layer_index=LayerIndex(1),
            received_detail_level=TransferDetailLevel.TOP_EXECUTIVE,
            transfer_rule=RULE,
        ),
    )
    assert layer.pull_events() == ()


def test_layer_four_is_rejected_when_a_rule_is_defined():
    layer = _layer(4, None)

    with pytest.raises(LayerReceivesNoTransferPackageError) as caught:
        layer.define_transfer_rule(
            received_detail_level=TransferDetailLevel.DETAILED_TECHNICAL,
            transfer_rule=RULE,
            defined_at=DEFINED_AT,
        )

    assert caught.value.code == "ORGANIZATION_LAYER_RECEIVES_NO_PACKAGE"
    assert caught.value.details == {"layer_index": 4}
    assert layer.transfer_rule is None
    assert layer.pull_events() == ()


def test_layer_four_is_rejected_when_rebuilt_with_a_rule():
    with pytest.raises(LayerReceivesNoTransferPackageError):
        Layer(
            layer_index=LayerIndex(4),
            name="Knowledge sources",
            role="Archive",
            received_detail_level=None,
            transfer_rule=RULE,
        )


def test_layers_are_equal_when_they_share_an_index():
    assert _layer(2, TransferDetailLevel.MANAGERIAL) == _layer(2, TransferDetailLevel.TOP_EXECUTIVE)
    assert hash(_layer(2, TransferDetailLevel.MANAGERIAL)) == hash(LayerIndex(2))
