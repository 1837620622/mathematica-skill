"""安装、更新、回滚和卸载。

原则：只写自己拥有或有明确记录的文件；不覆盖用户已有的 Skill/MCP 配置；
所有写操作先备份，支持 --dry-run。
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import sys
from datetime import datetime, timezone
from typing import Any

from . import SKILL_NAME, __version__
from .errors import MskError
from .jsonio import read_json, write_json
from .paths import skill_dir

MARKER = ".mathematica-skill.json"
STATE_HOME = Path.home() / ".mathematica-skill"
MANIFEST = STATE_HOME / "install.json"
BACKUPS = STATE_HOME / "backups"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_manifest() -> dict[str, Any]:
    if MANIFEST.is_file():
        try:
            data = read_json(MANIFEST)
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {"version": __version__, "installed_at": "", "targets": [], "mcp": []}


def _backup(destination: Path, label: str) -> Path | None:
    if not destination.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUPS / f"{stamp}-{label}" / destination.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_dir():
        shutil.copytree(destination, target)
    else:
        shutil.copy2(destination, target)
    return target


def default_targets() -> list[Path]:
    """只在宿主已经存在的配置目录里安装，避免凭空创建一堆目录。"""
    home = Path.home()
    candidates = [
        home / ".claude" / "skills",
        home / ".config" / "opencode" / "skills",
        home / ".codex" / "skills",
        home / ".pi" / "skills",
        home / ".cursor" / "skills",
    ]
    return [path for path in candidates if path.parent.exists()]


def install(targets: list[Path] | None = None, *, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    source = skill_dir()
    if not (source / "SKILL.md").is_file():
        raise MskError("INSTALL_FAILED", f"Skill source not found: {source}")
    targets = [Path(item).expanduser().resolve() for item in (targets or default_targets())]
    if not targets:
        raise MskError("INSTALL_FAILED",
                       "No known agent skill directory was found; pass --target <dir> explicitly.")
    actions: list[dict[str, Any]] = []
    installed: list[dict[str, Any]] = []
    for target in targets:
        destination = target / SKILL_NAME
        conflict = destination.exists() and not (destination / MARKER).is_file()
        if conflict and not force:
            raise MskError("INSTALL_CONFLICT",
                           f"Existing non-managed skill will not be overwritten: {destination}")
        if destination.exists():
            backup = _backup(destination, "skill")
        else:
            backup = None
        action = {"action": "install", "target": str(destination), "backup": str(backup) if backup else ""}
        actions.append(action)
        if dry_run:
            continue
        target.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
        write_json(destination / MARKER, {
            "name": SKILL_NAME, "version": __version__, "installed_at": _now(),
            "source": str(source),
        })
        installed.append({"path": str(destination), "version": __version__, "backup": str(backup) if backup else ""})
    if not dry_run:
        manifest = _read_manifest()
        manifest["targets"] = [item for item in manifest.get("targets", [])
                               if isinstance(item, dict) and item.get("path") not in {x["path"] for x in installed}]
        manifest["targets"].extend(installed)
        manifest["version"] = __version__
        manifest["installed_at"] = _now()
        write_json(MANIFEST, manifest)
    planned = [str(item / SKILL_NAME) for item in targets]
    return {"ok": True, "dry_run": dry_run, "version": __version__, "actions": actions,
            "targets": [item["path"] for item in installed] if not dry_run else planned}


def update(*, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    manifest = _read_manifest()
    targets = [Path(item["path"]).parent for item in manifest.get("targets", [])
               if isinstance(item, dict) and item.get("path")]
    if not targets:
        raise MskError("INSTALL_FAILED", "No previous installation was recorded; run install first.")
    return install(targets, force=True or force, dry_run=dry_run)


def uninstall(*, dry_run: bool = False, targets: list[Path] | None = None) -> dict[str, Any]:
    manifest = _read_manifest()
    removed: list[str] = []
    wanted = {str(Path(item).expanduser().resolve() / SKILL_NAME) for item in targets} if targets else None
    for entry in manifest.get("targets", []):
        if not isinstance(entry, dict):
            continue
        destination = Path(entry.get("path", ""))
        if wanted is not None and str(destination) not in wanted:
            continue
        if not destination.is_dir() or not (destination / MARKER).is_file():
            continue
        if not dry_run:
            shutil.rmtree(destination)
        removed.append(str(destination))
    if not dry_run:
        manifest["targets"] = [item for item in manifest.get("targets", [])
                               if str(Path(item.get("path", ""))) not in set(removed)]
        write_json(MANIFEST, manifest)
    return {"ok": True, "dry_run": dry_run, "removed": removed}


def rollback() -> dict[str, Any]:
    if not BACKUPS.is_dir():
        raise MskError("INSTALL_FAILED", "No backup is available.")
    candidates = sorted([path for path in BACKUPS.iterdir() if path.is_dir()])
    if not candidates:
        raise MskError("INSTALL_FAILED", "No backup is available.")
    latest = candidates[-1]
    restored: list[str] = []
    for source in latest.iterdir():
        if not source.is_dir():
            continue
        # 只恢复我们记录过的目标，避免把同名目录到处覆盖
        manifest = _read_manifest()
        for entry in manifest.get("targets", []):
            path = Path(entry.get("path", ""))
            if path.name == source.name:
                shutil.rmtree(path, ignore_errors=True)
                shutil.copytree(source, path)
                restored.append(str(path))
    return {"ok": True, "restored": restored, "backup": str(latest)}


def _mcp_entry(*, opencode: bool = False) -> dict[str, Any]:
    command = [sys.executable, "-m", "mathematica_skill.mcp_server"]
    if opencode:
        # OpenCode 的 MCP 配置格式：type=local，command 是数组，enabled 显式开启。
        return {"type": "local", "command": command, "enabled": True}
    return {"command": command[0], "args": command[1:], "env": {}}


def _merge_json(path: Path, *, opencode: bool, force: bool, dry_run: bool) -> dict[str, Any]:
    if path.is_file():
        try:
            data = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            raise MskError("INSTALL_CONFLICT", f"Existing config is not valid JSON: {path}") from exc
        if not isinstance(data, dict):
            raise MskError("INSTALL_CONFLICT", f"Existing config must be a JSON object: {path}")
    else:
        data = {}
    entry = _mcp_entry(opencode=opencode)
    key = "mcp" if opencode else "mcpServers"
    existing = data.setdefault(key, {})
    if not isinstance(existing, dict):
        raise MskError("INSTALL_CONFLICT", f"Config key {key!r} must be an object: {path}")
    if "mathematica-skill" in existing and not force:
        return {"ok": True, "changed": False, "path": str(path),
                "message": "mathematica-skill is already configured; use --force to replace"}
    existing["mathematica-skill"] = entry
    if not dry_run:
        if path.exists():
            _backup(path, "mcp")
        write_json(path, data)
    return {"ok": True, "changed": True, "path": str(path), "dry_run": dry_run}


def _merge_toml(path: Path, *, force: bool, dry_run: bool) -> dict[str, Any]:
    section = "[mcp_servers.mathematica-skill]"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    block = (f"{section}\n"
             f"command = {json.dumps(sys.executable)}\n"
             f"args = [\"-m\", \"mathematica_skill.mcp_server\"]\n")
    if section in text:
        if not force:
            return {"ok": True, "changed": False, "path": str(path),
                    "message": "mathematica-skill is already configured; use --force to replace"}
        pattern = re.compile(re.escape(section) + r".*?(?=\n\[|\Z)", re.S)
        text = pattern.sub(block.rstrip(), text)
    else:
        text = (text.rstrip() + "\n\n" + block) if text.strip() else block
    if not dry_run:
        if path.exists():
            _backup(path, "mcp")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return {"ok": True, "changed": True, "path": str(path), "dry_run": dry_run}


def configure_mcp(client: str, *, config_path: Path | None = None, force: bool = False,
                  dry_run: bool = False) -> dict[str, Any]:
    home = Path.home()
    if client == "claude":
        path = config_path or home / ".claude.json"
        result = _merge_json(path, opencode=False, force=force, dry_run=dry_run)
    elif client == "cursor":
        path = config_path or home / ".cursor" / "mcp.json"
        result = _merge_json(path, opencode=False, force=force, dry_run=dry_run)
    elif client == "opencode":
        path = config_path or home / ".config" / "opencode" / "opencode.json"
        result = _merge_json(path, opencode=True, force=force, dry_run=dry_run)
    elif client == "codex":
        path = config_path or home / ".codex" / "config.toml"
        result = _merge_toml(path, force=force, dry_run=dry_run)
    elif client == "generic":
        path = config_path or home / ".config" / "mathematica-skill" / "mcp.json"
        result = _merge_json(path, opencode=False, force=force, dry_run=dry_run)
    else:
        raise MskError("INSTALL_FAILED", f"Unknown MCP client: {client}")
    if result.get("changed"):
        manifest = _read_manifest()
        entries = [item for item in manifest.get("mcp", []) if isinstance(item, dict)
                   and item.get("path") != result["path"]]
        entries.append({"client": client, "path": result["path"], "configured_at": _now()})
        manifest["mcp"] = entries
        if not dry_run:
            write_json(MANIFEST, manifest)
    return result
