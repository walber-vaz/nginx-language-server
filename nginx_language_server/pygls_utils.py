"""Helpers bridging pygls documents and the nginx parser.

LSP positions count UTF-16 code units; the parser counts Python code
points. Everything that crosses that boundary goes through here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lsprotocol.types import Position, Range
from pygls.workspace import TextDocument

from nginx_language_server.parser import nginxconf

Pos = nginxconf.Pos

_WORD = re.compile(r"\$\{[A-Za-z0-9_]*\}?|\$?[A-Za-z0-9_]+|\$")


@dataclass(frozen=True, slots=True)
class Word:
    """A word in a line and where it is."""

    text: str
    start: Pos
    end: Pos


def to_server(document: TextDocument, position: Position) -> Pos:
    """Convert a client position to a parser position."""
    server = document.position_codec.position_from_client_units(
        document.lines, position
    )
    return (server.line, server.character)


def to_client_range(document: TextDocument, start: Pos, end: Pos) -> Range:
    """Convert a parser range to a client range."""
    return document.position_codec.range_to_client_units(
        document.lines,
        Range(
            start=Position(line=start[0], character=start[1]),
            end=Position(line=end[0], character=end[1]),
        ),
    )


def word_at(document: TextDocument, pos: Pos) -> Word | None:
    """Return the directive name or variable touching ``pos``."""
    line_number, char = pos
    if line_number >= len(document.lines):
        return None
    line = document.lines[line_number]
    for match in _WORD.finditer(line):
        if match.start() <= char <= match.end():
            return Word(
                match.group(),
                (line_number, match.start()),
                (line_number, match.end()),
            )
    return None


_cache: dict[str, tuple[int | None, str, nginxconf.Config]] = {}


def parse(document: TextDocument) -> nginxconf.Config:
    """Parse a document, reusing the last result while it is unchanged."""
    source = document.source
    cached = _cache.get(document.uri)
    if cached is not None and cached[0] == document.version:
        if document.version is not None or cached[1] == source:
            return cached[2]
    config = nginxconf.parse(source)
    _cache[document.uri] = (document.version, source, config)
    return config


def forget(uri: str) -> None:
    """Drop the cached parse of a closed document."""
    _cache.pop(uri, None)
