"""textDocument/hover."""

from __future__ import annotations

from lsprotocol.types import Hover, MarkupContent, MarkupKind
from pygls.workspace import TextDocument

from nginx_language_server import pygls_utils
from nginx_language_server.parser import (
    directives_for,
    find_variable,
    nginxconf,
)


def hover(document: TextDocument, pos: nginxconf.Pos) -> Hover | None:
    """Return documentation for the directive or variable at ``pos``."""
    word = pygls_utils.word_at(document, pos)
    if word is None:
        return None
    config = pygls_utils.parse(document)
    if word.text.startswith("$"):
        found = find_variable(word.text, config.context_at(pos))
    else:
        directive = config.directive_at(pos)
        if directive is None or directive.name != word.text:
            return None
        found = directives_for(directive.context()).get(directive.name)
    if found is None:
        return None
    return Hover(
        contents=MarkupContent(
            kind=MarkupKind.Markdown, value=found.ls_documentation
        ),
        range=pygls_utils.to_client_range(document, word.start, word.end),
    )
