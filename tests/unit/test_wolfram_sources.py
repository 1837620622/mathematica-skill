"""WL 脚本的静态约束：加载文件时必须显式指定 UTF-8。

$CharacterEncoding 的默认值随平台变化，Windows 上可能是本地代码页；Python 写出的代码文件和
MathematicaSkill.wl（含中文注释）都是 UTF-8，不指定编码就可能读坏中文。Get 文档也写明默认值
「可能产生错误和不同的结果」。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WOLFRAM = ROOT / "wolfram"
FILE_LOAD = re.compile(r"Get\[(?:codePath|FileNameJoin)")
UTF8_OPTION = 'CharacterEncoding -> "UTF-8"'
COMMENT = re.compile(r"\(\*.*?\*\)", re.S)


def test_every_file_load_pins_utf8() -> None:
    checked = 0
    offenders: list[str] = []
    for path in sorted(WOLFRAM.glob("*.wl*")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if FILE_LOAD.search(line):
                checked += 1
                if UTF8_OPTION not in line:
                    offenders.append(f"{path.name}:{number}")
    assert offenders == []
    # 六个脚本的库加载 + 三处代码加载；少于这个数说明正则没有覆盖到，测试会空跑通过。
    assert checked >= 9


def test_entry_scripts_are_ascii_outside_comments() -> None:
    """入口脚本的代码只能是 ASCII：字符串里的中文写成 \\:xxxx 转义，不依赖 wolframscript 的文件编码。

    注释里可以有中文，它不会被求值。
    """
    offenders = []
    for path in sorted(WOLFRAM.glob("*.wls")):
        code = COMMENT.sub("", path.read_text(encoding="utf-8"))
        if any(ord(char) > 127 for char in code):
            offenders.append(path.name)
    assert offenders == []
