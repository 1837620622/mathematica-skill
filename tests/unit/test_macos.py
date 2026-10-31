"""macOS 专属探测：PATH 补全、.app bundle 元数据、架构与前端能力。

这些测试用临时目录伪造 /etc/paths、/etc/paths.d 与 .app 结构，
所以能在任何平台上验证 macOS 分支的逻辑，不需要真的 Mac。
"""

from __future__ import annotations

import os
import plistlib
from pathlib import Path

import pytest

from mathematica_skill import discovery


def _write_plist(app: Path, *, version: str, name: str) -> None:
    contents = app / "Contents"
    contents.mkdir(parents=True, exist_ok=True)
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(
            {"CFBundleShortVersionString": version, "CFBundleName": name}, handle
        )


def _fake_app(root: Path, name: str, version: str) -> Path:
    app = root / f"{name}.app"
    kernel = app / "Contents" / "MacOS" / "WolframKernel"
    kernel.parent.mkdir(parents=True, exist_ok=True)
    kernel.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    _write_plist(app, version=version, name=name)
    return kernel


# ---------- PATH 补全 ----------

def test_macos_search_paths_reads_paths_and_paths_d(tmp_path: Path) -> None:
    etc = tmp_path / "etc"
    (etc / "paths.d").mkdir(parents=True)
    (etc / "paths").write_text("/usr/bin\n/bin\n/usr/local/bin\n", encoding="utf-8")
    (etc / "paths.d" / "40-x11").write_text("/opt/X11/bin\n", encoding="utf-8")
    (etc / "paths.d" / "99-wolfram").write_text("/Applications/Mathematica.app/Contents/MacOS\n", encoding="utf-8")

    found = discovery.macos_search_paths(etc=etc, home=tmp_path / "home")
    assert found[:4] == ["/usr/bin", "/bin", "/usr/local/bin", "/opt/X11/bin"]
    assert any("Mathematica.app" in item for item in found)
    assert str(tmp_path / "home" / ".local" / "bin") in found


def test_macos_search_paths_tolerates_missing_files(tmp_path: Path) -> None:
    assert discovery.macos_search_paths(etc=tmp_path / "nope", home=tmp_path / "h") == [
        str(tmp_path / "h" / ".local" / "bin")
    ]


def test_search_paths_are_deduplicated(tmp_path: Path) -> None:
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "paths").write_text("/usr/bin\n/usr/bin\n/usr/bin\n", encoding="utf-8")
    found = discovery.macos_search_paths(etc=etc, home=None)
    assert found == ["/usr/bin"]


def test_augmented_env_leaves_linux_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery.platform, "system", lambda: "Linux")
    env = discovery.augmented_env()
    assert env["PATH"] == os.environ.get("PATH", "")


def test_augmented_env_prepends_macos_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    extra = tmp_path / "extra"
    extra.mkdir()
    monkeypatch.setattr(discovery.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        discovery, "macos_search_paths", lambda etc=None, home=None: [str(extra), "/usr/bin"]
    )
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    env = discovery.augmented_env()
    assert env["PATH"].split(os.pathsep)[0] == str(extra)


# ---------- .app bundle ----------

def test_app_bundle_finds_root(tmp_path: Path) -> None:
    kernel = _fake_app(tmp_path, "Mathematica", "14.1.0")
    assert discovery.app_bundle(kernel) == tmp_path / "Mathematica.app"
    assert discovery.app_bundle("/usr/local/bin/wolframscript") is None


def test_bundle_info_reads_version_and_frontend(tmp_path: Path) -> None:
    kernel = _fake_app(tmp_path, "Mathematica", "14.1.0")
    info = discovery.bundle_info(kernel)
    assert info["version"] == (14, 1)
    assert info["has_frontend"] is True
    assert info["product"] == "Mathematica"


def test_wolfram_engine_has_no_frontend(tmp_path: Path) -> None:
    kernel = _fake_app(tmp_path, "Wolfram Engine", "14.0.0")
    info = discovery.bundle_info(kernel)
    assert info["version"] == (14, 0)
    assert info["has_frontend"] is False


def test_bundle_info_survives_broken_plist(tmp_path: Path) -> None:
    kernel = _fake_app(tmp_path, "Mathematica", "14.0.0")
    (tmp_path / "Mathematica.app" / "Contents" / "Info.plist").write_bytes(b"not a plist")
    info = discovery.bundle_info(kernel)
    assert info["version"] == (0, 0)
    assert info["has_frontend"] is True


def test_bundle_info_missing_plist(tmp_path: Path) -> None:
    app = tmp_path / "WolframEngine.app" / "Contents" / "MacOS"
    app.mkdir(parents=True)
    kernel = app / "WolframKernel"
    kernel.write_text("x", encoding="utf-8")
    info = discovery.bundle_info(kernel)
    assert info["version"] == (0, 0)
    assert info["has_frontend"] is False


# ---------- 排序：版本优先，同版本前端优先 ----------

def test_version_prefers_bundle_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery.platform, "system", lambda: "Darwin")
    old = _fake_app(tmp_path, "Mathematica 13", "13.3.0")
    new = _fake_app(tmp_path, "Wolfram Engine", "14.0.0")
    assert discovery._version_key(new) > discovery._version_key(old)


def test_same_version_prefers_frontend_capable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery.platform, "system", lambda: "Darwin")
    engine = _fake_app(tmp_path, "Wolfram Engine", "14.0.0")
    full = _fake_app(tmp_path, "Mathematica", "14.0.0")
    assert discovery._sort_key(full) > discovery._sort_key(engine)


def test_version_key_ignores_digits_above_product(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery.platform, "system", lambda: "Windows")
    old = Path(r"C:\Program Files (x86)\Wolfram Research\Mathematica\13.0\WolframKernel.exe")
    new = Path(r"C:\Program Files\Wolfram Research\Mathematica\14.0\WolframKernel.exe")
    assert discovery._version_key(new) > discovery._version_key(old)


# ---------- 前端提示 ----------

def test_frontend_hint_mentions_desktop_session() -> None:
    hint = discovery._frontend_hint("Darwin")
    assert "desktop" in hint.lower()
    assert "Finder" in hint


def test_frontend_hint_for_windows_and_linux() -> None:
    assert "desktop session" in discovery._frontend_hint("Windows").lower()
    assert "Wolfram Engine" in discovery._frontend_hint("Linux")


# ---------- 报告字段 ----------

def test_report_exposes_new_fields() -> None:
    report = discovery.EngineReport(platform_system="Darwin", platform_release="24",
                                    machine="arm64", python="3.12")
    payload = report.to_dict()
    for key in ("frontend_capable", "product", "arch_match"):
        assert key in payload
