"""MCP 配置必须自洽：GUI 宿主只按配置里的 command/env 启动，不经过 npm 包装脚本。

回归保护：npx 安装后，配置里曾经没有 PYTHONPATH，Claude Desktop 启动时直接
ModuleNotFoundError。这里用干净环境 + 无关 cwd 复现那种启动方式。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from mathematica_skill import installer

pytestmark = pytest.mark.integration


def test_configured_entry_starts_from_foreign_directory(tmp_path: Path) -> None:
    entry = installer._mcp_entry()
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ}
    env.update(entry["env"])
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    proc = subprocess.run([entry["command"], *entry["args"]], input=request.encode("utf-8"), cwd=tmp_path,
                          env=env, capture_output=True, timeout=120)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    response = json.loads(proc.stdout.decode("utf-8").splitlines()[0])
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert "mathematica_doctor" in names
