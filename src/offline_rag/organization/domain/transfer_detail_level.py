"""How detailed the knowledge is that a Layer receives from the Layer below."""

from enum import StrEnum


class TransferDetailLevel(StrEnum):
    """Detail level of a TransferPackage, from the most summarised to the most detailed.

    The values are the set of spec §6.4, as used in `fixtures/registry/layers.csv`
    (open question 2 in `docs/domain-model.md`, option a).
    """

    TOP_EXECUTIVE = "top_executive"
    MANAGERIAL = "managerial"
    TECHNICAL_SUMMARY = "technical_summary"
    DETAILED_TECHNICAL = "detailed_technical"
