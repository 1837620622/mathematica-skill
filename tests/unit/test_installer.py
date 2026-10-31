"""安装、更新、回滚、卸载与 MCP 配置合并。

全部在临时 HOME 下运行，绝不碰真实用户配置。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mathematica_skill import SKILL_NAME
from mathematica_skill.errors import MskError
from mathematica_skill.installer import configure_mcp, install, rollback, uninstall, update


@pytest.fixture()
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    for module in ("mathematica_skill.installer",):
        import importlib

        importlib.reload(__import__(module, fromlist=["_"]))
    return home


def test_install_requires_explicit_target_when_no_host(fake_home: Path) -> None:
    with pytest.raises(MskError) as excinfo:
        install()
    assert "target" in str(excinfo.value)


def test_install_writes_marker_and_manifest(fake_home: Path, tmp_path: Path) -> None:
    target = tmp_path / "skills"
    result = install([target])
    destination = target / SKILL_NAME
    assert result["ok"] is True
    assert (destination / "SKILL.md").is_file()
    assert (destination / ".mathematica-skill.json").is_file()
    assert (fake_home / ".mathematica-skill" / "install.json").is_file()


def test_dry_run_does_not_write(fake_home: Path, tmp_path: Path) -> None:
    target = tmp_path / "skills"
    install([target], dry_run=True)
    assert not (target / SKILL_NAME).exists()


def test_install_refuses_foreign_directory(fake_home: Path, tmp_path: Path) -> None:
    target = tmp_path / "skills"
    foreign = target / SKILL_NAME
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("someone else's skill")
    with pytest.raises(MskError) as excinfo:
        install([target])
    assert excinfo.value.code == "INSTALL_CONFLICT"
    assert "someone else's skill" in (foreign / "SKILL.md").read_text()


def test_force_overwrites_foreign_with_backup(fake_home: Path, tmp_path: Path) -> None:
    target = tmp_path / "skills"
    foreign = target / SKILL_NAME
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("old")
    result = install([target], force=True)
    assert result["ok"] is True
    backups = list((fake_home / ".mathematica-skill" / "backups").rglob("SKILL.md"))
    assert backups


def test_update_without_previous_install_fails(fake_home: Path) -> None:
    with pytest.raises(MskError):
        update()


def test_uninstall_removes_only_marked_directory(fake_home: Path, tmp_path: Path) -> None:
    target = tmp_path / "skills"
    other = target / "keep-me"
    other.mkdir(parents=True)
    (other / "SKILL.md").write_text("keep")
    install([target])
    result = uninstall()
    assert result["removed"]
    assert not (target / SKILL_NAME).exists()
    assert (other / "SKILL.md").is_file()


def test_uninstall_dry_run_keeps_files(fake_home: Path, tmp_path: Path) -> None:
    target = tmp_path / "skills"
    install([target])
    uninstall(dry_run=True)
    assert (target / SKILL_NAME).is_dir()


def test_rollback_restores_backup(fake_home: Path, tmp_path: Path) -> None:
    target = tmp_path / "skills"
    install([target])
    (target / SKILL_NAME / "SKILL.md").write_text("modified")
    install([target])  # 第二次安装会先备份当前内容
    result = rollback()
    assert result["restored"]


def test_mcp_config_merges_into_existing_json(fake_home: Path, tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "keep": 1}))
    result = configure_mcp("claude", config_path=config)
    data = json.loads(config.read_text())
    assert result["changed"] is True
    assert data["keep"] == 1
    assert data["mcpServers"]["other"]["command"] == "x"
    assert "mathematica-skill" in data["mcpServers"]


def test_mcp_config_refuses_silent_overwrite(fake_home: Path, tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"mcpServers": {"mathematica-skill": {"command": "old"}}}))
    result = configure_mcp("claude", config_path=config)
    assert result["changed"] is False
    assert json.loads(config.read_text())["mcpServers"]["mathematica-skill"]["command"] == "old"


def test_mcp_config_rejects_broken_json(fake_home: Path, tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text("{not json")
    with pytest.raises(MskError) as excinfo:
        configure_mcp("claude", config_path=config)
    assert excinfo.value.code == "INSTALL_CONFLICT"


def test_codex_toml_section_is_appended(fake_home: Path, tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('model = "x"\n')
    configure_mcp("codex", config_path=config)
    text = config.read_text()
    assert "[mcp_servers.mathematica-skill]" in text
    assert 'model = "x"' in text


def test_opencode_uses_local_type(fake_home: Path, tmp_path: Path) -> None:
    config = tmp_path / "opencode.json"
    config.write_text("{}")
    configure_mcp("opencode", config_path=config)
    data = json.loads(config.read_text())
    entry = data["mcp"]["mathematica-skill"]
    assert entry["type"] == "local"
    assert entry["enabled"] is True
    assert isinstance(entry["command"], list)
