"""PNG 只读检查与 Notebook 静态检查。"""

from __future__ import annotations

from pathlib import Path
import struct
import zlib

import pytest

from mathematica_skill.notebook import (
    _unescape_wl,
    build_code_script,
    build_notebook,
    inspect_notebook,
    plain_code,
    tokenize_wl,
    wl_string,
)
from mathematica_skill.models import TaskDocument, example_document
from mathematica_skill.plotqa import read_png, validate_png


def test_png_header_and_dimensions(fake_png: Path) -> None:
    report = read_png(fake_png)
    assert report["valid"] is True
    assert (report["width"], report["height"]) == (400, 300)


def test_validate_png_reports_ok(fake_png: Path) -> None:
    result = validate_png(fake_png)
    assert result["ok"] is True
    assert result["dark_ratio"] > 0


def test_blank_png_is_rejected(tmp_path: Path) -> None:
    width, height = 400, 300
    row = bytes([0]) + bytes((255, 255, 255)) * width
    raw = row * height
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path = tmp_path / "blank.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    result = validate_png(path)
    assert result["ok"] is False
    assert any("blank" in message for message in result["errors"])


def test_truncated_png_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "bad.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    result = validate_png(path)
    assert result["ok"] is False


def test_not_png_signature_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "x.png"
    path.write_bytes(b"not a png at all")
    result = read_png(path)
    assert result["valid"] is False


def test_draft_notebook_contains_input_cells(tmp_path: Path) -> None:
    document = TaskDocument.from_dict(example_document())
    path = build_notebook(document).write(tmp_path / "draft.nb")
    info = inspect_notebook(path)
    assert info["well_formed"] is True
    assert info["input_cells"] >= 2
    assert info["auto_execution"] == []


def test_wl_string_escapes_and_round_trips() -> None:
    original = 'say "hi" and \\ backslash'
    encoded = wl_string(original)
    assert encoded.startswith('"') and encoded.endswith('"')
    assert '\\"' in encoded and '\\\\' in encoded
    assert _unescape_wl(encoded) == original


def test_draft_notebook_keeps_quoted_code(tmp_path: Path) -> None:
    document = TaskDocument.from_dict(example_document())
    document.tasks[0].code = 'msg = "say \\"hi\\"";'
    path = build_notebook(document).write(tmp_path / "quotes.nb")
    text = path.read_text(encoding="utf-8")
    assert text.count('\\"') > 0
    assert "say" in plain_code(text)


def test_code_script_sets_seed() -> None:
    document = TaskDocument.from_dict(example_document())
    document.seed = 4242
    script = build_code_script(document)
    assert "SeedRandom[$msSeed]" in script
    assert "$msSeed = 4242;" in script
    assert "Integrate" in script


def test_tokenizer_keeps_operators() -> None:
    tokens = tokenize_wl("f[x_] := x^2 /; x > 0")
    assert ":=" in tokens
    assert "/;" in tokens


def test_inspect_flags_absolute_paths(tmp_path: Path) -> None:
    document = TaskDocument.from_dict(example_document())
    document.tasks[0].code = 'data = Import["/Users/student/data.csv"];'
    path = build_notebook(document).write(tmp_path / "abs.nb")
    info = inspect_notebook(path)
    assert info["absolute_paths"]


def test_inspect_flags_forbidden_marker(tmp_path: Path) -> None:
    document = TaskDocument.from_dict(example_document())
    document.tasks[0].code = '(* mathematica-skill test *)'
    path = build_notebook(document).write(tmp_path / "marker.nb")
    assert inspect_notebook(path)["forbidden_markers"]


@pytest.mark.parametrize("marker", ["Dynamic[", "InitializationCell -> True", "NotebookDynamicExpression"])
def test_inspect_flags_auto_execution(tmp_path: Path, marker: str) -> None:
    document = TaskDocument.from_dict(example_document())
    document.tasks[0].code = f"x = {marker}"
    path = build_notebook(document).write(tmp_path / "auto.nb")
    assert inspect_notebook(path)["auto_execution"]
