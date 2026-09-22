"""Tests for the bundled directive data and its lookups."""

from __future__ import annotations

import pytest

from nginx_language_server.parser.data import (
    context_keys,
    directives_for,
    find_variable,
    module_family,
)


@pytest.mark.parametrize(
    ("name", "stack"),
    [
        ("http3", ["http", "server"]),
        ("quic_retry", ["http", "server"]),
        ("ssl_certificate_cache", ["stream", "server"]),
        ("proxy_pass_trailers", ["http", "server", "location"]),
        ("mgmt", []),
        ("acme_issuer", ["http"]),
    ],
)
def test_recent_nginx_directives(name: str, stack: list[str]) -> None:
    assert name in directives_for(stack)


def test_obsolete_directives_are_gone() -> None:
    assert "spdy_chunk_size" not in directives_for(["http", "server"])


@pytest.mark.parametrize(
    ("module", "contexts", "family"),
    [
        ("ngx_http_core_module", [], "http"),
        ("ngx_stream_core_module", [], "stream"),
        ("ngx_mail_core_module", [], "mail"),
        ("ngx_otel_module", ["http", "server", "location"], "http"),
        ("Core functionality", ["main", "http", "stream", "mail"], "core"),
        ("ngx_mgmt_module", ["main"], "core"),
    ],
)
def test_module_family(module: str, contexts: list[str], family: str) -> None:
    assert module_family(module, contexts) == family


def test_context_keys() -> None:
    assert context_keys([]) == ["main"]
    assert context_keys(["events"]) == ["events"]
    assert context_keys(["stream", "server"]) == [
        "core/server",
        "stream/server",
    ]
    assert "http/ifinlocation" in context_keys(
        ["http", "server", "location", "if"]
    )
    assert "http/ifinlocation" not in context_keys(["http", "server", "if"])


def test_commercial_directives_are_marked() -> None:
    ntlm = directives_for(["http", "upstream"])["ntlm"]
    assert ntlm.commercial
    assert "NGINX Plus" in ntlm.ls_detail
    assert "NGINX Plus" in ntlm.ls_documentation
    assert "NGINX Plus" not in directives_for(["http"])["gzip"].ls_detail


def test_documentation_links_to_nginx_org() -> None:
    doc = directives_for(["http", "server"])["http3"].ls_documentation
    assert "https://nginx.org/en/docs/http/ngx_http_v3_module.html#http3" in (
        doc
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("$host", "$host"),
        ("${host}", "$host"),
        ("$arg_page", "$arg_name"),
        ("$http_user_agent", "$http_name"),
        ("$upstream_http_x_cache", "$upstream_http_name"),
        ("$oidc_claim_email", "$oidc_claim_name"),
        ("$server_name", "$server_name"),  # ends in _name, not a prefix
        ("$nope", None),
        ("$arg_", None),
    ],
)
def test_find_variable(name: str, expected: str | None) -> None:
    found = find_variable(name, ["http", "server"])
    assert (found.name if found else None) == expected


def test_variables_follow_family() -> None:
    http = find_variable("$remote_addr", ["http"])
    stream = find_variable("$remote_addr", ["stream"])
    assert http is not None
    assert http.module == "ngx_http_core_module"
    assert stream is not None
    assert stream.module == "ngx_stream_core_module"
