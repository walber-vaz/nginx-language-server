"""Nginx Language Server.

Creates the language server constant and wraps "features" with it.

Official language server spec:
    https://microsoft.github.io/language-server-protocol/specification
"""

from __future__ import annotations

from lsprotocol.types import (
    TEXT_DOCUMENT_COMPLETION,
    TEXT_DOCUMENT_DID_CLOSE,
    TEXT_DOCUMENT_HOVER,
    CompletionList,
    CompletionOptions,
    CompletionParams,
    DidCloseTextDocumentParams,
    Hover,
    HoverParams,
)
from pygls.lsp.server import LanguageServer

from nginx_language_server import __version__, pygls_utils
from nginx_language_server.features import completion, hover

SERVER = LanguageServer(
    name="nginx-language-server",
    version=__version__,
)


@SERVER.feature(
    TEXT_DOCUMENT_COMPLETION,
    CompletionOptions(trigger_characters=completion.TRIGGER_CHARACTERS),
)
def on_completion(
    server: LanguageServer, params: CompletionParams
) -> CompletionList:
    """Return completion items."""
    document = server.workspace.get_text_document(params.text_document.uri)
    pos = pygls_utils.to_server(document, params.position)
    return completion.complete(document, pos)


@SERVER.feature(TEXT_DOCUMENT_HOVER)
def on_hover(server: LanguageServer, params: HoverParams) -> Hover | None:
    """Return documentation for the word under the cursor."""
    document = server.workspace.get_text_document(params.text_document.uri)
    pos = pygls_utils.to_server(document, params.position)
    return hover.hover(document, pos)


@SERVER.feature(TEXT_DOCUMENT_DID_CLOSE)
def on_did_close(
    server: LanguageServer, params: DidCloseTextDocumentParams
) -> None:
    """Forget cached state of closed documents."""
    del server  # unused, required by pygls
    pygls_utils.forget(params.text_document.uri)
