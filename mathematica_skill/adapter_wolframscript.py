"""wolframscript 适配器：官方文档实测过的调用方式。

关键点（来自官方 wolframscript 文档）：

- `-file file` 后面直接跟脚本参数，`$ScriptCommandLine` 拿到 {脚本, 参数...}
- `-charset UTF8` 必须显式给，否则 Windows 上会按终端代码页输出，中文全乱
- `-timeout N` 是内核侧的限制，和 Python 侧的进程超时互为兜底
- `-local <kernelpath>` 可以强制使用指定内核，多版本共存时避免拿错

没有 wolframscript 时退回裸内核 `-run Get[...]`，参数走环境变量。
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from .adapter_base import NativeRun, extract_json, run_process
from .paths import wolfram_dir


class WolframscriptAdapter:
    def __init__(self, executable: str | Path, *, default_timeout: float = 600.0,
                 kernel_path: str | Path | None = None) -> None:
        self.executable = str(executable)
        self.kernel_path = str(kernel_path) if kernel_path else ""
        self.default_timeout = default_timeout

    @property
    def source_dir(self) -> Path:
        return wolfram_dir()

    def _script(self, name: str) -> Path:
        path = self.source_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"Wolfram script missing: {path}")
        return path

    def _is_wolframscript(self) -> bool:
        return Path(self.executable).name.lower().startswith("wolframscript")

    def command_for(self, script: str, args: list[str | Path], *, timeout: float,
                    launcher_timeout: float | None = None) -> list[str]:
        """构造命令行；单独抽出来是为了能对三平台的路径做单元测试。

        `-timeout` 是 wolframscript 的外层预算，必须比脚本内部 `TimeConstrained`
        更宽松，否则脚本还没机会写结果文件就被外层掐掉。
        """
        script_path = self._script(script)
        budget = max(1, int(launcher_timeout if launcher_timeout is not None else timeout))
        if self._is_wolframscript():
            command = [self.executable, "-charset", "UTF8", "-timeout", str(budget)]
            if self.kernel_path and Path(self.kernel_path).is_file():
                command += ["-local", self.kernel_path]
            command += ["-file", str(script_path)]
            command += [str(arg) for arg in args]
            return command
        # 裸内核没有 -file；改用 -run Get[...]，参数由 MSK_SCRIPT_ARGS 传入。
        escaped = script_path.as_posix().replace('"', '\\"')
        return [self.executable, "-noprompt", "-run", f'Get["{escaped}"]']

    def _run(self, script: str, args: list[str | Path], *, timeout: float | None = None,
             cwd: Path | None = None, result_path: Path | None = None,
             launcher_timeout: float | None = None) -> NativeRun:
        effective = float(timeout or self.default_timeout)
        budget = float(launcher_timeout if launcher_timeout is not None else effective)
        command = self.command_for(script, args, timeout=effective, launcher_timeout=budget)
        if result_path is not None:
            Path(result_path).unlink(missing_ok=True)
        result = run_process(command, cwd=cwd, timeout=budget + 30,
                             env={"MSK_SCRIPT_ARGS": "\n".join(str(arg) for arg in args)})
        payload = None
        # 结果文件比 stdout 更可靠：用户代码里的 Print 不会污染 JSON。
        if result_path is not None and Path(result_path).is_file():
            try:
                payload = json.loads(Path(result_path).read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                payload = None
        if payload is None:
            payload = extract_json(result.stdout)
        if payload is not None:
            result.payload = payload if isinstance(payload, dict) else {"result": payload}
            if result.payload.get("ok") is False:
                result.ok = False
                result.status = "failed"
                result.error_code = str(result.payload.get("error_code") or "EVALUATION_FAILED")
                result.message = str(result.payload.get("message") or "native script reported a failure")
            elif not result.ok:
                result.ok = False
                result.status = "failed"
                result.error_code = str(result.payload.get("error_code") or "EVALUATION_FAILED")
                result.message = str(result.payload.get("message") or "native script did not report success")
        elif result.ok:
            result.ok = False
            result.status = "failed"
            result.error_code = "EVALUATION_FAILED"
            result.message = "the Wolfram script did not return JSON"
        if result.status == "timeout":
            result.error_code = "TIMEOUT"
        return result

    def build_notebook(self, task_json: Path, notebook: Path, code_wl: Path, result_json: Path,
                       *, timeout: float | None = None) -> NativeRun:
        return self._run("BuildNotebook.wls", [task_json, notebook, code_wl, result_json],
                         timeout=timeout, result_path=result_json)

    def evaluate_notebook(self, notebook: Path, result_json: Path, *, mode: str = "evaluate",
                          timeout: float | None = None) -> NativeRun:
        effective = float(timeout or self.default_timeout)
        args: list[str | Path] = [notebook, result_json, mode, str(int(effective))]
        # 脚本内部允许 maxSeconds + 120；外层再多给 30 秒，超时才真的报 TIMEOUT。
        return self._run("EvaluateNotebook.wls", args, timeout=effective, result_path=result_json,
                         launcher_timeout=effective + 150)

    def inspect_notebook(self, notebook: Path, result_json: Path, *, timeout: float | None = None) -> NativeRun:
        return self.evaluate_notebook(notebook, result_json, mode="reopen", timeout=timeout)

    def export_artifacts(self, task_json: Path, code_wl: Path, out_dir: Path, result_json: Path,
                         *, timeout: float | None = None) -> NativeRun:
        return self._run("ExportGraphics.wls", [task_json, code_wl, out_dir, result_json],
                         timeout=timeout, result_path=result_json)

    def verify_results(self, task_json: Path, code_wl: Path, result_json: Path, *,
                       previous: Path | None = None, timeout: float | None = None) -> NativeRun:
        arguments: list[str | Path] = [task_json, code_wl, result_json]
        if previous is not None:
            arguments.append(previous)
        return self._run("VerifyResults.wls", arguments, timeout=timeout, result_path=result_json)

    def evaluate_code(self, code: str, *, timeout: float | None = None, cwd: Path | None = None) -> NativeRun:
        with tempfile.NamedTemporaryFile("w", suffix=".wls", delete=False, encoding="utf-8") as handle:
            handle.write(code)
            path = Path(handle.name)
        try:
            effective = float(timeout or self.default_timeout)
            if self._is_wolframscript():
                command = [self.executable, "-charset", "UTF8", "-timeout", str(int(effective)),
                           "-file", str(path)]
            else:
                escaped = path.as_posix().replace('"', '\\"')
                command = [self.executable, "-noprompt", "-run", f'Get["{escaped}"]']
            result = run_process(command, cwd=cwd, timeout=effective)
            if result.ok:
                result.payload = {"text": result.stdout.strip()}
            return result
        finally:
            path.unlink(missing_ok=True)
