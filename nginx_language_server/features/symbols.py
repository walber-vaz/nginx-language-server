"""textDocument/documentSymbol: the outline of a config."""

from __future__ import annotations

from lsprotocol.types import DocumentSymbol, SymbolKind
from pygls.workspace import TextDocument

from nginx_language_server import pygls_utils
from nginx_language_server.parser import nginxconf

_KINDS = {
    "http": SymbolKind.Namespace,
    "stream": SymbolKind.Namespace,
    "mail": SymbolKind.Namespace,
    "events": SymbolKind.Namespace,
    "server": SymbolKind.Class,
    "upstream": SymbolKind.Interface,
    "location": SymbolKind.Method,
    "if": SymbolKind.Boolean,
    "map": SymbolKind.Enum,
    "include": SymbolKind.File,
}
# Simple directives worth showing in the outline
_LEAVES = {"include"}


def _child_args(node: nginxconf.Directive, name: str) -> list[str]:
    """Return the arguments of the first ``name`` directive in a block."""
    for child in node.block or []:
        if child.name == name and child.args:
            return [arg.text for arg in child.args]
    return []


def _label(node: nginxconf.Directive) -> str:
    """Return how a directive is named in the outline."""
    args = [arg.text for arg in node.args]
    if node.name == "server" and not args:
        args = (
            _child_args(node, "server_name") or _child_args(node, "listen")[:1]
        )
    return " ".join([node.name, *args])


def _symbol(
    document: TextDocument, node: nginxconf.Directive
) -> DocumentSymbol:
    children = [
        _symbol(document, child)
        for child in node.block or []
        if child.is_block or child.name in _LEAVES
    ]
    return DocumentSymbol(
        name=_label(node),
        kind=_KINDS.get(node.name, SymbolKind.Struct),
        range=pygls_utils.to_client_range(document, node.start, node.end),
        selection_range=pygls_utils.to_client_range(
            document, node.name_token.start, node.name_token.end
        ),
        children=children,
    )


def document_symbols(document: TextDocument) -> list[DocumentSymbol]:
    """Return the block structure of ``document``."""
    config = pygls_utils.parse(document)
    return [
        _symbol(document, node)
        for node in config.directives
        if node.name and (node.is_block or node.name in _LEAVES)
    ]
