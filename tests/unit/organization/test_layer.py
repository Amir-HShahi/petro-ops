import pytest

from offline_rag.organization.domain.errors import InvalidLayerDetailLevelError
from offline_rag.organization.domain.layer import Layer
from offline_rag.organization.domain.transfer_detail_level import TransferDetailLevel
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
