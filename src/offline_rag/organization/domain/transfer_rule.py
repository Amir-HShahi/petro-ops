"""What a Layer requires of the TransferPackages it receives (spec §10.1)."""

from dataclasses import dataclass

from offline_rag.organization.domain.errors import (
    EmptyTransferRuleFieldError,
    InvalidPackageLengthError,
    TransferTopicRequiredAndExcludedError,
)
from offline_rag.shared_kernel.judge_threshold import JudgeThreshold


@dataclass(frozen=True, kw_only=True)
class TransferRule:
    """The transfer rules of one Layer (spec §10.1, docs/domain-model.md section 1).

    The required fields for Issue status, research gaps, achievements, project
    completion and RFPs in §10.1 wait for phase 11, when those concepts exist.

    Invariants:
    - A topic is never both required and excluded.
    - Topics, the output format and the source reference level are not blank.
    - The maximum package length is a positive number of tokens.

    Attributes:
        required_topics: Topics every package must cover, in the order given.
        excluded_topics: Topics no package may include.
        output_format: The preferred format of a package, as free text for now.
        min_judge_score: The lowest judge score a package needs to be accepted.
        max_package_length_tokens: The longest a package may be, in tokens.
        source_reference_level: How precisely a package cites its sources, as free
            text for now.

    Raises:
        TransferTopicRequiredAndExcludedError: A topic is in both lists.
        EmptyTransferRuleFieldError: A topic or a text field is blank.
        InvalidPackageLengthError: The length is not a positive number.
    """

    required_topics: tuple[str, ...]
    excluded_topics: tuple[str, ...]
    output_format: str
    min_judge_score: JudgeThreshold
    max_package_length_tokens: int
    source_reference_level: str

    def __post_init__(self) -> None:
        for field_name in ("output_format", "source_reference_level"):
            if not getattr(self, field_name).strip():
                raise EmptyTransferRuleFieldError(field_name)
        for field_name in ("required_topics", "excluded_topics"):
            if any(not topic.strip() for topic in getattr(self, field_name)):
                raise EmptyTransferRuleFieldError(field_name)
        both = sorted(set(self.required_topics) & set(self.excluded_topics))
        if both:
            raise TransferTopicRequiredAndExcludedError(both)
        if (
            isinstance(self.max_package_length_tokens, bool)
            or not isinstance(self.max_package_length_tokens, int)
            or self.max_package_length_tokens < 1
        ):
            raise InvalidPackageLengthError(self.max_package_length_tokens)
