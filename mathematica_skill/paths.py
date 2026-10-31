"""Filesystem layout and path-safety helpers."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import re
import sys

from .errors import UnsafePath

_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
_RESERVED = set('<>:"/\\|?*')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}


def package_root() -> Path:
    return Path(__file__).resolve().parent


def repo_root() -> Path:
    candidate = package_root().parent
    if (candidate / "pyproject.toml").is_file() or (candidate / "wolfram").is_dir():
        return candidate
    return package_root()


def wolfram_dir() -> Path:
    """Locate the WL helper scripts for source installs and packaged installs."""
    env = os.environ.get("MATHEMATICA_SKILL_WOLFRAM")
    candidates = [
        Path(env) if env else None,
        repo_root() / "wolfram",
        package_root() / "wolfram",
        package_root() / "scripts" / "wolfram",
        Path(sys.prefix) / "share" / "mathematica-skill" / "wolfram",
        Path.home() / ".mathematica-skill" / "wolfram",
    ]
    for candidate in candidates:
        if candidate and (candidate / "MathematicaSkill.wl").is_file():
            return candidate
    return repo_root() / "wolfram"


def skill_dir() -> Path:
    return repo_root() / "skills" / "mathematica-native"


def default_work_root() -> Path:
    return Path(os.environ.get("MATHEMATICA_SKILL_WORK", Path.cwd() / "work")).expanduser().resolve()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_absolute_like(value: str) -> bool:
    return value.startswith(("/", "\\", "~")) or bool(_DRIVE.match(value))


def safe_relative(value: str, *, field: str = "path") -> PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        raise UnsafePath(f"{field} must be a non-empty string.", {"value": value})
    normalized = value.replace("\\", "/")
    if is_absolute_like(normalized):
        raise UnsafePath(f"{field} must be relative: {value!r}", {"value": value})
    path = PurePosixPath(normalized)
    if any(part in ("", ".", "..") for part in path.parts):
        raise UnsafePath(f"{field} contains an unsafe segment: {value!r}", {"value": value})
    return path


def safe_filename(value: str, *, field: str = "filename") -> str:
    path = safe_relative(value, field=field)
    if len(path.parts) != 1:
        raise UnsafePath(f"{field} must not contain directories: {value!r}", {"value": value})
    name = path.name
    # 允许中文、日文、韩文等 Unicode 文件名；只拒绝路径分隔符、控制字符和 Windows 保留名。
    if not name or name.startswith(".") or name.endswith((" ", ".")):
        raise UnsafePath(f"{field} is not a portable filename: {value!r}", {"value": value})
    if any(ch in _RESERVED or ord(ch) < 32 for ch in name):
        raise UnsafePath(f"{field} contains unsupported characters: {value!r}", {"value": value})
    if name.split(".")[0].upper() in _WINDOWS_RESERVED:
        raise UnsafePath(f"{field} uses a reserved Windows name: {value!r}", {"value": value})
    if len(name) > 180:
        raise UnsafePath(f"{field} is too long: {len(name)} characters", {"value": value})
    return name


def resolve_inside(base: Path, relative: str, *, field: str = "path") -> Path:
    rel = safe_relative(relative, field=field)
    base = base.resolve()
    target = (base / Path(*rel.parts)).resolve()
    if base != target and base not in target.parents:
        raise UnsafePath(f"{field} escapes {base}: {relative!r}", {"base": str(base), "value": relative})
    return target


def redact_path(value: str, home: Path | None = None) -> str:
    home = (home or Path.home()).resolve()
    text = str(value)
    for prefix, replacement in ((str(home), "~"), ("/Users/", "~/"), ("/home/", "~/"),
                                ("C:\\Users\\", "%USERPROFILE%\\")):
        if text.startswith(prefix):
            return replacement + text[len(prefix):]
    return text


def slugify(value: str, fallback: str = "task") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "").strip()).strip("-._")
    return (text[:80] or fallback).lower()
