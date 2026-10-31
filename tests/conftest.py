"""共享测试夹具：假的 wolframscript 可执行文件、临时 PNG。

这里刻意用「假内核」只测 Python 调度层的行为：它必须拒绝把任何未真正
执行的结果标记为 verified。假脚本永远只用于测试调度和错误处理，不生产
任何交付物。
"""

from __future__ import annotations

import json
from pathlib import Path
import stat
import sys

import pytest


@pytest.fixture()
def task_payload() -> dict:
    return {
        "schema_version": "1.0",
        "title": "Unit Test Task",
        "language": "en",
        "seed": 7,
        "tasks": [
            {
                "id": "answer",
                "prompt": "Compute 1 + 1.",
                "code": "msAnswer = 1 + 1;",
                "checks": [
                    {"id": "answer_value", "kind": "numeric", "expression": "msAnswer", "expected": 2.0},
                ],
            }
        ],
        "outputs": [
            {"id": "fig", "task": "answer", "kind": "figure", "filename": "answer.png",
             "expression": "Plot[Sin[x], {x, 0, 1}]", "width": 400, "height": 300},
        ],
        "delivery": {"name": "unit-delivery", "include": ["fig"]},
    }


@pytest.fixture()
def task_file(tmp_path: Path, task_payload: dict) -> Path:
    path = tmp_path / "task.json"
    path.write_text(json.dumps(task_payload, ensure_ascii=False), encoding="utf-8")
    return path


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture()
def fake_wolframscript(tmp_path: Path) -> Path:
    """一个只打印 JSON 的假脚本，让测试看 Python 如何解释返回。"""
    body = """#!/bin/sh
if [ "$1" = "-f" ]; then
  shift 2
fi
echo '{"ok": true, "version": "stub"}'
exit 0
"""
    return _write_executable(tmp_path / "wolframscript", body)


@pytest.fixture()
def fake_wolframscript_failure(tmp_path: Path) -> Path:
    body = """#!/bin/sh
echo '{"ok": false, "error_code": "EVALUATION_FAILED", "message": "stub failure"}'
exit 1
"""
    return _write_executable(tmp_path / "wolframscript", body)


@pytest.fixture()
def fake_png(tmp_path: Path) -> Path:
    """生成一张真实 PNG（用纯标准库写 IHDR/IDAT），用来测只读检查。"""
    import struct
    import zlib

    width, height = 400, 300
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            dark = 0 if (x // 8 + y // 8) % 2 else 255
            rows.extend((dark, dark, dark))
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b""))
    path = tmp_path / "figure.png"
    path.write_bytes(data)
    return path


@pytest.fixture()
def python_executable() -> str:
    return sys.executable
