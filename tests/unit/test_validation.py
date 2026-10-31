"""验证门禁、交付白名单与报告。

这些测试刻意构造「不该通过」的情况，确认门禁真的会拦。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mathematica_skill.delivery import plan_delivery, stage_delivery
from mathematica_skill.errors import DeliveryBlocked
from mathematica_skill.models import TaskDocument, example_document
from mathematica_skill.reporting import render_markdown, write_reports
from mathematica_skill.validation import (
    ValidationReport,
    validate_artifacts,
    validate_checks,
    validate_delivery_tree,
    validate_notebook,
    validate_reproduction,
)


def test_missing_artifact_blocks(tmp_path: Path) -> None:
    report = ValidationReport()
    validate_artifacts(tmp_path, [{"id": "f", "filename": "a.png", "kind": "figure"}], report=report)
    assert not report.ok
    assert report.errors()[0].code == "ARTIFACT_MISSING"


def test_png_dimension_mismatch_blocks(tmp_path: Path, fake_png: Path) -> None:
    report = ValidationReport()
    validate_artifacts(tmp_path, [{"id": "f", "filename": fake_png.name, "kind": "figure",
                                   "width": 800, "height": 600}], report=report)
    assert any(finding.code == "PNG_DIMENSIONS" for finding in report.errors())


def test_pdf_magic_is_checked(tmp_path: Path) -> None:
    path = tmp_path / "a.pdf"
    path.write_bytes(b"NOTPDF")
    report = ValidationReport()
    validate_artifacts(tmp_path, [{"id": "p", "filename": "a.pdf", "kind": "pdf"}], report=report)
    assert any(finding.code == "PDF_INVALID" for finding in report.errors())


def test_delivery_tree_rejects_extra_files(tmp_path: Path) -> None:
    (tmp_path / "run.py").write_text("print(1)")
    report = ValidationReport()
    validate_delivery_tree(tmp_path, report=report)
    assert any(finding.code == "DELIVERY_EXTRA_FILE" for finding in report.errors())


def test_delivery_tree_rejects_hidden_files(tmp_path: Path) -> None:
    (tmp_path / ".DS_Store").write_bytes(b"x")
    report = ValidationReport()
    validate_delivery_tree(tmp_path, report=report)
    assert any(finding.code == "DELIVERY_HIDDEN_FILE" for finding in report.errors())


def test_delivery_tree_rejects_empty(tmp_path: Path) -> None:
    report = ValidationReport()
    validate_delivery_tree(tmp_path, report=report)
    assert any(finding.code == "DELIVERY_EMPTY" for finding in report.errors())


def test_notebook_requires_frontend_result(tmp_path: Path) -> None:
    document = TaskDocument.from_dict(example_document())
    from mathematica_skill.notebook import build_notebook

    notebook = build_notebook(document).write(tmp_path / "a.nb")
    report = ValidationReport()
    validate_notebook(notebook, native_result=None, report=report, require_frontend=True)
    assert any(finding.code == "FRONTEND_UNAVAILABLE" for finding in report.errors())


def test_notebook_without_output_blocks(tmp_path: Path) -> None:
    document = TaskDocument.from_dict(example_document())
    from mathematica_skill.notebook import build_notebook

    notebook = build_notebook(document).write(tmp_path / "b.nb")
    report = ValidationReport()
    validate_notebook(notebook, native_result={
        "ok": True, "mode": "evaluate", "frontend_used": True, "output_cells": 0, "messages": [],
    }, report=report, require_frontend=True)
    assert any(finding.code == "NOTEBOOK_NO_OUTPUT" for finding in report.errors())


def test_notebook_serious_messages_block(tmp_path: Path) -> None:
    document = TaskDocument.from_dict(example_document())
    from mathematica_skill.notebook import build_notebook

    notebook = build_notebook(document).write(tmp_path / "c.nb")
    report = ValidationReport()
    validate_notebook(notebook, native_result={
        "ok": True, "mode": "evaluate", "frontend_used": True, "output_cells": 2,
        "messages": ["Power::infy: Infinite expression 1/0 encountered."],
    }, report=report, require_frontend=True)
    assert any(finding.code == "NOTEBOOK_MESSAGES" for finding in report.errors())


def test_failed_check_blocks() -> None:
    report = ValidationReport()
    validate_checks({"ok": True, "total": 1, "passed": 0,
                     "checks": [{"id": "c", "passed": False, "expected": 2, "actual": 3}]}, report=report)
    assert any(finding.code == "CHECK_FAILED" for finding in report.errors())


def test_reproduction_incomplete_blocks() -> None:
    report = ValidationReport()
    validate_reproduction({"ok": True, "all_reproduced": False, "reproduced": 0, "total": 2}, report=report)
    assert any(finding.code == "REPRODUCTION_INCOMPLETE" for finding in report.errors())


def test_reproduction_missing_blocks() -> None:
    report = ValidationReport()
    validate_reproduction(None, report=report)
    assert any(finding.code == "REPRODUCTION_MISSING" for finding in report.errors())


def test_delivery_plan_only_contains_whitelisted_items(tmp_path: Path) -> None:
    document = TaskDocument.from_dict(example_document())
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "sine.png").write_bytes(b"png")
    notebook = tmp_path / "sine.nb"
    notebook.write_bytes(b"nb")
    plan = plan_delivery(document, notebook=notebook, artifacts_dir=artifacts)
    names = sorted(name for _, name in plan)
    assert names == ["sine-and-its-integral.nb", "sine.png"]
    assert all(name.endswith((".nb", ".png")) for name in names)


def test_delivery_refuses_to_overwrite(tmp_path: Path) -> None:
    document = TaskDocument.from_dict(example_document())
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "sine.png").write_bytes(b"png")
    notebook = tmp_path / "sine.nb"
    notebook.write_bytes(b"nb")
    report = ValidationReport()
    stage_delivery(tmp_path, document, notebook=notebook, artifacts_dir=artifacts, report=report)
    with pytest.raises(DeliveryBlocked):
        stage_delivery(tmp_path, document, notebook=notebook, artifacts_dir=artifacts, report=report)


def test_reports_are_written(tmp_path: Path) -> None:
    report = ValidationReport()
    report.add("warning", "W", "warn")
    paths = write_reports(tmp_path, {"title": "T", "run_id": "R", "status": "draft", "verified": False},
                          report.to_dict(), {"platform_system": "Darwin", "engine_usable": False})
    assert Path(paths["validation_json"]).is_file()
    text = Path(paths["validation_markdown"]).read_text(encoding="utf-8")
    assert "Verification boundary" in text
    assert "no" in text


def test_markdown_escapes_pipes() -> None:
    report = ValidationReport()
    report.add("error", "E", "a | b")
    text = render_markdown({"title": "t"}, report.to_dict(), {})
    assert "a \\| b" in text
