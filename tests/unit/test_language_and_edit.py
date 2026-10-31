"""语言跟随与 Notebook 编辑（无 Mathematica 时可验证的部分）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mathematica_skill.errors import InvalidTask, MskError
from mathematica_skill.langdetect import (
    cjk_stats,
    detect_language,
    notebook_text,
    resolve_language,
    strip_notebook_noise,
)
from mathematica_skill.models import TaskDocument, example_document
from mathematica_skill.notebook import build_notebook
from mathematica_skill.notebook_edit import NotebookEdit, _verify_edit, load_edits


def test_english_text_stays_english() -> None:
    assert detect_language("Plot sin(x) on [-pi, pi] and compute the integral.") == "en"


def test_chinese_prompt_detected() -> None:
    assert detect_language("请画出正弦函数在闭区间上的图像，并计算它在零到圆周率上的定积分。") == "zh"


def test_short_chinese_title_is_enough() -> None:
    assert detect_language("第三次作业：非线性动力学") == "zh"


def test_formula_only_text_is_not_chinese() -> None:
    assert detect_language("Integrate[Sin[x], {x, 0, Pi}] -> 2") == "en"


def test_single_chinese_variable_does_not_flip_language() -> None:
    text = "Plot the series stored in variable 位移 against time. " * 6
    assert detect_language(text) == "en"


def test_cjk_stats_counts_both() -> None:
    cjk, latin = cjk_stats("中文 abc 中文")
    assert cjk == 4
    assert latin == 3


def test_resolve_language_prefers_explicit() -> None:
    assert resolve_language("en", "中文材料" * 10) == "en"
    assert resolve_language("auto", "中文材料" * 10) == "zh"


def test_strip_notebook_noise_removes_boxes() -> None:
    raw = 'Cell[BoxData[RowBox[{"Plot", "[", "Sin"}]], "Input"]'
    cleaned = strip_notebook_noise(raw)
    assert "RowBox" not in cleaned and "Cell" not in cleaned
    assert "Plot" in cleaned


def test_notebook_prose_reads_utf8(tmp_path: Path) -> None:
    from mathematica_skill.langdetect import notebook_prose

    document = TaskDocument.from_dict(example_document())
    document.tasks[0].prompt = "这是中文题目，需要画图并计算积分。"
    path = build_notebook(document).write(tmp_path / "zh.nb")
    prose = notebook_prose(notebook_text(path))
    assert "中文题目" in prose
    assert detect_language(prose) == "zh"


def test_notebook_prose_ignores_english_notebook(tmp_path: Path) -> None:
    from mathematica_skill.langdetect import notebook_prose

    document = TaskDocument.from_dict(example_document())
    path = build_notebook(document).write(tmp_path / "en.nb")
    assert notebook_prose(notebook_text(path)) == ""


def test_auto_language_follows_task_material() -> None:
    payload = example_document()
    payload["language"] = "auto"
    payload["tasks"][0]["prompt"] = "画出图像并给出精确结果，说明所用参数。"
    assert TaskDocument.from_dict(payload).effective_language() == "zh"


def test_auto_language_follows_source_notebook(tmp_path: Path) -> None:
    payload = example_document()
    payload["language"] = "auto"
    reference = TaskDocument.from_dict(example_document())
    reference.tasks[0].prompt = "第一题：求特征值，第二题：画出相图，第三题：解释结果。"
    build_notebook(reference).write(tmp_path / "ref.nb")
    payload["sources"] = ["ref.nb"]
    path = tmp_path / "task.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = TaskDocument.load(path)
    assert loaded.effective_language() == "zh"


def test_auto_language_without_material_defaults_to_english(tmp_path: Path) -> None:
    payload = example_document()
    payload["language"] = "auto"
    payload["tasks"][0]["prompt"] = ""
    payload["subject"] = ""
    payload["title"] = "Task"
    path = tmp_path / "task.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert TaskDocument.load(path).effective_language() == "en"


def test_unknown_language_rejected() -> None:
    payload = example_document()
    payload["language"] = "fr"
    with pytest.raises(InvalidTask):
        TaskDocument.from_dict(payload)


def test_draft_notebook_headings_follow_language() -> None:
    payload = example_document()
    payload["language"] = "zh"
    builder = build_notebook(TaskDocument.from_dict(payload))
    text = builder.render()
    assert "题目" in text and "假设" in text


def _edit_doc(**overrides) -> dict:
    payload = {"operations": [{"op": "append_input", "content": "x = 1;"}]}
    payload.update(overrides)
    return payload


def test_edit_requires_something_to_do() -> None:
    with pytest.raises(InvalidTask):
        NotebookEdit.from_dict({"operations": []})


def test_edit_rejects_unknown_op() -> None:
    with pytest.raises(InvalidTask):
        NotebookEdit.from_dict({"operations": [{"op": "replace_all", "content": "x"}]})


def test_edit_requires_index_for_index_ops() -> None:
    with pytest.raises(InvalidTask):
        NotebookEdit.from_dict({"operations": [{"op": "replace_cell", "content": "x = 1;"}]})


def test_edit_requires_content_for_content_ops() -> None:
    with pytest.raises(InvalidTask):
        NotebookEdit.from_dict({"operations": [{"op": "append_input", "content": "  "}]})


def test_edit_rejects_bad_style() -> None:
    with pytest.raises(InvalidTask):
        NotebookEdit.from_dict({"operations": [{"op": "insert_after", "index": 1,
                                               "content": "x", "style": "Banner"}]})


def test_edit_round_trips_through_dict() -> None:
    edit = NotebookEdit.from_dict(_edit_doc(language="zh", title="作业"))
    assert edit.to_dict()["language"] == "zh"
    assert edit.to_dict()["operations"][0]["op"] == "append_input"


def test_load_edits_from_file(tmp_path: Path) -> None:
    path = tmp_path / "edits.json"
    path.write_text(json.dumps(_edit_doc(language="en")), encoding="utf-8")
    assert load_edits(path).language == "en"


def test_structural_check_flags_lost_input_cells() -> None:
    before = {"cells": 10, "input_cells": 4, "absolute_paths": [], "forbidden_markers": []}
    after = {"cells": 10, "input_cells": 0, "absolute_paths": [], "forbidden_markers": []}
    problems = _verify_edit(before, after, NotebookEdit.from_dict(_edit_doc()))
    assert any("Input" in item for item in problems)


def test_structural_check_flags_new_absolute_paths() -> None:
    before = {"cells": 10, "input_cells": 2, "absolute_paths": [], "forbidden_markers": []}
    after = {"cells": 11, "input_cells": 3, "absolute_paths": ["/Users/x/a.csv"],
             "forbidden_markers": []}
    problems = _verify_edit(before, after, NotebookEdit.from_dict(_edit_doc()))
    assert any("absolute" in item for item in problems)


def test_structural_check_allows_planned_delete() -> None:
    before = {"cells": 10, "input_cells": 2, "absolute_paths": [], "forbidden_markers": []}
    after = {"cells": 9, "input_cells": 2, "absolute_paths": [], "forbidden_markers": []}
    edit = NotebookEdit.from_dict({"operations": [{"op": "delete_cell", "index": 2}]})
    assert _verify_edit(before, after, edit) == []


def test_run_edit_refuses_in_place_without_flag(tmp_path: Path) -> None:
    from mathematica_skill.notebook_edit import run_edit

    document = TaskDocument.from_dict(example_document())
    path = build_notebook(document).write(tmp_path / "a.nb")

    class _Adapter:
        def edit_notebook(self, *args, **kwargs):  # pragma: no cover - never reached
            raise AssertionError("adapter must not run when the source would be overwritten")

    with pytest.raises(MskError) as excinfo:
        run_edit(_Adapter(), path, path, NotebookEdit.from_dict(_edit_doc()))
    assert excinfo.value.code == "UNSAFE_PATH"


def test_run_edit_defaults_to_sibling_edited_copy(tmp_path: Path) -> None:
    """不传 --out 时写同目录 -edited.nb，绝不碰源文件。"""
    from mathematica_skill.notebook_edit import plan_output

    source = tmp_path / "作业一.nb"
    assert plan_output(source).name == "作业一-edited.nb"
    assert plan_output(source, suffix="-v2").name == "作业一-v2.nb"
    assert plan_output(source).parent == source.parent


def test_run_edit_rejects_non_utf8_source(tmp_path: Path) -> None:
    from mathematica_skill.notebook_edit import run_edit

    path = tmp_path / "bad.nb"
    path.write_bytes(b"(* Content-type *) \xff\xfe not utf8")

    class _Adapter:
        def edit_notebook(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("adapter must not run on an undecodable file")

    with pytest.raises(MskError) as excinfo:
        run_edit(_Adapter(), path, tmp_path / "out.nb", NotebookEdit.from_dict(_edit_doc()))
    assert excinfo.value.code == "ENCODING_MISMATCH"


def test_backup_name_is_adjacent(tmp_path: Path) -> None:
    from mathematica_skill.notebook_edit import backup_notebook

    source = tmp_path / "作业一.nb"
    source.write_text("nb", encoding="utf-8")
    backup = backup_notebook(source)
    assert backup.parent == source.parent
    assert backup.name.startswith("作业一.nb.") and backup.name.endswith(".bak")
    assert backup.read_text(encoding="utf-8") == "nb"
