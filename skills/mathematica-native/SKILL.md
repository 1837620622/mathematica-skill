---
name: mathematica-native
description: Creates, executes, verifies and delivers native Mathematica work — real Wolfram Language computation, real .nb notebooks, native PNG/PDF plots, regression checks and clean client delivery. Use when the user asks for Mathematica homework, a runnable notebook, symbolic/numeric computation, ODE/dynamics analysis, Lyapunov/RQA/fractal/finance plots, or a reproducible Mathematica deliverable.
compatibility: Requires a licensed Mathematica or Wolfram Engine for verified work; draft mode works without it
metadata:
  author: 1837620622
  version: 0.1.0
---

# Mathematica Native

用真正的 Wolfram 内核做数学，用真正的 Mathematica 前端做 Notebook。Python 只做调度、文件、预检和对账，**不替代数学计算，也不重绘图形**。

## 先做环境检查

```bash
mathematica-skill doctor --json
```

- `engine_usable=true`：可以进入原生计算。
- `engine_usable=false`：只能生成 draft，状态必须写成 `draft`，不能声称已验证。
- `frontend_available=false`：可以跑 `.wl` 内核计算，但不能声明 Notebook 已在前端打开、执行、保存和重算。

安装与检查：

```bash
python3 -m pip install -e .
mathematica-skill install --mcp-client opencode --dry-run
mathematica-skill install --mcp-client opencode
```

## 标准工作流

1. **读题**：从 PDF、图片、Word、旧 `.nb` 或自然语言里提取题目、参数、单位、数据、输出格式。
2. **建任务**：写 `task.json`。每道题一个 `task`，代码是可执行的 Wolfram Language；每项结果写 `checks`。
3. **静态检查**：`mathematica-skill lint task.json`，修 WL 语法、路径和危险调用。
4. **原生执行**：`mathematica-skill run task.json`。流程固定为
   `intake → inspect → plan → lint → preflight → native_build → native_evaluate → export → close → reopen → rerun → compare → review → deliver`。
5. **看报告**：内部 `_validation/validation.json` 和 `VALIDATION.md` 记录每个门禁。只有 `verified=true` 才能交付。
6. **交付**：`deliver/<name>/` 只放 `.nb`、必要的 `.wl`、PNG/PDF、CSV/XLSX 和用户明确要求的文件。

## task.json 最小契约

```json
{
  "schema_version": "1.0",
  "title": "Sine and its integral",
  "language": "en",
  "seed": 20261031,
  "tasks": [
    {
      "id": "sine",
      "prompt": "Plot sin(x) and compute the exact integral on [0, pi].",
      "code": "p = Plot[Sin[x], {x, -Pi, Pi}];\ni = Integrate[Sin[x], {x, 0, Pi}];",
      "checks": [
        {"id": "integral", "kind": "symbolic", "expression": "i", "expected": "2"},
        {"id": "value", "kind": "numeric", "expression": "N[Sin[Pi/2]]", "expected": 1.0, "abs_tol": 1e-12}
      ]
    }
  ],
  "outputs": [
    {"id": "fig", "task": "sine", "kind": "figure", "filename": "sine.png",
     "expression": "p", "width": 1600, "height": 900, "dpi": 300}
  ],
  "delivery": {"name": "sine-delivery", "include": ["fig"]}
}
```

硬规则：

- `code` 必须是真实可执行的 Wolfram Language，不写伪代码。
- `checks` 必须给可比较的 `expected` 和容差；不能只凭图好看就算对。
- 导出表达式必须已经在上面的代码里算好，不能在导出阶段重新发明数据。
- 图只由 Wolfram `Plot`、`ListPlot`、`Graphics`、`Graphics3D` 等生成；Python 只检查 PNG 的尺寸、完整性和空白异常。
- `sources` 里的文件会复制进隔离工作区；默认只读，不覆盖用户原件。
- 未安装 Mathematica 时用 `--allow-draft`，输出只能标 `draft`。
- `language` 写 `auto` 时跟随材料：英文作业出英文，中文模版出中文；也可以显式写 `en` / `zh`。
- 修改旧 `.nb` 用 `edit`：按单元序号替换/插入/追加，默认另存新文件；`--in-place` 会先备份。
  写入后脚本会重新导入核对每个字符串，字符丢失即 `ENCODING_MISMATCH`，不会交付乱码。

## 常用命令

```bash
mathematica-skill doctor [--frontend] [--json]
mathematica-skill plan task.json
mathematica-skill lint task.json
mathematica-skill run task.json [--out DIR] [--seed N] [--no-rerun]
mathematica-skill build task.json [--draft] [--out DIR]
mathematica-skill evaluate notebook.nb [--out JSON]
mathematica-skill edit notebook.nb --edits edits.json --out edited.nb
mathematica-skill edit notebook.nb --op "append_input:..." --in-place
mathematica-skill export task.json --code computation.wl --out artifacts/
mathematica-skill verify task.json --code computation.wl --out verify.json [--previous verify-1.json]
mathematica-skill install --mcp-client opencode|claude|codex|cursor|generic
mathematica-skill update
mathematica-skill uninstall
mathematica-skill mcp serve
```

## 何时读 references

| 场景 | 文件 |
| --- | --- |
| 完整流水线、状态机、断点恢复 | `references/workflow.md` |
| Notebook 生成、修改、复算、单元格规则 | `references/notebook.md` |
| 4K/PDF 出图、主题、图面 QA | `references/plotting.md` |
| ODE、Lyapunov、RQA、Hurst、box counting、GBM | `references/mathematics.md` |
| 验证门禁、容差、复现策略 | `references/validation.md` |
| 完整可运行示例 | `references/examples.md` |
| macOS 深度适配、路径、前端、字体 | `references/macos.md` |
| Windows/Linux 兼容边界 | `references/compatibility.md` |
| 安全边界、外部文件、危险代码 | `references/security.md` |

## 交付形态

- 正式交付必须是 `verified=true`：内核真实计算、前端真实打开并执行、独立复算逐项通过、PNG 尺寸和内容通过。
- 工具链内部文件（JSON、日志、Python、测试、截图、缓存）只留在 `work/` 和 `_validation/`。
- 客户端 Notebook 不写本机绝对路径、不写“AI 生成”、不写测试说明。
- 失败就报 `blocked` / `failed` 和具体错误码，不用“看起来差不多”掩盖 `NUMERIC_MISMATCH`、`FRONTEND_UNAVAILABLE` 或 `PLOT_EXPORT_FAILED`。

## 错误码

`ENGINE_NOT_FOUND`、`LICENSE_UNAVAILABLE`、`FRONTEND_UNAVAILABLE`、`NOTEBOOK_OPEN_FAILED`、
`EVALUATION_FAILED`、`PLOT_EXPORT_FAILED`、`NUMERIC_MISMATCH`、`DELIVERY_BLOCKED`、`INVALID_TASK`、`UNSAFE_PATH`。
