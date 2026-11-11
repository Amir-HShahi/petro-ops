from typing import Any

import pytest
from tests.fakes.knowledge import FakeClock, InMemoryEventPublisher
from tests.fakes.organization import InMemoryLayerRepository, registry_layers

from offline_rag.organization.application.commands import DefineTransferRule
from offline_rag.organization.application.define_transfer_rule import (
    DefineTransferRuleHandler,
)
from offline_rag.organization.application.errors import LayerNotFoundError
from offline_rag.organization.domain.errors import (
    LayerReceivesNoTransferPackageError,
    TransferTopicRequiredAndExcludedError,
)
from offline_rag.organization.domain.events import LayerTransferRuleDefined
from offline_rag.organization.domain.transfer_detail_level import TransferDetailLevel
from offline_rag.shared_kernel.judge_threshold import JudgeThreshold
from offline_rag.shared_kernel.layer_index import LayerIndex


def _command(layer: int = 1, **changes: Any) -> DefineTransferRule:
    values: dict[str, Any] = {
        "layer_index": LayerIndex(layer),
        "received_detail_level": TransferDetailLevel.MANAGERIAL,
        "required_topics": ("key risks", "achievements"),
        "excluded_topics": ("shift rosters",),
        "output_format": "markdown",
        "min_judge_score": JudgeThreshold(18),
        "max_package_length_tokens": 1500,
        "source_reference_level": "document",
    }
    return DefineTransferRule(**(values | changes))


@pytest.fixture
def layers() -> InMemoryLayerRepository:
    return InMemoryLayerRepository(registry_layers())


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
    return InMemoryEventPublisher()


@pytest.fixture
def handler(
    layers: InMemoryLayerRepository, publisher: InMemoryEventPublisher
) -> DefineTransferRuleHandler:
    return DefineTransferRuleHandler(
        layer_repository=layers, clock=FakeClock(), event_publisher=publisher
    )


def test_rule_is_stored_on_the_layer_when_defined(
    handler: DefineTransferRuleHandler, layers: InMemoryLayerRepository
):
    handler.define(_command(1, received_detail_level=TransferDetailLevel.TOP_EXECUTIVE))

    stored = layers.get_by_index(LayerIndex(1))
    assert stored.received_detail_level == TransferDetailLevel.TOP_EXECUTIVE
    assert stored.transfer_rule is not None
    assert stored.transfer_rule.required_topics == ("key risks", "achievements")
    assert stored.transfer_rule.max_package_length_tokens == 1500


def test_defined_event_is_published_when_rule_is_defined(
    handler: DefineTransferRuleHandler, publisher: InMemoryEventPublisher
):
    handler.define(_command(2))

    assert [type(event) for event in publisher.events] == [LayerTransferRuleDefined]


def test_new_rule_replaces_the_old_one_when_defined_again(
    handler: DefineTransferRuleHandler, layers: InMemoryLayerRepository
):
    handler.define(_command(1))
    handler.define(_command(1, max_package_length_tokens=800, required_topics=()))

    rule = layers.get_by_index(LayerIndex(1)).transfer_rule
    assert rule is not None
    assert rule.max_package_length_tokens == 800
    assert rule.required_topics == ()


def test_nothing_is_published_when_layer_four_is_given_a_rule(
    handler: DefineTransferRuleHandler,
    layers: InMemoryLayerRepository,
    publisher: InMemoryEventPublisher,
):
    with pytest.raises(LayerReceivesNoTransferPackageError):
        handler.define(_command(4))

    assert layers.get_by_index(LayerIndex(4)).transfer_rule is None
    assert publisher.events == []


def test_nothing_is_stored_when_the_rule_breaks_an_invariant(
    handler: DefineTransferRuleHandler,
    layers: InMemoryLayerRepository,
    publisher: InMemoryEventPublisher,
):
    with pytest.raises(TransferTopicRequiredAndExcludedError):
        handler.define(_command(1, excluded_topics=("key risks",)))

    assert layers.get_by_index(LayerIndex(1)).transfer_rule is None
    assert publisher.events == []


def test_rule_is_rejected_when_the_layer_is_not_loaded():
    handler = DefineTransferRuleHandler(
        layer_repository=InMemoryLayerRepository([]),
        clock=FakeClock(),
        event_publisher=InMemoryEventPublisher(),
    )

    with pytest.raises(LayerNotFoundError):
        handler.define(_command(1))
