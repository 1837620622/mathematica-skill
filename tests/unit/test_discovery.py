"""引擎探测超时：所有入口共用一个值，且不随具体操作的超时缩短。

Mac 冷启动加许可证校验可能要 30-60 秒；探测超时太短会把能用的内核误报成 ENGINE_NOT_FOUND。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mathematica_skill import cli, discovery, mcp_server, workflow
from mathematica_skill.discovery import ENGINE_PROBE_TIMEOUT, EngineReport, detect
from mathematica_skill.errors import MskError
from mathematica_skill.workflow import RunOptions, run_task


def _unusable(**_kwargs: Any) -> EngineReport:
    return EngineReport(platform_system="Test", platform_release="0", machine="x86", python="3",
                        engine_usable=False, errors=["stub: no engine"])


def test_engine_probe_defaults_to_shared_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[float] = []

    def probe(kernel: Path | None, wolframscript: Path | None, timeout: float) -> dict[str, Any]:
        calls.append(timeout)
        return {"ok": False, "returncode": 1, "stdout": "", "stderr": "", "payload": {}}

    monkeypatch.setattr(discovery, "find_wolframscript", lambda: Path("/stub/wolframscript"))
    monkeypatch.setattr(discovery, "find_kernel", lambda: None)
    monkeypatch.setattr(discovery, "_probe_script", probe)
    report = detect()
    assert report.engine_usable is False
    assert calls == [ENGINE_PROBE_TIMEOUT]


def test_doctor_cli_default_is_the_shared_timeout() -> None:
    assert cli.build_parser().parse_args(["doctor"]).timeout == ENGINE_PROBE_TIMEOUT


def test_mcp_adapter_probe_uses_shared_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    def fake_detect(**kwargs: Any) -> EngineReport:
        calls.append(kwargs.get("timeout"))
        return _unusable()

    monkeypatch.setattr(mcp_server, "detect", fake_detect)
    with pytest.raises(MskError) as excinfo:
        mcp_server._adapter(900.0)
    assert excinfo.value.code == "ENGINE_NOT_FOUND"
    assert calls == [ENGINE_PROBE_TIMEOUT]


def test_preflight_probe_ignores_small_operation_timeout(monkeypatch: pytest.MonkeyPatch, task_file: Path,
                                                         tmp_path: Path) -> None:
    calls: list[Any] = []

    def fake_detect(**kwargs: Any) -> EngineReport:
        calls.append(kwargs.get("timeout"))
        return _unusable()

    monkeypatch.setattr(workflow, "detect", fake_detect)
    state = run_task(task_file, RunOptions(work_root=tmp_path / "work", dry_run=True, timeout=10.0))
    assert state["status"] == "dry_run"
    assert calls == [ENGINE_PROBE_TIMEOUT]
