"""End-to-end tests: talk to the real server over stdio.

Several of these tests record bugs of the old crossplane based parser
(see the git history for the xfail markers they carried).
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


def test_completion_in_main_while_typing(
    client: LspClient, open_doc: OpenDoc
) -> None:
    labels = complete(client, open_doc, "user nginx;\nwor|\n")
    assert "worker_processes" in labels


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


def test_completion_with_unclosed_block(
    client: LspClient, open_doc: OpenDoc
) -> None:
    labels = complete(
        client,
        open_doc,
        "http {\n    server {\n        listen 80;\n        gzi|\n",
    )
    assert "gzip" in labels


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


def test_hover_variable(client: LspClient, open_doc: OpenDoc) -> None:
    text = hover(
        client,
        open_doc,
        "http {\n server {\n  return 200 $ho|st;\n }\n}\n",
    )
    assert text is not None
    assert "ngx\\_http\\_core\\_module" in text


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


def test_completion_if_in_location_includes_ifinlocation(
    client: LspClient, open_doc: OpenDoc
) -> None:
    labels = complete(
        client,
        open_doc,
        "http {\n server {\n  location / {\n   if ($a) {\n    |\n"
        "   }\n  }\n }\n}\n",
    )
    assert "proxy_pass" in labels  # "if in location" context
    assert "rewrite" in labels  # "if" context
    assert "server_name" not in labels


def test_completion_in_included_server_snippet(
    client: LspClient, open_doc: OpenDoc
) -> None:
    labels = complete(client, open_doc, "server {\n  listen 80;\n  |\n}\n")
    assert "server_name" in labels
    assert "proxy_timeout" in labels  # family unknown: all are offered


def test_hover_in_included_server_snippet_prefers_http(
    client: LspClient, open_doc: OpenDoc
) -> None:
    text = hover(client, open_doc, "server {\n  lis|ten 80;\n}\n")
    assert text is not None
    assert "ngx\\_http\\_core\\_module" in text


def test_no_completion_in_argument_position(
    client: LspClient, open_doc: OpenDoc
) -> None:
    labels = complete(
        client, open_doc, "http {\n server {\n  listen 80 gz|;\n }\n}\n"
    )
    assert labels == []


def test_no_completion_inside_lua_block(
    client: LspClient, open_doc: OpenDoc
) -> None:
    labels = complete(
        client,
        open_doc,
        "location / {\n  content_by_lua_block {\n    ngx.|\n  }\n}\n",
    )
    assert labels == []


def test_variable_completion_replaces_dollar_prefix(
    client: LspClient, open_doc: OpenDoc
) -> None:
    source, line, char = cursor(
        "http {\n server {\n  return 200 $ho|;\n }\n}\n"
    )
    result = client.request(
        "textDocument/completion",
        {
            "textDocument": {"uri": open_doc(source)},
            "position": {"line": line, "character": char},
        },
    )
    host = next(i for i in result["items"] if i["label"] == "$host")
    assert host["textEdit"]["newText"] == "$host"
    assert host["textEdit"]["range"]["start"] == {"line": 2, "character": 13}
    assert host["textEdit"]["range"]["end"] == {"line": 2, "character": 16}
    labels = [i["label"] for i in result["items"]]
    assert "$request_uri" in labels
    assert "gzip" not in labels


def test_stream_variables(client: LspClient, open_doc: OpenDoc) -> None:
    text = hover(
        client,
        open_doc,
        "stream {\n server {\n  set $x $remote_ad|dr;\n }\n}\n",
    )
    assert text is not None
    assert "ngx\\_stream\\_core\\_module" in text


def test_hover_positions_are_utf16(
    client: LspClient, open_doc: OpenDoc
) -> None:
    # "😀" is 2 UTF-16 code units but 1 Python character
    source = "http {\n server { # 😀\n  gzip on; # 😀 gzip\n }\n}\n"
    uri = open_doc(source)
    result = client.request(
        "textDocument/hover",
        {
            "textDocument": {"uri": uri},
            "position": {"line": 2, "character": 3},
        },
    )
    assert result["range"]["start"] == {"line": 2, "character": 2}
    assert result["range"]["end"] == {"line": 2, "character": 6}
    # the "gzip" in the trailing comment is not a directive
    assert client.hover_text(uri, 2, 17) is None
