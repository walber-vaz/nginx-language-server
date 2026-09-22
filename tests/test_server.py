"""End-to-end tests: talk to the real server over stdio.

Tests marked ``xfail(strict=True)`` document known bugs. When a fix lands
they start passing, which fails the suite until the marker is removed.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.conftest import cursor
from tests.lsp_client import LspClient

OpenDoc = Callable[[str], str]


def complete(client: LspClient, open_doc: OpenDoc, text: str) -> list[str]:
    source, line, char = cursor(text)
    return client.completion_labels(open_doc(source), line, char)


def hover(client: LspClient, open_doc: OpenDoc, text: str) -> str | None:
    source, line, char = cursor(text)
    return client.hover_text(open_doc(source), line, char)


# --- capabilities ------------------------------------------------------


def test_capabilities(client: LspClient) -> None:
    caps = client.initialize()
    assert caps["hoverProvider"]
    assert "$" in caps["completionProvider"]["triggerCharacters"]


# --- completion --------------------------------------------------------


def test_completion_in_http_server(
    client: LspClient, open_doc: OpenDoc
) -> None:
    labels = complete(
        client,
        open_doc,
        "http {\n    server {\n        listen 80;\n        gzi|\n    }\n}\n",
    )
    assert "gzip" in labels
    assert "server_name" in labels
    assert "worker_processes" not in labels  # main-only directive


def test_completion_in_location(client: LspClient, open_doc: OpenDoc) -> None:
    labels = complete(
        client,
        open_doc,
        "http {\n server {\n  location / {\n"
        "   root /x;\n   pro|\n  }\n }\n}\n",
    )
    assert "proxy_pass" in labels
    assert "try_files" in labels


def test_completion_in_main(client: LspClient, open_doc: OpenDoc) -> None:
    labels = complete(client, open_doc, "user nginx;\n|\nevents {}\n")
    assert "worker_processes" in labels


@pytest.mark.xfail(strict=True, reason="bug 3: incomplete directive in main")
def test_completion_in_main_while_typing(
    client: LspClient, open_doc: OpenDoc
) -> None:
    labels = complete(client, open_doc, "user nginx;\nwor|\n")
    assert "worker_processes" in labels


@pytest.mark.xfail(strict=True, reason="bug 2: stream server gets http")
def test_completion_stream_server_excludes_http(
    client: LspClient, open_doc: OpenDoc
) -> None:
    labels = complete(
        client,
        open_doc,
        "stream {\n server {\n  listen 53 udp;\n  |\n }\n}\n",
    )
    assert "proxy_timeout" in labels
    assert "gzip" not in labels
    assert "root" not in labels


@pytest.mark.xfail(strict=True, reason="bug 3: unclosed block breaks parse")
def test_completion_with_unclosed_block(
    client: LspClient, open_doc: OpenDoc
) -> None:
    labels = complete(
        client,
        open_doc,
        "http {\n    server {\n        listen 80;\n        gzi|\n",
    )
    assert "gzip" in labels


@pytest.mark.xfail(strict=True, reason="variables offered without '$'")
def test_completion_variables_only_after_dollar(
    client: LspClient, open_doc: OpenDoc
) -> None:
    labels = complete(
        client,
        open_doc,
        "http {\n server {\n  listen 80;\n  gzi|\n }\n}\n",
    )
    assert not any(label.startswith("$") for label in labels)


# --- hover -------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="bug 2: shows stream 'listen' doc")
def test_hover_directive(client: LspClient, open_doc: OpenDoc) -> None:
    text = hover(
        client,
        open_doc,
        "http {\n server {\n  lis|ten 80;\n }\n}\n",
    )
    assert text is not None
    assert "listen" in text
    assert "ngx\\_http\\_core\\_module" in text


def test_hover_directive_unique_name(
    client: LspClient, open_doc: OpenDoc
) -> None:
    text = hover(
        client,
        open_doc,
        "http {\n server {\n  gz|ip on;\n }\n}\n",
    )
    assert text is not None
    assert "ngx\\_http\\_gzip\\_module" in text


def test_hover_unknown_word(client: LspClient, open_doc: OpenDoc) -> None:
    assert (
        hover(client, open_doc, "http {\n server {\n  foo|bar 1;\n }\n}\n")
        is None
    )


@pytest.mark.xfail(strict=True, reason="bug 1: '$' dropped from word")
def test_hover_variable(client: LspClient, open_doc: OpenDoc) -> None:
    text = hover(
        client,
        open_doc,
        "http {\n server {\n  return 200 $ho|st;\n }\n}\n",
    )
    assert text is not None
    assert "ngx\\_http\\_core\\_module" in text


@pytest.mark.xfail(strict=True, reason="bugs 1 and 6: prefix variables")
@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("set $x $arg_fo|o;", "argument name"),
        ("set $x $http_user_ag|ent;", "request header field"),
        ("set $x $cookie_ses|sion;", "the name cookie"),
    ],
)
def test_hover_prefix_variable(
    client: LspClient, open_doc: OpenDoc, line: str, expected: str
) -> None:
    text = hover(client, open_doc, f"http {{\n server {{\n  {line}\n }}\n}}\n")
    assert text is not None
    assert expected in text


@pytest.mark.xfail(strict=True, reason="bug 5: same-line directives collide")
def test_hover_block_with_inline_body(
    client: LspClient, open_doc: OpenDoc
) -> None:
    text = hover(
        client,
        open_doc,
        "http {\n ma|p $a $b { default 0; }\n}\n",
    )
    assert text is not None
    assert "ngx\\_http\\_map\\_module" in text
