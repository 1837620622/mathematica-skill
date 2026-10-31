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
# 引擎探测只回答「内核能不能启动、许可证能不能用」，与具体操作的超时无关。
# Mac 冷启动加许可证校验可能要 30-60 秒（见 docs/MACOS.md），太短会把能用的内核误报成不可用。
ENGINE_PROBE_TIMEOUT = 60.0

KERNEL_ENV_VARS = ("MATHEMATICA_KERNEL", "WOLFRAM_KERNEL", "WOLFRAMSCRIPT_KERNELPATH")
SCRIPT_ENV_VARS = ("WOLFRAMSCRIPT", "MATHEMATICA_WOLFRAMSCRIPT")


def _run(command: list[str], *, timeout: float = 25.0,
         env: dict[str, str] | None = None) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                                   encoding="utf-8", errors="replace", env=env)
        return completed.returncode, completed.stdout, completed.stderr
    except FileNotFoundError:
        return 127, "", "executable not found"
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        return 124, stdout, "timeout"
    except OSError as exc:
        return 126, "", str(exc)


_VERSION_SEGMENT = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})(?!\d)")


def _version_key(path: Path) -> tuple[int, ...]:
    """版本排序键：优先 .app bundle 的 Info.plist，其次路径里的 14.0 / 13.3。

    不能把路径里所有数字都算进来：Windows 的 Program Files (x86) 里那个 86
    会被误当成版本号，反而选中旧版。
    macOS 上 `Mathematica 14.1.app` 版本在路径里、`Wolfram Engine.app` 不在，
    所以必须读 bundle 元数据，否则引擎版本永远排最后。
    """
    if platform.system() == "Darwin" and ".app" in str(path):
        version = bundle_info(path).get("version") or (0, 0)
        if version != (0, 0):
            return tuple(version)
    matches = _VERSION_SEGMENT.findall(str(path))
    if not matches:
        return (0, 0)
    major, minor = matches[-1]
    return (int(major), int(minor))


def _sort_key(path: Path) -> tuple[int, int, int]:
    """版本优先；同版本时带前端的 Mathematica.app 优先于 Wolfram Engine。"""
    version = _version_key(path)
    has_frontend = 1
    if platform.system() == "Darwin" and ".app" in str(path):
        has_frontend = 1 if bundle_info(path).get("has_frontend") else 0
    return (version[0], version[1], has_frontend)


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


