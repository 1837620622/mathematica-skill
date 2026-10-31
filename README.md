# mathematica-skill

**让 Agent 真正控制 Mathematica 干活，而不是生成看起来像结果的图片。**

一套本地优先的 Mathematica / Wolfram Language 自动化系统：CLI + MCP + Agent Skill 三入口，负责
从自然语言或作业材料，到可运行的 `.nb`、原生 PNG/PDF、数据文件，再到**独立复算验收**的整条链路。

```
需求 → 计划 → Wolfram Language → 原生执行 → 原生出图 → 复算对账 → 白名单交付
```

<!-- 图标 -->
![mathematica-skill](assets/icon.svg)

---

## 1. 为什么需要它

大多数所谓「Mathematica AI 工具」止步于生成代码片段或者一张相似图：

- 生成 `.nb` 但打开后只有文字，没有可执行单元；
- 用 Python 画一张图，塞进 Notebook 冒充 Wolfram 输出；
- 声称「已验证」，实际没有运行过一次；
- 换个机器打开就报路径不存在；
- 交付出一个装满 `.py`、`.json`、日志、截图的目录。

这个项目的存在理由就是把这些做法逐条堵死。

## 2. 开发理念

### 2.1 真实计算，不允许替代

所有数学结果必须来自有许可证的 Wolfram 内核：

- 符号推导、数值积分、方程求解、优化、统计、动力学、随机过程 → `Integrate` / `DSolve` / `NDSolve` /
  `NMinimize` / `LinearModelFit` / `RandomVariate` …
- 图形 → `Plot` / `ListLinePlot` / `ParametricPlot3D` / `Graphics` / `Graphics3D` / `ArrayPlot`，
  由 `Rasterize` + `Export` 原生导出。

Python 只做四件事：调度进程、复制文件、检查产物、比较数值。它**不碰**最终数学，也**不重绘**最终图。

### 2.2 Notebook 必须是真的

`.nb` 由 Mathematica 自己的解析器和导出器生成；执行由真实前端完成：

```
NotebookOpen → NotebookEvaluate[InsertResults → True] → NotebookSave → NotebookClose → 重新打开
```

代码单元保存的是源码原文，所以注释、缩进、空行都在；不是把文字塞进 Text 单元冒充代码。

### 2.3 没有证据就不许说通过

`verified` 只有一条路径能拿到：

1. 内核真的算出 checks；
2. 前端真的打开、执行、保存、重新打开；
3. 新进程独立复算，逐项一致；
4. PNG 尺寸正确、非空白、文件完整；
5. 交付目录只有白名单文件。

缺一项就是 `draft` / `blocked`，报告里写清楚缺什么。

### 2.4 交付与内部分离

```
work/<run>/                 ← 内部：任务副本、日志、两轮对比、验证报告
└── deliver/<name>/         ← 客户：.nb + 必要 .wl + PNG/PDF/CSV/XLSX
```

内部目录永不进入客户目录；客户目录里永不出现 Python、JSON、日志、截图。

### 2.5 跨平台，但不说谎

macOS Apple Silicon 是主要验收平台；Windows / Linux 的路径、进程、编码都做了适配，
但**只有真的跑过才有资格写「已验证」**。兼容性表见 [COMPATIBILITY.md](COMPATIBILITY.md)。

## 3. 达到的效果

| 能力 | 具体表现 |
| --- | --- |
| 任务解析 | 从题目、旧 `.nb`、CSV/图片（由宿主 Agent 识别）整理成结构化 `task.json` |
| 代码质量 | 括号/字符串/注释词法检查 + 危险调用策略检查，默认阻断 |
| 原生计算 | 真实内核执行，捕获 `$Failed`、消息、`Abort`、超时 |
| Notebook | 真正的 Input 单元、真实 Output、可重开可再算 |
| 改 Notebook | `edit` 按单元序号替换/插入/追加，其余不动；写后回读核对，不乱码 |
| 语言跟随 | `language: "auto"` 时英文作业出英文、中文模版出中文（含图内中文字体） |
| 图形 | 1600×900 / 4K / A4-300dpi 预设，等比缩放补白，不拉伸 |
| 数据 | CSV / XLSX / JSON 原生 `Export`，导出后回读校验 |
| 复算 | 两次独立进程，逐项数值/符号比较，容差写在任务里 |
| 图面检查 | 尺寸、空白、单色、文件完整性（只读，不重绘） |
| 报告 | `validation.json` + `VALIDATION.md`，含「验证边界」声明 |
| 交付 | 白名单目录 + SHA-256 manifest，可核对 |
| 安装 | `install / update / rollback / uninstall`，只删自己创建的文件 |
| MCP | 9 个 `mathematica_*` 工具，stdio 传输，单行 JSON 帧 |
| Skill | 符合 Agent Skills frontmatter，可装到 Claude / Codex / Cursor / OpenCode 等 |

