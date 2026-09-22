"""Error tolerant lexer and parser for nginx configuration files.

The parser never raises on bad input. It always returns a syntax tree for
as much of the document as it understands, plus a list of errors, so the
language features keep working while the user is typing. It works purely
in memory and never follows ``include`` directives.

Positions are zero-based ``(line, character)`` pairs counted in Python
code points. Ends are exclusive.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

Pos = tuple[int, int]


class TokenKind(enum.Enum):
    """Kinds of lexical tokens."""

    WORD = "word"
    STRING = "string"  # quoted with ' or "
    LBRACE = "{"
    RBRACE = "}"
    SEMICOLON = ";"
    COMMENT = "comment"
    RAW = "raw"  # verbatim body of a *_by_lua_block


@dataclass(frozen=True, slots=True)
class Token:
    """A lexical token and where it is in the document."""

    kind: TokenKind
    text: str  # exactly as written, quotes included
    start: Pos
    end: Pos

    @property
    def value(self) -> str:
        """Return the token value with quotes and escapes resolved."""
        if self.kind is not TokenKind.STRING:
            return self.text
        body = self.text[1:-1] if len(self.text) > 1 else ""
        quote = self.text[0]
        return body.replace("\\" + quote, quote)

    def contains(self, pos: Pos) -> bool:
        """Return whether ``pos`` touches the token (end inclusive)."""
        return self.start <= pos <= self.end


@dataclass(frozen=True, slots=True)
class ParseError:
    """A syntax problem found while parsing."""

    start: Pos
    end: Pos
    message: str


@dataclass(eq=False, slots=True)
class Directive:
    """A simple (``name args;``) or block (``name args { ... }``) directive."""

    name_token: Token
    args: list[Token] = field(default_factory=list)
    parent: Directive | None = None
    # Set for block directives
    block: list[Directive] | None = None
    open_brace: Token | None = None
    close_brace: Token | None = None  # None when the block is not closed
    raw_body: Token | None = None  # for *_by_lua_block directives
    terminator: Token | None = None  # ';' of simple directives
    end: Pos = (0, 0)

    @property
    def name(self) -> str:
        """Return the directive name."""
        return self.name_token.value

    @property
    def start(self) -> Pos:
        """Return where the directive starts."""
        return self.name_token.start

    @property
    def is_block(self) -> bool:
        """Return whether the directive opens a block."""
        return self.open_brace is not None

    def ancestors(self) -> list[Directive]:
        """Return enclosing block directives, outermost first."""
        chain: list[Directive] = []
        node = self.parent
        while node is not None:
            chain.append(node)
            node = node.parent
        return chain[::-1]

    def context(self) -> list[str]:
        """Return the names of enclosing blocks, outermost first."""
        return [node.name for node in self.ancestors()]


@dataclass(slots=True)
class Config:
    """Result of parsing one document."""

    directives: list[Directive]
    tokens: list[Token]  # every token, comments included, in order
    errors: list[ParseError]

    def walk(self) -> Iterator[Directive]:
        """Yield every directive, depth first, in document order."""
        stack = list(reversed(self.directives))
        while stack:
            node = stack.pop()
            yield node
            if node.block:
                stack.extend(reversed(node.block))

    def directive_at(self, pos: Pos) -> Directive | None:
        """Return the directive whose name is under ``pos``."""
        for node in self.walk():
            if node.name_token.contains(pos):
                return node
        return None

    def argument_at(self, pos: Pos) -> tuple[Directive, Token] | None:
        """Return the directive and argument token under ``pos``."""
        for node in self.walk():
            if node.start > pos:
                break
            for arg in node.args:
                if arg.contains(pos):
                    return node, arg
        return None

    def blocks_at(self, pos: Pos) -> list[Directive]:
        """Return the block directives enclosing ``pos``, outermost first."""
        chain: list[Directive] = []
        children = self.directives
        while True:
            for node in children:
                if node.open_brace is None or node.block is None:
                    continue
                inside = node.open_brace.end <= pos and (
                    node.close_brace is None or pos <= node.close_brace.start
                )
                if inside:
                    chain.append(node)
                    children = node.block
                    break
            else:
                return chain

    def context_at(self, pos: Pos) -> list[str]:
        """Return the names of the blocks enclosing ``pos``."""
        return [node.name for node in self.blocks_at(pos)]

    def token_before(self, pos: Pos) -> Token | None:
        """Return the last non-comment token that ends before ``pos``.

        A token that touches ``pos`` (the word being typed) is skipped.
        """
        previous = None
        for token in self.tokens:
            if token.end >= pos:
                break
            if token.kind is not TokenKind.COMMENT:
                previous = token
        return previous


# --- lexer -------------------------------------------------------------

_SPECIAL = {"{": TokenKind.LBRACE, "}": TokenKind.RBRACE}
_SPECIAL[";"] = TokenKind.SEMICOLON
_WORD_BREAK = set(" \t\r\n;{}")
RAW_BLOCK_SUFFIX = "_by_lua_block"
_LUA_LONG_OPEN = re.compile(r"\[(=*)\[")


class _Lexer:
    def __init__(self, text: str) -> None:
        self.text = text
        self.index = 0
        self.line = 0
        self.col = 0
        self.errors: list[ParseError] = []

    @property
    def pos(self) -> Pos:
        return (self.line, self.col)

    def _peek(self, offset: int = 0) -> str:
        index = self.index + offset
        return self.text[index] if index < len(self.text) else ""

    def _advance(self) -> str:
        char = self.text[self.index]
        self.index += 1
        if char == "\n":
            self.line += 1
            self.col = 0
        else:
            self.col += 1
        return char

    def tokens(self) -> Iterator[Token]:
        while self.index < len(self.text):
            char = self._peek()
            if char in " \t\r\n":
                self._advance()
            elif char == "#":
                yield self._comment()
            elif char in _SPECIAL:
                start = self.pos
                self._advance()
                yield Token(_SPECIAL[char], char, start, self.pos)
            elif char in "\"'":
                yield self._string(char)
            else:
                yield self._word()

    def _comment(self) -> Token:
        start, begin = self.pos, self.index
        while self.index < len(self.text) and self._peek() != "\n":
            self._advance()
        return Token(
            TokenKind.COMMENT, self.text[begin : self.index], start, self.pos
        )

    def _string(self, quote: str) -> Token:
        start, begin = self.pos, self.index
        self._advance()
        while self.index < len(self.text):
            char = self._advance()
            if char == "\\" and self.index < len(self.text):
                self._advance()
            elif char == quote:
                break
        else:
            self.errors.append(
                ParseError(start, self.pos, f"unterminated {quote} string")
            )
        return Token(
            TokenKind.STRING, self.text[begin : self.index], start, self.pos
        )

    def _word(self) -> Token:
        start, begin = self.pos, self.index
        while self.index < len(self.text):
            char = self._peek()
            if char == "\\" and self._peek(1):
                self._advance()
                self._advance()
            elif char == "$" and self._peek(1) == "{":
                # ${var} is a single word, its braces are not blocks
                while self.index < len(self.text) and self._peek() != "}":
                    if self._peek() == "\n":
                        break
                    self._advance()
                if self._peek() == "}":
                    self._advance()
            elif char in _WORD_BREAK:
                break
            else:
                self._advance()
        return Token(
            TokenKind.WORD, self.text[begin : self.index], start, self.pos
        )

    def _skip_lua_long_bracket(self) -> bool:
        """Skip a Lua ``[[...]]`` / ``[==[...]==]`` if one starts here."""
        match = _LUA_LONG_OPEN.match(self.text, self.index)
        if match is None:
            return False
        close = "]" + match.group(1) + "]"
        end = self.text.find(close, match.end())
        end = len(self.text) if end == -1 else end + len(close)
        while self.index < end:
            self._advance()
        return True

    def _skip_lua_line(self, quote: str | None = None) -> None:
        """Skip a Lua short string (``quote`` given) or line comment."""
        if quote is not None:
            self._advance()
        while self.index < len(self.text):
            char = self._peek()
            if char == "\n":
                return
            self._advance()
            if char == "\\" and quote is not None and self._peek():
                self._advance()
            elif char == quote:
                return

    def raw_block(self) -> tuple[Token | None, Token | None]:
        """Read a Lua block body verbatim, up to its matching '}'."""
        start, begin = self.pos, self.index
        depth = 0
        while self.index < len(self.text):
            char = self._peek()
            if char == "-" and self._peek(1) == "-":
                self._advance()
                self._advance()
                if not self._skip_lua_long_bracket():
                    self._skip_lua_line()
                continue
            if char in "\"'":
                self._skip_lua_line(char)
                continue
            if char == "[" and self._skip_lua_long_bracket():
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                if depth == 0:
                    body = Token(
                        TokenKind.RAW,
                        self.text[begin : self.index],
                        start,
                        self.pos,
                    )
                    close_start = self.pos
                    self._advance()
                    close = Token(TokenKind.RBRACE, "}", close_start, self.pos)
                    return body, close
                depth -= 1
            self._advance()
        body = Token(TokenKind.RAW, self.text[begin:], start, self.pos)
        return body, None


# --- parser ------------------------------------------------------------


class _Parser:
    def __init__(self, text: str) -> None:
        self.lexer = _Lexer(text)
        self.errors = self.lexer.errors
        self.tokens: list[Token] = []
        self.root: list[Directive] = []
        # enclosing block directives; the innermost is last
        self.blocks: list[Directive] = []
        self.current: Directive | None = None  # directive reading its args

    @property
    def children(self) -> list[Directive]:
        if not self.blocks:
            return self.root
        block = self.blocks[-1].block
        assert block is not None
        return block

    @property
    def parent(self) -> Directive | None:
        return self.blocks[-1] if self.blocks else None

    def error(self, start: Pos, end: Pos, message: str) -> None:
        self.errors.append(ParseError(start, end, message))

    def parse(self) -> Config:
        handlers = {
            TokenKind.WORD: self._word,
            TokenKind.STRING: self._word,
            TokenKind.SEMICOLON: self._semicolon,
            TokenKind.LBRACE: self._open_block,
            TokenKind.RBRACE: self._close_block,
        }
        for token in self.lexer.tokens():
            self.tokens.append(token)
            handler = handlers.get(token.kind)
            if handler is not None:
                handler(token)
        self._end_of_file()
        self.errors.sort(key=lambda error: error.start)
        return Config(self.root, self.tokens, self.errors)

    def _start_directive(self, name: Token) -> Directive:
        self.current = Directive(name_token=name, parent=self.parent)
        self.children.append(self.current)
        return self.current

    def _finish_without_semicolon(self) -> None:
        node = self.current
        assert node is not None
        last = node.args[-1] if node.args else node.name_token
        node.end = last.end
        self.error(last.end, last.end, f'missing ";" after "{node.name}"')
        self.current = None

    def _word(self, token: Token) -> None:
        if self.current is None:
            self._start_directive(token)
        else:
            self.current.args.append(token)

    def _semicolon(self, token: Token) -> None:
        if self.current is None:
            self.error(token.start, token.end, 'unexpected ";"')
            return
        self.current.terminator = token
        self.current.end = token.end
        self.current = None

    def _open_block(self, token: Token) -> None:
        node = self.current
        if node is None:
            self.error(token.start, token.end, 'block "{" without a name')
            name = Token(TokenKind.WORD, "", token.start, token.start)
            node = self._start_directive(name)
        node.open_brace = token
        node.block = []
        self.current = None
        if node.name.endswith(RAW_BLOCK_SUFFIX):
            self._raw_block(node, token)
        else:
            self.blocks.append(node)

    def _raw_block(self, node: Directive, open_brace: Token) -> None:
        body, close = self.lexer.raw_block()
        node.raw_body = body
        if body is not None:
            self.tokens.append(body)
        if close is None:
            node.end = self.lexer.pos
            self.error(open_brace.start, open_brace.end, 'unclosed block "{"')
            return
        self.tokens.append(close)
        node.close_brace = close
        node.end = close.end

    def _close_block(self, token: Token) -> None:
        if self.current is not None:
            self._finish_without_semicolon()
        if not self.blocks:
            self.error(token.start, token.end, 'unexpected "}"')
            return
        node = self.blocks.pop()
        node.close_brace = token
        node.end = token.end

    def _end_of_file(self) -> None:
        if self.current is not None:
            self._finish_without_semicolon()
        for node in self.blocks:
            assert node.open_brace is not None
            node.end = self.lexer.pos
            self.error(
                node.open_brace.start,
                node.open_brace.end,
                f'unclosed block "{{" of "{node.name}"',
            )


def parse(text: str) -> Config:
    """Parse ``text`` into a :class:`Config`. Never raises."""
    return _Parser(text).parse()
