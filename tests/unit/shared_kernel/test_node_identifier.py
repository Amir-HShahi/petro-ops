import pytest

from offline_rag.shared_kernel.errors import InvalidNodeIdentifierError
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


def test_node_identifier_keeps_its_value_when_valid():
    node_id = NodeIdentifier("sp12_inspection_team")

    assert node_id.value == "sp12_inspection_team"
    assert str(node_id) == "sp12_inspection_team"
    assert node_id == NodeIdentifier("sp12_inspection_team")


@pytest.mark.parametrize("value", ["", " ", " platform_sp12", "platform_sp12 "])
def test_node_identifier_is_rejected_when_empty_or_padded(value: str):
    with pytest.raises(InvalidNodeIdentifierError) as caught:
        NodeIdentifier(value)

    assert caught.value.code == "ORGANIZATION_INVALID_NODE_IDENTIFIER"
    assert caught.value.details == {"value": value}