## 4. 快速开始

```bash
git clone https://github.com/1837620622/mathematica-skill.git
cd mathematica-skill
python3 -m pip install -e .
mathematica-skill doctor --frontend
```

`doctor` 会回答三个问题：有没有内核、许可证能不能用、有没有 Notebook 前端。

```bash
# 生成一个示例任务并完整跑一遍
mathematica-skill example --write task.json
mathematica-skill plan task.json
mathematica-skill run  task.json --out work --seed 20261031
```

产物：

```
work/<run>/deliver/<name>/
├── sine-and-its-integral.nb     # 真实 Notebook，带 Output
└── sine.png                     # Wolfram 原生导出的 1600×900
```

没有 Mathematica 的机器：

```bash
mathematica-skill run task.json --allow-draft   # 只生成 draft，verified 永远 false
mathematica-skill build task.json --draft --out build/
```

## 5. 任务格式

`task.json` 是 Agent 与内核之间唯一的契约。

```json
{
  "schema_version": "1.0",
  "title": "Logistic map and Lyapunov exponent",
  "language": "zh",
  "seed": 20261031,
  "assumptions": ["r = 4 处于完全混沌区", "跳过前 1000 步瞬态"],
  "sources": ["data/series.csv"],
  "tasks": [
    {
      "id": "logistic",
      "prompt": "计算 r = 4 时 Logistic 映射的 Lyapunov 指数并画出轨道。",
      "code": "orbit = NestList[4. # (1 - #) &, 0.123456, 5000];\nlyap = Mean[Log[Abs[4. (1 - 2 Most[orbit])]]];\nfig = ListLinePlot[orbit[[1 ;; 300]], Frame -> True];",
      "checks": [
        {"id": "lyap_value", "kind": "numeric", "expression": "lyap", "expected": 0.6931,
         "abs_tol": 0.01, "description": "r=4 时理论值 ln2"},
        {"id": "orbit_length", "kind": "numeric", "expression": "Length[orbit]", "expected": 5001}
      ]
    }
  ],
  "outputs": [
    {"id": "orbit_fig", "task": "logistic", "kind": "figure", "filename": "orbit.png",
     "expression": "fig", "width": 3840, "height": 2160, "dpi": 300, "title": "Logistic 轨道"}
  ],
  "delivery": {"name": "logistic-delivery", "include": ["orbit_fig"]},
  "metadata": {"deliver_code": false}
}
```

规则：

- `code` 必须是能跑的 Wolfram Language，不写伪代码。
- `checks` 必须给可比较的 `expected` 和容差；没检查就等于没验证。
- `outputs[].expression` 必须在前面的代码里算过。
- `sources` 只能是相对路径，运行时会复制进隔离目录。
- `delivery.include` 决定哪些 output 进客户目录。

完整字段说明见 [docs/CLI.md](docs/CLI.md) 与 `mathematica_skill/models.py`。

## 6. 命令一览

| 命令 | 作用 |
| --- | --- |
| `doctor` | 内核 / 许可证 / 前端 / AgentTools 探测，支持 `--json` |
| `plan` | 只解析任务，输出计划，不启动内核 |
| `lint` | 词法 + 危险调用静态检查 |
| `run` | 完整流水线，产出 verified 交付或明确的失败状态 |
| `build` | 只生成 `.nb` + `.wl`（`--draft` 无需 Mathematica） |
| `evaluate` | 用前端执行一个已有 `.nb` |
| `export` | 从真实表达式导出 PNG/PDF/CSV/XLSX |
| `verify` | 干净内核执行 checks，可与上一轮比较 |
| `install` / `update` / `uninstall` / `rollback` | Skill 安装与 MCP 配置，支持 `--dry-run` |
| `example` | 输出可运行的任务 JSON |
| `edit` | 修改既有 `.nb`（替换/插入/追加/删除单元、改标题、翻转标题语言） |
| `mcp serve` | 启动 MCP stdio 服务 |

## 7. MCP 工具

```
mathematica_doctor            mathematica_plan             mathematica_lint
mathematica_build             mathematica_run              mathematica_evaluate_notebook
mathematica_export            mathematica_verify           mathematica_example
mathematica_edit_notebook
```

