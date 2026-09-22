"""Load directive and variable definitions from the data folder."""

from __future__ import annotations

import functools
import json
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from types import MappingProxyType
from typing import Any

from .utils import wrap_plain_text, wrap_rich_text

ListDicts = list[dict[str, Any]]


def _finish(result: str) -> str:
    return result.replace("“", '"').replace("”", '"').strip()


DOCS_URL = "https://nginx.org/en/docs/"
_COMMERCIAL_NOTE = "**NGINX Plus:** part of the commercial subscription"


def _doc_link(link: str | None) -> str:
    return f"\n\n[nginx.org documentation]({DOCS_URL}{link})" if link else ""


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
    commercial: bool = False
    link: str | None = None

    ls_detail: str = field(init=False)
    ls_documentation: str = field(init=False)

    def __post_init__(self) -> None:
        """Compute the language server strings once."""
        detail = f"dir: {self.name}" + (
            " (NGINX Plus)" if self.commercial else ""
        )
        object.__setattr__(self, "ls_detail", detail)
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
            commercial=raw.get("commercial", False),
            link=raw.get("link"),
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
        if self.commercial:
            result += "\n" + _COMMERCIAL_NOTE
        if self.notes:
            result += "\n\n*Notes:*"
            notes = [wrap_rich_text(note) for note in self.notes]
            if len(notes) == 1:
                result += notes[0]
            else:
                result += "\n- " + "\n- ".join(notes)
        return _finish(result + _doc_link(self.link))


@dataclass(frozen=True, slots=True)
class VariableDefinition:
    """Strongly typed variable, from variables.json."""

    name: str
    desc: str
    module: str
    prefix: str | None = None  # "$arg_" for "$arg_name"
    commercial: bool = False
    link: str | None = None

    ls_detail: str = field(init=False)
    ls_documentation: str = field(init=False)

    def __post_init__(self) -> None:
        """Compute the language server strings once."""
        object.__setattr__(self, "ls_detail", f"var: {self.name}")
        object.__setattr__(self, "ls_documentation", self._documentation())

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> VariableDefinition:
        """Build from a raw variables.json entry."""
        return cls(
            name=raw["name"],
            desc=raw["desc"],
            module=raw["module"],
            prefix=raw.get("prefix"),
            commercial=raw.get("commercial", False),
            link=raw.get("link"),
        )

    def _documentation(self) -> str:
        result = ""
        if self.desc:
            result += _description(self.desc)
        if self.module:
            result += "\n\n"
            result += wrap_rich_text("**Module:** " + self.module)
        if self.commercial:
            result += "\n" + _COMMERCIAL_NOTE
        return _finish(result + _doc_link(self.link))


FAMILIES = ("http", "stream", "mail")
CORE = "core"
# Contexts that do not depend on the top-level block they are in
GLOBAL_CONTEXTS = ("main", "events", "any")
_HTTP_ONLY_CONTEXTS = {"location", "if", "ifinlocation", "limit_except"}


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


def directives_for(stack: list[str]) -> Mapping[str, DirectiveDefinition]:
    """Return the directives allowed inside the given block stack."""
    return _directives_for(tuple(context_keys(stack)))


@functools.cache
def _directives_for(
    keys: tuple[str, ...],
) -> Mapping[str, DirectiveDefinition]:
    output = dict(DIRECTIVES.get("any", {}))
    for key in keys:
        output.update(DIRECTIVES.get(key, {}))
    return MappingProxyType(output)


def variables_for(stack: list[str]) -> Mapping[str, VariableDefinition]:
    """Return the variables available inside the given block stack."""
    root = stack[0] if stack else None
    return _variables_for(root if root in FAMILIES else None)


@functools.cache
def _variables_for(family: str | None) -> Mapping[str, VariableDefinition]:
    families = [family] if family else ["mail", "stream", "http"]
    output: dict[str, VariableDefinition] = {}
    for name in [CORE, *families]:
        output.update(VARIABLES.get(name, {}))
    return MappingProxyType(output)


def find_variable(name: str, stack: list[str]) -> VariableDefinition | None:
    """Look up a variable, resolving prefixed names like ``$arg_foo``."""
    name = name.replace("${", "$").rstrip("}")
    available = variables_for(stack)
    if name in available:
        return available[name]
    matches = [
        variable
        for variable in available.values()
        if variable.prefix
        and name.startswith(variable.prefix)
        and len(name) > len(variable.prefix)
    ]
    # "$upstream_http_x" must win over "$http_x"-style shorter prefixes
    return max(matches, key=lambda v: len(v.prefix or ""), default=None)


ALL_DIRECTIVE_NAMES = frozenset(
    name for directives in DIRECTIVES.values() for name in directives
)
# Every block that holds directives, e.g. "server" or "acme_issuer"
KNOWN_CONTEXTS = frozenset(key.rsplit("/", 1)[-1] for key in DIRECTIVES) - {
    "any",
    "ifinlocation",
}


@dataclass(frozen=True, slots=True)
class Snippet:
    """A code snippet offered as a completion item."""

    label: str
    prefix: str
    contexts: tuple[str, ...]  # context keys, see context_keys()
    body: str


SNIPPETS = tuple(
    Snippet(
        label=raw["label"],
        prefix=raw["prefix"],
        contexts=tuple(raw["contexts"]),
        body=raw["body"],
    )
    for raw in load_raw_data("snippets.json")
)


def snippets_for(stack: list[str]) -> list[Snippet]:
    """Return the snippets that fit in the given block stack."""
    keys = set(context_keys(stack))
    return [s for s in SNIPPETS if keys.intersection(s.contexts)]
