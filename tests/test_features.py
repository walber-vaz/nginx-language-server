"""End-to-end tests for diagnostics, outline, navigation and formatting."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.conftest import cursor
from tests.lsp_client import LspClient

OpenDoc = Callable[[str], str]


def test_capabilities(client: LspClient) -> None:
    caps = client.initialize()
    assert caps["documentSymbolProvider"]
    assert caps["definitionProvider"]
    assert caps["documentFormattingProvider"]
    assert "documentLinkProvider" in caps


# --- diagnostics -------------------------------------------------------


def messages(client: LspClient, uri: str) -> list[tuple[int, str, int]]:
    """Return (line, message, severity) of the diagnostics for ``uri``."""
    return [
        (d["range"]["start"]["line"], d["message"], d["severity"])
        for d in client.diagnostics(uri)
    ]


ERROR, WARNING = 1, 2


def test_diagnostics_clean_config(
    client: LspClient, open_doc: OpenDoc
) -> None:
    uri = open_doc(
        "events {}\nhttp {\n  server {\n    listen 80;\n"
        "    location / { proxy_pass http://b; }\n  }\n}\n"
    )
    assert messages(client, uri) == []


def test_diagnostics_problems(client: LspClient, open_doc: OpenDoc) -> None:
    uri = open_doc(
        "events {}\n"
        "gzip on;\n"  # not allowed in main
        "http {\n"
        "  server {\n"
        "    frobnicate 1;\n"  # unknown
        "    worker_processes 2;\n"  # not allowed in server
        "    listen 80\n"  # missing ";" before "}"
        "  }\n"
        "  map $a $b { anything goes; }\n"  # map bodies are not checked
        "  server {\n"
    )
    assert messages(client, uri) == [
        (1, '"gzip" directive is not allowed here', ERROR),
        (2, 'unclosed block "{" of "http"', ERROR),
        (4, 'unknown directive "frobnicate"', WARNING),
        (5, '"worker_processes" directive is not allowed here', ERROR),
        (6, 'missing ";" after "listen"', ERROR),
        (9, 'unclosed block "{" of "server"', ERROR),
    ]


def test_diagnostics_stream_family(
    client: LspClient, open_doc: OpenDoc
) -> None:
    uri = open_doc(
        "events {}\nstream {\n  server {\n    listen 53 udp;\n"
        "    proxy_timeout 1s;\n    gzip on;\n  }\n}\n"
    )
    assert messages(client, uri) == [
        (5, '"gzip" directive is not allowed here', ERROR)
    ]


def test_diagnostics_included_file_top_level(
    client: LspClient, open_doc: OpenDoc
) -> None:
    # conf.d/site.conf: its top level is really "http", not "main"
    uri = open_doc(
        "server {\n  listen 80;\n  location / { root /srv; }\n}\n"
        "proxy_set_header Host $host;\n"
    )
    assert messages(client, uri) == []


def test_diagnostics_update_on_change(
    client: LspClient, open_doc: OpenDoc
) -> None:
    uri = open_doc("events {}\nhttp {\n")
    assert len(messages(client, uri)) == 1
    client.notify(
        "textDocument/didChange",
        {
            "textDocument": {"uri": uri, "version": 2},
            "contentChanges": [{"text": "events {}\nhttp {\n}\n"}],
        },
    )
    assert messages(client, uri) == []


# --- outline -----------------------------------------------------------


def test_document_symbols(client: LspClient, open_doc: OpenDoc) -> None:
    uri = open_doc(
        "http {\n"
        "  upstream backend { server 127.0.0.1:8080; }\n"
        "  server {\n"
        "    server_name example.com www.example.com;\n"
        "    include snippets/ssl.conf;\n"
        "    location /api { proxy_pass http://backend; }\n"
        "    location ~ \\.php$ { }\n"
        "  }\n"
        "}\n"
    )
    result = client.request(
        "textDocument/documentSymbol", {"textDocument": {"uri": uri}}
    )

    def tree(symbols: list[dict]) -> list:
        return [
            (s["name"], tree(s["children"])) if s["children"] else s["name"]
            for s in symbols
        ]

    assert tree(result) == [
        (
            "http",
            [
                "upstream backend",
                (
                    "server example.com www.example.com",
                    [
                        "include snippets/ssl.conf",
                        "location /api",
                        "location ~ \\.php$",
                    ],
                ),
            ],
        )
    ]


# --- navigation --------------------------------------------------------


@pytest.fixture
def config_tree(tmp_path: Path) -> Path:
    """Lay out an /etc/nginx-like folder."""
    (tmp_path / "nginx.conf").write_text("events {}\n")
    (tmp_path / "conf.d").mkdir()
    (tmp_path / "conf.d" / "a.conf").write_text("server {}\n")
    (tmp_path / "conf.d" / "b.conf").write_text("server {}\n")
    (tmp_path / "snippets").mkdir()
    (tmp_path / "snippets" / "ssl.conf").write_text("ssl_protocols TLSv1.3;\n")
    return tmp_path


def open_file(client: LspClient, path: Path, text: str) -> str:
    path.write_text(text)
    uri = path.as_uri()
    client.open(uri, text)
    return uri


def test_definition_of_glob_include(
    client: LspClient, config_tree: Path
) -> None:
    source, line, char = cursor("http {\n  include conf.d/*.co|nf;\n}\n")
    uri = open_file(client, config_tree / "nginx.conf", source)
    result = client.position_request(
        "textDocument/definition", uri, line, char
    )
    assert [r["uri"] for r in result] == [
        (config_tree / "conf.d" / "a.conf").as_uri(),
        (config_tree / "conf.d" / "b.conf").as_uri(),
    ]


def test_relative_include_from_included_file(
    client: LspClient, config_tree: Path
) -> None:
    # nginx resolves relative includes against the folder of nginx.conf
    source, line, char = cursor("server {\n  include snippets/ss|l.conf;\n}\n")
    uri = open_file(client, config_tree / "conf.d" / "site.conf", source)
    result = client.position_request(
        "textDocument/definition", uri, line, char
    )
    assert [r["uri"] for r in result] == [
        (config_tree / "snippets" / "ssl.conf").as_uri()
    ]
    links = client.request(
        "textDocument/documentLink", {"textDocument": {"uri": uri}}
    )
    assert [link["target"] for link in links] == [
        (config_tree / "snippets" / "ssl.conf").as_uri()
    ]


def test_definition_of_upstream(client: LspClient, open_doc: OpenDoc) -> None:
    source, line, char = cursor(
        "http {\n  upstream backend { server 127.0.0.1:1; }\n"
        "  server { location / { proxy_pass http://back|end/api; } }\n}\n"
    )
    uri = open_doc(source)
    result = client.position_request(
        "textDocument/definition", uri, line, char
    )
    assert result == [
        {
            "uri": uri,
            "range": {
                "start": {"line": 1, "character": 11},
                "end": {"line": 1, "character": 18},
            },
        }
    ]


# --- snippets ----------------------------------------------------------


def test_snippets_follow_context(client: LspClient, open_doc: OpenDoc) -> None:
    source, line, char = cursor("http {\n  |\n}\n")
    result = client.position_request(
        "textDocument/completion", open_doc(source), line, char
    )
    snippets = {
        item["label"]: item for item in result["items"] if item["kind"] == 15
    }
    assert "server block (HTTPS)" in snippets
    assert "location block" not in snippets
    assert snippets["server block"]["insertTextFormat"] == 2


# --- formatting --------------------------------------------------------


def test_formatting(client: LspClient, open_doc: OpenDoc) -> None:
    uri = open_doc("http {\nserver { listen 80; }\n}\n")
    edits = client.request(
        "textDocument/formatting",
        {
            "textDocument": {"uri": uri},
            "options": {"tabSize": 2, "insertSpaces": True},
        },
    )
    assert [e["newText"] for e in edits] == [
        "http {\n  server {\n    listen 80;\n  }\n}\n"
    ]


def test_formatting_refuses_broken_files(
    client: LspClient, open_doc: OpenDoc
) -> None:
    uri = open_doc("http {\nserver { listen 80; }\n")
    edits = client.request(
        "textDocument/formatting",
        {
            "textDocument": {"uri": uri},
            "options": {"tabSize": 4, "insertSpaces": True},
        },
    )
    assert edits is None
