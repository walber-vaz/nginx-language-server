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


FAMILIES = ("http", "stream", "mail")
CORE = "core"
# Contexts that do not depend on the top-level block they are in
GLOBAL_CONTEXTS = ("main", "events", "any")
_HTTP_ONLY_CONTEXTS = {"location", "if", "ifinlocation", "limit_except"}

# Variables whose name ends with an arbitrary part, e.g. $arg_foo. Keys are
# the prefix as written in configs, values the entry name in variables.json.
PREFIX_VARIABLES = {
    prefix: prefix + "name"
    for prefix in (
        "$arg_",
        "$cookie_",
        "$http_",
        "$jwt_claim_",
        "$jwt_header_",
        "$sent_http_",
        "$sent_trailer_",
        "$upstream_cookie_",
        "$upstream_http_",
        "$upstream_trailer_",
    )
}


def module_family(module: str, contexts: list[str] | None = None) -> str:
    """Return which top-level block family a module belongs to."""
    for family in FAMILIES:
        if module.startswith(f"ngx_{family}_"):
            return family
    # e.g. ngx_otel_module is http-only despite its name; directives that
    # span several families (error_log) or none (worker_processes) are core
    contexts = contexts or []
    found = {family for family in FAMILIES if family in contexts}
    if _HTTP_ONLY_CONTEXTS.intersection(contexts):
        found.add("http")
    return found.pop() if len(found) == 1 else CORE


def context_keys(stack: list[str]) -> list[str]:
    """Return lookup keys for the directives allowed in a block stack.

    ``stack`` holds the names of the enclosing blocks, outermost first.
    Keys look like ``"main"``, ``"events"`` or ``"<family>/<context>"``.
    """
    if not stack:
        return ["main"]
    last = stack[-1]
    if last == "events":
        return ["events"]
    contexts = [last]
    if last == "if" and len(stack) >= 2 and stack[-2] == "location":
        contexts.append("ifinlocation")
    root = stack[0]
    if root in FAMILIES:
        families = [CORE, root]
    else:
        # A file included from elsewhere, e.g. conf.d/site.conf starting
        # with "server {". Allow every family, http last so it wins.
        families = [CORE, "mail", "stream", "http"]
    return [f"{family}/{ctx}" for family in families for ctx in contexts]


DirectiveIndex = dict[str, dict[str, DirectiveDefinition]]


def index_directives(directives: ListDicts) -> DirectiveIndex:
    """Index directives by context key and name."""
    output: DirectiveIndex = {}
    for raw in directives:
        directive = DirectiveDefinition.from_json(raw)
        family = module_family(directive.module, directive.contexts)
        for context in directive.contexts:
            key = (
                context
                if context in GLOBAL_CONTEXTS
                else (f"{family}/{context}")
            )
            output.setdefault(key, {})[directive.name] = directive
    return output


VariableIndex = dict[str, dict[str, VariableDefinition]]


def index_variables(variables: ListDicts) -> VariableIndex:
    """Index variables by family and name."""
    output: VariableIndex = {}
    for raw in variables:
        variable = VariableDefinition.from_json(raw)
        family = module_family(variable.module)
        output.setdefault(family, {})[variable.name] = variable
    return output


def load_raw_data(basename: str) -> ListDicts:
    """Read a JSON file shipped in the package's data folder."""
    data = resources.files("nginx_language_server") / "data" / basename
    return json.loads(data.read_text(encoding="utf-8"))


DIRECTIVES = index_directives(load_raw_data("directives.json"))
VARIABLES = index_variables(load_raw_data("variables.json"))


def directives_for(stack: list[str]) -> dict[str, DirectiveDefinition]:
    """Return the directives allowed inside the given block stack."""
    output = dict(DIRECTIVES.get("any", {}))
    for key in context_keys(stack):
        output.update(DIRECTIVES.get(key, {}))
    return output


def variables_for(stack: list[str]) -> dict[str, VariableDefinition]:
    """Return the variables available inside the given block stack."""
    root = stack[0] if stack else None
    families = [root] if root in FAMILIES else ["mail", "stream", "http"]
    output: dict[str, VariableDefinition] = {}
    for family in [CORE, *families]:
        output.update(VARIABLES.get(family, {}))
    return output


def find_variable(name: str, stack: list[str]) -> VariableDefinition | None:
    """Look up a variable, resolving prefixed names like ``$arg_foo``."""
    name = name.replace("${", "$").rstrip("}")
    available = variables_for(stack)
    if name in available:
        return available[name]
    for prefix in sorted(PREFIX_VARIABLES, key=len, reverse=True):
        if name.startswith(prefix) and len(name) > len(prefix):
            return available.get(PREFIX_VARIABLES[prefix])
    return None
