"""快速计算：在真实内核里执行一段 Wolfram Language，返回结果、消息和可选的 PNG。

这是给交互式建模用的入口：不跑 checks、Notebook 和复算流水线，所以返回值永远是
`verified: false`。需要可交付、可复算的成果，请用 run。

校验顺序：语法 → 危险调用策略 → 引擎探测 → 内核执行。前三道没过就不启动内核。
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .adapter_wolframscript import WolframscriptAdapter
from .discovery import detect
from .errors import EngineNotFound, InvalidTask, MskError
from .paths import default_work_root, ensure_dir, unique_path
from .plotqa import validate_png
from .policy import scan_policy
from .wlsyntax import check_syntax

MAX_CODE_CHARS = 200_000
# Mac 冷启动加许可证校验可能要 30-60 秒（见 docs/MACOS.md），探测太短会误报 ENGINE_NOT_FOUND。
ENGINE_PROBE_TIMEOUT = 60.0
NOTE = "快速计算不进入 checks、Notebook 与复算流程，只用于回答问题；可交付成果请使用 run。"


def read_code(code: str | None, code_path: str | None) -> str:
    """代码可以直接给字符串，也可以给文件；两者必须且只能给一个。"""
    if (code is None) == (code_path is None):
        raise InvalidTask("provide exactly one of code or code_path")
    if code is not None:
        return code
    path = Path(code_path).expanduser().resolve()
    if not path.is_file():
        raise InvalidTask(f"code file not found: {path}")
    # utf-8-sig：Windows 记事本保存的文件带 BOM，直接交给 WL 会多出一个奇怪的字符。
    return path.read_text(encoding="utf-8-sig")


def compute_code(code: str, *, out_dir: str | Path | None = None, timeout: float = 120.0,
                 allow_external: bool = False, working_dir: str | Path | None = None,
                 figure_path: str | Path | None = None) -> dict[str, Any]:
    if not code.strip():
        raise InvalidTask("code is empty")
    if len(code) > MAX_CODE_CHARS:
        raise InvalidTask(f"code is longer than {MAX_CODE_CHARS} characters; put it in a task file instead")
    syntax = check_syntax(code)
    if not syntax.balanced:
        raise InvalidTask("Wolfram Language code has unbalanced brackets, strings or comments",
                          details={"errors": syntax.errors})
    findings = scan_policy(code, "compute")
    if findings and not allow_external:
        raise MskError("POLICY_BLOCKED", "code uses a blocked call; allow_external needs explicit approval",
                       "Review the call, then pass allow_external only if it is intended.",
                       details={"findings": findings})
    if figure_path is not None and Path(figure_path).suffix.lower() != ".png":
        raise InvalidTask("figure_path must end with .png")
    work = Path(working_dir).expanduser().resolve() if working_dir else None
    if work is not None and not work.is_dir():
        raise InvalidTask(f"working directory not found: {work}")

    doctor = detect(timeout=ENGINE_PROBE_TIMEOUT)
    if not doctor.engine_usable:
        raise EngineNotFound("No usable Wolfram kernel was found; compute needs a licensed engine.",
                             details={"doctor": doctor.to_dict()})

    # 每次计算一个独立的内部目录；图形和结果文件都先写在这里，客户想要的才复制出去。
    root = ensure_dir(Path(out_dir).expanduser().resolve() if out_dir else default_work_root() / "compute")
    run_dir = Path(tempfile.mkdtemp(prefix=f"compute-{datetime.now():%Y%m%d-%H%M%S}-", dir=root))
    code_wl = run_dir / "compute.wl"
    code_wl.write_text(code, encoding="utf-8")
    result_json = run_dir / "compute.json"
    figure_png = run_dir / "figure.png"
    adapter = WolframscriptAdapter(doctor.wolframscript or doctor.kernel_path, default_timeout=timeout,
                                   kernel_path=doctor.kernel_path)
    run = adapter.compute_code(code_wl, result_json, figure_png, work or run_dir, timeout=timeout)
    payload = run.payload or {}
    if not run.ok:
        raise MskError(run.error_code or "EVALUATION_FAILED", run.message or "computation failed",
                       details={"messages": payload.get("messages", []), "stderr": run.stderr[-4000:]})

    return {
        "ok": True,
        "verified": False,
        "note": NOTE,
        "result": payload.get("result", ""),
        "result_head": payload.get("result_head", ""),
        "result_tex": payload.get("result_tex", ""),
        "truncated": bool(payload.get("truncated", False)),
        "messages": payload.get("messages", []),
        "warnings": [{"severity": "warning", "code": "POLICY_ALLOWED",
                      "message": f"{item['kind']} allowed by allow_external: {item['match']}"}
                     for item in findings],
        "figure": _figure(payload, figure_png, figure_path),
        "seconds": payload.get("seconds", 0.0),
        "run_dir": str(run_dir),
    }


def _figure(payload: dict[str, Any], figure_png: Path, figure_path: str | Path | None) -> dict[str, Any] | None:
    """图形由 Wolfram 导出；这里只校验 PNG 文件并按需复制，不重绘。"""
    if not payload.get("figure_written"):
        return None
    if not figure_png.is_file():
        raise MskError("PLOT_EXPORT_FAILED", "the kernel reported a figure but no file was written")
    png = validate_png(figure_png)
    if not png.get("ok"):
        raise MskError("PLOT_EXPORT_FAILED", "the exported figure failed the PNG integrity check",
                       details={"png": png})
    target = figure_png
    if figure_path is not None:
        target = unique_path(Path(figure_path).expanduser().resolve())
        ensure_dir(target.parent)
        shutil.copy2(figure_png, target)
    return {**png, "path": str(target)}
