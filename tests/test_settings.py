"""initializationOptions are honored."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.lsp_client import LspClient


@pytest.fixture(scope="module")
def initialization_options() -> object:
    return {"diagnostics": {"unknownDirectives": False}}


def test_unknown_directives_can_be_silenced(
    client: LspClient, open_doc: Callable[[str], str]
) -> None:
    uri = open_doc(
        "events {}\nhttp {\n  lua_shared_dict cache 10m;\n  gzip on;\n}\n"
        "gzip on;\n"
    )
    assert [d["message"] for d in client.diagnostics(uri)] == [
        '"gzip" directive is not allowed here'
    ]
