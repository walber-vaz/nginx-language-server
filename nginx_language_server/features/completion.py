"""textDocument/completion."""

from __future__ import annotations

import re

from lsprotocol.types import (
    CompletionItem,
    CompletionItemKind,
    CompletionList,
    InsertTextFormat,
    MarkupContent,
    MarkupKind,
    TextEdit,
)
from pygls.workspace import TextDocument

from nginx_language_server import pygls_utils
from nginx_language_server.parser import (
    directives_for,
    nginxconf,
    variables_for,
)
from nginx_language_server.parser.data import Snippet, snippets_for

TRIGGER_CHARACTERS = ["$"]

_VARIABLE_BEING_TYPED = re.compile(r"\$\{?[A-Za-z0-9_]*$")
_STATEMENT_BOUNDARY = {
    nginxconf.TokenKind.SEMICOLON,
    nginxconf.TokenKind.LBRACE,
    nginxconf.TokenKind.RBRACE,
}


def _at_directive_name(config: nginxconf.Config, pos: nginxconf.Pos) -> bool:
    """Return whether a directive name (not an argument) goes at ``pos``."""
    previous = config.token_before(pos)
    return (
        previous is None
        or previous.kind in _STATEMENT_BOUNDARY
        # previous statement lacks ";" but we are on a new line
        or previous.end[0] < pos[0]
    )


def complete(document: TextDocument, pos: nginxconf.Pos) -> CompletionList:
    """Return completion items for ``pos`` in ``document``."""
    config = pygls_utils.parse(document)
    blocks = config.blocks_at(pos)
    if blocks and blocks[-1].raw_body is not None:
        return CompletionList(is_incomplete=False, items=[])
    stack = [block.name for block in blocks]
    line = document.lines[pos[0]] if pos[0] < len(document.lines) else ""
    typed = _VARIABLE_BEING_TYPED.search(line[: pos[1]])

    items: list[CompletionItem] = []
    if typed is not None:
        # Replace the whole "$pre" so clients whose word pattern lacks "$"
        # do not end up inserting "$$prefix".
        edit_range = pygls_utils.to_client_range(
            document, (pos[0], typed.start()), pos
        )
        for variable in variables_for(stack).values():
            items.append(
                CompletionItem(
                    label=variable.name,
                    kind=CompletionItemKind.Variable,
                    detail=variable.ls_detail,
                    documentation=MarkupContent(
                        kind=MarkupKind.Markdown,
                        value=variable.ls_documentation,
                    ),
                    filter_text=variable.name,
                    text_edit=TextEdit(
                        range=edit_range, new_text=variable.name
                    ),
                    insert_text_format=InsertTextFormat.PlainText,
                )
            )
    elif _at_directive_name(config, pos):
        for directive in directives_for(stack).values():
            items.append(
                CompletionItem(
                    label=directive.name,
                    kind=CompletionItemKind.Property,
                    detail=directive.ls_detail,
                    documentation=MarkupContent(
                        kind=MarkupKind.Markdown,
                        value=directive.ls_documentation,
                    ),
                    filter_text=directive.name,
                    insert_text=directive.name,
                    insert_text_format=InsertTextFormat.PlainText,
                )
            )
        for snippet in snippets_for(stack):
            items.append(
                CompletionItem(
                    label=snippet.label,
                    kind=CompletionItemKind.Snippet,
                    detail="snippet",
                    documentation=MarkupContent(
                        kind=MarkupKind.Markdown,
                        value=f"```nginx\n{snippet_preview(snippet)}\n```",
                    ),
                    filter_text=snippet.prefix,
                    # after the directive of the same name
                    sort_text=f"{snippet.prefix}~{snippet.label}",
                    insert_text=snippet.body,
                    insert_text_format=InsertTextFormat.Snippet,
                )
            )
    return CompletionList(is_incomplete=False, items=items)


_PLACEHOLDER = re.compile(r"\$\{\d+:((?:[^}\\]|\\.)*)\}|\$\d+")


def snippet_preview(snippet: Snippet) -> str:
    """Return the snippet body with placeholders filled with defaults."""
    text = _PLACEHOLDER.sub(lambda m: m.group(1) or "", snippet.body)
    return text.replace("\\$", "$").replace("\\}", "}").expandtabs(4)
