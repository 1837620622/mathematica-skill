"""Native notebook construction and static inspection.

The draft builder produces a valid notebook expression for environments without
Mathematica. On a licensed machine the Wolfram builder in
``wolfram/BuildNotebook.wls`` is authoritative and uses Mathematica's parser to
create Input-cell boxes. A draft is never reported as verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Iterable

from .errors import UnsafePath
from .jsonio import atomic_write_text
from .models import OutputSpec, TaskDocument

_NOTEBOOK_HEADER = "(* Content-type: application/vnd.wolfram.mathematica *)\n\n"
_OPERATORS = [
    "/;", ":=", ":>", "->", ":>", "/.", "//.", "/@", "@@@", "@@", "@*", "/*",
    "&&", "||", "===", "=!=", "==", "!=", "<=", ">=", "<->", "~~", "<>",
    "++", "--", "+=", "-=", "*=", "/=", "^=", "^:=", "/:", "//", "[[", "]]",
    ";;", "&", "#", "@", "%", "!", "?", "/", "^", "+", "-", "*", "=", "<", ">",
]
_TOKEN = re.compile(
    r'"(?:\\.|[^"\\])*"'
    r"|\(\*.*?\*\)"
    r"|[A-Za-z$][A-Za-z0-9$]*"
    r"|\d+(?:\.\d+)?(?:`\d*)?(?:\*\^-?\d+)?"
    r"|\\\[[A-Za-z][A-Za-z0-9]*\]"
    r"|"
    + "|".join(re.escape(op) for op in _OPERATORS)
    + r"|.",
    re.S,
)


def wl_string(value: str) -> str:
    out: list[str] = ['"']
    for char in value:
        if char == "\\":
            out.append("\\\\")
        elif char == '"':
            out.append('\\"')
        elif char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif char == "\t":
            out.append("\\t")
        elif ord(char) < 32:
            # Wolfram Language 的 \[011] 是「名称」形式，控制字符要用 \.xx
            out.append(f"\\.{ord(char):02x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def tokenize_wl(code: str) -> list[str]:
    tokens = [match.group(0) for match in _TOKEN.finditer(code)]
    return tokens or [code]


def boxes_for_code(code: str) -> str:
    tokens = tokenize_wl(code)
    inner = ", ".join(wl_string(token) for token in tokens)
    return f"RowBox[{{{inner}}}]"


_ROWBOX = re.compile(r"RowBox\[\{(.*?)\}\](?=,\s*(?:\"|BoxData|\)|\]))", re.S)
_QUOTED = re.compile(r'"(?:\\.|[^"\\])*"', re.S)


def _unescape_wl(token: str) -> str:
    body = token[1:-1] if token.startswith('"') and token.endswith('"') else token
    out: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        nxt = body[index + 1] if index + 1 < len(body) else ""
        mapping = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}
        if nxt in mapping:
            out.append(mapping[nxt])
            index += 2
        elif nxt == ".":
            # \.xx —— 两位十六进制（控制字符用这个形式）
            code = body[index + 2:index + 4]
            try:
                out.append(chr(int(code, 16)))
            except ValueError:
                out.append("\\." + code)
            index += 4
        elif nxt == ":":
            # \:xxxx —— 四位十六进制 Unicode
            code = body[index + 2:index + 6]
            try:
                out.append(chr(int(code, 16)))
            except ValueError:
                out.append("\\:" + code)
            index += 6
        elif nxt == "[":
            end = body.find("]", index)
            code = body[index + 2:end] if end > 0 else ""
            try:
                out.append(chr(int(code)))
            except ValueError:
                out.append("\\[" + code + "]")
            index = (end + 1) if end > 0 else index + 2
        else:
            out.append(nxt)
            index += 2
    return "".join(out)


def plain_code(text: str) -> str:
    """把草稿里的 RowBox 字符串 token 还原成可读代码，供静态规则扫描。

    正式 Notebook 由 Mathematica 生成，本身就是可读的表达式；草稿是
    token 化的行内框，扫描前必须先拼回去，否则危险调用检测会漏。
    """
    pieces: list[str] = []
    for match in _ROWBOX.finditer(text):
        for token in _QUOTED.finditer(match.group(1)):
            pieces.append(_unescape_wl(token.group(0)))
        pieces.append("\n")
    return "".join(pieces)


def _cell(content: str, style: str) -> str:
    return f"Cell[{content}, {wl_string(style)}]"


def _text_cell(text: str) -> str:
    return f"Cell[TextData[{{{wl_string(text)}}}], \"Text\"]"


@dataclass(slots=True)
class NotebookBuilder:
    title: str
    language: str = "en"
    cells: list[str] = field(default_factory=list)
    window_width: int = 1280
    window_height: int = 900

    def add_title(self, text: str) -> "NotebookBuilder":
        self.cells.append(_cell(wl_string(text), "Title"))
        return self

    def add_section(self, title: str) -> "NotebookBuilder":
        self.cells.append(_cell(wl_string(title), "Section"))
        return self

    def add_subsection(self, title: str) -> "NotebookBuilder":
        self.cells.append(_cell(wl_string(title), "Subsection"))
        return self

    def add_text(self, text: str) -> "NotebookBuilder":
        blocks = [block.strip() for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]
        for block in blocks:
            self.cells.append(_text_cell(block.replace("\n", " ")))
        return self

    def add_code(self, code: str) -> "NotebookBuilder":
        self.cells.append(f"Cell[BoxData[{boxes_for_code(code)}], \"Input\"]")
        return self

    def add_display(self, expression: str, caption: str = "") -> "NotebookBuilder":
        if caption:
            self.cells.append(_text_cell(caption))
        self.cells.append(f"Cell[BoxData[{boxes_for_code(expression)}], \"Input\"]")
        return self

    def render(self) -> str:
        body = ",\n".join(self.cells)
        options = (f"WindowSize -> {{{self.window_width}, {self.window_height}}},\n"
                   "WindowMargins -> {{Automatic, Automatic}, {Automatic, Automatic}},\n"
                   "Magnification -> 1.0,\n"
                   "StyleDefinitions -> \"Default.nb\",\n"
                   "Saveable -> True,\n"
                   "TrackCellChangeTimes -> False")
        return f"{_NOTEBOOK_HEADER}Notebook[{{\n{body}\n}},\n{options}\n]\n"

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, self.render())
        return path


def _localized(document: TaskDocument, en: str, zh: str) -> str:
    return zh if document.effective_language() == "zh" else en


def build_notebook(document: TaskDocument, *, include_assumptions: bool = True) -> NotebookBuilder:
    builder = NotebookBuilder(document.title, document.effective_language())
    builder.add_title(document.title)
    if document.subject:
        builder.add_text(document.subject)
    builder.add_section(_localized(document, "Problem", "题目"))
    for task in document.tasks:
        builder.add_subsection(task.id)
        if task.prompt:
            builder.add_text(task.prompt)
        builder.add_code(task.code)
        if task.notes:
            builder.add_text(task.notes)
        for output in document.outputs:
            if output.task != task.id:
                continue
            caption = output.title or output.filename
            builder.add_display(output.expression, _localized(document, f"Output: {caption}", f"输出：{caption}"))
    if include_assumptions and document.assumptions:
        builder.add_section(_localized(document, "Assumptions", "假设"))
        for assumption in document.assumptions:
            builder.add_text(f"- {assumption}")
    return builder


def build_code_script(document: TaskDocument) -> str:
    lines = [
        "(* Generated by mathematica-skill. Native computation; not a preview. *)",
        f"$msSeed = {int(document.seed)};",
        "SeedRandom[$msSeed];",
        "$HistoryLength = 0;",
        "",
    ]
    for task in document.tasks:
        lines.extend([task.code, "", ""])
    return "\n".join(lines)


def notebook_cell_count(text: str) -> int:
    return len(re.findall(r"(?<![A-Za-z0-9$])Cell\[", text))


AUTO_EXECUTION_MARKERS = ("InitializationCell -> True", "InitializationCell->True",
                          "NotebookDynamicExpression", "Dynamic[", "DynamicModule[",
                          "AutoEvaluate", "NotebookEvaluate")


def has_auto_execution(text: str) -> list[str]:
    haystack = text + "\n" + plain_code(text)
    return [marker for marker in AUTO_EXECUTION_MARKERS if marker in haystack]


def absolute_paths_in(text: str) -> list[str]:
    patterns = [r"/Users/[^\"\\\s]+", r"/home/[^\"\\\s]+",
                r"[A-Za-z]:\\\\?Users\\\\?[^\"\\\s]+", r"/private/var/[^\"\\\s]+", r"/tmp/[^\"\\\s]+"]
    found: list[str] = []
    for pattern in patterns:
        found.extend(re.findall(pattern, text))
        found.extend(re.findall(pattern, plain_code(text)))
    return sorted(set(found))


FORBIDDEN_MARKERS = ("AI-generated", "AI generated", "generated by AI", "ChatGPT", "Claude",
                     "TODO", "FIXME", "PLACEHOLDER", "ai-generated", "mathematica-skill")


def forbidden_markers(text: str) -> list[str]:
    haystack = text + "\n" + plain_code(text)
    return [marker for marker in FORBIDDEN_MARKERS if marker in haystack]


CELL_STYLES = ("Title", "Subtitle", "Section", "Subsection", "Subsubsection",
               "Text", "Input", "Output", "Code", "Program")


def count_cell_styles(text: str) -> dict[str, int]:
    """统计单元样式。

    样式名不一定是 Cell 的最后一个参数（真实保存的 .nb 常带 CellChangeTimes、
    CellTags 等尾随选项），所以只要求「逗号 + 带引号的样式名」出现。
    """
    counts = {style: 0 for style in CELL_STYLES}
    pattern = re.compile(r'Cell\[[^\x00]*?,\s*"(' + "|".join(CELL_STYLES) + r')"')
    for match in pattern.finditer(text):
        counts[match.group(1)] += 1
    return counts


def inspect_notebook(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    styles = count_cell_styles(text)
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "cells": notebook_cell_count(text),
        "style_counts": styles,
        "input_cells": styles["Input"],
        "output_cells": styles["Output"],
        "text_cells": styles["Text"],
        "title_cells": styles["Title"],
        "section_cells": styles["Section"],
        "subsection_cells": styles["Subsection"],
        "auto_execution": has_auto_execution(text),
        "absolute_paths": absolute_paths_in(text),
        "forbidden_markers": forbidden_markers(text),
        "well_formed": text.lstrip().startswith("(* Content-type:") and text.rstrip().endswith("]")
        and "Notebook[{" in text,
    }


def validate_output_name(name: str) -> str:
    if "/" in name or "\\" in name or name in {".", ".."}:
        raise UnsafePath(f"output filename must be flat: {name!r}")
    return name


def output_expressions(document: TaskDocument) -> Iterable[tuple[OutputSpec, str]]:
    for output in document.selected_outputs():
        yield output, output.expression
