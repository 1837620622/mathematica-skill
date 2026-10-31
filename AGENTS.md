# AGENTS.md — 开发与维护约束

本文件是给 AI 编程 Agent 的项目级约束。**它不是给最终用户看的**，用户入口是 `README.md` 与
`skills/mathematica-native/SKILL.md`。

## 0. 不可妥协的四条

1. **数学只能由 Wolfram 内核算。** 不用 SymPy/NumPy/SciPy/Matplotlib 生成最终结果或最终图。
2. **`.nb` 必须是真 Notebook。** Input 单元可执行，Output 由执行产生；不能把图片或文字伪装成计算结果。
3. **没有原生执行不许说 verified。** 缺内核 → `draft`；缺前端 → 不算 verified；复算不一致 → `blocked`。
4. **客户目录只放白名单文件。** `.nb .wl .wls .png .pdf .svg .csv .xlsx .txt .json`，其余一律内部保留。

## 1. 分工

| 层 | 允许做的事 | 禁止做的事 |
| --- | --- | --- |
| `mathematica_skill/`（Python） | 解析任务、复制文件、起进程、收集产物、读 PNG 头、比较数值、写报告 | 计算数学、渲染图、解析 `.nb` 语义、假装执行成功 |
| `wolfram/`（WL） | 建 Notebook、前端执行、原生导出、checks、方法库、绘图主题 | 读用户私有凭据、写客户目录之外的路径 |

不要在 Python 里实现 `Plot` 的替代品；也不要在 WL 里实现策略检查（那是 Python 的活）。

## 2. 改动规则

- 改 WL 之前先跑 `python3 scripts/check.py`，它会检查括号/字符串/注释平衡。
- 改 `models.py` 的 schema 必须同步：`SKILL.md`、`references/`、`examples/`、`tests/unit/test_models.py`。
- 改 CLI 参数必须同步 `docs/CLI.md` 与 `README.md`/`README.en.md`（两份都要）。
- 新增 MCP 工具必须同步 `tests/unit/test_mcp_server.py` 里的工具名集合断言。
- 任何「更宽松的通过条件」都要有测试证明它仍然拦得住错误结果。

## 3. 测试分层

| 层 | 内容 | 需要 Mathematica |
| --- | --- | --- |
| L0 静态 | `scripts/check.py`：语法编译、括号平衡、未使用导入、行宽 | 否 |
| L1 单元 | `tests/unit/`：模型、路径、词法、PNG 头、安装器、MCP 协议、状态机 | 否 |
| L2 集成 | `tests/integration/`：dry-run 流水线、失败传播、交付白名单 | 否 |
| L3 原生 | `tests/native/`（`@pytest.mark.native`）：真实内核 + 前端 | **是** |
| L4 回归 | `tests/regression/`：Logistic/Lorenz/RQA/Hurst/盒计数的基准值 | **是** |

L3/L4 在没有许可证的机器上必须 skip，并在输出里明确写「skipped: no Wolfram engine」。
**不允许**把 skip 说成 pass，也不允许为了变绿删掉断言。

## 4. 错误码

新增错误码要同时改三处：`errors.py`、`references/workflow.md` 的错误码表、`SKILL.md` 的错误码行。
错误码是机器契约，不要改已有字符串。

## 5. 提交规范

```
<area>: <what changed>
```

`area` ∈ `python` / `wolfram` / `skill` / `docs` / `tests` / `ci`。
一次提交只做一件事；重构与行为改变分开。提交前必须：

```bash
python3 scripts/check.py
python3 -m pytest -q
```

## 6. 发布

1. 改 `pyproject.toml` 与 `mathematica_skill/__init__.py` 的版本号。
2. 在 `CHANGELOG.md` 写这一节，含「已验证 / 未验证」范围。
3. `python3 scripts/check.py` 全绿。
4. 打 tag `vX.Y.Z`，推送。
5. 若在真实 Mathematica 上跑过，把 `_validation` 摘要写进 `docs/VALIDATION.md`；没跑过就写「未验证」。

## 7. 文档

- 中英文档必须同步功能、命令、限制；不能只改一边。
- 不要写「全平台通过」「完全自动化」这类没有证据的话。
- 不要移除第三方版权声明；本仓库只依赖 Wolfram 官方工具，不复制其源码。
