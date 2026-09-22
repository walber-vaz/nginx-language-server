"""Nginx Language Server.

Creates the language server constant and wraps "features" with it.

Official language server spec:
    https://microsoft.github.io/language-server-protocol/specification
"""

from __future__ import annotations

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from nginx_language_server import __version__, pygls_utils
from nginx_language_server.features import (
    completion,
    diagnostics,
    formatting,
    hover,
    navigation,
    symbols,
)


class NginxLanguageServer(LanguageServer):
    """Language server with the user's settings attached."""

    def __init__(self) -> None:
        """Create the server."""
        super().__init__(name="nginx-language-server", version=__version__)
        self.diagnostic_settings = diagnostics.Settings()


SERVER = NginxLanguageServer()


@SERVER.feature(types.INITIALIZE)
def on_initialize(
    server: NginxLanguageServer, params: types.InitializeParams
) -> None:
    """Read the settings sent in ``initializationOptions``."""
    server.diagnostic_settings = diagnostics.Settings.from_options(
        params.initialization_options
    )


# --- diagnostics -------------------------------------------------------


def _publish(server: NginxLanguageServer, uri: str) -> None:
    document = server.workspace.get_text_document(uri)
    server.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(
            uri=uri,
            version=document.version,
            diagnostics=diagnostics.diagnostics(
                document, server.diagnostic_settings
            ),
        )
    )


@SERVER.feature(types.TEXT_DOCUMENT_DID_OPEN)
def on_did_open(
    server: NginxLanguageServer, params: types.DidOpenTextDocumentParams
) -> None:
    """Check a document when it is opened."""
    _publish(server, params.text_document.uri)


@SERVER.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def on_did_change(
    server: NginxLanguageServer, params: types.DidChangeTextDocumentParams
) -> None:
    """Check a document when it changes."""
    _publish(server, params.text_document.uri)


@SERVER.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def on_did_close(
    server: NginxLanguageServer, params: types.DidCloseTextDocumentParams
) -> None:
    """Clear diagnostics and cached state of closed documents."""
    uri = params.text_document.uri
    pygls_utils.forget(uri)
    server.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(uri=uri, diagnostics=[])
    )


# --- language features -------------------------------------------------


@SERVER.feature(
    types.TEXT_DOCUMENT_COMPLETION,
    types.CompletionOptions(trigger_characters=completion.TRIGGER_CHARACTERS),
)
def on_completion(
    server: NginxLanguageServer, params: types.CompletionParams
) -> types.CompletionList:
    """Return completion items."""
    document = server.workspace.get_text_document(params.text_document.uri)
    pos = pygls_utils.to_server(document, params.position)
    return completion.complete(document, pos)


@SERVER.feature(types.TEXT_DOCUMENT_HOVER)
def on_hover(
    server: NginxLanguageServer, params: types.HoverParams
) -> types.Hover | None:
    """Return documentation for the word under the cursor."""
    document = server.workspace.get_text_document(params.text_document.uri)
    pos = pygls_utils.to_server(document, params.position)
    return hover.hover(document, pos)


@SERVER.feature(types.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def on_document_symbol(
    server: NginxLanguageServer, params: types.DocumentSymbolParams
) -> list[types.DocumentSymbol]:
    """Return the outline of the document."""
    document = server.workspace.get_text_document(params.text_document.uri)
    return symbols.document_symbols(document)


@SERVER.feature(types.TEXT_DOCUMENT_DEFINITION)
def on_definition(
    server: NginxLanguageServer, params: types.DefinitionParams
) -> list[types.Location] | None:
    """Go to included files and to upstream blocks."""
    document = server.workspace.get_text_document(params.text_document.uri)
    pos = pygls_utils.to_server(document, params.position)
    return navigation.definition(document, pos)


@SERVER.feature(
    types.TEXT_DOCUMENT_DOCUMENT_LINK,
    types.DocumentLinkOptions(resolve_provider=False),
)
def on_document_link(
    server: NginxLanguageServer, params: types.DocumentLinkParams
) -> list[types.DocumentLink]:
    """Make ``include`` paths clickable."""
    document = server.workspace.get_text_document(params.text_document.uri)
    return navigation.document_links(document)


@SERVER.feature(types.TEXT_DOCUMENT_FORMATTING)
def on_formatting(
    server: NginxLanguageServer, params: types.DocumentFormattingParams
) -> list[types.TextEdit] | None:
    """Format the whole document."""
    document = server.workspace.get_text_document(params.text_document.uri)
    return formatting.formatting(document, params.options)
