"""MCP 协议：帧解析、初始化、工具列表与错误处理。"""

from __future__ import annotations

import io
import json
from pathlib import Path

from mathematica_skill import mcp_server


class _Buffer:
    def __init__(self, payload: bytes) -> None:
        self._stream = io.BytesIO(payload)

    def readline(self) -> bytes:
        return self._stream.readline()

    def read(self, size: int) -> bytes:
        return self._stream.read(size)


def _request(**payload) -> dict:
    return payload


def test_initialize_negotiates_protocol() -> None:
    response = mcp_server._handle({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26"},
    })
    assert response["result"]["protocolVersion"] == "2025-03-26"
    assert response["result"]["serverInfo"]["name"] == "mathematica-skill"
    assert "tools" in response["result"]["capabilities"]


def test_initialize_falls_back_for_unknown_version() -> None:
    response = mcp_server._handle({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "1999-01-01"},
    })
    assert response["result"]["protocolVersion"] == mcp_server.PROTOCOL_DEFAULT


def test_notification_gets_no_response() -> None:
    assert mcp_server._handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tool_list_has_schemas() -> None:
    response = mcp_server._handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = response["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert {"mathematica_doctor", "mathematica_run", "mathematica_verify"} <= names
    for tool in tools:
        assert tool["inputSchema"]["type"] == "object"
        assert "description" in tool
        assert tool["inputSchema"]["required"] is not None


def test_unknown_method_returns_jsonrpc_error() -> None:
    response = mcp_server._handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})
    assert response["error"]["code"] == -32601


def test_tool_call_with_bad_arguments_is_marked_error() -> None:
    response = mcp_server._handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                   "params": {"name": "mathematica_plan", "arguments": "not-an-object"}})
    assert response["result"]["isError"] is True


def test_tool_call_missing_task_returns_structured_error(tmp_path: Path) -> None:
    result = mcp_server._tool_result("mathematica_plan", {"task_path": str(tmp_path / "missing.json")})
    assert result["isError"] is True
    payload = json.loads(result["content"][0]["text"])
    assert payload["code"] == "INVALID_TASK"


def test_unknown_tool_is_error() -> None:
    result = mcp_server._tool_result("mathematica_unknown", {})
    assert result["isError"] is True


def test_example_tool_returns_task_document() -> None:
    result = mcp_server._tool_result("mathematica_example", {})
    payload = json.loads(result["content"][0]["text"])
    assert result["isError"] is False
    assert payload["schema_version"] == "1.0"


def test_read_message_newline_framing() -> None:
    body = b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
    assert mcp_server._read_message(_Buffer(body))["method"] == "ping"


def test_read_message_content_length_framing() -> None:
    body = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}).encode()
    stream = _Buffer(b"Content-Length: %d\r\n\r\n%s" % (len(body), body))
    payload = mcp_server._read_message(stream)
    assert payload["id"] == 2


def test_read_message_rejects_oversized_length() -> None:
    stream = _Buffer(b"Content-Length: 999999999\r\n\r\n{}")
    assert mcp_server._read_message(stream) is None


def test_write_message_is_single_line_json() -> None:
    buffer = io.BytesIO()

    class _Out:
        def write(self, data: bytes) -> None:
            buffer.write(data)

        def flush(self) -> None:
            pass

    mcp_server._write_message(_Out(), {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})
    text = buffer.getvalue().decode()
    assert text.count("\n") == 1
    assert json.loads(text)["result"]["ok"] is True
