"""mathematica-skill 命令行入口。

日常只需要两个命令：
  mathematica-skill doctor
  mathematica-skill run task.json
其余子命令用于计划、构建、执行、导出、对账和安装管理。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from . import __version__
from .adapter_frontend import FrontendAdapter
from .adapter_wolframscript import WolframscriptAdapter
from .discovery import detect, summarize
from .errors import MskError
from .models import example_document
from .notebook_edit import NotebookEdit, load_edits, run_edit
from .workflow import RunOptions, build_only, lint_task, plan_task, run_task

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_BLOCKED = 3
EXIT_DRAFT = 4


def _emit(payload: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    elif isinstance(payload, (dict, list)):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(payload)


def _doctor(args: argparse.Namespace) -> int:
    report = detect(deep_frontend=args.frontend, timeout=args.timeout)
    if args.json:
        _emit(report.to_dict(), True)
    else:
        print(summarize(report))
    return EXIT_OK if report.engine_usable or args.json else EXIT_BLOCKED


def _plan(args: argparse.Namespace) -> int:
    from .workflow import plan_task

    payload = plan_task(args.task, RunOptions(allow_external=args.allow_external))
    _emit(payload, True)
    return EXIT_OK


def _lint(args: argparse.Namespace) -> int:
    payload = lint_task(args.task, allow_external=args.allow_external)
    _emit(payload, True)
    return EXIT_OK if payload.get("ok") else EXIT_BLOCKED


def _run(args: argparse.Namespace) -> int:
    options = RunOptions(
        timeout=args.timeout,
        verify_rerun=not args.no_rerun,
        dry_run=args.dry_run,
        allow_external=args.allow_external,
        allow_draft=args.allow_draft,
        no_frontend=args.no_frontend,
        frontend_probe=not args.no_frontend,
        seed=args.seed,
        work_root=Path(args.out).resolve() if args.out else None,
        overwrite=args.overwrite,
        frontend_timeout=args.frontend_timeout,
    )
    state = run_task(args.task, options)
    _emit(state, True)
    if state.get("status") == "verified":
        return EXIT_OK
    if state.get("status") == "draft":
        return EXIT_DRAFT
    if state.get("status") in {"blocked", "failed"}:
        return EXIT_BLOCKED
    return EXIT_OK


def _build(args: argparse.Namespace) -> int:
    payload = build_only(args.task, out_dir=args.out, draft=args.draft, timeout=args.timeout)
    _emit(payload, True)
    return EXIT_OK if payload.get("ok") else EXIT_ERROR


def _evaluate(args: argparse.Namespace) -> int:
    doctor = detect(deep_frontend=True, timeout=min(args.timeout, 45.0))
    if not doctor.engine_usable:
        raise MskError("ENGINE_NOT_FOUND", "No usable Wolfram kernel was found.")
    adapter = WolframscriptAdapter(doctor.wolframscript or doctor.kernel_path, default_timeout=args.timeout,
                                 kernel_path=doctor.kernel_path)
    frontend = FrontendAdapter(adapter, available=doctor.frontend_available, detail=doctor.frontend_detail)
    run = frontend.evaluate(Path(args.notebook).expanduser().resolve(),
                            Path(args.out).expanduser().resolve() if args.out else Path("evaluate.json"),
                            timeout=args.timeout)
    _emit({"ok": run.ok, "payload": run.payload, "stdout": run.stdout[-4000:], "stderr": run.stderr[-4000:]}, True)
    return EXIT_OK if run.ok else EXIT_BLOCKED


def _parse_quick_ops(values: list[str], style: str) -> list[dict[str, Any]]:
    """把 `append_input:<code>` / `replace_cell:3=<code>` 解析成操作对象。"""
    operations: list[dict[str, Any]] = []
    for raw in values:
        kind, _, rest = raw.partition(":")
        if kind in {"replace_cell", "delete_cell", "insert_after"}:
            index_text, sep, content = rest.partition("=")
            if not index_text.isdigit():
                raise MskError("INVALID_TASK", f"--op {raw!r} needs a 1-based cell index, e.g. {kind}:3=...")
            item: dict[str, Any] = {"op": kind, "index": int(index_text)}
            if sep:
                item["content"] = content
            if kind == "insert_after":
                item["style"] = style
            operations.append(item)
        else:
            operations.append({"op": kind, "content": rest})
    return operations


def _edit(args: argparse.Namespace) -> int:
    if args.edits:
        if args.op or args.title or args.language:
            raise MskError("INVALID_TASK",
                           "--edits cannot be combined with --op / --title / --language; "
                           "put them in the edits JSON instead")
        edit = load_edits(args.edits)
    else:
        edit = NotebookEdit(language=args.language or "", title=args.title or "",
                            operations=[NotebookEdit.from_dict({"operations": [item]}).operations[0]
                                        for item in _parse_quick_ops(args.op or [], args.style)])
    if not edit.operations and not edit.language and not edit.title:
        raise MskError("INVALID_TASK", "edit needs --edits, --op, --title or --language")

    doctor = detect(timeout=min(args.timeout, 45.0))
    if not doctor.engine_usable:
        raise MskError("ENGINE_NOT_FOUND", "No usable Wolfram kernel was found.")
    adapter = WolframscriptAdapter(doctor.wolframscript or doctor.kernel_path, default_timeout=args.timeout,
                                   kernel_path=doctor.kernel_path)
    payload = run_edit(adapter, args.notebook, args.out, edit, allow_in_place=args.in_place,
                       timeout=args.timeout, work_dir=args.work)
    _emit(payload, True)
    return EXIT_OK


def _export(args: argparse.Namespace) -> int:
    doctor = detect(timeout=min(args.timeout, 45.0))
    if not doctor.engine_usable:
        raise MskError("ENGINE_NOT_FOUND", "No usable Wolfram kernel was found.")
    adapter = WolframscriptAdapter(doctor.wolframscript or doctor.kernel_path, default_timeout=args.timeout,
                                 kernel_path=doctor.kernel_path)
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    run = adapter.export_artifacts(Path(args.task).resolve(), Path(args.code).expanduser().resolve(),
                                   out_dir, Path(args.result).expanduser().resolve(), timeout=args.timeout)
    _emit({"ok": run.ok, "payload": run.payload, "stdout": run.stdout[-4000:], "stderr": run.stderr[-4000:]}, True)
    return EXIT_OK if run.ok else EXIT_BLOCKED


def _verify(args: argparse.Namespace) -> int:
    doctor = detect(timeout=min(args.timeout, 45.0))
    if not doctor.engine_usable:
        raise MskError("ENGINE_NOT_FOUND", "No usable Wolfram kernel was found.")
    adapter = WolframscriptAdapter(doctor.wolframscript or doctor.kernel_path, default_timeout=args.timeout,
                                 kernel_path=doctor.kernel_path)
    previous = Path(args.previous).expanduser().resolve() if args.previous else None
    run = adapter.verify_results(Path(args.task).expanduser().resolve(), Path(args.code).expanduser().resolve(),
                                 Path(args.out).expanduser().resolve(), previous=previous, timeout=args.timeout)
    _emit({"ok": run.ok, "payload": run.payload, "stdout": run.stdout[-4000:], "stderr": run.stderr[-4000:]}, True)
    return EXIT_OK if run.ok else EXIT_BLOCKED


def _install(args: argparse.Namespace) -> int:
    from .installer import configure_mcp, install

    targets = [Path(item).expanduser().resolve() for item in args.target] if args.target else None
    if args.config and not args.mcp_client:
        raise MskError("INSTALL_FAILED", "--config requires --mcp-client")
    skill_result = install(targets, force=args.force, dry_run=args.dry_run)
    mcp_result = None
    if args.mcp_client:
        mcp_result = configure_mcp(args.mcp_client, config_path=Path(args.config).expanduser() if args.config else None,
                                   force=args.force, dry_run=args.dry_run)
    payload = {"ok": bool(skill_result.get("ok")) and (mcp_result is None or bool(mcp_result.get("ok"))),
               "skill": skill_result, "mcp": mcp_result}
    _emit(payload, True)
    return EXIT_OK if payload["ok"] else EXIT_ERROR


def _update(args: argparse.Namespace) -> int:
    from .installer import update

    payload = update(force=args.force, dry_run=args.dry_run)
    _emit(payload, True)
    return EXIT_OK if payload.get("ok") else EXIT_ERROR


def _uninstall(args: argparse.Namespace) -> int:
    from .installer import uninstall

    targets = [Path(item).expanduser().resolve() for item in args.target] if args.target else None
    payload = uninstall(dry_run=args.dry_run, targets=targets)
    _emit(payload, True)
    return EXIT_OK if payload.get("ok") else EXIT_ERROR


def _rollback(args: argparse.Namespace) -> int:
    from .installer import rollback

    payload = rollback()
    _emit(payload, True)
    return EXIT_OK if payload.get("ok") else EXIT_ERROR


def _example(args: argparse.Namespace) -> int:
    payload = example_document()
    if args.write:
        from .jsonio import write_json

        write_json(Path(args.write).expanduser().resolve(), payload)
        print(str(Path(args.write).expanduser().resolve()))
    else:
        _emit(payload, True)
    return EXIT_OK


def _mcp(args: argparse.Namespace) -> int:
    if args.action != "serve":
        raise MskError("MCP_ERROR", "only `mcp serve` is supported")
    from .mcp_server import serve

    serve()
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mathematica-skill",
                                     description="Native Mathematica/Notebook automation for AI agents")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="检测 Wolfram 内核、许可证和前端")
    doctor.add_argument("--frontend", action="store_true", help="额外启动前端探测 Notebook 能力")
    doctor.add_argument("--timeout", type=float, default=25.0)
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=_doctor)

    plan = sub.add_parser("plan", help="只解析任务并输出执行计划")
    plan.add_argument("task")
    plan.add_argument("--allow-external", action="store_true")
    plan.set_defaults(func=_plan)

    lint = sub.add_parser("lint", help="静态检查 WL 语法和高风险调用")
    lint.add_argument("task")
    lint.add_argument("--allow-external", action="store_true")
    lint.set_defaults(func=_lint)

    run = sub.add_parser("run", help="跑完整原生流水线并验证交付")
    run.add_argument("task")
    run.add_argument("--out", help="内部工作目录根路径")
    run.add_argument("--timeout", type=float, default=900.0)
    run.add_argument("--frontend-timeout", type=float, default=240.0)
    run.add_argument("--seed", type=int)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--allow-draft", action="store_true", help="没有 Mathematica 时只生成 draft")
    run.add_argument("--allow-external", action="store_true", help="允许代码读取声明过的外部文件或网络")
    run.add_argument("--no-frontend", action="store_true", help="不做 Notebook 前端执行（结果只能是 blocked）")
    run.add_argument("--no-rerun", action="store_true", help="跳过第二次独立复算")
    run.add_argument("--overwrite", action="store_true", help="允许覆盖已有交付目录")
    run.set_defaults(func=_run)

    build = sub.add_parser("build", help="只生成 .nb 和 .wl")
    build.add_argument("task")
    build.add_argument("--out")
    build.add_argument("--draft", action="store_true", help="不需要 Mathematica，生成未验证草稿")
    build.add_argument("--timeout", type=float, default=900.0)
    build.set_defaults(func=_build)

    evaluate = sub.add_parser("evaluate", help="用前端执行一个已有 .nb")
    evaluate.add_argument("notebook")
    evaluate.add_argument("--out")
    evaluate.add_argument("--timeout", type=float, default=240.0)
    evaluate.set_defaults(func=_evaluate)

    edit = sub.add_parser("edit", help="在既有 .nb 上做定点修改（默认另存新文件）")
    edit.add_argument("notebook")
    edit.add_argument("--edits", help="修改指令 JSON")
    edit.add_argument("--op", action="append", default=[],
                      help="快捷操作：append_input:<code> / replace_cell:<n>=<code> / delete_cell:<n>")
    edit.add_argument("--style", default="Input", help="insert_after 使用的单元样式")
    edit.add_argument("--title", help="替换标题")
    edit.add_argument("--language", choices=["en", "zh"], help="翻转标题语言（只改固定标题）")
    edit.add_argument("--out", help="输出路径；默认同目录 -edited.nb")
    edit.add_argument("--in-place", action="store_true", help="覆盖源文件（会先备份 .bak）")
    edit.add_argument("--work", help="内部工作目录")
    edit.add_argument("--timeout", type=float, default=240.0)
    edit.set_defaults(func=_edit)

    export = sub.add_parser("export", help="从真实 WL 表达式导出图和数据")
    export.add_argument("task")
    export.add_argument("--code", required=True)
    export.add_argument("--out", required=True)
    export.add_argument("--result", default="export.json")
    export.add_argument("--timeout", type=float, default=600.0)
    export.set_defaults(func=_export)

    verify = sub.add_parser("verify", help="在干净内核中执行 checks，可选和上一次比较")
    verify.add_argument("task")
    verify.add_argument("--code", required=True)
    verify.add_argument("--out", required=True)
    verify.add_argument("--previous")
    verify.add_argument("--timeout", type=float, default=600.0)
    verify.set_defaults(func=_verify)

    install = sub.add_parser("install", help="安装 Skill 到 Agent 技能目录")
    install.add_argument("--target", action="append", default=[], help="可重复；不传则自动检测已知目录")
    install.add_argument("--mcp-client", choices=["claude", "codex", "cursor", "opencode", "generic"])
    install.add_argument("--config", help="显式指定 MCP 配置文件")
    install.add_argument("--force", action="store_true")
    install.add_argument("--dry-run", action="store_true")
    install.set_defaults(func=_install)

    update = sub.add_parser("update", help="更新已安装的 Skill")
    update.add_argument("--force", action="store_true")
    update.add_argument("--dry-run", action="store_true")
    update.set_defaults(func=_update)

    uninstall = sub.add_parser("uninstall", help="只删除本项目安装的文件")
    uninstall.add_argument("--target", action="append", default=[])
    uninstall.add_argument("--dry-run", action="store_true")
    uninstall.set_defaults(func=_uninstall)

    rollback = sub.add_parser("rollback", help="恢复最近一次备份")
    rollback.set_defaults(func=_rollback)

    example = sub.add_parser("example", help="输出一个可运行的任务 JSON 示例")
    example.add_argument("--write")
    example.set_defaults(func=_example)

    mcp = sub.add_parser("mcp", help="MCP 服务")
    mcp.add_argument("action", choices=["serve"])
    mcp.set_defaults(func=_mcp)

    return parser


def _force_utf8_stdio() -> None:
    """Windows 控制台默认代码页会把中文 JSON 输出打挂；显式改 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except MskError as exc:
        if "--json" in (argv if argv is not None else sys.argv):
            print(json.dumps(exc.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"{exc.code}: {exc.message}", file=sys.stderr)
            if exc.hint:
                print(exc.hint, file=sys.stderr)
        blocked = {"DELIVERY_BLOCKED", "NUMERIC_MISMATCH", "FRONTEND_UNAVAILABLE"}
        return EXIT_BLOCKED if exc.code in blocked else EXIT_ERROR
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
