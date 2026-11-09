import pytest

from offline_rag.shared_kernel.errors import InvalidJudgeThresholdError
from offline_rag.shared_kernel.judge_threshold import (
    DEFAULT_JUDGE_THRESHOLD_POINTS,
    JudgeThreshold,
)


@pytest.mark.parametrize("points", [1, 18, 20])
def test_threshold_keeps_its_points_when_in_range(points: int):
    assert JudgeThreshold(points).points == points


def test_default_threshold_is_eighteen_of_twenty_when_read():
    assert str(JudgeThreshold(DEFAULT_JUDGE_THRESHOLD_POINTS)) == "18/20"


@pytest.mark.parametrize("points", [0, 21, -3, True, 18.5, "18"])
def test_threshold_is_rejected_when_not_a_whole_number_from_one_to_twenty(points: object):
    with pytest.raises(InvalidJudgeThresholdError) as caught:
        JudgeThreshold(points)  # type: ignore[arg-type]

    assert caught.value.code == "EVALUATION_INVALID_JUDGE_THRESHOLD"
    assert caught.value.details == {"value": points}
