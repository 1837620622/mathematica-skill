"""Optional client for an official AgentTools MCP server.

The official Wolfram AgentTools MCP server speaks JSON-RPC over stdio. This
client is intentionally small and optional: the skill's core channel is
wolframscript, so a missing or incompatible MCP server never blocks local
native computation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import subprocess
from typing import Any

from .errors import MskError


@dataclass(slots=True)
class MCPTool:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


class AgentToolsMCPClient:
    def __init__(self, command: list[str], *, timeout: float = 60.0) -> None:
        self.command = command
        self.timeout = timeout
        self.process: subprocess.Popen[bytes] | None = None
        self.next_id = 1

    def __enter__(self) -> "AgentToolsMCPClient":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def start(self) -> None:
        if self.process is not None:
            return
        try:
            self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE)
        except FileNotFoundError as exc:
            raise MskError("MCP_ERROR", f"MCP command not found: {self.command[0]}") from exc
        self._request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "mathematica-skill", "version": "0.1.0"},
        })
        self._notify("notifications/initialized", {})

    def close(self) -> None:
        if self.process is None:
            return
        try:
            self.process.terminate()
            self.process.wait(timeout=5)
        except Exception:
            self.process.kill()
        finally:
            self.process = None

    def _send(self, payload: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise MskError("MCP_ERROR", "MCP server is not running")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.process.stdin.write(b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
        self.process.stdin.flush()

    def _read(self) -> dict[str, Any]:
        if self.process is None or self.process.stdout is None:
            raise MskError("MCP_ERROR", "MCP server is not running")
        headers: dict[str, str] = {}
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise MskError("MCP_ERROR", "MCP server closed the connection")
            stripped = line.strip()
            if not stripped:
                break
            key, _, value = stripped.decode("latin-1").partition(":")
            headers[key.lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        if not length:
            raise MskError("MCP_ERROR", "MCP server returned no Content-Length")
        body = self.process.stdout.read(length)
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise MskError("MCP_ERROR", "MCP server returned invalid JSON") from exc

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            response = self._read()
            if response.get("id") == request_id:
                if "error" in response:
                    raise MskError("MCP_ERROR", str(response["error"].get("message", "MCP request failed")),
                                   details=response["error"])
                return response.get("result") or {}

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def list_tools(self) -> list[MCPTool]:
        result = self._request("tools/list", {})
        return [MCPTool(name=str(item.get("name", "")), description=str(item.get("description", "")),
                        input_schema=item.get("inputSchema", {}) or {})
                for item in result.get("tools", []) if isinstance(item, dict)]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request("tools/call", {"name": name, "arguments": arguments})
