import json
from pathlib import Path

import pytest

from offline_rag.issue.application.errors import KnowledgeTooLargeError
from offline_rag.issue.application.ports import KnowledgePassage
from offline_rag.issue.domain.sub_issue_candidate import Citation
from offline_rag.issue.infrastructure.errors import (
    DecompositionAnswerInvalidError,
    ModelUnavailableError,
    ModelUrlNotLocalError,
)
from offline_rag.issue.infrastructure.model_registry import RegisteredPrompt
from offline_rag.issue.infrastructure.ollama_issue_decomposer import (
    OllamaIssueDecomposer,
    format_passages,
    parse_decomposition,
)

ROOT = Path(__file__).parents[3]
PASSAGE = KnowledgePassage(
    item_id="ins-02-v2", page_or_section="4. Recommendation", text="Install a wrap.", token_count=5
)


def _answer(**changes: object) -> str:
    answer: dict[str, object] = {
        "sub_issues": [
            {
                "title": "Reduced survey interval",
                "description": "Survey every 6 months.",
                "position": 2,
                "citations": [],
            },
            {
                "title": "Temporary wrap",
                "description": "Wrap the splash zone.",
                "position": 1,
                "citations": [
                    {"doc_id": "ins-02-v2", "page_or_section": "4.", "quote": "Install a wrap."},
                    {"doc_id": "ins-02-v2", "page_or_section": "4.", "quote": " "},
                ],
            },
        ],
        "missing_information": "  ",
    }
    return json.dumps(answer | changes)


def _decomposer(url: str = "http://127.0.0.1:9") -> OllamaIssueDecomposer:
    return OllamaIssueDecomposer(
        base_url=url,
        timeout_s=2,
        prompts_dir=ROOT / "prompts",
        model_manifest_path=ROOT / "models" / "manifest.yaml",
    )


def test_suggestions_follow_their_position_when_the_answer_is_valid():
    decomposition = parse_decomposition(_answer())

    assert decomposition is not None
    assert [(c.number, c.title) for c in decomposition.candidates] == [
        (1, "Temporary wrap"),
        (2, "Reduced survey interval"),
    ]
    assert decomposition.candidates[0].citations == (
        Citation(doc_id="ins-02-v2", page_or_section="4.", quote="Install a wrap."),
    )
    assert decomposition.missing_information is None


@pytest.mark.parametrize(
    "answer",
    [
        "not json",
        json.dumps({"missing_information": "all"}),
        _answer(sub_issues="many"),
        _answer(sub_issues=[{"title": "", "description": "D", "position": 1, "citations": []}]),
        _answer(missing_information=3),
    ],
)
def test_answer_is_refused_when_it_is_not_the_expected_json(answer: str):
    assert parse_decomposition(answer) is None


def test_passages_are_given_under_the_ids_they_are_cited_by_when_formatted():
    untitled = KnowledgePassage(item_id="ins-01", page_or_section="", text=" Text. ", token_count=1)

    assert format_passages([PASSAGE, untitled]) == (
        "[doc_id: ins-02-v2 | page_or_section: 4. Recommendation]\nInstall a wrap.\n\n"
        "[doc_id: ins-01 | page_or_section: -]\nText."
    )


def test_decomposer_is_refused_when_the_server_is_not_on_this_machine():
    with pytest.raises(ModelUrlNotLocalError):
        _decomposer("http://10.0.0.5:11434")


def test_model_is_not_asked_when_the_knowledge_does_not_fit():
    huge = KnowledgePassage(item_id="big", page_or_section="", text="x", token_count=50_000)

    with pytest.raises(KnowledgeTooLargeError) as caught:
        _decomposer().decompose(title="T", description="D", passages=[huge])

    assert caught.value.details["token_count"] == 50_000


def test_model_unavailable_is_raised_when_nothing_listens():
    with pytest.raises(ModelUnavailableError):
        _decomposer().decompose(title="T", description="D", passages=[PASSAGE])


def test_second_answer_is_used_when_the_first_is_malformed(monkeypatch: pytest.MonkeyPatch):
    answers = iter(["{", _answer()])
    prompts: list[str] = []

    def fake_chat(_self: OllamaIssueDecomposer, _prompt: RegisteredPrompt, text: str) -> str:
        prompts.append(text)
        return next(answers)

    monkeypatch.setattr(OllamaIssueDecomposer, "_chat", fake_chat)

    decomposition = _decomposer().decompose(
        title="Riser R-3 corrosion", description="Wall loss.", passages=[PASSAGE]
    )

    assert len(decomposition.candidates) == 2
    assert "Riser R-3 corrosion" in prompts[0]
    assert "[doc_id: ins-02-v2 | page_or_section: 4. Recommendation]" in prompts[0]
    assert "{context}" not in prompts[0]


def test_decomposition_fails_when_every_answer_is_malformed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(OllamaIssueDecomposer, "_chat", lambda *_: "not json")

    with pytest.raises(DecompositionAnswerInvalidError) as caught:
        _decomposer().decompose(title="T", description="D", passages=[PASSAGE])

    assert caught.value.details["attempts"] == 2
