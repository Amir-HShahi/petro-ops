"""A token count estimated from the text length, with no model loaded (ADR 0009)."""

import math

CHARACTERS_PER_TOKEN = 4


class ApproximateTokenizer:
    """Counts one token per four characters, rounded up.

    That is close for English text in common subword tokenizers. Persian text may
    need more tokens per character, which is why ADR 0009 keeps the hard limit far
    below the embedding model's 2048-token context.
    """

    def count_tokens(self, text: str) -> int:
        """Return the estimated number of tokens in the text."""
        return math.ceil(len(text) / CHARACTERS_PER_TOKEN)
