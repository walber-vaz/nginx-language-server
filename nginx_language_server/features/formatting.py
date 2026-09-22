"""textDocument/formatting.

The formatter works on the token stream, so comments and blank lines are
kept, and never changes a token: only whitespace between tokens moves.
Documents with syntax errors are left alone.
"""

from __future__ import annotations

import re

from lsprotocol.types import FormattingOptions, Position, Range, TextEdit
from pygls.workspace import TextDocument

from nginx_language_server import pygls_utils
from nginx_language_server.parser import nginxconf

Kind = nginxconf.TokenKind
Token = nginxconf.Token


def _reindent_lua(body: str, indent: str) -> str:
    """Shift a multi-line Lua body to ``indent``, keeping relative indents.

    Bodies with long brackets are kept verbatim: whitespace inside
    ``[[ ... ]]`` strings is significant.
    """
    if "[[" in body or re.search(r"\[=+\[", body):
        return body.rstrip()
    lines = body.rstrip().split("\n")
    # lines[0] is what follows "{" on the opening line
    rest = [line.expandtabs(4) for line in lines[1:]]
    common = min(
        (len(line) - len(line.lstrip()) for line in rest if line.strip()),
        default=0,
    )
    shifted = [indent + line[common:] if line.strip() else "" for line in rest]
    return "\n".join([lines[0].rstrip(), *shifted])


class _Formatter:
    def __init__(self, indent_unit: str) -> None:
        self.indent_unit = indent_unit
        self.lines: list[str] = []
        self.line: str | None = None  # line being built
        self.depth = 0
        self.previous: Token | None = None
        self.in_statement = False
        self.continuation: int | None = None  # column of the first argument
        self.inline_raw = False

    # --- output ----------------------------------------------------------

    def _flush(self) -> None:
        if self.line is not None:
            self.lines.append(self.line.rstrip())
            self.line = None

    def _start_line(self, text: str, column: int | None = None) -> None:
        self._flush()
        if column is None:
            self.line = self.indent_unit * self.depth + text
        else:
            self.line = " " * column + text

    def _append(self, text: str, space: bool = True) -> None:
        assert self.line is not None
        self.line += (" " if space else "") + text

    def _blank(self) -> None:
        """Add a blank line, never two in a row or after an opening brace."""
        self._flush()
        if self.lines and self.lines[-1] and not self.lines[-1].endswith("{"):
            self.lines.append("")

    def _end_statement(self) -> None:
        self.in_statement = False
        self.continuation = None

    # --- tokens ----------------------------------------------------------

    def run(self, tokens: list[Token]) -> str:
        handlers = {
            Kind.COMMENT: self._comment,
            Kind.WORD: self._word,
            Kind.STRING: self._word,
            Kind.SEMICOLON: self._semicolon,
            Kind.LBRACE: self._open_brace,
            Kind.RAW: self._raw,
            Kind.RBRACE: self._close_brace,
        }
        for token in tokens:
            handlers[token.kind](token)
            self.previous = token
        self._flush()
        while self.lines and not self.lines[-1]:
            self.lines.pop()
        return "\n".join(self.lines) + "\n" if self.lines else ""

    def _same_line(self, token: Token) -> bool:
        return (
            self.previous is not None
            and token.start[0] == self.previous.end[0]
        )

    def _blank_before(self, token: Token) -> bool:
        return (
            self.previous is not None
            and token.start[0] - self.previous.end[0] > 1
        )

    def _comment(self, token: Token) -> None:
        if self._same_line(token) and self.line is not None:
            self._append(token.text)  # trailing comment stays put
        else:
            if self._blank_before(token) and not self.in_statement:
                self._blank()
            column = self.continuation if self.in_statement else None
            self._start_line(token.text, column)
        self._flush()

    def _word(self, token: Token) -> None:
        if not self.in_statement:  # directive name
            if self._blank_before(token):
                self._blank()
            self._start_line(token.text)
            self.in_statement = True
            self.continuation = None
        elif self.line is None or not self._same_line(token):
            # argument on a new line: align with the first argument
            column = self.continuation
            if column is None:
                column = len(self.indent_unit * (self.depth + 1))
                self.continuation = column
            self._start_line(token.text, column)
        else:
            if self.continuation is None:
                self.continuation = len(self.line) + 1
            self._append(token.text)

    def _semicolon(self, token: Token) -> None:
        if self.line is None:
            self._start_line(token.text, self.continuation)
        else:
            self._append(token.text, space=False)
        self._end_statement()

    def _open_brace(self, token: Token) -> None:
        if self.line is None:
            self._start_line(token.text, self.continuation)
        else:
            self._append(token.text)
        self.depth += 1
        self._end_statement()

    def _raw(self, token: Token) -> None:
        self.inline_raw = "\n" not in token.text
        if self.inline_raw:
            self._append(token.text.strip())
        else:
            assert self.line is not None
            self.line += _reindent_lua(
                token.text, self.indent_unit * self.depth
            )

    def _close_brace(self, token: Token) -> None:
        self.depth -= 1
        if self.inline_raw:
            self._append(token.text)
            self.inline_raw = False
        else:
            self._start_line(token.text)
        self._end_statement()


def format_config(config: nginxconf.Config, indent_unit: str) -> str | None:
    """Return the formatted text, or ``None`` if it cannot be formatted."""
    if config.errors:
        return None
    return _Formatter(indent_unit).run(config.tokens)


def formatting(
    document: TextDocument, options: FormattingOptions
) -> list[TextEdit] | None:
    """Return the edits that format ``document``."""
    config = pygls_utils.parse(document)
    indent_unit = " " * options.tab_size if options.insert_spaces else "\t"
    formatted = format_config(config, indent_unit)
    if formatted is None:
        return None
    if formatted == document.source:
        return []
    end = pygls_utils.to_client_range(
        document, (0, 0), (len(document.lines), 0)
    ).end
    return [
        TextEdit(
            range=Range(start=Position(line=0, character=0), end=end),
            new_text=formatted,
        )
    ]
