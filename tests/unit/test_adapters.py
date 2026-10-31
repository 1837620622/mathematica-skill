"""适配器与错误传播（用假内核，不产生任何真实交付）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mathematica_skill.adapter_base import NativeRun, extract_json, run_process
from mathematica_skill.adapter_wolframscript import WolframscriptAdapter
from mathematica_skill.errors import FrontendUnavailable
from mathematica_skill.adapter_frontend import FrontendAdapter


def test_extract_json_from_noisy_stdout() -> None:
    payload = extract_json('Mathematica says hello\n{"ok": true, "value": 1}\ntrailing')
    assert payload == {"ok": True, "value": 1}


def test_extract_json_ignores_braces_in_strings() -> None:
    payload = extract_json('noise {"ok": true, "text": "a } b"} noise')
    assert payload["text"] == "a } b"


def test_extract_json_returns_none_for_garbage() -> None:
    assert extract_json("no json here") is None


def test_run_process_reports_missing_executable() -> None:
    result = run_process(["definitely-not-a-real-binary-xyz"], timeout=5)
    assert result.ok is False
    assert result.error_code == "ENGINE_NOT_FOUND"


def test_run_process_times_out(tmp_path: Path) -> None:
    result = run_process(["sleep", "5"], timeout=0.4)
    assert result.status == "timeout"
    assert result.error_code == "TIMEOUT"


def test_adapter_propagates_native_failure(fake_wolframscript_failure: Path, tmp_path: Path) -> None:
    adapter = WolframscriptAdapter(fake_wolframscript_failure, default_timeout=10)
    run = adapter.evaluate_notebook(tmp_path / "x.nb", tmp_path / "r.json")
    assert run.ok is False
    assert run.error_code == "EVALUATION_FAILED"
    assert "stub failure" in run.message


def test_adapter_accepts_success_payload(fake_wolframscript: Path, tmp_path: Path) -> None:
    adapter = WolframscriptAdapter(fake_wolframscript, default_timeout=10)
    run = adapter.build_notebook(tmp_path / "t.json", tmp_path / "x.nb", tmp_path / "c.wl", tmp_path / "r.json")
    assert run.ok is True
    assert run.payload["version"] == "stub"


def test_frontend_adapter_refuses_when_unavailable(tmp_path: Path, fake_wolframscript: Path) -> None:
    adapter = WolframscriptAdapter(fake_wolframscript)
    frontend = FrontendAdapter(adapter, available=False, detail="no desktop session")
    with pytest.raises(FrontendUnavailable):
        frontend.evaluate(tmp_path / "x.nb", tmp_path / "r.json")


def test_native_run_defaults_are_false() -> None:
    run = NativeRun()
    assert run.ok is False
    assert run.payload == {}


def test_adapter_prefers_result_file_over_stdout(tmp_path: Path) -> None:
    """用户代码打印噪音时，仍应以脚本写出的结果文件为准。"""
    result = tmp_path / "result.json"
    script = tmp_path / "wolframscript"
    script.write_text(
        "#!/bin/sh\n"
        "echo 'noise {\"ok\": false}'\n"
        f"printf '%s' '{{\"ok\": true, \"via\": \"file\"}}' > '{result}'\n"
        "exit 0\n"
    )
    script.chmod(0o755)
    adapter = WolframscriptAdapter(script, default_timeout=10)
    run = adapter.build_notebook(tmp_path / "t.json", tmp_path / "x.nb", tmp_path / "c.wl", result)
    assert run.ok is True
    assert run.payload["via"] == "file"


def test_adapter_ignores_stale_result_file(tmp_path: Path) -> None:
    """上一轮遗留的 result.json 不能被当成这一轮的成功证据。"""
    script = tmp_path / "wolframscript"
    script.write_text("""#!/bin/sh
echo '{"ok": true, "via": "stdout"}'
exit 0
""")
    script.chmod(0o755)
    result = tmp_path / "result.json"
    result.write_text('{"ok": true, "via": "stale"}', encoding="utf-8")
    adapter = WolframscriptAdapter(script, default_timeout=10)
    run = adapter.build_notebook(tmp_path / "t.json", tmp_path / "x.nb", tmp_path / "c.wl", result)
    assert run.payload["via"] == "stdout"


def test_command_uses_documented_flags(tmp_path: Path) -> None:
    """官方文档的调用形状：-charset UTF8 -file <script> <args>。"""
    fake = tmp_path / "wolframscript"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    adapter = WolframscriptAdapter(fake, default_timeout=30)
    command = adapter.command_for("VerifyResults.wls", ["a.json", "b.wl"], timeout=30)
    assert command[0] == str(fake)
    assert "-charset" in command and command[command.index("-charset") + 1] == "UTF8"
    assert "-timeout" in command
    assert "-file" in command
    assert "--" not in command
    assert command[-2:] == ["a.json", "b.wl"]


def test_command_includes_local_kernel_when_known(tmp_path: Path) -> None:
    fake = tmp_path / "wolframscript"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    kernel = tmp_path / "WolframKernel"
    kernel.write_text("#!/bin/sh\nexit 0\n")
    kernel.chmod(0o755)
    adapter = WolframscriptAdapter(fake, kernel_path=kernel)
    command = adapter.command_for("BuildNotebook.wls", [], timeout=10)
    assert "-local" in command
    assert command[command.index("-local") + 1] == str(kernel)


def test_command_falls_back_to_kernel_run(tmp_path: Path) -> None:
    kernel = tmp_path / "WolframKernel"
    kernel.write_text("#!/bin/sh\nexit 0\n")
    kernel.chmod(0o755)
    adapter = WolframscriptAdapter(kernel)
    command = adapter.command_for("BuildNotebook.wls", ["x"], timeout=10)
    assert command[1] == "-noprompt"
    assert command[2] == "-run"
    assert "Get[" in command[3]


def test_evaluate_notebook_passes_timeout(tmp_path: Path) -> None:
    fake = tmp_path / "wolframscript"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    adapter = WolframscriptAdapter(fake, default_timeout=30)
    command = adapter.command_for("EvaluateNotebook.wls", ["nb", "r.json", "evaluate", "240"], timeout=240)
    assert "-timeout" in command
    assert command[command.index("-timeout") + 1] == "240"
