"""针对已修复缺陷的回归测试。

每一条都对应一次真实审阅发现的 bug：任务 JSON 位置、输出表达式绕过策略、
check 数量不符、自动 check id、Windows 版本排序、16 位 PNG、回滚串档等。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mathematica_skill import workflow
from mathematica_skill.discovery import _version_key
from mathematica_skill.models import TaskDocument, example_document
from mathematica_skill.notebook import inspect_notebook, wl_string
from mathematica_skill.plotqa import read_png
from mathematica_skill.validation import ValidationReport, validate_checks
from mathematica_skill.workflow import RunOptions, lint_task, run_task
from mathematica_skill.errors import InvalidTask


def _no_engine(**_kwargs):
    from mathematica_skill.discovery import EngineReport

    return EngineReport(platform_system="t", platform_release="0", machine="x", python="3",
                        engine_usable=False)


def test_sources_are_reachable_from_task_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                   task_payload: dict) -> None:
    """sources 与 task.json 必须在同一目录，否则 WL 里 Import["data.csv"] 找不到。"""
    (tmp_path / "data.csv").write_text("t,v\n0,1\n", encoding="utf-8")
    task_payload["sources"] = ["data.csv"]
    path = tmp_path / "task.json"
    path.write_text(json.dumps(task_payload), encoding="utf-8")
    monkeypatch.setattr(workflow, "detect", _no_engine)
    state = run_task(path, RunOptions(work_root=tmp_path / "work", allow_draft=True))
    run_dir = Path(state["run_dir"])
    assert (run_dir / "input" / "data.csv").is_file()
    assert (run_dir / "input" / "task.json").is_file()
    assert not (run_dir / "task.json").exists()


def test_output_expression_is_policy_checked(tmp_path: Path, task_payload: dict) -> None:
    task_payload["tasks"][0]["code"] = "x = 1;"
    task_payload["outputs"][0]["expression"] = 'RunProcess[{"rm", "-rf", "/"}]; x'
    path = tmp_path / "task.json"
    path.write_text(json.dumps(task_payload), encoding="utf-8")
    payload = lint_task(path)
    assert payload["ok"] is False
    assert any(item["code"] == "POLICY_BLOCKED" for item in payload["errors"])


def test_output_expression_syntax_is_checked(tmp_path: Path, task_payload: dict) -> None:
    task_payload["outputs"][0]["expression"] = "Plot[Sin[x], {x, 0, 1}"
    path = tmp_path / "task.json"
    path.write_text(json.dumps(task_payload), encoding="utf-8")
    assert any(item["code"] == "WL_SYNTAX" for item in lint_task(path)["errors"])


def test_check_count_mismatch_blocks() -> None:
    report = ValidationReport()
    validate_checks({"ok": True, "total": 2, "passed": 2,
                     "checks": [{"id": "a", "passed": True}, {"id": "b", "passed": True}]},
                    report=report, expected_total=3)
    assert any(finding.code == "CHECKS_INCOMPLETE" for finding in report.errors())


def test_check_record_must_be_object() -> None:
    report = ValidationReport()
    validate_checks({"ok": True, "total": 1, "passed": 1, "checks": ["oops"]}, report=report)
    assert any(finding.code == "CHECK_MALFORMED" for finding in report.errors())


def test_generated_check_id_is_valid(task_payload: dict) -> None:
    task_payload["tasks"][0]["checks"] = [
        {"kind": "numeric", "expression": "1", "expected": 1.0},
    ]
    document = TaskDocument.from_dict(task_payload)
    assert document.tasks[0].checks[0].id == "answer-check1"
    assert document.tasks[0].checks[0].id.startswith("answer")


def test_windows_version_key_prefers_new_major() -> None:
    old = Path(r"C:\Program Files (x86)\Wolfram Research\Mathematica\13.0\WolframKernel.exe")
    new = Path(r"C:\Program Files\Wolfram Research\Mathematica\14.0\WolframKernel.exe")
    assert _version_key(new) > _version_key(old)
    assert _version_key(Path("/Applications/Mathematica 14.0.app/Contents/MacOS/WolframKernel")) == (14, 0)


def test_version_key_without_version_is_lowest() -> None:
    assert _version_key(Path("/usr/local/bin/wolframscript")) == (0, 0)


def test_wl_string_control_characters_use_hex_escape() -> None:
    encoded = wl_string("a\x0bb\x07c")
    assert "\\[011]" not in encoded
    assert "\\.0b" in encoded and "\\.07" in encoded


def test_notebook_input_cells_detected_with_trailing_options(tmp_path: Path) -> None:
    """真实保存的 .nb 单元常带尾随选项，样式名不一定在最后。"""
    text = (
        '(* Content-type: application/vnd.wolfram.mathematica *)\n\n'
        'Notebook[{\n'
        'Cell["Title", "Title"],\n'
        'Cell[BoxData[RowBox[{"1+1"}]], "Input", CellChangeTimes->{{3.9, 4.0}}],\n'
        'Cell[BoxData["2"], "Output", CellTags->{"a"}]\n'
        '}, WindowSize->{600, 400}]\n'
    )
    path = tmp_path / "saved.nb"
    path.write_text(text, encoding="utf-8")
    info = inspect_notebook(path)
    assert info["input_cells"] == 1
    assert info["output_cells"] == 1
    assert info["title_cells"] == 1


def test_16bit_png_matches_8bit_statistics(tmp_path: Path) -> None:
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    def make(name: str, depth: int) -> Path:
        w = h = 64
        raw = bytearray()
        for y in range(h):
            raw.append(0)
            for x in range(w):
                value = 0 if (x // 4) % 2 else 255
                raw.extend(bytes([value]) * (3 if depth == 8 else 6))
        header = struct.pack(">IIBBBBB", w, h, depth, 2, 0, 0, 0)
        target = tmp_path / name
        target.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                           + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))
        return target

    eight = read_png(make("a8.png", 8))
    sixteen = read_png(make("a16.png", 16))
    assert sixteen["valid"] is True
    assert sixteen["unique_colors"] == eight["unique_colors"]
    assert abs(float(sixteen["dark_ratio"]) - float(eight["dark_ratio"])) < 1e-9


def test_invalid_task_message_for_duplicate_check_ids(task_payload: dict) -> None:
    task_payload["tasks"][0]["checks"] = [
        {"id": "same", "kind": "numeric", "expression": "1", "expected": 1.0},
        {"id": "same", "kind": "numeric", "expression": "2", "expected": 2.0},
    ]
    with pytest.raises(InvalidTask):
        TaskDocument.from_dict(task_payload)


def test_example_document_still_valid() -> None:
    document = TaskDocument.from_dict(example_document())
    assert document.tasks[0].checks[0].id == "integral_exact"
