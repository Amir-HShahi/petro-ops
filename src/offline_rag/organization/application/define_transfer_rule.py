"""Use case: set what a Layer requires of the TransferPackages it receives (spec §10.1)."""

import structlog

from offline_rag.organization.application.commands import DefineTransferRule
from offline_rag.organization.application.ports import Clock, EventPublisher, LayerRepository
from offline_rag.organization.domain.layer import Layer
from offline_rag.organization.domain.transfer_rule import TransferRule

log = structlog.get_logger()


class DefineTransferRuleHandler:
    """Replaces the detail level and transfer rules of one Layer."""

    def __init__(
        self,
        *,
        layer_repository: LayerRepository,
        clock: Clock,
        event_publisher: EventPublisher,
    ) -> None:
        """Create the handler with the ports it needs."""
        self._layer_repository = layer_repository
        self._clock = clock
        self._event_publisher = event_publisher

    def define(self, command: DefineTransferRule) -> Layer:
        """Store the rules on the Layer and return it.

        Raises:
            LayerNotFoundError: The Layer is not in the registry.
            LayerReceivesNoTransferPackageError: The Layer is Layer 4.
            TransferTopicRequiredAndExcludedError: A topic is in both lists.
            EmptyTransferRuleFieldError: A topic or a text field is blank.
            InvalidPackageLengthError: The length is not a positive number of tokens.
        """
        transfer_rule = TransferRule(
            required_topics=command.required_topics,
            excluded_topics=command.excluded_topics,
            output_format=command.output_format,
            min_judge_score=command.min_judge_score,
            max_package_length_tokens=command.max_package_length_tokens,
            source_reference_level=command.source_reference_level,
        )
        layer = self._layer_repository.get_by_index(command.layer_index)
        layer.define_transfer_rule(
            received_detail_level=command.received_detail_level,
            transfer_rule=transfer_rule,
            defined_at=self._clock.now(),
        )
        self._layer_repository.save(layer)
        self._event_publisher.publish(layer.pull_events())
        log.info(
            "layer_transfer_rule_defined",
            layer_index=layer.layer_index.value,
            detail_level=command.received_detail_level.value,
            required_topics=len(transfer_rule.required_topics),
            excluded_topics=len(transfer_rule.excluded_topics),
            min_judge_score=transfer_rule.min_judge_score.points,
            max_package_length_tokens=transfer_rule.max_package_length_tokens,
        )
        return layer
