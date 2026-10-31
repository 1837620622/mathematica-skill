"""End-to-end native workflow and state machine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import shutil
import time
from pathlib import Path
from typing import Any

from . import __version__
from .adapter_frontend import FrontendAdapter
from .adapter_wolframscript import WolframscriptAdapter
from .delivery import delivery_folder_name, stage_delivery
from .discovery import detect
from .errors import DeliveryBlocked, EngineNotFound, MskError
from .jsonio import file_record, write_json
from .models import TaskDocument
from .notebook import build_code_script, build_notebook
from .paths import default_work_root, ensure_dir, slugify
from .policy import scan_policy
from .reporting import write_reports
from .validation import (
    ValidationReport,
    validate_artifacts,
    validate_checks,
    validate_notebook,
    validate_reproduction,
)
from .wlsyntax import check_syntax

STAGES = ("intake", "inspect", "plan", "lint", "preflight", "native_build",
          "native_evaluate", "export", "close", "reopen", "rerun", "compare",
          "review", "deliver")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _record(state: dict[str, Any], stage: str, status: str, *, message: str = "", seconds: float = 0.0,
            detail: dict[str, Any] | None = None) -> None:
    entry: dict[str, Any] = {"stage": stage, "status": status, "at": _now(), "seconds": round(seconds, 3)}
    if message:
        entry["message"] = message
    if detail:
        entry["detail"] = detail
    state.setdefault("stages", []).append(entry)
    state["updated_at"] = entry["at"]


def _save(state: dict[str, Any]) -> None:
    path = Path(state["run_dir"]) / "state.json"
    write_json(path, state)
    state["state_path"] = str(path)


@dataclass(slots=True)
class RunOptions:
    timeout: float = 900.0
    verify_rerun: bool = True
    dry_run: bool = False
    allow_external: bool = False
    allow_draft: bool = False
    no_frontend: bool = False
    frontend_probe: bool = True
    seed: int | None = None
    work_root: Path | None = None
    overwrite: bool = False
    frontend_timeout: float = 240.0
    notebook_only: bool = False


def lint_task(task_path: str | Path, *, allow_external: bool = False) -> dict[str, Any]:
    """只做静态检查：WL 词法、危险调用和任务结构。"""
    document = TaskDocument.load(Path(task_path).expanduser().resolve())
    report = ValidationReport()
    code_results = _lint(document, allow_external=allow_external, report=report)
    return {
        "ok": report.ok,
        "task": document.title,
        "tasks": code_results,
        "findings": [item.to_dict() for item in report.findings],
        "errors": [item.to_dict() for item in report.errors()],
    }


def plan_task(task_path: str | Path, options: RunOptions | None = None) -> dict[str, Any]:
    options = options or RunOptions()
    document = TaskDocument.load(Path(task_path).expanduser().resolve())
    return {
        "ok": True,
        "title": document.title,
        "language": document.effective_language(),
        "language_mode": document.language,
        "seed": document.seed,
        "tasks": [task.to_dict() for task in document.tasks],
        "outputs": [output.to_dict() for output in document.outputs],
        "sources": [str(path) for path in document.source_paths()],
        "delivery": {"name": delivery_folder_name(document),
                     "outputs": [item.id for item in document.selected_outputs()]},
    }


def _code_units(document: TaskDocument) -> list[tuple[str, str]]:
    """所有会被真正求值的代码：任务代码 + 每个输出表达式。"""
    units = [(task.id, task.code) for task in document.tasks]
    units += [(f"output:{output.id}", output.expression) for output in document.outputs]
    return units


def _policy_findings(document: TaskDocument, *, allow_external: bool) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for unit_id, code in _code_units(document):
        findings.extend(scan_policy(code, unit_id))
    if not allow_external:
        for source in document.sources:
            if source.startswith(("http://", "https://", "ftp://")):
                findings.append({"task": "(sources)", "kind": "remote source", "match": source})
    return findings


def _lint(document: TaskDocument, *, allow_external: bool, report: ValidationReport) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for unit_id, code in _code_units(document):
        syntax = check_syntax(code)
        item = {"task": unit_id, **syntax.to_dict()}
        results.append(item)
        for message in syntax.errors:
            report.add("error", "WL_SYNTAX", f"{unit_id}: {message}", unit_id)
    # 危险调用默认阻断；操作员明确 --allow-external 时降级为 warning，
    # 但永远记录在报告里，不会静默放行。
    policy = _policy_findings(document, allow_external=allow_external)
    for finding in policy:
        if allow_external:
            report.add("warning", "POLICY_ALLOWED",
                       f"{finding['task']}: {finding['kind']} allowed by --allow-external",
                       finding["task"])
        else:
            report.add("error", "POLICY_BLOCKED",
                       f"{finding['task']}: {finding['kind']} needs explicit --allow-external approval",
                       finding["task"])
    return results


def _copy_inputs(source: Path, run_dir: Path, document: TaskDocument) -> TaskDocument:
    input_dir = ensure_dir(run_dir / "input")
    copied = input_dir / source.name
    # 从工具自己写出的 input/task.json 再次构建时，源和目标是同一个文件。
    if source.resolve() != copied.resolve():
        shutil.copy2(source, copied)
    local = TaskDocument.load(copied)
    for relative in document.sources:
        origin = (source.parent / relative).resolve()
        if origin.is_file():
            target = input_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if origin != target:
                shutil.copy2(origin, target)
    return local


def _inventory(document: TaskDocument, run_dir: Path, *, report: ValidationReport) -> dict[str, Any]:
    inventory: dict[str, Any] = {"task": file_record(document.path) if document.path else {},
                                 "sources": [], "missing": [], "checks": 0, "outputs": len(document.outputs)}
    for relative in document.sources:
        path = (document.base_dir / relative).resolve()
        if path.is_file():
            inventory["sources"].append({"relative": relative, **file_record(path)})
        else:
            inventory["missing"].append(relative)
            report.add("error", "SOURCE_MISSING", f"declared source is missing: {relative}", relative)
    inventory["checks"] = sum(len(task.checks) for task in document.tasks)
    if inventory["checks"] == 0:
        report.add("warning", "CHECKS_EMPTY", "no checks are declared; results cannot be compared numerically")
    return inventory


def _plan_document(document: TaskDocument, run_dir: Path, *, report: ValidationReport) -> dict[str, Any]:
    plan: dict[str, Any] = {"tasks": [], "outputs": [], "assumptions": document.assumptions}
    for task in document.tasks:
        plan["tasks"].append({"id": task.id, "prompt": task.prompt,
                              "checks": [check.id for check in task.checks]})
    for output in document.outputs:
        plan["outputs"].append({"id": output.id, "task": output.task, "kind": output.kind,
                                "filename": output.filename, "width": output.width,
                                "height": output.height, "dpi": output.dpi})
    output_names = [item.filename for item in document.outputs]
    if len(output_names) != len(set(output_names)):
        report.add("error", "OUTPUT_NAME_DUPLICATE", "output filenames must be unique")
    for output in document.outputs:
        if output.task not in {task.id for task in document.tasks}:
            report.add("error", "OUTPUT_TASK_UNKNOWN", f"{output.id} references unknown task {output.task}")
    return plan


def _artifact_records(artifacts_dir: Path) -> list[dict[str, Any]]:
    if not artifacts_dir.is_dir():
        return []
    return [file_record(path) for path in sorted(artifacts_dir.iterdir()) if path.is_file()]


def _resolve_notebook_paths(document: TaskDocument, notebook: Path, *, report: ValidationReport) -> list[str]:
    targets: list[str] = []
    for output in document.outputs:
        if output.kind in {"figure", "pdf"}:
            targets.append(output.expression)
    for expression in targets:
        if "$msArtifacts" not in expression and not re.search(r'\bExport\s*\[', expression):
            report.add("warning", "PLOT_EXPORT_EXPRESSION",
                       f"figure expression does not appear to export: {expression[:80]}", notebook.name)
    return targets


def run_task(task_path: str | Path, options: RunOptions | None = None) -> dict[str, Any]:
    options = options or RunOptions()
    started = time.monotonic()
    source = Path(task_path).expanduser().resolve()
    if not source.is_file():
        raise MskError("INVALID_TASK", f"Task file not found: {source}")
    document = TaskDocument.load(source)
    root = ensure_dir(Path(options.work_root).expanduser().resolve() if options.work_root else default_work_root())
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = root / f"{slugify(document.title, 'task')}-{stamp}-{source.stem[:12]}"
    if run_dir.exists():
        run_dir = root / f"{slugify(document.title, 'task')}-{stamp}-{source.stem[:12]}-{int(time.time())}"
    ensure_dir(run_dir)
    state: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "tool_version": __version__,
        "title": document.title,
        "source": str(source),
        "run_dir": str(run_dir),
        "started_at": _now(),
        "updated_at": _now(),
        "status": "running",
        "verified": False,
        "stages": [],
        "artifacts": {},
        "errors": [],
    }
    report = ValidationReport()
    try:
        _record(state, "intake", "completed", seconds=time.monotonic() - started,
                detail={"source": str(source), "bytes": source.stat().st_size})
        document = _copy_inputs(source, run_dir, document)
        if options.seed is not None and document.path is not None:
            # 只改隔离副本，绝不动用户原始任务文件。
            document.seed = int(options.seed)
            document.save(document.path)
        intake = _inventory(document, run_dir, report=report)
        _record(state, "inspect", "completed", detail=intake)
        plan = _plan_document(document, run_dir, report=report)
        _record(state, "plan", "completed", detail=plan)
        lint = _lint(document, allow_external=options.allow_external, report=report)
        _record(state, "lint", "completed" if report.ok else "failed", detail={"code": lint})
        # 预检：只有这里通过，才允许进入原生 Wolfram 执行
        doctor = detect(deep_frontend=options.frontend_probe and not options.no_frontend,
                        timeout=min(max(options.timeout, 20.0), 60.0))
        state["doctor"] = doctor.to_dict()
        if not report.ok:
            _record(state, "preflight", "failed", detail={"errors": [item.to_dict() for item in report.errors()]})
            state["status"] = "blocked"
            state["errors"] = [item.to_dict() for item in report.errors()]
            _save(state)
            return state
        _record(state, "preflight", "completed" if doctor.engine_usable else "failed",
                detail={"engine_usable": doctor.engine_usable, "frontend_available": doctor.frontend_available})
        if options.dry_run:
            state["status"] = "dry_run"
            _record(state, "native_build", "skipped", message="dry run; nothing was evaluated")
            _save(state)
            return state
        if not doctor.engine_usable:
            if options.allow_draft:
                draft = build_notebook(document)
                notebook = draft.write(run_dir / f"{slugify(document.title, 'notebook')}.nb")
                code_wl = run_dir / "computation.wl"
                code_wl.write_text(build_code_script(document), encoding="utf-8")
                state["status"] = "draft"
                state["notebook"] = str(notebook)
                state["code"] = str(code_wl)
                state["verified"] = False
                _record(state, "native_build", "draft", message="no usable Wolfram engine; draft only")
                _save(state)
                return state
            raise EngineNotFound("No usable Wolfram kernel was found; use --allow-draft for an unverified draft.",
                                 {"doctor": doctor.to_dict()})

        adapter = WolframscriptAdapter(doctor.wolframscript or doctor.kernel_path,
                                       default_timeout=options.timeout,
                                       kernel_path=doctor.kernel_path)
        # 与 sources 放在同一目录：WL 脚本会用 task.json 的目录做 cwd，
        # 用户写 Import["data.csv"] 才能找到同目录下的数据文件。
        task_json = run_dir / "input" / "task.json"
        document.save(task_json, resolve_language=True)
        code_wl = run_dir / "computation.wl"
        code_wl.write_text(build_code_script(document), encoding="utf-8")
        notebook = run_dir / f"{slugify(document.title, 'notebook')}.nb"
        artifacts_dir = ensure_dir(run_dir / "artifacts")
        build_result_path = run_dir / "native_build.json"
        state["code"] = str(code_wl)
        state["notebook"] = str(notebook)

        # 原生建 Notebook：用 Mathematica 的解析器把代码变成真正的 Input 单元
        stage_started = time.monotonic()
        build = adapter.build_notebook(task_json, notebook, code_wl, build_result_path, timeout=options.timeout)
        _record(state, "native_build", "completed" if build.ok else "failed", seconds=time.monotonic() - stage_started,
                message=build.message, detail={"payload": build.payload, "stderr": build.stderr[-2000:]})
        if not build.ok:
            raise MskError(build.error_code or "EVALUATION_FAILED", build.message or "native notebook build failed",
                           details={"stdout": build.stdout[-4000:], "stderr": build.stderr[-4000:]})
        state["build"] = build.payload
        _save(state)

        # 桌面前端执行：这一步才真正把 Input 单元跑出 Output
        frontend = FrontendAdapter(adapter, available=doctor.frontend_available,
                                   detail=doctor.frontend_detail)
        eval_result: dict[str, Any] | None = None
        if options.no_frontend or not doctor.frontend_available:
            _record(state, "native_evaluate", "skipped",
                    message="no Mathematica frontend; notebook was not executed")
        else:
            stage_started = time.monotonic()
            evaluate = frontend.evaluate(notebook, run_dir / "native_evaluate.json", timeout=options.frontend_timeout)
            _record(state, "native_evaluate", "completed" if evaluate.ok else "failed",
                    seconds=time.monotonic() - stage_started, message=evaluate.message,
                    detail={"payload": evaluate.payload})
            if not evaluate.ok:
                raise MskError(evaluate.error_code or "EVALUATION_FAILED",
                               evaluate.message or "notebook evaluation failed",
                               details={"payload": evaluate.payload})
            eval_result = evaluate.payload
            state["native_evaluate"] = eval_result
            _save(state)

        # 原生导出：图和数据都从真实 Wolfram 表达式导出，Python 不重绘
        stage_started = time.monotonic()
        export = adapter.export_artifacts(task_json, code_wl, artifacts_dir, run_dir / "native_export.json",
                                          timeout=options.timeout)
        _record(state, "export", "completed" if export.ok else "failed", seconds=time.monotonic() - stage_started,
                message=export.message, detail={"payload": export.payload})
        if not export.ok:
            raise MskError(export.error_code or "PLOT_EXPORT_FAILED",
                           export.message or "native artifact export failed",
                           details={"payload": export.payload, "stderr": export.stderr[-4000:]})
        state["export"] = export.payload
        state["artifacts"] = {"dir": str(artifacts_dir), "files": _artifact_records(artifacts_dir)}
        _save(state)

        # 关闭并由前端重新打开交付候选 Notebook，确认不是只有文件存在
        reopen_result: dict[str, Any] | None = None
        if eval_result is not None:
            stage_started = time.monotonic()
            reopen = frontend.reopen(notebook, run_dir / "native_reopen.json", timeout=options.frontend_timeout)
            _record(state, "close", "completed", seconds=0.0)
            _record(state, "reopen", "completed" if reopen.ok else "failed",
                    seconds=time.monotonic() - stage_started, message=reopen.message,
                    detail={"payload": reopen.payload})
            if not reopen.ok:
                raise MskError(reopen.error_code or "NOTEBOOK_OPEN_FAILED",
                               reopen.message or "the notebook could not be reopened",
                               details={"payload": reopen.payload})
            reopen_result = reopen.payload
            state["native_reopen"] = reopen_result
            _save(state)
        else:
            _record(state, "close", "skipped", message="notebook was never evaluated")
            _record(state, "reopen", "skipped", message="notebook was never evaluated")
        # 独立复算：复制最终 Notebook 到新的内核里重新执行，不能复用第一次的全局状态
        rerun_result: dict[str, Any] | None = None
        if options.verify_rerun and eval_result is not None:
            rerun_copy = run_dir / "rerun" / f"{notebook.stem}-rerun.nb"
            rerun_copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(notebook, rerun_copy)
            stage_started = time.monotonic()
            rerun = frontend.rerun(rerun_copy, run_dir / "native_rerun.json", timeout=options.frontend_timeout)
            _record(state, "rerun", "completed" if rerun.ok else "failed",
                    seconds=time.monotonic() - stage_started, message=rerun.message,
                    detail={"payload": rerun.payload})
            if not rerun.ok:
                raise MskError(rerun.error_code or "EVALUATION_FAILED",
                               rerun.message or "the independent notebook re-run failed",
                               details={"payload": rerun.payload})
            rerun_result = rerun.payload
            state["native_rerun"] = rerun_result
            _save(state)
        else:
            _record(state, "rerun", "skipped", message="no frontend evaluation to repeat")

        # 数值对账：第一次与第二次分别在干净内核执行，逐项比较
        stage_started = time.monotonic()
        first = adapter.verify_results(task_json, code_wl, run_dir / "verify-1.json", timeout=options.timeout)
        if not first.ok:
            raise MskError(first.error_code or "NUMERIC_MISMATCH",
                           first.message or "native verification failed",
                           details={"payload": first.payload, "stderr": first.stderr[-4000:]})
        second: Any = None
        if options.verify_rerun:
            second = adapter.verify_results(task_json, code_wl, run_dir / "verify-2.json",
                                            previous=run_dir / "verify-1.json", timeout=options.timeout)
            if not second.ok:
                raise MskError(second.error_code or "NUMERIC_MISMATCH",
                               second.message or "independent verification failed",
                               details={"payload": second.payload, "stderr": second.stderr[-4000:]})
            comparison = second.payload
        else:
            comparison = first.payload
        _record(state, "compare", "completed", seconds=time.monotonic() - stage_started,
                detail={"first": first.payload, "second": second.payload if second else None})
        state["checks"] = first.payload
        state["reproduction"] = comparison
        _save(state)

        # 最终审查：Notebook 结构、原生输出、PNG 尺寸与内容、数值检查、复算结果
        validate_artifacts(artifacts_dir, [item.to_dict() for item in document.selected_outputs()], report=report)
        validate_notebook(notebook, native_result=reopen_result, report=report, require_frontend=True)
        validate_checks(first.payload, report=report, expected_total=len(list(document.all_checks())))
        validate_reproduction(comparison, report=report)
        _resolve_notebook_paths(document, notebook, report=report)
        validation = report.to_dict()
        state["validation"] = validation
        if not report.ok:
            state["status"] = "blocked"
            state["errors"] = [item.to_dict() for item in report.errors()]
            write_reports(run_dir, state, validation, doctor.to_dict())
            _record(state, "review", "failed", detail={"errors": state["errors"]})
            _save(state)
            raise DeliveryBlocked("Verification gates failed; no verified delivery was produced.",
                                  {"run_dir": str(run_dir), "errors": state["errors"][:20]})
        _record(state, "review", "completed")
        _save(state)

        # 只有全部硬门禁通过，才允许复制白名单文件到 deliver/
        delivery_dir = stage_delivery(run_dir, document, notebook=notebook, artifacts_dir=artifacts_dir,
                                      include_code=code_wl, report=report, overwrite=options.overwrite)
        validation = report.to_dict()
        state["validation"] = validation
        if not report.ok:
            state["status"] = "blocked"
            state["errors"] = [item.to_dict() for item in report.errors()]
            write_reports(run_dir, state, validation, doctor.to_dict())
            _record(state, "deliver", "failed", detail={"errors": state["errors"]})
            _save(state)
            raise DeliveryBlocked("Delivery whitelist check failed.", {"errors": state["errors"][:20]})
        state["delivery_dir"] = str(delivery_dir)
        state["verified"] = True
        state["status"] = "verified"
        state["duration_seconds"] = round(time.monotonic() - started, 3)
        write_json(delivery_dir.parent.parent / "_validation" / "manifest.json", {
            "delivery_dir": str(delivery_dir),
            "files": _artifact_records(delivery_dir),
            "task": document.title,
            "verified": True,
            "verified_at": _now(),
            "run_id": state["run_id"],
        })
        write_reports(run_dir, state, validation, doctor.to_dict())
        _record(state, "deliver", "completed", detail={"delivery_dir": str(delivery_dir)})
        _save(state)
        return state

    except MskError as exc:
        state["status"] = "failed" if exc.code != "DELIVERY_BLOCKED" else "blocked"
        state["verified"] = False
        state["errors"] = [exc.to_dict()]
        state["duration_seconds"] = round(time.monotonic() - started, 3)
        _record(state, "workflow", "failed", message=exc.message, detail=exc.to_dict())
        try:
            doctor_dict = state.get("doctor") or detect(timeout=20.0).to_dict()
            write_reports(run_dir, state, report.to_dict(), doctor_dict)
        except Exception:
            pass
        _save(state)
        raise
    except Exception as exc:  # noqa: BLE001 - convert unexpected failures into a recorded state
        state["status"] = "failed"
        state["verified"] = False
        state["errors"] = [{"ok": False, "code": "UNEXPECTED", "message": str(exc)}]
        state["duration_seconds"] = round(time.monotonic() - started, 3)
        _record(state, "workflow", "failed", message=str(exc), detail={"type": type(exc).__name__})
        _save(state)
        raise


def plan_only(task_path: str | Path, options: RunOptions | None = None) -> dict[str, Any]:
    options = options or RunOptions()
    options.dry_run = True
    return run_task(task_path, options)


def build_only(task_path: str | Path, out_dir: str | Path | None = None, *, draft: bool = False,
               timeout: float = 900.0) -> dict[str, Any]:
    """只生成 Notebook 和计算脚本，不跑完整验证。draft=True 时完全不需要 Mathematica。"""
    source = Path(task_path).expanduser().resolve()
    document = TaskDocument.load(source)
    target = ensure_dir(Path(out_dir).expanduser().resolve() if out_dir
                        else default_work_root() / f"{slugify(document.title, 'build')}-build")
    notebook = target / f"{slugify(document.title, 'notebook')}.nb"
    code_wl = target / "computation.wl"
    if draft:
        build_notebook(document).write(notebook)
        code_wl.write_text(build_code_script(document), encoding="utf-8")
        return {"ok": True, "status": "draft", "notebook": str(notebook), "code": str(code_wl),
                "message": "draft only; no Wolfram kernel verified this notebook"}
    doctor = detect(timeout=min(timeout, 60.0))
    if not doctor.engine_usable:
        raise EngineNotFound("No licensed Wolfram engine is available; use --draft for an unverified draft.",
                             {"doctor": doctor.to_dict()})
    adapter = WolframscriptAdapter(doctor.wolframscript or doctor.kernel_path, default_timeout=timeout,
                                   kernel_path=doctor.kernel_path)
    # 与 run_task 一致：task.json 和 sources 同目录，Import 才能找到数据文件。
    document = _copy_inputs(source, target, document)
    task_json = target / "input" / "task.json"
    document.save(task_json, resolve_language=True)
    run = adapter.build_notebook(task_json, notebook, code_wl, target / "build.json", timeout=timeout)
    if not run.ok:
        raise MskError(run.error_code or "EVALUATION_FAILED", run.message or "native notebook build failed",
                       details={"stdout": run.stdout[-4000:], "stderr": run.stderr[-4000:]})
    return {"ok": True, "status": "built", "notebook": str(notebook), "code": str(code_wl),
            "payload": run.payload}
