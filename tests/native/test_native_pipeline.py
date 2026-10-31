"""真实 Mathematica 上的验收：只在有许可证的机器上运行，否则明确 skip。

在装有 Mathematica 的机器上运行：

    python3 -m pytest tests/native -m native -ra

输出里的 SKIPPED 原因会写明缺什么。skip 不等于通过；只有 PASSED 才是原生验证的证据，
把结果记录到 docs/VALIDATION.md。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mathematica_skill.compute import compute_code
from mathematica_skill.discovery import detect
from mathematica_skill.workflow import RunOptions, run_task

pytestmark = pytest.mark.native

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture(scope="module")
def engine():
    report = detect(deep_frontend=True, timeout=180.0)
    if not report.engine_usable:
        pytest.skip("skipped: no Wolfram engine")
    return report


def test_kernel_computes_exact_integral(engine, tmp_path: Path) -> None:
    payload = compute_code("Integrate[Sin[x], {x, 0, Pi}]", out_dir=tmp_path)
    assert payload["result"] == "2"
    assert payload["verified"] is False


def test_plot_is_exported_by_the_kernel(engine, tmp_path: Path) -> None:
    payload = compute_code("Plot[Sin[x], {x, 0, Pi}]", out_dir=tmp_path, figure_path=tmp_path / "sine.png")
    assert payload["figure"]["ok"] is True
    assert payload["figure"]["width"] > 0
    assert Path(payload["figure"]["path"]).is_file()


def test_example_reaches_verified_delivery(engine, tmp_path: Path) -> None:
    if not engine.frontend_available:
        pytest.skip("skipped: no Wolfram frontend")
    state = run_task(EXAMPLES / "01-sine.json", RunOptions(work_root=tmp_path / "work"))
    assert state["status"] == "verified", state.get("errors")
    assert state["verified"] is True
    assert state["reproduction"]["all_reproduced"] is True
