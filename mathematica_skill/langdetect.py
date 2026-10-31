"""语言判定：跟随用户给的 Notebook / 题目语言，而不是写死。

规则刻意保守：只有「正文里真的出现足够多的中日韩文字」才判中文。纯公式、
纯英文、空白、只有数字与符号，一律保持英文，避免把英文作业误判成中文。
"""

from __future__ import annotations

import re
from typing import Iterable

CJK_RANGES = (
    (0x3400, 0x4DBF),    # CJK 扩展 A
    (0x4E00, 0x9FFF),    # CJK 基本区
    (0xF900, 0xFAFF),    # 兼容表意文字
    (0x3040, 0x30FF),    # 日文假名
    (0xAC00, 0xD7AF),    # 韩文音节
    (0x20000, 0x2FA1F),  # 扩展 B 及以后
)

# 至少这么多汉字才算「中文材料」：一句短中文标题也算。
MIN_CJK = 8
# 汉字占「文字字符」的比例门槛；英文作业里引用一个中文变量名不该翻转语言。
CJK_RATIO = 0.15

_LATIN = re.compile(r"[A-Za-z]")


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return any(start <= code <= end for start, end in CJK_RANGES)


def cjk_stats(text: str) -> tuple[int, int]:
    """返回 (汉字数, 拉丁字母数)。"""
    cjk = sum(1 for char in text if _is_cjk(char))
    latin = len(_LATIN.findall(text))
    return cjk, latin


def detect_language(text: str, *, default: str = "en") -> str:
    cjk, latin = cjk_stats(text or "")
    if cjk >= MIN_CJK and cjk / max(1, cjk + latin) >= CJK_RATIO:
        return "zh"
    return default


def detect_from_parts(parts: Iterable[str], *, default: str = "en") -> str:
    """把多段材料拼起来判定；调用方按「题目 → 正文 → 备注」的顺序传。"""
    joined = "\n".join(part for part in parts if part)
    return detect_language(joined, default=default)


PLAIN_TEXT_LIMIT = 200_000


def notebook_text(path: str) -> str:
    """粗读 .nb 里的可读文本（Text/Section/Title 单元 + 代码单元里的字符串）。

    这不是 Notebook 解析器，只用来判语言；真正的结构操作交给 Mathematica。
    """
    from pathlib import Path

    target = Path(path)
    try:
        raw = target.read_bytes()
    except OSError:
        return ""
    # .nb 可能是 UTF-8，也可能带 BOM；按 utf-8 解码，失败就忽略坏字节。
    text = raw.decode("utf-8", errors="ignore")
    if len(text) > PLAIN_TEXT_LIMIT:
        text = text[:PLAIN_TEXT_LIMIT]
    # 保留原文：notebook_prose 需要按字符串字面量切分，自己去噪。
    return text


def _quoted_strings(text: str) -> list[str]:
    """粗取 .nb 里的字符串字面量（含 Text 单元与代码里的字符串）。"""
    return re.findall(r'"(?:\\.|[^"\\])*"', text)


def notebook_prose(text: str) -> str:
    """只保留「含中日韩文字」的字符串。

    代码标识符、样式名、转义序列都是拉丁字符，不该把中文材料判成英文；
    反过来，英文作业里出现一个中文变量名也不会被判成中文（少于 MIN_CJK）。
    """
    chunks: list[str] = []
    for literal in _quoted_strings(text):
        body = literal[1:-1]
        if cjk_stats(strip_notebook_noise(body))[0] >= MIN_CJK:
            chunks.append(strip_notebook_noise(body))
    return "\n".join(chunks)


def strip_notebook_noise(text: str) -> str:
    """去掉框符标记、样式名和转义序列，只留下自然语言。"""
    cleaned = re.sub(r"\\\[[A-Za-z][A-Za-z0-9]*\]", " ", text)
    cleaned = re.sub(r"\\.", " ", cleaned)
    cleaned = re.sub(r"\b(?:Cell|BoxData|RowBox|TextData|StyleBox|FormBox|Notebook|"
                     r"Title|Subtitle|Section|Subsection|Subsubsection|Text|Input|Output|"
                     r"StandardForm|TraditionalForm|CellChangeTimes|WindowSize|WindowMargins|"
                     r"StyleDefinitions|Saveable|TrackCellChangeTimes|ShowChatbar|"
                     r"Magnification|Content-type|application/vnd\.wolfram\.mathematica)\b",
                     " ", cleaned)
    cleaned = re.sub(r"[\[\]{},\"]", " ", cleaned)
    return cleaned


def resolve_language(document_language: str, *materials: str) -> str:
    """`auto` 时从材料推断；显式语言永远优先。"""
    if document_language and document_language != "auto":
        return document_language
    return detect_from_parts(materials) if any(materials) else "en"
