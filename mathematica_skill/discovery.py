"""跨平台发现 Wolfram 内核、wolframscript、许可证与前端。

发现顺序（每一层都可以被环境变量覆盖）：

1. `MATHEMATICA_KERNEL` / `WOLFRAM_KERNEL` / `WOLFRAMSCRIPT`
2. `PATH` 上的 `wolframscript`
3. wolframscript 自己的配置文件里的 `KERNELPATH`（三平台路径不同，官方文档给出）
4. 各平台标准安装目录

配置文件位置（来自官方 wolframscript 文档）：
  Windows  %APPDATA%\\Wolfram\\WolframScript\\WolframScript.conf
  macOS    ~/Library/Application Support/Wolfram/WolframScript/WolframScript.conf
  Unix     ~/.config/Wolfram/WolframScript/WolframScript.conf
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
from typing import Any

PROBE_BEGIN = "MSK_JSON_BEGIN"
PROBE_END = "MSK_JSON_END"
FRONTEND_MARKER = "MSK_FRONTEND_OK"

KERNEL_ENV_VARS = ("MATHEMATICA_KERNEL", "WOLFRAM_KERNEL", "WOLFRAMSCRIPT_KERNELPATH")
SCRIPT_ENV_VARS = ("WOLFRAMSCRIPT", "MATHEMATICA_WOLFRAMSCRIPT")


def _run(command: list[str], *, timeout: float = 25.0) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                                   encoding="utf-8", errors="replace")
        return completed.returncode, completed.stdout, completed.stderr
    except FileNotFoundError:
        return 127, "", "executable not found"
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        return 124, stdout, "timeout"
    except OSError as exc:
        return 126, "", str(exc)


def _version_key(path: Path) -> tuple[int, ...]:
    """按路径里的数字排序，取最新版本（14.0 > 13.3 > 13.2）。"""
    numbers = [int(item) for item in re.findall(r"\d+", str(path))]
    return tuple(numbers[-6:])


def wolframscript_config_paths() -> list[Path]:
    home = Path.home()
    system = platform.system()
    paths: list[Path] = []
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            paths.append(Path(appdata) / "Wolfram" / "WolframScript" / "WolframScript.conf")
    elif system == "Darwin":
        paths.append(home / "Library" / "Application Support" / "Wolfram" / "WolframScript" / "WolframScript.conf")
    paths.append(home / ".config" / "Wolfram" / "WolframScript" / "WolframScript.conf")
    return paths


def kernel_from_config() -> Path | None:
    """wolframscript -config 写下的 KERNELPATH，是最可靠的用户意图。"""
    for path in wolframscript_config_paths():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            if key.strip().upper() not in {"KERNELPATH", "WOLFRAMSCRIPT_KERNELPATH"}:
                continue
            candidate = Path(value.strip().strip('"'))
            if candidate.is_file():
                return candidate
    return None


def _candidate_kernels() -> list[Path]:
    home = Path.home()
    system = platform.system()
    candidates: list[Path] = []
    if system == "Darwin":
        for base in (Path("/Applications"), home / "Applications"):
            candidates.append(base / "Mathematica.app/Contents/MacOS/WolframKernel")
            candidates.append(base / "Wolfram Engine.app/Contents/MacOS/WolframKernel")
            candidates.append(base / "WolframEngine.app/Contents/MacOS/WolframKernel")
        candidates += sorted(Path("/Applications").glob("Mathematica*.app/Contents/MacOS/WolframKernel"))
        candidates += sorted(Path("/Applications").glob("Wolfram*Engine*.app/Contents/MacOS/WolframKernel"))
        candidates += sorted((home / "Applications").glob("Mathematica*.app/Contents/MacOS/WolframKernel"))
        candidates += [Path("/opt/homebrew/bin/WolframKernel"), Path("/usr/local/bin/WolframKernel")]
    elif system == "Windows":
        roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
                 Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
                 Path(os.environ.get("LOCALAPPDATA", str(home / "AppData/Local")))]
        for root in roots:
            for product in ("Wolfram Research", "Wolfram"):
                base = root / product
                if not base.is_dir():
                    continue
                # 布局：Wolfram Research\Mathematica\14.0\WolframKernel.exe
                for name in ("Mathematica", "Wolfram Engine", "WolframEngine", "Wolfram"):
                    product_dir = base / name
                    if not product_dir.is_dir():
                        continue
                    candidates += sorted(product_dir.glob("*/WolframKernel.exe"))
                    candidates += sorted(product_dir.glob("WolframKernel.exe"))
    else:
        for root in (Path("/usr/local/Wolfram"), Path("/opt/Wolfram"), Path("/usr/local"), Path("/opt")):
            if not root.is_dir():
                continue
            for product in ("Mathematica", "WolframEngine", "Wolfram Engine", "Wolfram"):
                base = root / product
                if not base.is_dir():
                    continue
                candidates += sorted(base.glob("*/Executables/WolframKernel"))
                candidates += sorted(base.glob("*/WolframKernel"))
                candidates.append(base / "Executables/WolframKernel")
            candidates += [root / "WolframKernel", root / "bin/WolframKernel"]
    candidates += [Path("/usr/bin/WolframKernel"), Path("/usr/local/bin/WolframKernel"),
                   Path("/usr/bin/math"), Path("/usr/local/bin/math")]
    return candidates


def find_kernel() -> Path | None:
    for variable in KERNEL_ENV_VARS:
        value = os.environ.get(variable)
        if value and Path(value).expanduser().is_file():
            return Path(value).expanduser()
    configured = kernel_from_config()
    if configured is not None:
        return configured
    matches = [path for path in _candidate_kernels() if path.is_file()]
    matches.sort(key=_version_key, reverse=True)
    return matches[0] if matches else None


def _candidate_scripts() -> list[Path]:
    home = Path.home()
    system = platform.system()
    names = ("wolframscript.exe", "wolframscript") if system == "Windows" else ("wolframscript",)
    candidates: list[Path] = []
    if system == "Darwin":
        candidates += [Path("/Applications/Mathematica.app/Contents/MacOS/wolframscript"),
                       home / "Applications/Mathematica.app/Contents/MacOS/wolframscript",
                       Path("/Applications/Wolfram Engine.app/Contents/MacOS/wolframscript"),
                       Path("/opt/homebrew/bin/wolframscript"),
                       Path("/usr/local/bin/wolframscript")]
        candidates += sorted(Path("/Applications").glob("Mathematica*.app/Contents/MacOS/wolframscript"))
        candidates += sorted(Path("/Applications").glob("Wolfram*Engine*.app/Contents/MacOS/wolframscript"))
        candidates += sorted((home / "Applications").glob("Mathematica*.app/Contents/MacOS/wolframscript"))
    elif system == "Windows":
        for root in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
                     Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))):
            base = root / "Wolfram Research"
            for name in ("Mathematica", "Wolfram Engine", "WolframEngine", "Wolfram"):
                product = base / name
                if product.is_dir():
                    candidates += sorted(product.glob("*/wolframscript.exe"))
                    candidates += sorted(product.glob("wolframscript.exe"))
    else:
        for root in (Path("/usr/local/Wolfram"), Path("/opt/Wolfram"), Path("/usr/local"), Path("/opt")):
            if not root.is_dir():
                continue
            for name in ("Mathematica", "WolframEngine", "Wolfram Engine", "Wolfram"):
                base = root / name
                if base.is_dir():
                    candidates += sorted(base.glob("*/Executables/wolframscript"))
                    candidates.append(base / "Executables/wolframscript")
        candidates += [Path("/usr/local/bin/wolframscript"), Path("/usr/bin/wolframscript"),
                       Path("/opt/homebrew/bin/wolframscript")]
    return [path for name in names for path in candidates if path.name == name or path.is_file()]


def find_wolframscript() -> Path | None:
    for variable in SCRIPT_ENV_VARS:
        value = os.environ.get(variable)
        if value and Path(value).expanduser().is_file():
            return Path(value).expanduser()
    found = shutil.which("wolframscript")
    if found:
        return Path(found)
    matches = [path for path in _candidate_scripts() if path.is_file()]
    if not matches:
        return None
    matches.sort(key=_version_key, reverse=True)
    return matches[0]


def find_agenttools() -> tuple[str, list[str]]:
    candidates: list[Path] = []
    home = Path.home()
    roots = [
        home / ".Mathematica/Paclets/Repository",
        home / "Library/Mathematica/Paclets/Repository",
        home / "Library/Wolfram/Paclets/Repository",
        home / "AppData/Roaming/Mathematica/Paclets/Repository",
        home / "AppData/Roaming/Wolfram/Paclets/Repository",
        Path("/usr/local/Wolfram/Mathematica"),
    ]
    for root in roots:
        if root.is_dir():
            candidates += sorted(root.glob("Wolfram-AgentTools-*"))
    versions = [path.name.replace("Wolfram-AgentTools-", "") for path in candidates]
    return (versions[-1] if versions else ""), [str(path) for path in candidates]


def _probe_expression() -> str:
    return r"""
