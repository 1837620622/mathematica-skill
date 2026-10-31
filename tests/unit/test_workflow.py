"""工作流状态机：没有真内核时必须明确失败，绝不产出 verified。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mathematica_skill import workflow
from mathematica_skill.discovery import EngineReport
from mathematica_skill.errors import DeliveryBlocked, EngineNotFound, MskError
from mathematica_skill.workflow import RunOptions, lint_task, plan_task, run_task


def _no_engine(**_kwargs) -> EngineReport:
    return EngineReport(platform_system="Test", platform_release="0", machine="x86", python="3",
                        engine_usable=False, errors=["stub: no engine"])


def _engine_no_frontend(**_kwargs) -> EngineReport:
    return EngineReport(platform_system="Test", platform_release="0", machine="x86", python="3",
                        engine_usable=True, frontend_available=False, frontend_detail="stub: no frontend",
                        mode="wolframscript", wolframscript="/nonexistent/wolframscript",
                        kernel_path="/nonexistent/WolframKernel")


def test_plan_is_static(task_file: Path) -> None:
    payload = plan_task(task_file)
    assert payload["ok"] is True
    assert payload["tasks"][0]["id"] == "answer"
    assert payload["delivery"]["outputs"] == ["fig"]


def test_lint_flags_syntax_error(tmp_path: Path, task_payload: dict) -> None:
    task_payload["tasks"][0]["code"] = "f[1, 2"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(task_payload))
    payload = lint_task(path)
    assert payload["ok"] is False
    assert any(item["code"] == "WL_SYNTAX" for item in payload["errors"])


def test_lint_blocks_shell_escape(tmp_path: Path, task_payload: dict) -> None:
    task_payload["tasks"][0]["code"] = 'RunProcess[{"rm", "-rf", "x"}];'
    path = tmp_path / "shell.json"
    path.write_text(json.dumps(task_payload))
    payload = lint_task(path)
    assert any(item["code"] == "POLICY_BLOCKED" for item in payload["errors"])


def test_lint_allows_shell_when_opted_in(tmp_path: Path, task_payload: dict) -> None:
    task_payload["tasks"][0]["code"] = 'RunProcess[{"echo", "hi"}];'
    path = tmp_path / "shell.json"
    path.write_text(json.dumps(task_payload))
    payload = lint_task(path, allow_external=True)
    assert payload["ok"] is True


def test_lint_blocks_absolute_external_read(tmp_path: Path, task_payload: dict) -> None:
    task_payload["tasks"][0]["code"] = 'Import["/etc/hosts"];'
    path = tmp_path / "read.json"
    path.write_text(json.dumps(task_payload))
    assert any(item["code"] == "POLICY_BLOCKED" for item in lint_task(path)["errors"])


def test_run_without_engine_raises(monkeypatch: pytest.MonkeyPatch, task_file: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(workflow, "detect", _no_engine)
    with pytest.raises(EngineNotFound):
        run_task(task_file, RunOptions(work_root=tmp_path / "work"))


def test_dry_run_records_state(monkeypatch: pytest.MonkeyPatch, task_file: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(workflow, "detect", _no_engine)
    state = run_task(task_file, RunOptions(work_root=tmp_path / "work", dry_run=True))
    assert state["status"] == "dry_run"
    assert state["verified"] is False
    assert Path(state["state_path"]).is_file()


def test_draft_mode_never_verified(monkeypatch: pytest.MonkeyPatch, task_file: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(workflow, "detect", _no_engine)
    state = run_task(task_file, RunOptions(work_root=tmp_path / "work", allow_draft=True))
    assert state["status"] == "draft"
    assert state["verified"] is False
    assert Path(state["notebook"]).is_file()


def test_engine_without_frontend_never_delivers(monkeypatch: pytest.MonkeyPatch, task_file: Path,
                                                tmp_path: Path) -> None:
    """即使内核可用，只要前端不可用，就不能交付 verified。"""
    monkeypatch.setattr(workflow, "detect", _engine_no_frontend)
    with pytest.raises(Exception) as excinfo:
        run_task(task_file, RunOptions(work_root=tmp_path / "work", frontend_probe=True))
    assert getattr(excinfo.value, "code", "") != ""
    deliver_dirs = list((tmp_path / "work").rglob("deliver"))
    assert not any(path.is_dir() and any(path.iterdir()) for path in deliver_dirs)


def test_open_engine_with_stub_frontend_still_blocks(monkeypatch: pytest.MonkeyPatch, task_file: Path,
                                                     tmp_path: Path, fake_wolframscript: Path) -> None:
    """假内核能「返回成功」，但没有真 Notebook 和真前端，门禁必须拦住。"""
    report = _engine_no_frontend()
    report.wolframscript = str(fake_wolframscript)
    monkeypatch.setattr(workflow, "detect", lambda **_: report)
    with pytest.raises(DeliveryBlocked) as excinfo:
        run_task(task_file, RunOptions(work_root=tmp_path / "work", frontend_probe=False))
    assert excinfo.value.code == "DELIVERY_BLOCKED"
    assert not any((tmp_path / "work").rglob("deliver"))


def test_run_without_checks_is_blocked_before_native_work(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                         task_payload: dict) -> None:
    """没有 checks 的任务不能进入 verified；门禁要在原生阶段之前拦下，并留下验收报告。"""
    task_payload["tasks"][0]["checks"] = []
    path = tmp_path / "nochecks.json"
    path.write_text(json.dumps(task_payload), encoding="utf-8")
    monkeypatch.setattr(workflow, "detect", _no_engine)
    state = run_task(path, RunOptions(work_root=tmp_path / "work"))
    assert state["status"] == "blocked"
    assert state["verified"] is False
    assert [item["code"] for item in state["errors"]] == ["CHECKS_EMPTY"]
    assert "native_build" not in [stage["stage"] for stage in state["stages"]]
    report = json.loads((Path(state["run_dir"]) / "_validation" / "validation.json").read_text(encoding="utf-8"))
    assert report["ok"] is False


def test_policy_block_short_circuits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                     task_payload: dict) -> None:
    task_payload["tasks"][0]["code"] = 'RunProcess[{"rm", "-rf", "/"}];'
    path = tmp_path / "shell.json"
    path.write_text(json.dumps(task_payload))
    monkeypatch.setattr(workflow, "detect", _engine_no_frontend)
    state = run_task(path, RunOptions(work_root=tmp_path / "work"))
    assert state["status"] == "blocked"
    assert any(item["code"] == "POLICY_BLOCKED" for item in state["errors"])


def test_seed_override_does_not_touch_source(monkeypatch: pytest.MonkeyPatch, task_file: Path,
                                             tmp_path: Path) -> None:
    before = task_file.read_bytes()
    monkeypatch.setattr(workflow, "detect", _no_engine)
    run_task(task_file, RunOptions(work_root=tmp_path / "work", allow_draft=True, seed=99))
    assert task_file.read_bytes() == before


def test_missing_task_file_is_invalid() -> None:
    with pytest.raises(MskError) as excinfo:
        plan_task("/nonexistent/task.json")
    assert excinfo.value.code == "INVALID_TASK"