def macos_search_paths(etc: Path | None = None, home: Path | None = None) -> list[str]:
    """macOS 上 GUI 应用拿到的 PATH 只有 /usr/bin:/bin:/usr/sbin:/sbin。

    官方 wolframscript 安装器把链接放在 /usr/local/bin，而 /etc/paths 与
    /etc/paths.d/* 才是系统声明的可执行目录；从 Finder 启动的宿主（包括各种
    Agent 客户端）不会执行 path_helper，所以这里手动补一份。
    """
    root = etc or Path("/etc")
    directories: list[str] = []

    def _add(value: str) -> None:
        value = value.strip()
        if value and value not in directories:
            directories.append(value)

    paths_file = root / "paths"
    if paths_file.is_file():
        try:
            for line in paths_file.read_text(encoding="utf-8", errors="replace").splitlines():
                _add(line)
        except OSError:
            pass
    paths_dir = root / "paths.d"
    if paths_dir.is_dir():
        try:
            for entry in sorted(paths_dir.iterdir()):
                if not entry.is_file():
                    continue
                try:
                    _add(entry.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
        except OSError:
            pass
    if home is not None:
        _add(str(home / ".local" / "bin"))
    return directories


def augmented_env() -> dict[str, str]:
    """给子进程用的环境：在 macOS 上补上系统路径声明里的目录。"""
    env = os.environ.copy()
    if platform.system() != "Darwin":
        return env
    extras = [path for path in macos_search_paths(home=Path.home()) if Path(path).is_dir()]
    if not extras:
        return env
    current = env.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    for item in reversed(extras):
        if item not in parts:
            parts.insert(0, item)
    env["PATH"] = os.pathsep.join(parts)
    return env


def _which(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if platform.system() != "Darwin":
        return None
    for directory in macos_search_paths(home=Path.home()):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def app_bundle(path: Path | str) -> Path | None:
    """从 .app 内任意路径回推 bundle 根目录。"""
    target = Path(path)
    for parent in [target, *target.parents]:
        if parent.suffix == ".app":
            return parent
    return None


def bundle_info(path: Path | str) -> dict[str, Any]:
    """读 .app 的 Info.plist：版本号，以及它是否带 Notebook 前端。

    Mathematica.app 有前端；Wolfram Engine.app 只有内核。
    版本号取自 CFBundleShortVersionString（14.1.0 → (14, 1)）。
    """
    bundle = app_bundle(path)
    info: dict[str, Any] = {"bundle": str(bundle) if bundle else "",
                            "version": (0, 0), "has_frontend": None, "product": ""}
    if bundle is None:
        return info
    name = bundle.stem
    info["product"] = name
    info["has_frontend"] = "mathematica" in name.lower()
    plist = bundle / "Contents" / "Info.plist"
    if not plist.is_file():
        return info
    try:
        import plistlib

        with plist.open("rb") as handle:
            data = plistlib.load(handle)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return info
    if not isinstance(data, dict):
        return info
    raw = str(data.get("CFBundleShortVersionString") or data.get("CFBundleVersion") or "")
    match = _VERSION_SEGMENT.search(raw)
    if match:
        info["version"] = (int(match.group(1)), int(match.group(2)))
    return info


def _candidate_kernels() -> list[Path]:
    home = Path.home()
    system = platform.system()
    candidates: list[Path] = []
    if system == "Darwin":
        # 官方安装器：/Applications/Mathematica.app、/Applications/Wolfram Engine.app
        # 也见过带版本号的 /Applications/Mathematica 14.1.app、用户级 ~/Applications。
        for base in (Path("/Applications"), home / "Applications"):
            for name in ("Mathematica.app", "Wolfram Engine.app", "WolframEngine.app",
                         "Wolfram.app"):
                candidates.append(base / name / "Contents/MacOS/WolframKernel")
        for pattern in ("Mathematica*.app", "Wolfram*Engine*.app", "Wolfram*.app"):
            candidates += sorted(Path("/Applications").glob(f"{pattern}/Contents/MacOS/WolframKernel"))
            candidates += sorted((home / "Applications").glob(f"{pattern}/Contents/MacOS/WolframKernel"))
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
    matches.sort(key=_sort_key, reverse=True)
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
    wanted = set(names)
    return [path for path in candidates if path.is_file() and path.name in wanted]


def find_wolframscript() -> Path | None:
    for variable in SCRIPT_ENV_VARS:
        value = os.environ.get(variable)
        if value and Path(value).expanduser().is_file():
            return Path(value).expanduser()
    found = _which("wolframscript")
    if found:
        return Path(found)
    matches = [path for path in _candidate_scripts() if path.is_file()]
    if not matches:
        return None
    matches.sort(key=_sort_key, reverse=True)
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
    probe_env = augmented_env()
    try:
        if wolframscript is not None:
            return _run([str(wolframscript), "-charset", "UTF8", "-file", str(path)],
                        timeout=timeout, env=probe_env)
        if kernel is not None:
            escaped = path.as_posix().replace('"', '\\"')
            return _run([str(kernel), "-noprompt", "-run", f'Get["{escaped}"]'],
                        timeout=timeout, env=probe_env)
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
    frontend_capable: bool | None = None
    frontend_detail: str = "not probed"
    product: str = ""
    arch_match: bool | None = None
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
            "frontend_capable": self.frontend_capable,
            "frontend_detail": self.frontend_detail,
            "product": self.product,
            "arch_match": self.arch_match,
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


def detect(*, deep_frontend: bool = False, timeout: float = ENGINE_PROBE_TIMEOUT) -> EngineReport:
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

    if platform.system() == "Darwin" and kernel is not None:
        info = bundle_info(kernel)
        report.product = str(info.get("product", ""))
        report.frontend_capable = info.get("has_frontend")
        if report.frontend_capable is False:
            report.warnings.append(
                "This installation is Wolfram Engine, which ships no notebook front end; "
                "本机只能算 .wl 与出图，无法验证 .nb。"
            )
        kernel_arch = str(payload.get("processor", ""))
        host_arch = platform.machine().lower()
        if kernel_arch and host_arch:
            kernel_arm = "arm" in kernel_arch.lower() or "apple" in kernel_arch.lower()
            host_arm = host_arch in {"arm64", "aarch64"}
            report.arch_match = kernel_arm == host_arm
            if not report.arch_match:
                report.warnings.append(
                    f"Kernel architecture ({kernel_arch}) differs from the host ({platform.machine()}); "
                    "Rosetta or emulation may slow every run down."
                )
    if not wolframscript:
        report.warnings.append("wolframscript was not found; notebook building uses the kernel fallback.")
    if deep_frontend:
        if report.frontend_capable is False:
            # Wolfram Engine：没有前端，探活只会白等一分钟。
            report.frontend_available = False
            report.frontend_detail = "this installation has no notebook front end (Wolfram Engine)"
        else:
            # macOS 上 Mathematica 冷启动（含许可证校验）可能要 30-60 秒，
            # 探活超时太短会误判"没有前端"，进而错误地阻止交付。
            probe_timeout = max(60.0, min(timeout, 180.0))
            available, detail = _probe_frontend(wolframscript, kernel, probe_timeout)
            report.frontend_available = available
            report.frontend_detail = detail
        if not report.frontend_available:
            report.warnings.append(
                "Notebook frontend is unavailable; verified notebook delivery is not possible on this machine."
                + _frontend_hint(platform.system())
            )
    else:
        report.frontend_detail = "not probed; run doctor --frontend"
    return report


def _frontend_hint(system: str) -> str:
    if system == "Darwin":
        return (" On macOS the front end needs a logged-in desktop session: launch Mathematica once from "
                "Finder, then run `mathematica-skill doctor --frontend` again from that same user session. "
                "SSH sessions and launchd agents usually cannot start it.")
    if system == "Windows":
        return (" On Windows the front end needs an interactive desktop session; a service or scheduled "
                "task running as SYSTEM cannot open a notebook window.")
    return (" On Linux, Wolfram Engine has no notebook front end; only .wl computation and PNG export "
            "are possible there.")


def summarize(report: EngineReport) -> str:
    lines = [
        f"platform : {report.platform_system} {report.platform_release} ({report.machine})",
        f"python   : {report.python}",
        f"script   : {report.wolframscript or 'not found'}",
        f"kernel   : {report.kernel_path or 'not found'}",
        f"version  : {report.kernel_version or 'unknown'}",
        f"licence  : {report.license_type or 'unknown'} {report.license_expiration}".rstrip(),
        f"engine   : {'usable' if report.engine_usable else 'unavailable'}",
        f"product  : {report.product or 'unknown'}",
        f"frontend : {'available' if report.frontend_available else 'unavailable'} ({report.frontend_detail})",
        f"AgentTools: {report.agenttools_version or 'not detected'}",
    ]
    for item in report.errors:
        lines.append(f"error   : {item}")
    for item in report.warnings:
        lines.append(f"warning : {item}")
    return "\n".join(lines)
