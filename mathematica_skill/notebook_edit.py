"""在既有 .nb 上做定点修改，并守住编码与结构。

三条硬规则：

1. **不原地改源文件**：默认写到新路径；要覆盖必须先备份成 `.nb.<stamp>.bak`。
2. **不乱码**：写入后重新解码校验，出现替换字符（U+FFFD）或用户文本读不回来就判失败。
3. **不乱结构**：单元总数不能减少（除显式 delete），Input 单元数不能因为替换而消失。

真正的编辑由 `wolfram/EditNotebook.wls` 在 Mathematica 里完成；Python 只校验操作、
传参、并对结果做独立复核。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import InvalidTask, MskError, UnsafePath
from .notebook import inspect_notebook
from .paths import ensure_dir, safe_filename, slugify

OPERATIONS = {
    "replace_cell", "delete_cell", "insert_after",
    "append_input", "append_text", "append_section", "append_subsection",
}
CELL_STYLES = {"Input", "Text", "Section", "Subsection", "Subsubsection", "Title"}
CONTENT_OPS = {"replace_cell", "insert_after", "append_input", "append_text",
               "append_section", "append_subsection"}
INDEX_OPS = {"replace_cell", "delete_cell", "insert_after"}


@dataclass(slots=True)
class EditOperation:
    op: str
    index: int = 0
    content: str = ""
    style: str = "Input"

    @classmethod
    def from_dict(cls, data: Any, position: int) -> "EditOperation":
        if not isinstance(data, dict):
            raise InvalidTask(f"operations[{position}] must be an object")
        op = data.get("op")
        if op not in OPERATIONS:
            raise InvalidTask(f"operations[{position}].op must be one of {sorted(OPERATIONS)}")
        index = data.get("index", 0)
        content = data.get("content", data.get("text", ""))
        style = data.get("style", "Input")
        if op in INDEX_OPS:
            if not isinstance(index, int) or isinstance(index, bool) or index < 1:
                raise InvalidTask(f"operations[{position}].index must be an integer >= 1")
        if op in CONTENT_OPS:
            if not isinstance(content, str) or not content.strip():
                raise InvalidTask(f"operations[{position}].content is required")
            if len(content) > 200_000:
                raise InvalidTask(f"operations[{position}].content is too long")
        if op in {"insert_after"} and style not in CELL_STYLES:
            raise InvalidTask(f"operations[{position}].style must be one of {sorted(CELL_STYLES)}")
        return cls(op=str(op), index=int(index or 0), content=str(content or ""), style=str(style))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"op": self.op, "content": self.content}
        if self.op in INDEX_OPS:
            payload["index"] = self.index
        if self.op == "insert_after":
            payload["style"] = self.style
        return payload


@dataclass(slots=True)
class NotebookEdit:
    language: str = ""
    title: str = ""
    operations: list[EditOperation] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Any) -> "NotebookEdit":
        if not isinstance(data, dict):
            raise InvalidTask("edits must be a JSON object")
        language = data.get("language", "")
        if language and language not in {"en", "zh"}:
            raise InvalidTask("language must be 'en' or 'zh' when provided")
        title = data.get("title", "")
        if title and not isinstance(title, str):
            raise InvalidTask("title must be a string")
        operations_data = data.get("operations", [])
        if not isinstance(operations_data, list):
            raise InvalidTask("operations must be a list")
        operations = [EditOperation.from_dict(item, index) for index, item in enumerate(operations_data)]
        if not operations and not language and not title:
            raise InvalidTask("edit requests at least one operation, title or language")
        return cls(language=str(language or ""), title=str(title or ""), operations=operations)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"operations": [item.to_dict() for item in self.operations]}
        if self.language:
            payload["language"] = self.language
        if self.title:
            payload["title"] = self.title
        return payload


def load_edits(path: str | Path) -> NotebookEdit:
    from .jsonio import read_json

    return NotebookEdit.from_dict(read_json(path))


def _assert_utf8(path: Path) -> str:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MskError("ENCODING_MISMATCH",
                       f"notebook is not valid UTF-8: {path}", details={"error": str(exc)}) from exc
    if "\ufffd" in text:
        raise MskError("ENCODING_MISMATCH",
                       f"notebook contains Unicode replacement characters: {path}")
    return text


def _verify_edit(before: dict[str, Any], after: dict[str, Any], edit: NotebookEdit) -> list[str]:
    problems: list[str] = []
    deletes = sum(1 for item in edit.operations if item.op == "delete_cell")
    if after["cells"] < before["cells"] - deletes:
        problems.append(f"cell count dropped: {before['cells']} -> {after['cells']}")
    if before["input_cells"] > 0 and after["input_cells"] == 0:
        problems.append("all Input cells disappeared")
    if after["absolute_paths"] and not before["absolute_paths"]:
        problems.append(f"edit introduced absolute paths: {after['absolute_paths'][:3]}")
    if after["forbidden_markers"] and not before["forbidden_markers"]:
        problems.append(f"edit introduced development markers: {after['forbidden_markers']}")
    return problems


def plan_output(source: Path, *, suffix: str = "-edited") -> Path:
    """默认输出路径：与源文件同目录的 `<name><suffix>.nb`，保留中文文件名。"""
    try:
        name = safe_filename(f"{source.stem}{suffix}.nb")
    except UnsafePath:
        name = f"{slugify(source.stem, 'notebook')}{suffix}.nb"
    return source.parent / name


def run_edit(adapter: Any, source: str | Path, out: str | Path | None, edit: NotebookEdit,
             *, allow_in_place: bool = False, timeout: float = 240.0,
             work_dir: str | Path | None = None) -> dict[str, Any]:
    """调用原生编辑器改 Notebook，然后做独立的编码与结构复核。"""
    from .jsonio import write_json

    origin = Path(source).expanduser().resolve()
    if not origin.is_file():
        raise MskError("NOTEBOOK_OPEN_FAILED", f"notebook not found: {origin}")
    _assert_utf8(origin)

    destination = Path(out).expanduser().resolve() if out else plan_output(origin)
    in_place = destination == origin
    if in_place and not allow_in_place:
        raise MskError("UNSAFE_PATH",
                       "refusing to overwrite the source notebook; pass --in-place or a new --out path")

    work = ensure_dir(Path(work_dir).expanduser().resolve() if work_dir
                      else origin.parent / "_edit")
    edits_json = write_json(work / "edits.json", edit.to_dict())
    result_json = work / "edit-result.json"
    target = work / "edited.nb" if in_place else destination

    before = inspect_notebook(origin)
    run = adapter.edit_notebook(origin, edits_json, target, result_json, timeout=timeout)
    payload = run.payload or {}
    if not run.ok:
        raise MskError(run.error_code or "EVALUATION_FAILED",
                       run.message or "native notebook edit failed",
                       details={"payload": payload, "stderr": run.stderr[-4000:]})

    _assert_utf8(target)
    after = inspect_notebook(target)
    problems = _verify_edit(before, after, edit)
    if problems:
        raise MskError("EVALUATION_FAILED", "edited notebook failed the structural check",
                       details={"problems": problems, "before": before, "after": after})

    backup = None
    if in_place:
        backup = backup_notebook(origin)
        shutil.move(str(target), str(origin))
        after = inspect_notebook(origin)

    return {
        "ok": True,
        "source": str(origin),
        "notebook": str(origin if in_place else target),
        "in_place": in_place,
        "backup": str(backup) if backup else "",
        "before": before,
        "after": after,
        "applied": payload.get("applied", []),
        "encoding_ok": payload.get("encoding_ok", True),
        "messages": payload.get("messages", []),
        "result": payload,
    }


def backup_notebook(source: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = source.with_name(f"{source.name}.{stamp}.bak")
    shutil.copy2(source, target)
    return target
