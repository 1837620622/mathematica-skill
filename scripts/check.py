#!/usr/bin/env python3
"""项目自检：编译、未使用导入、行宽、WL 括号平衡、单元测试。

只做静态与纯 Python 检查，不需要 Mathematica。需要许可证的验证在 tests/native。
"""

from __future__ import annotations

import ast
import compileall
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mathematica_skill.wlsyntax import check_syntax  # noqa: E402

MAX_LINE = 120
SKIP_DIRS = {".git", "work", "_validation", "__pycache__", ".pytest_cache", "node_modules"}


def python_files() -> list[Path]:
    return sorted(p for p in ROOT.rglob("*.py") if not SKIP_DIRS & set(p.relative_to(ROOT).parts))


def check_compile(failures: list[str]) -> None:
    ok = compileall.compile_dir(str(ROOT / "mathematica_skill"), quiet=2, force=True)
    if not ok:
        failures.append("compileall: 有文件无法编译")


def check_unused_imports(failures: list[str]) -> None:
    for path in python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: dict[str, int] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported[alias.asname or alias.name.split(".")[0]] = node.lineno
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported[alias.asname or alias.name] = node.lineno
        used: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                base = node
                while isinstance(base, ast.Attribute):
                    base = base.value
                if isinstance(base, ast.Name):
                    used.add(base.id)
        for name, line in imported.items():
            if name in {"annotations", "*"} or name in used:
                continue
            failures.append(f"{path.relative_to(ROOT)}:{line}: 未使用的导入 {name}")


def check_line_length(failures: list[str]) -> None:
    for path in python_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if len(line) > MAX_LINE:
                failures.append(f"{path.relative_to(ROOT)}:{number}: 行宽 {len(line)} > {MAX_LINE}")


def check_trailing_whitespace(failures: list[str]) -> None:
    for path in python_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.rstrip() != line:
                failures.append(f"{path.relative_to(ROOT)}:{number}: 行尾空白")


def check_wolfram(failures: list[str]) -> None:
    files = sorted([*(ROOT / "wolfram").glob("*.wl"), *(ROOT / "wolfram").glob("*.wls")])
    if not files:
        failures.append("wolfram/: 没有找到 .wl/.wls")
        return
    for path in files:
        report = check_syntax(path.read_text(encoding="utf-8"))
        if not report.balanced:
            failures.append(f"{path.relative_to(ROOT)}: 括号不平衡 {report.errors[:3]}")


def check_skill_frontmatter(failures: list[str]) -> None:
    path = ROOT / "skills" / "mathematica-native" / "SKILL.md"
    if not path.is_file():
        failures.append("skills/mathematica-native/SKILL.md 缺失")
        return
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        failures.append("SKILL.md 缺少 frontmatter")
        return
    header = text.split("---\n")[1]
    for key in ("name:", "description:", "compatibility:"):
        if key not in header:
            failures.append(f"SKILL.md frontmatter 缺少 {key}")
    body = text.split("---\n", 2)[2]
    for ref in sorted(set(part.split(")")[0] for part in body.split("references/")[1:])):
        target = ROOT / "skills" / "mathematica-native" / "references" / ref.split()[0].strip("`")
        if not target.suffix:
            continue
        if not target.is_file():
            failures.append(f"SKILL.md 引用的 references/{target.name} 不存在")


def check_examples(failures: list[str]) -> None:
    import json

    from mathematica_skill.models import TaskDocument
    from mathematica_skill.notebook_edit import NotebookEdit

    good = sorted((ROOT / "examples").glob("*.json"))
    if not good:
        failures.append("examples/: 没有示例")
    for path in good:
        if path.name.startswith("bad-"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and "operations" in payload:
                NotebookEdit.from_dict(payload)      # 编辑指令示例
            else:
                TaskDocument.load(path)              # 任务文档示例
        except Exception as exc:  # noqa: BLE001 - 示例必须能被 schema 接受
            failures.append(f"{path.relative_to(ROOT)}: {exc}")


def run_tests(failures: list[str]) -> None:
    result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True)
    tail = (result.stdout or "").strip().splitlines()[-3:]
    print("pytest:", " | ".join(tail))
    if result.returncode != 0:
        failures.append("pytest 失败")


def main() -> int:
    failures: list[str] = []
    check_compile(failures)
    check_unused_imports(failures)
    check_line_length(failures)
    check_trailing_whitespace(failures)
    check_wolfram(failures)
    check_skill_frontmatter(failures)
    check_examples(failures)
    run_tests(failures)
    if failures:
        print("\n发现 %d 个问题：" % len(failures))
        for item in failures:
            print(" -", item)
        return 1
    print("\n全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
