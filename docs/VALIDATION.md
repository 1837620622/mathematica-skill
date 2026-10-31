# 验证记录 / Validation log

本文件记录**真实执行过**的验证，以及尚未验证的部分。没有记录的环境一律视为未验证。

## 当前状态（v0.1.0）

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| Python 单元 + 集成测试 | 通过 | `python3 -m pytest -q`：239 通过，3 个 native 测试 skip |
| WL 词法/括号检查 | 通过 | `python3 scripts/check.py` |
| 项目自检（无 Mathematica） | 通过 | `doctor` 正确报告 `engine_usable: false` |
| 安装器 dry-run 与 MCP 配置合并 | 通过 | `install --target ... --dry-run`；`tests/unit/test_installer.py` |
| 干净环境按配置启动 MCP | 通过 | `tests/integration/test_mcp_launch.py`（cwd 在仓库外，只带配置里的 env） |
| MCP 协议（initialize/tools/list/tools/call/错误） | 通过 | `tests/unit/test_mcp_server.py`，工具名为精确集合 |
| 零检查任务被门禁拦下（无内核） | 通过 | `run` 在进入内核之前以 `CHECKS_EMPTY` 结束，`_validation/` 有报告 |
| 真内核计算（`compute`、`run`） | **未验证** | 开发环境无 Mathematica；`tests/native` 全部 skip：`skipped: no Wolfram engine` |
| `ComputeCode.wls` 实际执行 | **未验证** | 没有内核，WL 侧只做了括号平衡检查 |
| 真前端 Notebook 执行 | **未验证** | 同上 |
| 原生 PNG 尺寸/图面 | **未验证** | 同上 |
| macOS 实机端到端 | **未验证** | 需要在装有 Mathematica 的机器上执行 |

> 说明：本仓库的开发环境（iSH / Alpine aarch64）没有 Wolfram 内核，因此所有
> `ENGINE_NOT_FOUND` 分支都是**真实**跑过的，而需要许可证的链路全部标为未验证。
> 这一点不会被说成「已通过」。

## 复现命令

```bash
python3 -m pip install -e .
python3 -m pytest -q
python3 scripts/check.py
mathematica-skill doctor --json
```

## 在装有 Mathematica 的机器上补齐验证

```bash
mathematica-skill doctor --frontend --json > doctor.json
python3 -m pytest tests/native -m native -ra        # 真内核 + 前端的端到端验收
mathematica-skill compute "Integrate[Sin[x], {x, 0, Pi}]"
mathematica-skill run examples/01-sine.json --out work --seed 20261031
# 期望：state.json 里 status=verified, verified=true
# 期望：_validation/validation.json 里 findings 无 error, reproduction.all_reproduced=true
```

`tests/native` 的输出里，`PASSED` 才是证据；`SKIPPED` 的原因会写明缺什么，不能当作通过。

把 `doctor.json` 关键字段、`state.json` 的 status、`validation.json` 的摘要贴回本文件，
并在 `COMPATIBILITY.md` 对应行标注「已验证」，才算完成该平台的验收。

## 已知限制

- 只有内核没有前端时，`.nb` 无法验证；`run` 会在 review 阶段 `blocked`。
- `--no-rerun` 会让 `all_reproduced` 缺失，review 会拦下，不会产出 verified。
- 混沌系统的 checks 需要按积分长度放宽容差；`1e-9` 对 Lyapunov 指数没有意义。
- 草稿 Notebook（`build --draft`）只是 token 化的预览，注释与格式不保证，永远不是 verified。
