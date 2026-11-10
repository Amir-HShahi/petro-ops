import pytest

from offline_rag.knowledge.application.ports import IngestionLane
from offline_rag.knowledge.interface import cli
from offline_rag.settings import Settings


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, object]]:
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(cli, "run_worker", lambda lane, settings: calls.append(("worker", lane)))
    monkeypatch.setattr(cli, "run_relay", lambda settings: calls.append(("relay", None)))
    monkeypatch.setattr(cli, "run_api", lambda settings: calls.append(("api", None)))
    return calls


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["worker", "run", "--lane", "text"], ("worker", IngestionLane.TEXT)),
        (["worker", "run", "--lane", "vision"], ("worker", IngestionLane.VISION)),
        (["worker", "run", "--lane", "chunking"], ("worker", IngestionLane.CHUNKING)),
        (["relay", "run"], ("relay", None)),
        (["api", "run"], ("api", None)),
    ],
)
def test_long_running_process_starts_when_its_run_command_is_given(
    started: list[tuple[str, object]], arguments: list[str], expected: tuple[str, object]
):
    exit_code = cli.main(arguments, settings=Settings())

    assert exit_code == cli.EXIT_OK
    assert started == [expected]


def test_worker_is_refused_when_the_lane_is_unknown(started: list[tuple[str, object]]):
    with pytest.raises(SystemExit):
        cli.main(["worker", "run", "--lane", "audio"], settings=Settings())

    assert started == []


@pytest.mark.parametrize("command", ["show-content", "show-chunks", "reingest"])
def test_version_option_is_read_as_the_version_tag_when_given(command: str):
    arguments = cli.build_parser().parse_args([command, "ki-1", "--version", "v2"])

    assert arguments.version_tag == "v2"


@pytest.mark.parametrize("command", ["show-content", "show-chunks", "reingest"])
def test_version_tag_is_left_to_the_use_case_when_no_version_is_given(command: str):
    arguments = cli.build_parser().parse_args([command, "ki-1"])

    assert arguments.version_tag is None


def test_publish_version_reads_the_item_file_and_change_reason_when_given():
    arguments = cli.build_parser().parse_args(
        ["publish-version", "ki-1", "report_v2.docx", "--change-reason", "Adds 3 readings."]
    )

    assert (arguments.item_id, arguments.file.name, arguments.change_reason) == (
        "ki-1",
        "report_v2.docx",
        "Adds 3 readings.",
    )


def test_publish_version_is_refused_when_no_change_reason_is_given():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["publish-version", "ki-1", "report_v2.docx"])
