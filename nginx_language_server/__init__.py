"""Nginx Language Server."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("nginx-language-server")
except PackageNotFoundError:  # running from a source tree
    __version__ = "0.0.0+unknown"
