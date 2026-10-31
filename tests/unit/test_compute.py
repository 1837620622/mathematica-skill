"""快速计算入口：校验顺序、结果不会被标成 verified、图形只在复制时落到客户路径。

内核用替身代替：这里测的是 Python 调度层，真实的 WL 执行在 tests/native 里跑。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mathematica_skill import compute
from mathematica_skill.adapter_base import NativeRun
from mathematica_skill.adapter_wolframscript import WolframscriptAdapter
from mathematica_skill.cli import build_parser
from mathematica_skill.discovery import EngineReport
from mathematica_skill.errors import EngineNotFound, InvalidTask, MskError
from mathematica_skill.mcp_server import _tool_result
from mathematica_skill.paths import unique_path
from mathematica_skill.policy import scan_policy


def _engine(**_kwargs: Any) -> EngineReport:
    return EngineReport(platform_system="Test", platform_release="0", machine="x86", python="3",
                        engine_usable=True, wolframscript="/stub/wolframscript", kernel_path="/stub/WolframKernel")


def _no_engine(**_kwargs: Any) -> EngineReport:
    return EngineReport(platform_system="Test", platform_release="0", machine="x86", python="3",
                        engine_usable=False, errors=["stub: no engine"])


def _kernel_must_not_run(**_kwargs: Any) -> EngineReport:
    raise AssertionError("the kernel must not be probed for this request")


def _stub_kernel(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], *, png: bytes | None = None,
                 calls: list[dict[str, Any]] | None = None) -> None:
    """替换内核调用：把 payload 写进 result.json，并按需写出一张 PNG，和 WL 脚本的契约一致。"""
    monkeypatch.setattr(compute, "detect", _engine)

    def compute_code(self: WolframscriptAdapter, code_wl: Path, result_json: Path, figure_png: Path,
                     work_dir: Path, *, timeout: float | None = None) -> NativeRun:
        if calls is not None:
            calls.append({"code": code_wl.read_text(encoding="utf-8"), "work_dir": work_dir})
        if png is not None:
            figure_png.write_bytes(png)
        result_json.write_text(json.dumps(payload), encoding="utf-8")
        ok = payload.get("ok") is True
        return NativeRun(ok=ok, status="completed" if ok else "failed", payload=payload,
                         error_code="" if ok else "EVALUATION_FAILED", message=str(payload.get("message", "")))

    monkeypatch.setattr(WolframscriptAdapter, "compute_code", compute_code)


def _ok_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": True, "result": "2", "result_head": "Integer", "result_tex": "2",
                               "truncated": False, "messages": [], "figure_written": False, "seconds": 0.1}
    payload.update(overrides)
    return payload


def test_result_is_returned_and_never_verified(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    _stub_kernel(monkeypatch, _ok_payload(), calls=calls)
    payload = compute.compute_code("Integrate[Sin[x], {x, 0, Pi}]", out_dir=tmp_path)
    assert payload["result"] == "2"
    assert payload["result_head"] == "Integer"
    assert payload["verified"] is False
    assert payload["figure"] is None
    assert calls[0]["code"] == "Integrate[Sin[x], {x, 0, Pi}]"
    # 没有指定工作目录时，内核在内部目录里运行，不会在用户当前目录里留下文件。
    assert calls[0]["work_dir"] == Path(payload["run_dir"])


def test_modelling_libraries_status_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """建模库随 compute 预加载；每个库是否加载成功都要回到调用方，而不是静默失败。"""
    _stub_kernel(monkeypatch, _ok_payload(libraries={"DomainMethods": True, "PlotTheme": False}))
    payload = compute.compute_code("1 + 1", out_dir=tmp_path)
    assert payload["libraries"] == {"DomainMethods": True, "PlotTheme": False}


def test_working_dir_becomes_kernel_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    _stub_kernel(monkeypatch, _ok_payload(), calls=calls)
    data_dir = tmp_path / "project"
    data_dir.mkdir()
    compute.compute_code("1 + 1", out_dir=tmp_path / "work", working_dir=data_dir)
    assert calls[0]["work_dir"] == data_dir.resolve()


def test_missing_working_dir_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(InvalidTask):
        compute.compute_code("1 + 1", out_dir=tmp_path, working_dir=tmp_path / "nope")


def test_syntax_error_never_reaches_kernel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(compute, "detect", _kernel_must_not_run)
    with pytest.raises(InvalidTask) as excinfo:
        compute.compute_code("f[1, 2", out_dir=tmp_path)
    assert excinfo.value.code == "INVALID_TASK"


def test_empty_code_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(InvalidTask):
        compute.compute_code("   \n", out_dir=tmp_path)


def test_policy_block_never_reaches_kernel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(compute, "detect", _kernel_must_not_run)
    with pytest.raises(MskError) as excinfo:
        compute.compute_code('RunProcess[{"rm", "-rf", "/"}]', out_dir=tmp_path)
    assert excinfo.value.code == "POLICY_BLOCKED"
    assert excinfo.value.details["findings"][0]["kind"] == "process execution"


def test_allow_external_runs_and_records_the_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub_kernel(monkeypatch, _ok_payload())
    payload = compute.compute_code('RunProcess[{"echo", "hi"}]', out_dir=tmp_path, allow_external=True)
    assert payload["verified"] is False
    assert payload["warnings"][0]["code"] == "POLICY_ALLOWED"
    assert "process execution" in payload["warnings"][0]["message"]


def test_no_engine_is_reported_not_faked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(compute, "detect", _no_engine)
    with pytest.raises(EngineNotFound) as excinfo:
        compute.compute_code("1 + 1", out_dir=tmp_path)
    assert excinfo.value.code == "ENGINE_NOT_FOUND"


def test_evaluation_failure_carries_wolfram_messages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = {"ok": False, "messages": ["Integrate::idiv: Integral did not converge."],
               "message": "evaluation failed; see messages"}
    _stub_kernel(monkeypatch, payload)
    with pytest.raises(MskError) as excinfo:
        compute.compute_code("Integrate[1/x, x]", out_dir=tmp_path)
    assert excinfo.value.code == "EVALUATION_FAILED"
    assert excinfo.value.details["messages"] == ["Integrate::idiv: Integral did not converge."]


def test_figure_is_copied_to_requested_path_without_overwrite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                              fake_png: Path) -> None:
    _stub_kernel(monkeypatch, _ok_payload(figure_written=True, result_head="Graphics"),
                 png=fake_png.read_bytes())
    target = tmp_path / "client" / "plot.png"
    first = compute.compute_code("Plot[Sin[x], {x, 0, Pi}]", out_dir=tmp_path / "work", figure_path=target)
    second = compute.compute_code("Plot[Sin[x], {x, 0, Pi}]", out_dir=tmp_path / "work", figure_path=target)
    assert first["figure"]["ok"] is True
    assert Path(first["figure"]["path"]) == target
    assert Path(second["figure"]["path"]) == tmp_path / "client" / "plot-2.png"
    assert target.read_bytes() == fake_png.read_bytes()


def test_figure_stays_internal_without_figure_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                   fake_png: Path) -> None:
    _stub_kernel(monkeypatch, _ok_payload(figure_written=True), png=fake_png.read_bytes())
    payload = compute.compute_code("Plot[Sin[x], {x, 0, Pi}]", out_dir=tmp_path / "work")
    assert Path(payload["figure"]["path"]).parent == Path(payload["run_dir"])


def test_reported_figure_that_was_not_written_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub_kernel(monkeypatch, _ok_payload(figure_written=True), png=None)
    with pytest.raises(MskError) as excinfo:
        compute.compute_code("Plot[Sin[x], {x, 0, Pi}]", out_dir=tmp_path)
    assert excinfo.value.code == "PLOT_EXPORT_FAILED"


def test_figure_path_must_be_png(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(compute, "detect", _kernel_must_not_run)
    with pytest.raises(InvalidTask):
        compute.compute_code("1 + 1", out_dir=tmp_path, figure_path=tmp_path / "plot.svg")


def test_read_code_needs_exactly_one_source(tmp_path: Path) -> None:
    with pytest.raises(InvalidTask):
        compute.read_code(None, None)
    with pytest.raises(InvalidTask):
        compute.read_code("1", str(tmp_path / "x.wl"))


def test_read_code_accepts_bom_from_editors(tmp_path: Path) -> None:
    path = tmp_path / "model.wl"
    path.write_text("﻿x = 1 + 1", encoding="utf-8")
    assert compute.read_code(None, str(path)) == "x = 1 + 1"


def test_unique_path_never_overwrites(tmp_path: Path) -> None:
    first = tmp_path / "a.png"
    first.write_bytes(b"x")
    assert unique_path(first) == tmp_path / "a-2.png"
    (tmp_path / "a-2.png").write_bytes(b"y")
    assert unique_path(first) == tmp_path / "a-3.png"


def test_policy_scan_names_the_call() -> None:
    findings = scan_policy('data = Import["/etc/hosts"];', "unit")
    assert findings == [{"task": "unit", "kind": "external file read", "match": 'Import["/'}]
    assert scan_policy('Import["data.csv"]', "unit") == []


def test_mcp_tool_maps_errors_to_structured_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compute, "detect", _kernel_must_not_run)
    result = _tool_result("mathematica_compute", {"code": "f[1"})
    assert result["isError"] is True
    assert json.loads(result["content"][0]["text"])["code"] == "INVALID_TASK"


def test_mcp_tool_returns_verified_false(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub_kernel(monkeypatch, _ok_payload())
    result = _tool_result("mathematica_compute", {"code": "1 + 1", "out_dir": str(tmp_path)})
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"])["verified"] is False


def test_cli_compute_parses_code_and_figure() -> None:
    args = build_parser().parse_args(["compute", "Plot[x, {x, 0, 1}]", "--figure", "p.png", "--timeout", "30"])
    assert args.command == "compute"
    assert args.code == "Plot[x, {x, 0, 1}]"
    assert args.figure == "p.png"
    assert args.timeout == 30.0
