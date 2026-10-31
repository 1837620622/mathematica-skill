"""任务模型与 schema 校验。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mathematica_skill.errors import InvalidTask
from mathematica_skill.models import CheckSpec, OutputSpec, TaskDocument, example_document


def test_example_document_round_trips() -> None:
    document = TaskDocument.from_dict(example_document())
    assert document.title == "Sine and its integral"
    assert [task.id for task in document.tasks] == ["plot_sine"]
    assert document.selected_outputs()[0].filename == "sine.png"
    again = TaskDocument.from_dict(document.to_dict())
    assert again.to_dict() == document.to_dict()


def test_load_accepts_utf8_bom(tmp_path: Path, task_payload: dict) -> None:
    path = tmp_path / "bom.json"
    path.write_text(json.dumps(task_payload), encoding="utf-8-sig")
    document = TaskDocument.load(path)
    assert document.seed == 7
    assert document.path == path.resolve()


def test_unknown_output_reference_is_rejected(task_payload: dict) -> None:
    task_payload["outputs"][0]["task"] = "nope"
    with pytest.raises(InvalidTask) as excinfo:
        TaskDocument.from_dict(task_payload)
    assert "OUTPUT" in str(excinfo.value.details) or "reference" in json.dumps(excinfo.value.details)


def test_duplicate_output_filename_is_rejected(task_payload: dict) -> None:
    duplicate = dict(task_payload["outputs"][0], id="fig2")
    task_payload["outputs"].append(duplicate)
    with pytest.raises(InvalidTask):
        TaskDocument.from_dict(task_payload)


def test_duplicate_check_ids_are_rejected(task_payload: dict) -> None:
    task_payload["tasks"].append({
        "id": "second", "prompt": "x", "code": "msOther = 3;",
        "checks": [{"id": "answer_value", "kind": "numeric", "expression": "msOther", "expected": 3.0}],
    })
    with pytest.raises(InvalidTask):
        TaskDocument.from_dict(task_payload)


def test_absolute_source_path_is_rejected(task_payload: dict) -> None:
    task_payload["sources"] = ["/etc/passwd"]
    with pytest.raises(InvalidTask):
        TaskDocument.from_dict(task_payload)


def test_parent_traversal_is_rejected(task_payload: dict) -> None:
    task_payload["sources"] = ["../secret.csv"]
    with pytest.raises(InvalidTask):
        TaskDocument.from_dict(task_payload)


def test_output_filename_cannot_contain_directories(task_payload: dict) -> None:
    task_payload["outputs"][0]["filename"] = "sub/answer.png"
    with pytest.raises(InvalidTask):
        TaskDocument.from_dict(task_payload)


def test_unicode_output_filename_is_allowed(task_payload: dict) -> None:
    task_payload["outputs"][0]["filename"] = "正弦曲线.png"
    document = TaskDocument.from_dict(task_payload)
    assert document.outputs[0].filename == "正弦曲线.png"


def test_windows_reserved_name_is_rejected(task_payload: dict) -> None:
    task_payload["outputs"][0]["filename"] = "CON.png"
    with pytest.raises(InvalidTask):
        TaskDocument.from_dict(task_payload)


def test_numeric_check_requires_number() -> None:
    errors: list[str] = []
    CheckSpec.from_dict({"id": "c", "kind": "numeric", "expression": "1", "expected": "1"}, "t", 0, errors)
    assert any("numeric" in message for message in errors)


def test_boolean_check_requires_bool() -> None:
    errors: list[str] = []
    CheckSpec.from_dict({"id": "c", "kind": "boolean", "expression": "True", "expected": 1}, "t", 0, errors)
    assert any("boolean" in message for message in errors)


def test_range_check_requires_pair() -> None:
    errors: list[str] = []
    CheckSpec.from_dict({"id": "c", "kind": "range", "expression": "x", "expected": [1]}, "t", 0, errors)
    assert any("min" in message for message in errors)


def test_output_size_bounds_are_enforced() -> None:
    errors: list[str] = []
    OutputSpec.from_dict({"id": "o", "task": "t", "kind": "figure", "filename": "a.png",
                          "expression": "p", "width": 99999}, 0, {"t"}, errors)
    assert any("width" in message for message in errors)


def test_negative_tolerance_is_reported() -> None:
    errors: list[str] = []
    CheckSpec.from_dict({"id": "c", "kind": "numeric", "expression": "1", "expected": 1.0, "abs_tol": -1},
                        "t", 0, errors)
    assert any("abs_tol" in message for message in errors)


def test_delivery_include_must_reference_known_output(task_payload: dict) -> None:
    task_payload["delivery"]["include"] = ["ghost"]
    with pytest.raises(InvalidTask):
        TaskDocument.from_dict(task_payload)
