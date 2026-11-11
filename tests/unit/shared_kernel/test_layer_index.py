import pytest

from offline_rag.shared_kernel.errors import InvalidLayerIndexError
from offline_rag.shared_kernel.layer_index import LayerIndex


@pytest.mark.parametrize("value", [0, 1, 2, 3, 4])
def test_layer_index_keeps_its_value_when_in_range(value: int):
    assert LayerIndex(value).value == value


@pytest.mark.parametrize("value", [-1, 5, True, 1.0, "2"])
def test_layer_index_is_rejected_when_not_a_whole_number_from_zero_to_four(value: object):
    with pytest.raises(InvalidLayerIndexError) as caught:
        LayerIndex(value)  # type: ignore[arg-type]

    assert caught.value.code == "ORGANIZATION_INVALID_LAYER_INDEX"
    assert caught.value.details == {"value": value}


def test_lower_index_is_above_when_compared():
    assert LayerIndex(1).is_above(LayerIndex(3))
    assert not LayerIndex(3).is_above(LayerIndex(1))
    assert not LayerIndex(2).is_above(LayerIndex(2))


def test_only_layer_zero_is_top_when_checked():
    assert [LayerIndex(value).is_top for value in range(5)] == [True, False, False, False, False]


def test_only_layer_four_is_knowledge_source_when_checked():
    assert [LayerIndex(value).is_knowledge_source for value in range(5)] == [
        False,
        False,
        False,
        False,
        True,
    ]
