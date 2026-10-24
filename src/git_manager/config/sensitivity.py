"""Which config keys are sensitive: changing them needs the ``approve`` scope.

A key is sensitive when it, or any section above it, carries the ``SENSITIVE`` marker in
its ``Annotated`` metadata. The marker sits on the models, so a new field inside a
sensitive section is protected without touching this module.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import get_args, get_origin

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class Sensitive:
    """Marks a config field whose change could skip approval or widen what runs."""


SENSITIVE = Sensitive()


def _models_in(annotation: object) -> list[type[BaseModel]]:
    """Pydantic models reachable from an annotation (through lists, tuples and unions)."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    if get_origin(annotation) is not None:
        return [model for arg in get_args(annotation) for model in _models_in(arg)]
    return []


def is_sensitive(model: type[BaseModel], path: Sequence[str | int]) -> bool:
    """Whether changing the value at ``path`` (YAML keys and list indexes) is sensitive.

    Unknown keys are reported as sensitive, so a typo can never slip past the check.
    """
    current: list[type[BaseModel]] = [model]
    for part in path:
        if isinstance(part, int):
            # A list index: the element type is already in ``current``.
            continue
        fields = [
            candidate.model_fields[part] for candidate in current if part in candidate.model_fields
        ]
        if not fields:
            return True
        if any(SENSITIVE in field.metadata for field in fields):
            return True
        current = [found for field in fields for found in _models_in(field.annotation)]
    return False
