"""Shared fixtures."""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.lsp_client import LspClient

_doc_counter = itertools.count()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[LspClient]:
    """Start one server per test module, already initialized."""
    log = tmp_path_factory.mktemp("lsp") / "server.log"
    lsp = LspClient(log)
    lsp.initialize()
    yield lsp
    lsp.close()


@pytest.fixture
def open_doc(client: LspClient) -> Callable[[str], str]:
    """Open ``text`` under a fresh URI and return that URI."""

    def _open(text: str) -> str:
        uri = f"file:///tmp/test-{next(_doc_counter)}/nginx.conf"
        client.open(uri, text)
        return uri

    return _open


def cursor(text: str) -> tuple[str, int, int]:
    """Strip the ``|`` cursor marker and return (text, line, character)."""
    index = text.index("|")
    before = text[:index]
    line = before.count("\n")
    char = index - (before.rfind("\n") + 1)
    return text[:index] + text[index + 1 :], line, char


@pytest.fixture
def repo_root() -> Path:
    """Return the repository root."""
    return Path(__file__).resolve().parent.parent
