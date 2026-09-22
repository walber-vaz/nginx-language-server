"""Parsing of nginx configs and of the bundled directive data."""

from . import nginxconf
from .data import (
    DirectiveDefinition,
    VariableDefinition,
    directives_for,
    find_variable,
    variables_for,
)

__all__ = [
    "DirectiveDefinition",
    "VariableDefinition",
    "directives_for",
    "find_variable",
    "nginxconf",
    "variables_for",
]
