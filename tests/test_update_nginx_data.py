"""Tests for scripts/update_nginx_data.py, using saved nginx.org pages."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "nginx-docs"


@pytest.fixture(scope="module")
def scraper() -> ModuleType:
    pytest.importorskip("bs4")
    path = ROOT / "scripts" / "update_nginx_data.py"
    spec = importlib.util.spec_from_file_location("update_nginx_data", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_module_index(scraper: ModuleType) -> None:
    pages = scraper.module_pages(page("index.html"))
    assert pages[0] == ("ngx_core_module.html", "Core functionality")
    assert ("http/ngx_http_v3_module.html", "ngx_http_v3_module") in pages
    assert ("ngx_mgmt_module.html", "ngx_mgmt_module") in pages
    hrefs = {href for href, _ in pages}
    assert not hrefs & {"dirindex.html", "varindex.html"}
    assert "http/ngx_http_index_module.html" in hrefs


def test_directives_and_variables(scraper: ModuleType) -> None:
    directives, variables = scraper.parse_module(
        page("ngx_http_v3_module.html"),
        "http/ngx_http_v3_module.html",
        "ngx_http_v3_module",
    )
    by_name = {d["name"]: d for d in directives}
    http3 = by_name["http3"]
    assert http3["syntax"] == ["http3 on | off;"]
    assert http3["def"] == "http3 on;"
    assert http3["contexts"] == ["http", "server"]
    assert http3["desc"] == "Enables HTTP/3 protocol negotiation."
    assert http3["link"] == "http/ngx_http_v3_module.html#http3"
    assert http3["commercial"] is False
    assert "quic_retry" in by_name
    assert [v["name"] for v in variables] == ["$http3"]
    assert variables[0]["prefix"] is None


def test_commercial_module(scraper: ModuleType) -> None:
    directives, _ = scraper.parse_module(
        page("ngx_http_keyval_module.html"),
        "http/ngx_http_keyval_module.html",
        "ngx_http_keyval_module",
    )
    assert directives
    assert all(d["commercial"] for d in directives)


def test_layout_change_is_detected(scraper: ModuleType) -> None:
    broken = page("ngx_http_v3_module.html").replace("Syntax:", "Usage:")
    with pytest.raises(scraper.LayoutError):
        scraper.parse_module(broken, "x.html", "x")
