"""Minimal synchronous LSP client that talks to the server over stdio.

It does not depend on pygls, so the same tests exercise the server no
matter which pygls version the server itself is built on.
"""

from __future__ import annotations

import itertools
import json
import subprocess
import sys
import threading
from pathlib import Path
from queue import Empty, Queue
from typing import Any

TIMEOUT = 10


class LspClient:
    """Spawn the language server and exchange JSON-RPC messages with it."""

    def __init__(self, stderr_path: Path) -> None:
        self._stderr = stderr_path.open("w")
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "nginx_language_server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
        )
        self._ids = itertools.count(1)
        self._responses: dict[int, Queue[dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self.notifications: Queue[dict[str, Any]] = Queue()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    # --- transport -------------------------------------------------------

    def _write(self, message: dict[str, Any]) -> None:
        assert self._proc.stdin is not None
        body = json.dumps({"jsonrpc": "2.0", **message}).encode()
        header = f"Content-Length: {len(body)}\r\n\r\n".encode()
        self._proc.stdin.write(header + body)
        self._proc.stdin.flush()

    def _read_loop(self) -> None:
        stdout = self._proc.stdout
        assert stdout is not None
        while True:
            headers: dict[str, str] = {}
            while line := stdout.readline():
                line = line.strip()
                if not line:
                    break
                key, value = line.decode().split(":", 1)
                headers[key.strip().lower()] = value.strip()
            if not headers:
                return  # EOF
            message = json.loads(stdout.read(int(headers["content-length"])))
            if "id" in message and "method" not in message:
                self._queue_for(message["id"]).put(message)
            elif "id" in message:
                # server -> client request: acknowledge with an empty result
                self._write({"id": message["id"], "result": None})
            else:
                self.notifications.put(message)

    def _queue_for(self, request_id: int) -> Queue[dict[str, Any]]:
        with self._lock:
            return self._responses.setdefault(request_id, Queue())

    # --- public API ------------------------------------------------------

    def request(self, method: str, params: Any = None) -> Any:
        """Send a request and return its ``result`` (raise on error)."""
        request_id = next(self._ids)
        self._write({"id": request_id, "method": method, "params": params})
        try:
            response = self._queue_for(request_id).get(timeout=TIMEOUT)
        except Empty:
            raise TimeoutError(f"no response to {method}") from None
        if "error" in response:
            raise RuntimeError(f"{method} failed: {response['error']}")
        return response.get("result")

    def notify(self, method: str, params: Any = None) -> None:
        """Send a notification."""
        self._write({"method": method, "params": params})

    def initialize(self, options: Any = None) -> dict[str, Any]:
        """Run the initialize handshake and return the server capabilities."""
        result = self.request(
            "initialize",
            {
                "processId": None,
                "rootUri": None,
                "capabilities": {},
                "initializationOptions": options,
            },
        )
        self.notify("initialized", {})
        return result["capabilities"]

    def open(self, uri: str, text: str, version: int = 1) -> None:
        """Open a document in the server."""
        self.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": "nginx",
                    "version": version,
                    "text": text,
                }
            },
        )

    def diagnostics(self, uri: str) -> list[dict[str, Any]]:
        """Wait for the diagnostics published for ``uri``."""
        while True:
            try:
                message = self.notifications.get(timeout=TIMEOUT)
            except Empty:
                raise TimeoutError(f"no diagnostics for {uri}") from None
            params = message.get("params") or {}
            if (
                message.get("method") == "textDocument/publishDiagnostics"
                and params.get("uri") == uri
            ):
                return params["diagnostics"]

    def position_request(
        self, method: str, uri: str, line: int, char: int
    ) -> Any:
        """Send a request that takes a document and a position."""
        return self.request(
            method,
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": char},
            },
        )

    def completion_labels(self, uri: str, line: int, char: int) -> list[str]:
        """Return the labels of completion items at a position."""
        result = self.request(
            "textDocument/completion",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": char},
            },
        )
        if result is None:
            return []
        items = result["items"] if isinstance(result, dict) else result
        return [item["label"] for item in items]

    def hover_text(self, uri: str, line: int, char: int) -> str | None:
        """Return the markdown of a hover at a position, if any."""
        result = self.request(
            "textDocument/hover",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": char},
            },
        )
        return None if result is None else result["contents"]["value"]

    def close(self) -> None:
        """Shut the server down cleanly."""
        try:
            self.request("shutdown")
            self.notify("exit")
            self._proc.wait(timeout=TIMEOUT)
        finally:
            if self._proc.poll() is None:
                self._proc.kill()
            self._stderr.close()
