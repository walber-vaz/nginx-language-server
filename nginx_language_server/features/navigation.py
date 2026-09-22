"""textDocument/definition and textDocument/documentLink.

- ``include`` arguments point at the included files (globs expanded).
- ``proxy_pass http://name`` and friends point at ``upstream name``.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

from lsprotocol.types import DocumentLink, Location, Position, Range
from pygls.workspace import TextDocument

from nginx_language_server import pygls_utils
from nginx_language_server.parser import nginxconf

_PASS_DIRECTIVES = {
    "proxy_pass",
    "fastcgi_pass",
    "grpc_pass",
    "memcached_pass",
    "scgi_pass",
    "uwsgi_pass",
}
_GLOB_CHARS = re.compile(r"[*?\[]")
_UPSTREAM_REF = re.compile(r"^(?:[a-z]+://)?([^/:$]+)(?::\d+)?(?:/.*)?$")
# How far up to look for the nginx.conf that relative includes start from
_MAX_ROOT_DEPTH = 4


def _search_dirs(document_path: Path) -> list[Path]:
    """Return the directories relative includes may be resolved against.

    nginx resolves them against its configuration prefix, the folder of
    the main nginx.conf, which is often an ancestor of the edited file.
    """
    folder = document_path.parent
    dirs = [folder]
    for candidate in [folder, *folder.parents][:_MAX_ROOT_DEPTH]:
        if (candidate / "nginx.conf").is_file() and candidate not in dirs:
            dirs.append(candidate)
    return dirs


def include_targets(document: TextDocument, argument: str) -> list[Path]:
    """Return the files an ``include`` argument refers to."""
    if not document.path:
        return []
    path = Path(argument).expanduser()
    bases = (
        [Path()] if path.is_absolute() else _search_dirs(Path(document.path))
    )
    for base in bases:
        pattern = str(base / path)
        if _GLOB_CHARS.search(argument):
            matches = sorted(glob.glob(pattern))
        else:
            matches = [pattern] if Path(pattern).is_file() else []
        files = [Path(match) for match in matches if Path(match).is_file()]
        if files:
            return files
    return []


def _file_start(path: Path) -> Location:
    start = Position(line=0, character=0)
    return Location(
        uri=path.resolve().as_uri(), range=Range(start=start, end=start)
    )


def _upstream_name(argument: str) -> str | None:
    match = _UPSTREAM_REF.match(argument)
    return match.group(1) if match else None


def definition(
    document: TextDocument, pos: nginxconf.Pos
) -> list[Location] | None:
    """Return where the argument under ``pos`` is defined."""
    config = pygls_utils.parse(document)
    found = config.argument_at(pos)
    if found is None:
        return None
    directive, argument = found
    if directive.name == "include":
        targets = include_targets(document, argument.value)
        return [_file_start(target) for target in targets] or None
    if directive.name in _PASS_DIRECTIVES and argument is directive.args[0]:
        name = _upstream_name(argument.value)
        locations = [
            Location(
                uri=document.uri,
                range=pygls_utils.to_client_range(
                    document, node.args[0].start, node.args[0].end
                ),
            )
            for node in config.walk()
            if node.name == "upstream"
            and node.args
            and node.args[0].value == name
        ]
        return locations or None
    return None


def document_links(document: TextDocument) -> list[DocumentLink]:
    """Return clickable links for ``include`` directives."""
    links: list[DocumentLink] = []
    for node in pygls_utils.parse(document).walk():
        if node.name != "include" or len(node.args) != 1:
            continue
        argument = node.args[0]
        if _GLOB_CHARS.search(argument.value):
            continue  # several targets: use go-to-definition instead
        targets = include_targets(document, argument.value)
        if len(targets) == 1:
            links.append(
                DocumentLink(
                    range=pygls_utils.to_client_range(
                        document, argument.start, argument.end
                    ),
                    target=targets[0].resolve().as_uri(),
                )
            )
    return links