全部返回结构化 JSON 文本；内部错误也是 JSON，`isError: true`，不抛栈给客户端。
工具名前缀 `mathematica_`，不会和官方 Wolfram MCP 冲突。

接入方式：

```bash
mathematica-skill install --mcp-client claude
mathematica-skill install --mcp-client codex
mathematica-skill install --mcp-client opencode
mathematica-skill install --mcp-client cursor --config ~/.cursor/mcp.json
```

安装器只合并自己的那一个键，不覆盖其他 MCP；已存在时提醒用 `--force`。

## 8. 目录结构

```
mathematica-skill/
├── mathematica_skill/        # Python 调度层（只做 I/O、进程、校验）
├── wolfram/                  # 原生侧：Notebook 构建/执行/导出/验证 + 方法库 + 绘图主题
├── skills/mathematica-native # Agent Skill：SKILL.md + references
├── examples/                 # 可运行任务示例（含故意失败的样本）
├── tests/                    # 单元 / 集成 / 回归
├── docs/                     # 架构、CLI、验证、安全、macOS
└── .github/workflows/        # 静态检查与测试
```

## 8.1 语言跟随与 Notebook 修改

`language` 写 `auto` 时按材料判断：

- 题目（`prompt` / `notes` / `subject` / 标题 / 假设）里汉字 >= 8 且占比 >= 15% → 中文，否则英文。
- 题目判不出来时看 `sources` 里的 `.nb`：先解码 `\:xxxx` 形式的 7-bit 转义，再比较
  「中文片段 vs 英文句子」的占比（>= 25%），所以英文作业里引用一句中文不会翻转语言。
- 代码字符串（含 `[]{};=<>|&_$`）不算英文正文，代码很多的中文作业仍判中文。
- 图内文字同步换字体：macOS 用 PingFang SC，Windows 用微软雅黑，Linux 用 Noto Sans CJK；
  无前端时按平台约定顺序挑，不会在 Linux 上写死 macOS 字体。

修改既有 Notebook：

```bash
mathematica-skill edit 旧作业.nb --edits edits.json --out 新作业.nb
mathematica-skill edit 旧作业.nb --op "replace_cell:4=sol = DSolveValue[...];" --in-place
mathematica-skill edit 旧作业.nb --language zh --out 中文版.nb
```

写入由 Mathematica 完成（`Export[..., "NB"]`），随后脚本重新导入核对每个字符串，
Python 再校验 UTF-8 与 U+FFFD。任何字符丢失都判失败，不会交付乱码文件。

编辑细节：

- 不给 `--out` 时写同目录 `<名字>-edited.nb`；已存在则自动加 `-2`、`-3`，不静默覆盖。
- `--in-place` 才覆盖源文件，且先写 `<名字>.nb.<时间戳>.bak`（同秒重名自动加序号）。
- 内部工作目录用系统临时目录，成功后自动清理，不在用户目录留 `_edit/`。
- `--edits` 不能和 `--op` / `--title` / `--language` 混用，混用直接报错而不是静默忽略。

## 9. 验证边界（必读）

| 环境 | 能证明什么 |
| --- | --- |
| 无 Mathematica | 只能生成 draft；`verified` 永远 false |
| 有内核无前端 | 能算 `.wl`、能出 PNG、能对账；`.nb` **不能**标 verified |
| 内核 + 前端 | 完整链路；仍需独立复算通过 |
| 只在 Linux 跑过 | 不能声称 macOS/Windows 已验证 |

审查者只需看两样东西：`_validation/validation.json` 的 `findings`，以及 `native` 段里的
`frontend_used / output_cells / failed_outputs`。

## 10. 安全

- 任务代码视为不可信：`Run`、`RunProcess`、`URL*`、本机绝对路径、`LibraryLoad` 默认阻断。
- `--allow-external` 只把阻断降级为 warning，并写进报告。
- 不上传题目、数据、Notebook；所有计算本地完成。
- 不内置、不分享激活信息；许可证不可用就停。

细节见 `skills/mathematica-native/references/security.md`。

## 11. 开发

```bash
python3 -m pip install -e .
python3 -m pytest -q                     # 单元测试（不需要 Mathematica）
python3 scripts/check.py                 # 词法检查 + WL 括号平衡 + 测试
```

需要真实内核的测试标记为 `@pytest.mark.native`，在普通 CI 上跳过，**不会**假装通过。

发布前：

```bash
python3 scripts/check.py && git tag v0.1.0
```

## 12. 许可

MIT，见 [LICENSE](LICENSE)。Wolfram Mathematica 本身是商业软件，本项目不包含、不修改、不绕过其授权。

---

**English**: [README.en.md](README.en.md)
