"""Regenerate the directive and variable data from nginx.org.

Usage::

    uv run python scripts/update_nginx_data.py [--no-cache]

Pages are cached in ``.cache/nginx-docs`` so reruns are fast. The script
fails loudly when the documentation layout changes instead of silently
writing incomplete data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

BASE_URL = "https://nginx.org/en/docs/"
ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "nginx_language_server" / "data"
CACHE = ROOT / ".cache" / "nginx-docs"

MODULES_TITLE = "Modules reference"
TABLE_HEAD = "Syntax:Default:Context:"
SINCE = re.compile(r"^This directive appeared in versions? (\d+\.\d+\.\d+)")
COMMERCIAL = re.compile(
    r"This (directive|module|variable) is available as (a )?part of"
    r" our commercial subscription"
)
USER_AGENT = "nginx-language-server data updater"

Fetch = Callable[[str], str]


class LayoutError(RuntimeError):
    """The documentation no longer looks like what this script expects."""


def check(condition: object, message: str) -> None:
    """Raise :class:`LayoutError` unless ``condition`` holds."""
    if not condition:
        raise LayoutError(message)


def make_fetcher(use_cache: bool) -> Fetch:
    """Return a function that downloads a docs page, with a disk cache."""

    def fetch(page: str) -> str:
        url = BASE_URL + page
        cached = CACHE / hashlib.sha256(url.encode()).hexdigest()
        if use_cache and cached.exists():
            return cached.read_text(encoding="utf-8")
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            html = response.read().decode("utf-8")
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_text(html, encoding="utf-8")
        return html

    return fetch


def squash(text: str) -> str:
    """Collapse whitespace into single spaces."""
    return re.sub(r"\s+", " ", text).strip()


# --- index -------------------------------------------------------------


def module_pages(index_html: str) -> list[tuple[str, str]]:
    """Return (page, module name) for every module in the docs index."""
    soup = BeautifulSoup(index_html, "html.parser")
    titles = [
        h4 for h4 in soup.find_all("h4") if h4.get_text() == MODULES_TITLE
    ]
    check(len(titles) == 1, f'expected one "{MODULES_TITLE}" title')
    pages: list[tuple[str, str]] = []
    for link in titles[0].find_all_next("a", href=True):
        href = str(link["href"])
        if not re.fullmatch(r"(\w+/)?ngx_\w+\.html", href):
            continue
        name = squash(link.get_text())
        if (href, name) not in pages:
            pages.append((href, name))
    check(len(pages) >= 80, f"only {len(pages)} module pages found")
    return pages


# --- module pages ------------------------------------------------------


def _following_content(directive: Tag) -> list[Tag]:
    """Return the p/note/example/dl elements right after a directive."""
    nodes: list[Tag] = []
    node = directive.find_next_sibling()
    while isinstance(node, Tag):
        classes = node.get("class") or []
        if node.name in ("p", "dl") or (
            node.name == "blockquote"
            and ("note" in classes or "example" in classes)
        ):
            nodes.append(node)
            node = node.find_next_sibling()
        else:
            break
    return nodes


def parse_directive(
    box: Tag, page: str, module: str, module_commercial: bool
) -> dict[str, Any]:
    """Turn one ``div.directive`` into a directives.json entry."""
    head = re.sub(r"\s", "", "".join(th.get_text() for th in box("th")))
    check(head == TABLE_HEAD, f"{page}: unexpected table head {head!r}")
    cells = box("td")
    check(len(cells) == 3, f"{page}: expected 3 cells, got {len(cells)}")
    syntax_cell, default_cell, context_cell = cells

    strong = syntax_cell.find("strong")
    check(strong is not None, f"{page}: directive without a name")
    assert strong is not None
    name = strong.get_text().strip()
    syntax = [
        code.get_text().strip()
        for code in syntax_cell.find_all("code", recursive=False)
    ]
    check(syntax, f"{page}: {name} without syntax")

    default = default_cell.get_text().strip()
    contexts = re.sub(r"\s", "", context_cell.get_text()).split(",")
    check(all(contexts), f"{page}: {name} with an empty context")

    since = None
    appeared = box.find("p")
    if appeared is not None:
        match = SINCE.match(appeared.get_text().strip())
        check(match, f"{page}: {name}: unexpected {appeared.get_text()!r}")
        assert match is not None
        since = match.group(1)

    anchor = box.find_previous_sibling("a")
    check(anchor is not None, f"{page}: {name} has no anchor")
    assert anchor is not None
    anchor_name = anchor.attrs.get("name")
    check(anchor_name, f"{page}: {name} anchor has no name")

    desc = ""
    notes: list[str] = []
    commercial = module_commercial
    for node in _following_content(box):
        if node.name == "p" and not desc and node.get_text().strip():
            desc = squash(node.get_text())
        elif node.name == "blockquote" and "note" in (node.get("class") or []):
            note = node.get_text()
            if COMMERCIAL.search(squash(note)):
                commercial = True
            notes.append(note)

    return {
        "name": name,
        "syntax": syntax,
        "def": None if default == "—" else default,
        "contexts": contexts,
        "desc": desc,
        "notes": notes,
        "since": since,
        "module": module,
        "commercial": commercial,
        "link": f"{page}#{anchor_name}",
    }


def parse_variables(
    soup: BeautifulSoup, page: str, module: str, module_commercial: bool
) -> list[dict[str, Any]]:
    """Return the variables.json entries of a module page."""
    variables: list[dict[str, Any]] = []
    for term in soup.select('dt[id^="var_"]'):
        definition = term.find_next_sibling("dd")
        check(definition is not None, f"{page}: {term.get_text()} has no dd")
        assert definition is not None
        commercial = module_commercial
        for note in definition.find_all("blockquote"):
            if COMMERCIAL.search(squash(note.get_text())):
                commercial = True
            note.extract()
        name = squash(term.get_text())
        check(name.startswith("$"), f"{page}: odd variable {name!r}")
        # "$arg_<i>name</i>": the italic part stands for any suffix
        codes = term.find_all("code", recursive=False)
        prefix = None
        if len(codes) == 2 and codes[1].find("i") is not None:
            prefix = squash(codes[0].get_text())
        variables.append(
            {
                "name": name,
                "prefix": prefix,
                "desc": definition.get_text().strip(),
                "module": module,
                "commercial": commercial,
                "link": f"{page}#{term['id']}",
            }
        )
    return variables


def parse_module(
    html: str, page: str, module: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (directives, variables) documented on a module page."""
    soup = BeautifulSoup(html, "html.parser")
    module_commercial = False
    summary = soup.find("a", attrs={"name": "summary"})
    if summary is not None:
        for node in summary.find_all_next(["p", "blockquote"], limit=6):
            match = COMMERCIAL.search(squash(node.get_text()))
            if match is not None and match.group(1) == "module":
                module_commercial = True
    directives = [
        parse_directive(box, page, module, module_commercial)
        for box in soup.select("div.directive")
    ]
    variables = parse_variables(soup, page, module, module_commercial)
    return directives, variables


