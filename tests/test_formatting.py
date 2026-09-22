"""Unit tests for the formatter and the bundled snippets."""

from __future__ import annotations

import pytest

from nginx_language_server.features.completion import snippet_preview
from nginx_language_server.features.diagnostics import Settings, check
from nginx_language_server.features.formatting import format_config
from nginx_language_server.parser.data import SNIPPETS, Snippet
from nginx_language_server.parser.nginxconf import parse

MESSY = """\
user  nginx;
worker_processes auto;   # one per core


events { worker_connections 1024; }
http {
  include       mime.types;
    log_format  main  '$remote_addr - $remote_user [$time_local] "$request" '
                      '$status $body_bytes_sent';
  map $a $b { default 0; ~x 1; }

  server {


      listen 80;
     # comment line
      location / {
        content_by_lua_block {
                local a = 1
                  if a then ngx.say('hi') end
        }
      }
      location /x { access_by_lua_block { ngx.exit(403) } }
  }
}
"""

TIDY = """\
user nginx;
worker_processes auto; # one per core

events {
    worker_connections 1024;
}
http {
    include mime.types;
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
               '$status $body_bytes_sent';
    map $a $b {
        default 0;
        ~x 1;
    }

    server {
        listen 80;
        # comment line
        location / {
            content_by_lua_block {
                local a = 1
                  if a then ngx.say('hi') end
            }
        }
        location /x {
            access_by_lua_block { ngx.exit(403) }
        }
    }
}
"""


def test_format() -> None:
    assert format_config(parse(MESSY), "    ") == TIDY


def test_format_is_idempotent() -> None:
    assert format_config(parse(TIDY), "    ") == TIDY


def test_format_with_tabs() -> None:
    assert format_config(parse("a { b 1; }"), "\t") == "a {\n\tb 1;\n}\n"


def test_lua_long_strings_are_not_reindented() -> None:
    text = (
        "location / {\n content_by_lua_block {\n"
        " local s = [[\n  x\n]]\n }\n}\n"
    )
    out = format_config(parse(text), "    ")
    assert out is not None
    assert "\n  x\n]]\n" in out


def test_broken_config_is_not_formatted() -> None:
    assert format_config(parse("http {\n"), "    ") is None


def test_empty_document() -> None:
    assert format_config(parse(""), "    ") == ""


# Blocks to wrap a snippet in to put it in each context key
_WRAPPERS = {
    "main": [],
    "http/http": ["http"],
    "http/server": ["http", "server"],
    "http/location": ["http", "server", "location"],
    "stream/stream": ["stream"],
}


@pytest.mark.parametrize("snippet", SNIPPETS, ids=lambda s: s.label)
def test_snippets_are_valid_in_their_context(snippet: Snippet) -> None:
    """Each snippet, expanded, parses and passes diagnostics in place."""
    body = snippet_preview(snippet)
    for key in snippet.contexts:
        wrappers = _WRAPPERS[key]
        text = "events {}\n"
        text += "".join(f"{name} {{\n" for name in wrappers)
        text += body + "\n" + "}\n" * len(wrappers)
        assert check(parse(text), Settings()) == [], (key, text)
