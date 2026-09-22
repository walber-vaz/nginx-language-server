"""textDocument/publishDiagnostics."""

from __future__ import annotations

from dataclasses import dataclass

from lsprotocol.types import Diagnostic, DiagnosticSeverity
from pygls.workspace import TextDocument

from nginx_language_server import pygls_utils
from nginx_language_server.parser import data, nginxconf

SOURCE = "nginx"

# Top-level blocks that only appear in a main nginx.conf
_MAIN_ONLY = {"http", "events", "stream", "mail"}


@dataclass(slots=True)
class Settings:
    """User settings, from ``initializationOptions.diagnostics``."""

    enabled: bool = True
    unknown_directives: bool = True

    @classmethod
    def from_options(cls, options: object) -> Settings:
        """Build from the client's initialization options."""
        settings = cls()
        if not isinstance(options, dict):
            return settings
        section = options.get("diagnostics")
        if isinstance(section, bool):
            settings.enabled = section
        elif isinstance(section, dict):
            settings.enabled = bool(section.get("enable", True))
            settings.unknown_directives = bool(
                section.get("unknownDirectives", True)
            )
        return settings


def _is_main_config(config: nginxconf.Config) -> bool:
    """Guess whether this is a main nginx.conf and not an included file."""
    return any(node.name in _MAIN_ONLY for node in config.directives)


def _checks_context(stack: list[str]) -> bool:
    """Return whether the directives allowed in ``stack`` are known.

    Blocks such as ``map``, ``geo`` or ``types`` hold key/value pairs,
    not directives, so nothing inside them is checked.
    """
    return not stack or stack[-1] in data.KNOWN_CONTEXTS


def _check_directive(
    node: nginxconf.Directive, settings: Settings, main_config: bool
) -> _Problem | None:
    """Return the problem with one directive, if any."""
    stack = node.context()
    if not node.name or not _checks_context(stack):
        return None
    name = node.name_token
    if node.name not in data.ALL_DIRECTIVE_NAMES:
        if not settings.unknown_directives:
            return None
        return _Problem(
            name.start,
            name.end,
            f'unknown directive "{node.name}"',
            DiagnosticSeverity.Warning,
        )
    if not stack and not main_config:
        return None  # included file: the top-level context is unknown
    if node.name in data.directives_for(stack):
        return None
    return _Problem(
        name.start,
        name.end,
        f'"{node.name}" directive is not allowed here',
        DiagnosticSeverity.Error,
    )


def check(config: nginxconf.Config, settings: Settings) -> list[_Problem]:
    """Return the problems found in a parsed document."""
    problems = [
        _Problem(
            error.start, error.end, error.message, DiagnosticSeverity.Error
        )
        for error in config.errors
    ]
    main_config = _is_main_config(config)
    for node in config.walk():
        problem = _check_directive(node, settings, main_config)
        if problem is not None:
            problems.append(problem)
    return sorted(problems, key=lambda problem: problem.start)


@dataclass(frozen=True, slots=True)
class _Problem:
    start: nginxconf.Pos
    end: nginxconf.Pos
    message: str
    severity: DiagnosticSeverity


def diagnostics(
    document: TextDocument, settings: Settings
) -> list[Diagnostic]:
    """Return LSP diagnostics for ``document``."""
    if not settings.enabled:
        return []
    config = pygls_utils.parse(document)
    return [
        Diagnostic(
            range=pygls_utils.to_client_range(
                document, problem.start, problem.end
            ),
            message=problem.message,
            severity=problem.severity,
            source=SOURCE,
        )
        for problem in check(config, settings)
    ]
