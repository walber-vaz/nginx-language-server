"""Unit tests for the error tolerant nginx parser."""

from __future__ import annotations

from nginx_language_server.parser.nginxconf import TokenKind, parse


def names(text: str) -> list[tuple[str, list[str]]]:
    """Return (name, context) for every directive in document order."""
    return [(d.name, d.context()) for d in parse(text).walk()]


def test_simple_and_nested() -> None:
    config = parse("user nginx;\nhttp {\n  server {\n    listen 80;\n  }\n}\n")
    assert config.errors == []
    assert names("user nginx;\nhttp {\n server {\n  listen 80;\n }\n}\n") == [
        ("user", []),
        ("http", []),
        ("server", ["http"]),
        ("listen", ["http", "server"]),
    ]
    listen = next(d for d in config.walk() if d.name == "listen")
    assert [a.value for a in listen.args] == ["80"]
    assert listen.start == (3, 4)
    assert listen.end == (3, 14)


def test_several_directives_on_one_line() -> None:
    config = parse("http {\n map $a $b { default 0; }\n}\n")
    assert config.errors == []
    assert names("http {\n map $a $b { default 0; }\n}\n") == [
        ("http", []),
        ("map", ["http"]),
        ("default", ["http", "map"]),
    ]
    assert config.directive_at((1, 2)) is not None
    assert config.directive_at((1, 2)).name == "map"  # type: ignore[union-attr]


def test_unclosed_blocks_are_closed_at_eof() -> None:
    config = parse("http {\n    server {\n        listen 80;\n        gzi\n")
    assert names("http {\n server {\n  listen 80;\n  gzi\n") == [
        ("http", []),
        ("server", ["http"]),
        ("listen", ["http", "server"]),
        ("gzi", ["http", "server"]),
    ]
    messages = [error.message for error in config.errors]
    assert 'missing ";" after "gzi"' in messages
    assert 'unclosed block "{" of "http"' in messages
    assert 'unclosed block "{" of "server"' in messages
    assert config.context_at((3, 11)) == ["http", "server"]


def test_missing_semicolon_before_close_brace() -> None:
    config = parse("events {\n  worker_connections 10\n}\n")
    assert [e.message for e in config.errors] == [
        'missing ";" after "worker_connections"'
    ]
    events = config.directives[0]
    assert events.close_brace is not None


def test_unexpected_tokens() -> None:
    config = parse("}\n;\n{ }\n")
    messages = [error.message for error in config.errors]
    assert messages == [
        'unexpected "}"',
        'unexpected ";"',
        'block "{" without a name',
    ]


def test_strings_comments_and_variables() -> None:
    text = (
        "# leading comment\n"
        "log_format main '$remote_addr \"$request\" {x}' # trailing\n"
        '  "a;b";\n'
        "set $x ${host}_suffix;\n"
        "location ~ ^/a#b$ { return 204; }\n"
    )
    config = parse(text)
    assert config.errors == []
    log_format, set_, location, _ = list(config.walk())
    assert [a.value for a in log_format.args] == [
        "main",
        '$remote_addr "$request" {x}',
        "a;b",
    ]
    assert [a.text for a in set_.args] == ["$x", "${host}_suffix"]
    assert [a.text for a in location.args] == ["~", "^/a#b$"]
    comments = [t.text for t in config.tokens if t.kind is TokenKind.COMMENT]
    assert comments == ["# leading comment", "# trailing"]


def test_escaped_characters_in_words() -> None:
    config = parse("return 200 a\\;b\\{c;\n")
    assert config.errors == []
    assert [a.text for a in config.directives[0].args] == ["200", "a\\;b\\{c"]


def test_unterminated_string() -> None:
    config = parse('return 200 "oops;\n}\n')
    assert config.errors[0].message == 'unterminated " string'


def test_lua_block_is_kept_verbatim() -> None:
    text = (
        "location / {\n"
        "  content_by_lua_block {\n"
        '    local t = { a = "}" } -- } in a comment\n'
        "    ngx.say(t.a)\n"
        "  }\n"
        "  return 200;\n"
        "}\n"
    )
    config = parse(text)
    assert config.errors == []
    assert names(text) == [
        ("location", []),
        ("content_by_lua_block", ["location"]),
        ("return", ["location"]),
    ]
    lua = config.directives[0].block[0]  # type: ignore[index]
    assert lua.raw_body is not None
    assert "ngx.say(t.a)" in lua.raw_body.text


def test_blocks_at_position() -> None:
    text = "http {\n  server {\n\n  }\n  \n}\n"
    config = parse(text)
    assert config.context_at((0, 0)) == []
    assert config.context_at((2, 0)) == ["http", "server"]
    assert config.context_at((4, 2)) == ["http"]
    assert config.context_at((6, 0)) == []


def test_token_before_skips_word_being_typed() -> None:
    config = parse("user nginx;\nwor\n")
    before = config.token_before((1, 3))
    assert before is not None
    assert before.kind is TokenKind.SEMICOLON


def test_never_raises_on_garbage() -> None:
    for text in ["", "{{{{", "}}}}", "'", '"', "${", "a\\", "\\", ";;;", "#"]:
        parse(text)


def test_lua_long_brackets_and_comments_hide_braces() -> None:
    text = (
        "location = /t {\n"
        "  content_by_lua_block {\n"
        "    --[[\n      {{{\n    ]]\n"
        "    --[==[\n      }}}\n    ]==]\n"
        "    local s = [[}content{]] .. '}x{' .. \"{y}\"\n"
        "    -- a } in a line comment, and a ' quote\n"
        "    ngx.say(s)\n"
        "  }\n"
        "  return 204;\n"
        "}\n"
    )
    config = parse(text)
    assert config.errors == []
    assert [d.name for d in config.walk()] == [
        "location",
        "content_by_lua_block",
        "return",
    ]