# --- main --------------------------------------------------------------


def collect(fetch: Fetch) -> tuple[list[Any], list[Any]]:
    """Download every module page and return (directives, variables)."""
    directives: list[dict[str, Any]] = []
    variables: list[dict[str, Any]] = []
    for page, module in module_pages(fetch("")):
        page_directives, page_variables = parse_module(
            fetch(page), page, module
        )
        print(
            f"{module:40} {len(page_directives):4} directives "
            f"{len(page_variables):4} variables",
            file=sys.stderr,
        )
        directives += page_directives
        variables += page_variables
    check(len(directives) >= 700, f"only {len(directives)} directives")
    check(len(variables) >= 150, f"only {len(variables)} variables")
    return directives, variables


def write_json(path: Path, data: object) -> None:
    """Write ``data`` the way the repository stores it."""
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def main() -> None:
    """Command line entry point."""
    parser = argparse.ArgumentParser(
        description="Regenerate directive and variable data from nginx.org."
    )
    parser.add_argument(
        "--no-cache", action="store_true", help="download every page again"
    )
    args = parser.parse_args()
    directives, variables = collect(make_fetcher(not args.no_cache))
    write_json(OUTPUT / "directives.json", directives)
    write_json(OUTPUT / "variables.json", variables)
    print(
        f"{len(directives)} directives, {len(variables)} variables",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
