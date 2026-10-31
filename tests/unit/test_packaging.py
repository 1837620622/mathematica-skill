"""打包与入口：npm 布局、版本一致、Skill 可被发现。

这些是「装完就能干活」的契约：缺一个目录，npm 安装后就会在运行期炸。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _package() -> dict:
    return json.loads((ROOT / "package.json").read_text(encoding="utf-8"))


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.M)
    assert match, "pyproject.toml 缺少 version"
    return match.group(1)


def test_versions_match_across_manifests() -> None:
    from mathematica_skill import __version__

    assert _package()["version"] == _pyproject_version() == __version__


def test_bin_entry_exists_with_shebang() -> None:
    bins = _package()["bin"]
    assert bins["mathematica-skill"] == "bin/mathematica-skill.js"
    target = ROOT / bins["mathematica-skill"]
    assert target.is_file()
    assert target.read_text(encoding="utf-8").startswith("#!/usr/bin/env node")


def test_files_whitelist_covers_runtime() -> None:
    listed = {item.rstrip("/") for item in _package()["files"]}
    for required in ("bin", "mathematica_skill", "wolfram", "skills", "README.md", "LICENSE"):
        assert required in listed, f"npm files 未包含 {required}"


@pytest.mark.parametrize("relative", ["mathematica_skill/cli.py", "wolfram/BuildNotebook.wls",
                                      "wolfram/EditNotebook.wls", "skills/mathematica-native/SKILL.md",
                                      "skills/mathematica-native/references/workflow.md"])
def test_runtime_assets_exist(relative: str) -> None:
    assert (ROOT / relative).is_file()


def test_skill_dir_is_discoverable() -> None:
    from mathematica_skill.paths import skill_dir, wolfram_dir

    skill = skill_dir()
    assert (skill / "SKILL.md").is_file()
    assert (skill / "references" / "workflow.md").is_file()
    assert (wolfram_dir() / "MathematicaSkill.wl").is_file()


def test_wrapper_sets_pythonpath() -> None:
    source = (ROOT / "bin" / "mathematica-skill.js").read_text(encoding="utf-8")
    assert "PYTHONPATH" in source
    assert "mathematica_skill.cli" in source
    assert "MATHEMATICA_SKILL_PYTHON" in source


def test_wrapper_checks_minimum_python() -> None:
    source = (ROOT / "bin" / "mathematica-skill.js").read_text(encoding="utf-8")
    assert "MIN_PYTHON" in source
    assert "3, 10" in source.replace("[", "").replace("]", "")


def test_installed_layout_resolves_share_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """pip 安装时 wolfram/ 与 skills/ 在 sys.prefix/share 下。"""
    from mathematica_skill import paths

    prefix = tmp_path / "venv"
    share = prefix / "share" / "mathematica-skill"
    (share / "wolfram").mkdir(parents=True)
    (share / "wolfram" / "MathematicaSkill.wl").write_text("(* x *)", encoding="utf-8")
    (share / "skills" / "mathematica-native").mkdir(parents=True)
    (share / "skills" / "mathematica-native" / "SKILL.md").write_text("---", encoding="utf-8")

    monkeypatch.setattr(paths.sys, "prefix", str(prefix), raising=False)
    monkeypatch.setattr(paths, "repo_root", lambda: tmp_path / "no-repo")
    monkeypatch.setattr(paths, "package_root", lambda: tmp_path / "no-pkg")

    assert paths.wolfram_dir() == share / "wolfram"
    assert paths.skill_dir() == share / "skills" / "mathematica-native"
