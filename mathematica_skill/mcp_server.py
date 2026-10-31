"""最小但完整的 MCP stdio 服务，仅用标准库实现。

只做本地进程通信，不监听网络端口；工具名统一 mathematica_*，避免和官方
Wolfram MCP 冲突。每个工具返回结构化 JSON 文本，出错时 isError=true。
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

from . import __version__
from .adapter_frontend import FrontendAdapter
from .adapter_wolframscript import WolframscriptAdapter
from .discovery import detect
from .errors import MskError
from .models import example_document
from .workflow import RunOptions, build_only, lint_task, plan_task, run_task

PROTOCOL_DEFAULT = "2025-06-18"
PROTOCOL_SUPPORTED = {"2025-06-18", "2025-03-26", "2024-11-05"}


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    }


TOOLS: list[dict[str, Any]] = [
    _tool("mathematica_doctor", "检测 Wolfram 内核、许可证、前端和 wolframscript。",
          {"frontend": {"type": "boolean", "default": False}}),
    _tool("mathematica_plan", "解析任务 JSON 并返回执行计划，不启动 Mathematica。",
          {"task_path": {"type": "string"}}, ["task_path"]),
    _tool("mathematica_lint", "静态检查 Wolfram Language 语法与高风险调用。",
          {"task_path": {"type": "string"}, "allow_external": {"type": "boolean", "default": False}}, ["task_path"]),
    _tool("mathematica_build", "生成原生 .nb 和 .wl；draft=true 时不要求 Mathematica。",
          {"task_path": {"type": "string"}, "out_dir": {"type": "string"},
           "draft": {"type": "boolean", "default": False}, "timeout": {"type": "number", "default": 900}},
          ["task_path"]),
    _tool("mathematica_run", "跑完整流水线：预检、原生执行、导出、重开复算、对账、交付。",
          {"task_path": {"type": "string"}, "out_dir": {"type": "string"},
           "timeout": {"type": "number", "default": 900}, "frontend_timeout": {"type": "number", "default": 240},
           "allow_external": {"type": "boolean", "default": False},
           "allow_draft": {"type": "boolean", "default": False},
           "no_frontend": {"type": "boolean", "default": False},
           "no_rerun": {"type": "boolean", "default": False},
           "seed": {"type": "integer"}, "overwrite": {"type": "boolean", "default": False},
           "dry_run": {"type": "boolean", "default": False}},
          ["task_path"]),
    _tool("mathematica_evaluate_notebook", "用桌面前端执行已有 .nb 并返回结果。",
          {"notebook_path": {"type": "string"}, "out_path": {"type": "string"},
           "timeout": {"type": "number", "default": 240}}, ["notebook_path"]),
    _tool("mathematica_export", "从真实 Wolfram 图形导出 PNG/PDF/CSV。",
          {"task_path": {"type": "string"}, "code_path": {"type": "string"}, "out_dir": {"type": "string"},
           "result_path": {"type": "string", "default": "export.json"}, "timeout": {"type": "number", "default": 600}},
          ["task_path", "code_path", "out_dir"]),
    _tool("mathematica_verify", "在干净内核中重新执行 checks 并与参考结果比较。",
          {"task_path": {"type": "string"}, "code_path": {"type": "string"}, "out_path": {"type": "string"},
           "previous_path": {"type": "string"}, "timeout": {"type": "number", "default": 600}},
          ["task_path", "code_path", "out_path"]),
    _tool("mathematica_example", "返回一个可运行的示例任务 JSON。", {}),
]


def _json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _adapter(timeout: float = 600.0) -> WolframscriptAdapter:
    report = detect(timeout=min(timeout, 45.0))
    if not report.engine_usable:
        raise MskError("ENGINE_NOT_FOUND", "No usable Wolfram kernel was found.",
                       {"doctor": report.to_dict()})
    return WolframscriptAdapter(report.wolframscript or report.kernel_path, default_timeout=timeout,
                             kernel_path=report.kernel_path)


def _call(name: str, arguments: dict[str, Any]) -> Any:
    if name == "mathematica_doctor":
        return detect(deep_frontend=bool(arguments.get("frontend"))).to_dict()
    if name == "mathematica_plan":
        return plan_task(arguments["task_path"])
    if name == "mathematica_lint":
        return lint_task(arguments["task_path"], allow_external=bool(arguments.get("allow_external")))
    if name == "mathematica_build":
        return build_only(arguments["task_path"], out_dir=arguments.get("out_dir"),
                          draft=bool(arguments.get("draft")), timeout=float(arguments.get("timeout", 900)))
    if name == "mathematica_run":
        options = RunOptions(
            timeout=float(arguments.get("timeout", 900)),
            frontend_timeout=float(arguments.get("frontend_timeout", 240)),
            verify_rerun=not arguments.get("no_rerun", False),
            dry_run=bool(arguments.get("dry_run", False)),
            allow_external=bool(arguments.get("allow_external", False)),
            allow_draft=bool(arguments.get("allow_draft", False)),
            no_frontend=bool(arguments.get("no_frontend", False)),
            frontend_probe=not arguments.get("no_frontend", False),
            seed=arguments.get("seed"),
            work_root=Path(arguments["out_dir"]).resolve() if arguments.get("out_dir") else None,
            overwrite=bool(arguments.get("overwrite", False)),
        )
        return run_task(arguments["task_path"], options)
    if name == "mathematica_evaluate_notebook":
        adapter = _adapter(float(arguments.get("timeout", 240)))
        report = detect(deep_frontend=True, timeout=45.0)
        frontend = FrontendAdapter(adapter, available=report.frontend_available, detail=report.frontend_detail)
        out = Path(arguments.get("out_path") or "evaluate.json").resolve()
        run = frontend.evaluate(Path(arguments["notebook_path"]).resolve(), out,
                                timeout=float(arguments.get("timeout", 240)))
        return {"ok": run.ok, "payload": run.payload, "stdout": run.stdout[-4000:], "stderr": run.stderr[-4000:]}
    if name == "mathematica_export":
        adapter = _adapter(float(arguments.get("timeout", 600)))
        out = Path(arguments["out_dir"]).resolve()
        out.mkdir(parents=True, exist_ok=True)
        run = adapter.export_artifacts(Path(arguments["task_path"]).resolve(), Path(arguments["code_path"]).resolve(),
                                       out, out / arguments.get("result_path", "export.json"),
                                       timeout=float(arguments.get("timeout", 600)))
        return {"ok": run.ok, "payload": run.payload, "stdout": run.stdout[-4000:], "stderr": run.stderr[-4000:]}
    if name == "mathematica_verify":
        adapter = _adapter(float(arguments.get("timeout", 600)))
        previous = Path(arguments["previous_path"]).resolve() if arguments.get("previous_path") else None
        run = adapter.verify_results(Path(arguments["task_path"]).resolve(), Path(arguments["code_path"]).resolve(),
                                     Path(arguments["out_path"]).resolve(), previous=previous,
                                     timeout=float(arguments.get("timeout", 600)))
        return {"ok": run.ok, "payload": run.payload, "stdout": run.stdout[-4000:], "stderr": run.stderr[-4000:]}
    if name == "mathematica_example":
        return example_document()
    raise MskError("MCP_ERROR", f"Unknown tool: {name}")


def _tool_result(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        result = _call(name, arguments)
        return {"content": [{"type": "text", "text": _json_text(result)}], "isError": False}
    except MskError as exc:
        return {"content": [{"type": "text", "text": _json_text(exc.to_dict())}], "isError": True}
    except Exception as exc:  # noqa: BLE001 - MCP 必须把内部错误转成结构化结果
        return {"content": [{"type": "text", "text": _json_text({
            "code": "MCP_ERROR", "message": str(exc), "trace": traceback.format_exc(limit=5),
        })}], "isError": True}


def _handle(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}
    if request_id is None:
        return None  # notification
    if method == "initialize":
        requested = str(params.get("protocolVersion") or PROTOCOL_DEFAULT)
        version = requested if requested in PROTOCOL_SUPPORTED else PROTOCOL_DEFAULT
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "mathematica-skill", "version": __version__},
            "instructions": "所有数学计算都交给本地 Wolfram 内核；没有 Mathematica 时只能生成 draft。",
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return {"jsonrpc": "2.0", "id": request_id, "result": {
                "content": [{"type": "text", "text": _json_text({"code": "MCP_INVALID_PARAMS",
                                                                 "message": "arguments must be an object"})}],
                "isError": True}}
        return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(name, arguments)}
    if method in {"resources/list", "prompts/list"}:
        return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": []} if method == "resources/list"
                else {"prompts": []}}
    if method in {"shutdown", "exit"}:
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def _read_message(stream) -> dict[str, Any] | None:
    """兼容两种 stdio 帧：MCP 官方的逐行 JSON，以及 LSP 风格的 Content-Length。"""
    line = stream.readline()
    if not line:
        return None
    stripped = line.strip()
    if stripped.startswith(b"{"):
        try:
            return json.loads(stripped.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
    headers: dict[str, str] = {}
    current = line
    while True:
        if current in (b"\r\n", b"\n", b""):
            break
        key, _, value = current.decode("ascii", "replace").partition(":")
        headers[key.strip().lower()] = value.strip()
        current = stream.readline()
        if not current:
            return None
    try:
        length = int(headers.get("content-length", "0"))
    except ValueError:
        return None
    if length <= 0 or length > 8 * 1024 * 1024:
        return None
    payload = stream.read(length)
    if not payload:
        return None
    try:
        return json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_message(stream, payload: dict[str, Any]) -> None:
    # MCP 的 stdio transport 用换行分隔 JSON，不加 Content-Length 头。
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    stream.write(body + b"\n")
    stream.flush()


def serve() -> None:
    input_stream = sys.stdin.buffer
    output_stream = sys.stdout.buffer
    while True:
        request = _read_message(input_stream)
        if request is None:
            break
        if not request:
            _write_message(output_stream, {"jsonrpc": "2.0", "id": None,
                                           "error": {"code": -32700, "message": "Parse error"}})
            continue
        response = _handle(request)
        if response is not None:
            _write_message(output_stream, response)
        if request.get("method") == "exit":
            break


if __name__ == "__main__":
    serve()