Print["MSK_JSON_BEGIN"];
Print[ExportString[<|
  "version" -> ToString[$Version],
  "version_number" -> ToString[$VersionNumber],
  "installation" -> $InstallationDirectory,
  "operating_system" -> $OperatingSystem,
  "processor" -> $ProcessorType,
  "processor_count" -> $ProcessorCount,
  "license_type" -> ToString[Quiet[Check[$LicenseType, "unknown"]]],
  "license_expiration" -> ToString[Quiet[Check[$LicenseExpirationDate, "unknown"]]]
|>, "JSON", "Compact" -> True]];
Print["MSK_JSON_END"];
Print[ToString[1 + 1]];
"""


def _run_wls(script: str, *, wolframscript: Path | None, kernel: Path | None, timeout: float,
             suffix: str = ".wls") -> tuple[int, str, str]:
    """优先用 wolframscript；只有内核时退回 -run Get[...]。"""
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as handle:
        handle.write(script)
        path = Path(handle.name)
    try:
        if wolframscript is not None:
            return _run([str(wolframscript), "-charset", "UTF8", "-file", str(path)], timeout=timeout)
        if kernel is not None:
            escaped = path.as_posix().replace('"', '\\"')
            return _run([str(kernel), "-noprompt", "-run", f'Get["{escaped}"]'], timeout=timeout)
        return 127, "", "no kernel or wolframscript"
    finally:
        path.unlink(missing_ok=True)


def _probe_script(kernel: Path | None, wolframscript: Path | None, timeout: float) -> dict[str, Any]:
    code, out, err = _run_wls(_probe_expression(), wolframscript=wolframscript, kernel=kernel, timeout=timeout)
    payload: dict[str, Any] = {}
    begin = out.find(PROBE_BEGIN)
    end = out.find(PROBE_END)
    if begin >= 0 and end > begin:
        body = out[begin + len(PROBE_BEGIN):end].strip()
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}
    tail = out.split(PROBE_END)[-1].strip().splitlines()
    arithmetic_ok = bool(tail) and tail[-1].strip() == "2"
    usable = code == 0 and arithmetic_ok and bool(payload.get("version"))
    return {"ok": usable, "returncode": code, "stdout": out[-4000:], "stderr": err[-4000:],
            "payload": payload}


def _probe_frontend(wolframscript: Path | None, kernel: Path | None, timeout: float) -> tuple[bool, str]:
    # 前端可能被系统弹窗挡住，加 timeout 兜底，避免探活挂死。
    limit = str(max(5, int(timeout)))
    script = (
        "result = TimeConstrained[UsingFrontEnd[Print[\"" + FRONTEND_MARKER + "\"]], "
        + limit + ", \"TIMEOUT\"];\n"
        "If[result === \"TIMEOUT\", Print[\"MSK_FRONTEND_TIMEOUT\"]]\n"
    )
    code, out, err = _run_wls(script, wolframscript=wolframscript, kernel=kernel, timeout=timeout + 10)
    if FRONTEND_MARKER in out:
        return True, "UsingFrontEnd probe succeeded"
    if "MSK_FRONTEND_TIMEOUT" in out or code == 124:
        return False, "UsingFrontEnd probe timed out"
    detail = (err.strip() or out.strip() or "UsingFrontEnd probe failed")[-500:]
    return False, detail


@dataclass(slots=True)
class EngineReport:
    platform_system: str
    platform_release: str
    machine: str
    python: str
    wolframscript: str = ""
    kernel_path: str = ""
    kernel_version: str = ""
    version_number: str = ""
    installation: str = ""
    license_type: str = ""
    license_expiration: str = ""
    engine_usable: bool = False
    frontend_available: bool = False
    frontend_detail: str = "not probed"
    agenttools_version: str = ""
    agenttools_paths: list[str] = field(default_factory=list)
    mode: str = "none"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    probe: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.engine_usable,
            "platform_system": self.platform_system,
            "platform_release": self.platform_release,
            "machine": self.machine,
            "python": self.python,
            "wolframscript": self.wolframscript,
            "kernel_path": self.kernel_path,
            "kernel_version": self.kernel_version,
            "version_number": self.version_number,
            "installation": self.installation,
            "license_type": self.license_type,
            "license_expiration": self.license_expiration,
            "engine_usable": self.engine_usable,
            "frontend_available": self.frontend_available,
            "frontend_detail": self.frontend_detail,
            "agenttools_version": self.agenttools_version,
            "agenttools_paths": self.agenttools_paths,
            "mode": self.mode,
            "errors": self.errors,
            "warnings": self.warnings,
            "probe": self.probe,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


def detect(*, deep_frontend: bool = False, timeout: float = 25.0) -> EngineReport:
    report = EngineReport(platform_system=platform.system(), platform_release=platform.release(),
                          machine=platform.machine(), python=platform.python_version())
    wolframscript = find_wolframscript()
    kernel = find_kernel()
    report.wolframscript = str(wolframscript) if wolframscript else ""
    report.kernel_path = str(kernel) if kernel else ""
    if wolframscript is None and kernel is None:
        report.errors.append("No wolframscript or WolframKernel was found in PATH or standard install locations.")
        return report
    probe = _probe_script(kernel, wolframscript, timeout)
    report.probe = {key: probe.get(key) for key in ("ok", "returncode", "stdout", "stderr")}
    payload = probe.get("payload") or {}
    report.kernel_version = str(payload.get("version", ""))
    report.version_number = str(payload.get("version_number", ""))
    report.installation = str(payload.get("installation", ""))
    report.license_type = str(payload.get("license_type", ""))
    report.license_expiration = str(payload.get("license_expiration", ""))
    report.engine_usable = bool(probe.get("ok"))
    if not report.engine_usable:
        text = ((probe.get("stderr") or "") + (probe.get("stdout") or "")).lower()
        if "license" in text or "licensing" in text or "entitlement" in text:
            report.errors.append("Wolfram kernel was found but the licence check failed.")
        else:
            report.errors.append("The Wolfram kernel probe failed; run `wolframscript -code 1+1` manually.")
        return report
    report.mode = "wolframscript" if wolframscript else "kernel"
    report.agenttools_version, report.agenttools_paths = find_agenttools()
    if not wolframscript:
        report.warnings.append("wolframscript was not found; notebook building uses the kernel fallback.")
    if deep_frontend:
        available, detail = _probe_frontend(wolframscript, kernel, max(10.0, min(timeout, 30.0)))
        report.frontend_available = available
        report.frontend_detail = detail
        if not available:
            report.warnings.append(
                "Notebook frontend is unavailable; verified notebook delivery is not possible on this machine."
            )
    else:
        report.frontend_detail = "not probed; run doctor --frontend"
    return report


def summarize(report: EngineReport) -> str:
    lines = [
        f"platform : {report.platform_system} {report.platform_release} ({report.machine})",
        f"python   : {report.python}",
        f"script   : {report.wolframscript or 'not found'}",
        f"kernel   : {report.kernel_path or 'not found'}",
        f"version  : {report.kernel_version or 'unknown'}",
        f"licence  : {report.license_type or 'unknown'} {report.license_expiration}".rstrip(),
        f"engine   : {'usable' if report.engine_usable else 'unavailable'}",
        f"frontend : {'available' if report.frontend_available else 'unavailable'} ({report.frontend_detail})",
        f"AgentTools: {report.agenttools_version or 'not detected'}",
    ]
    for item in report.errors:
        lines.append(f"error   : {item}")
    for item in report.warnings:
        lines.append(f"warning : {item}")
    return "\n".join(lines)
