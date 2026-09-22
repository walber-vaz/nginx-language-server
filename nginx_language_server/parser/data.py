"""Load directive and variable definitions from the data folder."""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from .utils import wrap_plain_text, wrap_rich_text

ListDicts = list[dict[str, Any]]


def _finish(result: str) -> str:
    return result.replace("“", '"').replace("”", '"').strip()


def _description(desc: str) -> str:
    desc = wrap_rich_text(desc.strip())
    if desc.endswith(":"):
        desc = desc[:-1] + "."
    return desc


@dataclass(frozen=True, slots=True)
class DirectiveDefinition:
    """Strongly typed directive, from directives.json."""

    name: str
    syntax: list[str]
    default: str | None
    contexts: list[str]
    desc: str
    notes: list[str]
    since: str | None
    module: str

    ls_detail: str = field(init=False)
    ls_documentation: str = field(init=False)

    def __post_init__(self) -> None:
        """Compute the language server strings once."""
        object.__setattr__(self, "ls_detail", f"dir: {self.name}")
        object.__setattr__(self, "ls_documentation", self._documentation())

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> DirectiveDefinition:
        """Build from a raw directives.json entry."""
        return cls(
            name=raw["name"],
            syntax=raw["syntax"],
            default=raw["def"],
            contexts=raw["contexts"],
            desc=raw["desc"],
            notes=raw["notes"],
            since=raw["since"],
            module=raw["module"],
        )

    def _documentation(self) -> str:
        result = ""
        if self.default:
            result += (
                "```nginx\n"
                + wrap_plain_text(";\n".join(self.default.split(";")))
                + "\n```\n\n"
            )
        if self.desc:
            result += _description(self.desc)
        if self.syntax:
            result += "\n\n"
            result += (
                "```nginx\n"
                + textwrap.indent(
                    wrap_plain_text("\n".join(self.syntax)),
                    "  ",
                )
                + "\n```"
            )
        if self.contexts:
            result += "\n"
            result += wrap_plain_text(
                "**Contexts:** `" + ", ".join(self.contexts) + "`"
            )
        if self.module:
            result += "\n"
            result += wrap_rich_text("**Module:** " + self.module)
        if self.since:
            result += "\n"
            result += wrap_rich_text("**Since:** " + self.since)
        if self.notes:
            result += "\n\n*Notes:*"
            notes = [wrap_rich_text(note) for note in self.notes]
            if len(notes) == 1:
                result += notes[0]
            else:
                result += "\n- " + "\n- ".join(notes)
        return _finish(result)


@dataclass(frozen=True, slots=True)
class VariableDefinition:
    """Strongly typed variable, from variables.json."""

    name: str
    desc: str
    module: str

    ls_detail: str = field(init=False)
    ls_documentation: str = field(init=False)

    def __post_init__(self) -> None:
        """Compute the language server strings once."""
        object.__setattr__(self, "ls_detail", f"var: {self.name}")
        object.__setattr__(self, "ls_documentation", self._documentation())

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> VariableDefinition:
        """Build from a raw variables.json entry."""
        return cls(name=raw["name"], desc=raw["desc"], module=raw["module"])

    def _documentation(self) -> str:
        result = ""
        if self.desc:
            result += _description(self.desc)
        if self.module:
            result += "\n\n"
            result += wrap_rich_text("**Module:** " + self.module)
        return _finish(result)


# nested directive, with context and directive name as keys
DirectiveDefinitionLookup = dict[str, dict[str, DirectiveDefinition]]
VariableDefinitionLookup = dict[str, VariableDefinition]


def load_raw_data(basename: str) -> ListDicts:
    """Read a JSON file shipped in the package's data folder."""
    data = resources.files("nginx_language_server") / "data" / basename
    return json.loads(data.read_text(encoding="utf-8"))


def get_directives(directives: ListDicts) -> DirectiveDefinitionLookup:
    """Translate raw JSON directives into cleaned output."""
    output: DirectiveDefinitionLookup = {}
    for raw in directives:
        directive = DirectiveDefinition.from_json(raw)
        for context in directive.contexts:
            output.setdefault(context, {})[directive.name] = directive
    return output


def get_variables(variables: ListDicts) -> VariableDefinitionLookup:
    """Translate raw JSON data into cleaned output."""
    output: VariableDefinitionLookup = {}
    for raw in variables:
        variable = VariableDefinition.from_json(raw)
        output[variable.name] = variable
    return output


DIRECTIVES = get_directives(load_raw_data("directives.json"))
VARIABLES = get_variables(load_raw_data("variables.json"))
