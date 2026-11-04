"""Base classes for every error the core raises.

The contract shared with the backend and frontend is in `docs/errors.md`. Each
concrete error inherits from exactly one category below and sets a `code`.
"""

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, ClassVar

CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+")

_class_by_code: dict[str, type["ProjectError"]] = {}


class ProjectError(Exception):
    """Root of all project errors. Raise a concrete error, never this class.

    Attributes:
        code: Stable `CONTEXT_REASON` code. Clients act on it, never on the message.
        category: The category class the error belongs to. It decides the HTTP status.
    """

    code: ClassVar[str]
    category: ClassVar[type["ProjectError"]]
    _is_category: ClassVar[bool] = False

    def __init_subclass__(cls, *, is_category: bool = False, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._is_category = is_category
        if is_category:
            return
        if not cls.__name__.endswith("Error"):
            msg = f"Error class {cls.__qualname__} must have a name ending in 'Error'."
            raise TypeError(msg)
        categories = [
            base for base in cls.__mro__[1:] if issubclass(base, ProjectError) and base._is_category
        ]
        if len(categories) != 1:
            msg = f"{cls.__qualname__} must inherit from exactly one error category."
            raise TypeError(msg)
        cls.category = categories[0]
        _register_code(cls)

    def __init__(self, message: str, *, details: Mapping[str, object] | None = None) -> None:
        """Create the error.

        Args:
            message: What is wrong and, when known, what to do about it. Shown to
                users as is, so it must not contain stack traces, file paths or
                library errors.
            details: Structured values such as ids and limits, so callers never
                parse the message.
        """
        super().__init__(message)
        self.message = message
        self.details: Mapping[str, object] = MappingProxyType(dict(details or {}))


class DomainError(ProjectError, is_category=True):
    """A business rule was broken by the request."""


class NotFoundError(ProjectError, is_category=True):
    """The requested item does not exist."""


class InfrastructureError(ProjectError, is_category=True):
    """A model, database, file or other dependency failed."""


class UnexpectedError(ProjectError, is_category=True):
    """Anything not covered by the other categories. It always means a bug."""


def _register_code(error_class: type[ProjectError]) -> None:
    code = error_class.__dict__.get("code")
    if not isinstance(code, str) or not CODE_PATTERN.fullmatch(code):
        msg = f"{error_class.__qualname__} needs its own `code` in CONTEXT_REASON form."
        raise TypeError(msg)

    existing = _class_by_code.get(code)
    # The same class seen again, for example after a module reload, is not a clash.
    is_same_class = existing is not None and (existing.__module__, existing.__qualname__) == (
        error_class.__module__,
        error_class.__qualname__,
    )
    if existing is not None and not is_same_class:
        msg = f"Error code {code} is already used by {existing.__qualname__}."
        raise TypeError(msg)
    _class_by_code[code] = error_class
