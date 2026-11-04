import pytest

from offline_rag.shared_kernel.errors import (
    DomainError,
    InfrastructureError,
    NotFoundError,
    ProjectError,
    UnexpectedError,
)


class SampleDomainError(DomainError):
    code = "TEST_SAMPLE_DOMAIN"


class SampleNotFoundError(NotFoundError):
    code = "TEST_SAMPLE_NOT_FOUND"


class SampleInfrastructureError(InfrastructureError):
    code = "TEST_SAMPLE_INFRASTRUCTURE"


class SampleUnexpectedError(UnexpectedError):
    code = "TEST_SAMPLE_UNEXPECTED"


def test_error_keeps_code_message_and_details_when_raised():
    message = "Item a17 duplicates b42."

    with pytest.raises(SampleDomainError) as caught:
        raise SampleDomainError(message, details={"item_id": "a17"})

    assert caught.value.code == "TEST_SAMPLE_DOMAIN"
    assert caught.value.message == "Item a17 duplicates b42."
    assert str(caught.value) == "Item a17 duplicates b42."
    assert caught.value.details == {"item_id": "a17"}


def test_details_are_empty_when_not_given():
    assert SampleDomainError("Broken rule.").details == {}


def test_details_cannot_be_changed_when_error_exists():
    source = {"limit_mb": 50}
    error = SampleDomainError("File too large.", details=source)

    source["limit_mb"] = 1

    assert error.details == {"limit_mb": 50}
    with pytest.raises(TypeError):
        error.details["limit_mb"] = 1  # type: ignore[index]


@pytest.mark.parametrize(
    ("error_class", "category"),
    [
        (SampleDomainError, DomainError),
        (SampleNotFoundError, NotFoundError),
        (SampleInfrastructureError, InfrastructureError),
        (SampleUnexpectedError, UnexpectedError),
    ],
)
def test_error_reports_its_category_when_defined(
    error_class: type[ProjectError], category: type[ProjectError]
):
    assert error_class.category is category
    assert issubclass(error_class, category)


def test_error_is_caught_by_its_category_when_raised():
    message = "Node N7 does not exist."

    with pytest.raises(NotFoundError):
        raise SampleNotFoundError(message)


def test_definition_fails_when_error_skips_the_categories():
    with pytest.raises(TypeError, match="exactly one error category"):

        class RootOnlyError(ProjectError):
            code = "TEST_ROOT_ONLY"


def test_definition_fails_when_error_has_two_categories():
    with pytest.raises(TypeError, match="exactly one error category"):

        class TwoCategoriesError(DomainError, NotFoundError):
            code = "TEST_TWO_CATEGORIES"


def test_definition_fails_when_name_does_not_end_in_error():
    with pytest.raises(TypeError, match="ending in 'Error'"):
        type("SampleProblem", (DomainError,), {"code": "TEST_SAMPLE_PROBLEM"})


def test_definition_fails_when_code_is_missing():
    with pytest.raises(TypeError, match="needs its own `code`"):

        class NoCodeError(DomainError):
            pass


def test_definition_fails_when_code_is_only_inherited():
    with pytest.raises(TypeError, match="needs its own `code`"):

        class InheritedCodeError(SampleDomainError):
            pass


@pytest.mark.parametrize("code", ["DUPLICATE", "knowledge_duplicate", "KNOWLEDGE-DUPLICATE", ""])
def test_definition_fails_when_code_is_not_context_reason(code: str):
    with pytest.raises(TypeError, match="CONTEXT_REASON"):
        type("BadCodeError", (DomainError,), {"code": code})


def test_definition_fails_when_code_is_already_used():
    with pytest.raises(TypeError, match="already used by SampleDomainError"):

        class OtherDomainError(DomainError):
            code = "TEST_SAMPLE_DOMAIN"
