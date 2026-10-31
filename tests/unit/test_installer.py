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


def test_mcp_entry_carries_pythonpath_for_source_installs(fake_home: Path, tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """npx/源码安装时包目录不在 site-packages 里，GUI 宿主启动时必须靠配置里的 PYTHONPATH 找到它。"""
    from mathematica_skill import installer

    root = tmp_path / "mathematica-skill"
    monkeypatch.setattr(installer, "_package_root", lambda: root)
    entry = installer._mcp_entry()
    assert entry["env"]["PYTHONPATH"] == str(root)
    assert entry["env"]["PYTHONUTF8"] == "1"


def test_mcp_entry_skips_pythonpath_for_pip_installs(fake_home: Path, tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    from mathematica_skill import installer

    monkeypatch.setattr(installer, "_package_root", lambda: tmp_path / "lib" / "python3.12" / "site-packages")
    entry = installer._mcp_entry()
    assert "PYTHONPATH" not in entry["env"]
    assert entry["env"]["PYTHONUTF8"] == "1"


def test_opencode_entry_uses_environment_key(fake_home: Path, tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    from mathematica_skill import installer

    monkeypatch.setattr(installer, "_package_root", lambda: tmp_path / "mathematica-skill")
    entry = installer._mcp_entry(opencode=True)
    assert "env" not in entry
    assert entry["environment"]["PYTHONPATH"] == str(tmp_path / "mathematica-skill")


def test_codex_toml_env_survives_forced_reinstall(fake_home: Path, tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """--force 重写 TOML 段时，Windows 路径里的反斜杠不能被正则替换吃掉（曾经会写成 C:\\Users 这种坏值）。"""
    from mathematica_skill import installer

    root = r"C:\Users\me\mathematica-skill"
    monkeypatch.setattr(installer, "_package_root", lambda: Path(root))
    config = tmp_path / "config.toml"
    config.write_text('model = "x"\n', encoding="utf-8")
    configure_mcp("codex", config_path=config)
    configure_mcp("codex", config_path=config, force=True)
    text = config.read_text(encoding="utf-8")
    assert text.count("[mcp_servers.mathematica-skill]") == 1
    assert 'model = "x"' in text
    assert json.dumps(root) in text


def test_rollback_restores_only_its_own_target(fake_home: Path, tmp_path: Path) -> None:
    """两个目标分别备份、分别回滚，不能互相串档。"""
    first = tmp_path / "a"
    second = tmp_path / "b"
    install([first])
    install([second])
    (first / SKILL_NAME / "SKILL.md").write_text("A-modified", encoding="utf-8")
    install([first])                    # 备份 A 的修改版
    (first / SKILL_NAME / "SKILL.md").write_text("A-broken", encoding="utf-8")
    (second / SKILL_NAME / "SKILL.md").write_text("B-untouched", encoding="utf-8")
    rollback()
    assert (first / SKILL_NAME / "SKILL.md").read_text(encoding="utf-8") == "A-modified"
    assert (second / SKILL_NAME / "SKILL.md").read_text(encoding="utf-8") == "B-untouched"


def test_update_without_force_keeps_foreign_directory(fake_home: Path, tmp_path: Path) -> None:
    target = tmp_path / "skills"
    install([target])
    # 模拟目标被别的技能接管：去掉标记
    (target / SKILL_NAME / ".mathematica-skill.json").unlink()
    with pytest.raises(MskError):
        update()
    assert (target / SKILL_NAME).is_dir()


def test_update_with_force_replaces_foreign_directory(fake_home: Path, tmp_path: Path) -> None:
    target = tmp_path / "skills"
    install([target])
    (target / SKILL_NAME / ".mathematica-skill.json").unlink()
    (target / SKILL_NAME / "SKILL.md").write_text("foreign", encoding="utf-8")
    result = update(force=True)
    assert result["ok"] is True
    assert "mathematica-native" in (target / SKILL_NAME / "SKILL.md").read_text(encoding="utf-8")


def test_claude_desktop_uses_app_support_on_macos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    from mathematica_skill import installer

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(installer.platform, "system", lambda: "Darwin")
    module = importlib.reload(installer)
    monkeypatch.setattr(module, "BACKUPS", home / ".mathematica-skill" / "backups")
    monkeypatch.setattr(module, "MANIFEST", home / ".mathematica-skill" / "install.json")
    expected = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    assert module.claude_desktop_config() == expected
    result = module.configure_mcp("claude-desktop")
    assert result["path"] == str(expected)
    data = json.loads(expected.read_text(encoding="utf-8"))
    assert "mathematica-skill" in data["mcpServers"]


def test_claude_desktop_uses_appdata_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    from mathematica_skill import installer

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setattr(installer.platform, "system", lambda: "Windows")
    module = importlib.reload(installer)
    monkeypatch.setattr(module, "BACKUPS", tmp_path / "state" / "backups")
    monkeypatch.setattr(module, "MANIFEST", tmp_path / "state" / "install.json")
    expected = tmp_path / "roaming" / "Claude" / "claude_desktop_config.json"
    assert module.claude_desktop_config() == expected
