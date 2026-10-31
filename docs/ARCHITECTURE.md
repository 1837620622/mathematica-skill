# 架构 / Architecture

## 1. 总览

```
┌──────────────────────┐
│ Agent (Claude/Codex/ │
│ Cursor/OpenCode/Pi)  │
└───────┬──────────────┘
        │ SKILL.md 指示 + 自然语言
        ▼
┌──────────────────────────────────────────────┐
│ mathematica-skill CLI / MCP server           │
│  ├─ models.py      task.json schema          │
│  ├─ workflow.py    状态机与门禁               │
│  ├─ adapter_*      进程启动 / 结果解析        │
│  ├─ validation.py  校验与白名单               │
│  ├─ plotqa.py      PNG 只读检查               │
│  ├─ reporting.py   validation.json/md        │
│  └─ installer.py   安装 / MCP 配置           │
└───────┬──────────────────────────┬───────────┘
        │ wolframscript -f          │ 读取产物
        ▼                          ▼
┌──────────────────────┐   ┌──────────────────┐
│ wolfram/*.wls        │   │ artifacts/       │
│ BuildNotebook        │   │ PNG/PDF/CSV/XLSX │
│ EvaluateNotebook     │   └──────────────────┘
│ ExportGraphics       │
│ VerifyResults        │
│ + DomainMethods.wl   │
│ + PlotTheme.wl       │
└───────┬──────────────┘
        │ UsingFrontEnd / NDSolve / Rasterize
        ▼
┌──────────────────────┐
│ Wolfram Kernel 前端  │
└──────────────────────┘
```

Python 与 WL 之间只有两种数据交换：**task JSON** 和 **result JSON**。没有隐式状态，没有共享内存。

## 2. 为什么是「脚本 + JSON」而不是长驻内核

| 方案 | 优点 | 缺点 | 结论 |
| --- | --- | --- | --- |
| 常驻内核 + 管道 | 快 | 状态污染、难隔离、崩溃不可恢复 | 不做 |
| 每次 `wolframscript -f` | 干净、可复算、易超时 | 启动约 1-3 秒 | **采用** |
| `wolframclient` | Python 原生 | 额外依赖、版本敏感 | 可选，不进核心 |

复算要的正是「干净内核」，所以进程隔离不是浪费，而是验证手段本身。

## 3. 状态机

```
intake ─▶ inspect ─▶ plan ─▶ lint ─▶ preflight ─┬─▶ draft（无内核且允许 draft）
                                                ├─▶ dry_run（只规划）
                                                └─▶ native_build
                                                      │
                                                      ▼
                                               native_evaluate ─┬─▶ skipped（无前端）
                                                                └─▶ completed
                                                      ▼
                                                   export
                                                      ▼
                                              close ─▶ reopen
                                                      ▼
                                                    rerun
                                                      ▼
                                                   compare
                                                      ▼
                                                   review ─┬─▶ blocked
                                                           └─▶ deliver ─▶ verified
```

每个阶段都会 append 一条记录到 `state.json` 的 `stages`，含 `status`、`seconds`、`detail`。
失败时保留已完成阶段的证据，便于断点排查。

## 4. 关键设计决定

### 4.1 结果文件优先于 stdout

WL 脚本把结果写到 `result.json`，同时打印一份紧凑 JSON。Python **优先读文件**，
因为用户代码里的 `Print` 会污染 stdout。读文件失败才回退到解析 stdout 的平衡括号。

### 4.2 task 副本不可变

`input/` 下是任务和 sources 的副本；`--seed` 只改副本。用户原始文件永远不被写。
这一点有测试锁住（`test_seed_override_does_not_touch_source`）。

### 4.3 交付白名单 + manifest

`stage_delivery` 只复制 `plan_delivery` 列出的文件；复制后立即 `validate_delivery_tree`，
发现多余扩展名或隐藏文件就整体判失败，并写 `manifest.json`（含每个文件的 SHA-256）。

### 4.4 前端是独立能力

`detect(deep_frontend=True)` 用 `UsingFrontEnd[Print[...]]` 探活。内核可用但前端不可用时，
`run` 会跑到 review 阶段然后 `blocked`，而不是假装成功。这条也有测试。

### 4.5 MCP 用最小实现

只实现 `initialize`、`ping`、`tools/list`、`tools/call`、`resources/list`、`prompts/list`，
stdio 用换行分隔 JSON（与官方 Wolfram MCP 一致），同时兼容 `Content-Length` 帧以适配老客户端。
不监听端口，不引入 SDK 依赖。

## 5. 扩展点

| 想加什么 | 改哪里 |
| --- | --- |
| 新 check 类型 | `models.py` 的 `CHECK_KINDS` + `wolfram/VerifyResults.wls` 的 `msReproduced`/`passed` 分支 |
| 新输出格式 | `models.py` 的 `EXTENSIONS` + `wolfram/ExportGraphics.wls` 的 `Which` 分支 |
| 新领域方法 | `wolfram/DomainMethods.wl`，并在 `references/mathematics.md` 写基准 |
| 新 Agent 客户端 | `installer.py` 的 `configure_mcp` 加一个分支 + 单测 |
| 新 MCP 工具 | `mcp_server.py` 的 `TOOLS` 与 `_call` + 协议测试 |

## 6. 明确的非目标

- 不做云端渲染 / 云端内核池。
- 不替代官方 AgentTools；`doctor` 只报告它的版本。
- 不实现 `.nb` 的完整 AST 编辑（当前只做「读结构 + 新建」）。
- 不跨平台伪造验收结果。
