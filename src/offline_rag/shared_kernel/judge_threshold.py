"""The lowest judge score an output needs, shared by every context that gates on a judge."""

from dataclasses import dataclass

from offline_rag.shared_kernel.errors import InvalidJudgeThresholdError

MAX_JUDGE_SCORE_POINTS = 20
DEFAULT_JUDGE_THRESHOLD_POINTS = 18


@dataclass(frozen=True, slots=True)
class JudgeThreshold:
    """Minimum acceptable judge score, out of 20 points, such as 18 (spec §5.3, §16.1).

    Raises:
        InvalidJudgeThresholdError: The value is not a whole number from 1 to 20.
    """

    points: int

    def __post_init__(self) -> None:
        # bool is an int in Python, so `True` would otherwise pass as 1 point.
        if (
            isinstance(self.points, bool)
            or not isinstance(self.points, int)
            or not 1 <= self.points <= MAX_JUDGE_SCORE_POINTS
        ):
            raise InvalidJudgeThresholdError(self.points)

    def __str__(self) -> str:
        return f"{self.points}/{MAX_JUDGE_SCORE_POINTS}"
