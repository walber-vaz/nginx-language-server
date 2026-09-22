"""Import all parser functions to top of module."""

from . import nginxconf
from .data import (
    DIRECTIVES,
    VARIABLES,
    DirectiveDefinition,
    VariableDefinition,
)

__all__ = [
    "DIRECTIVES",
    "VARIABLES",
    "DirectiveDefinition",
    "VariableDefinition",
    "nginxconf",
]
