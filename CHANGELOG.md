# Changelog

## 未发布

### 修复
- **Claude 桌面版 MCP 配置**：`install --mcp-client claude-desktop` 写入的 `env` 现在包含 `PYTHONUTF8`，
  源码或 npm 安装时还包含 `PYTHONPATH`。此前 npx 安装后 GUI 宿主启动 MCP 会 `ModuleNotFoundError`。
  OpenCode 使用 `environment` 键，Codex TOML 同步写入。
- **Codex TOML 强制重装**：替换段时改用函数替换，Windows 路径里的反斜杠不再被正则吃掉。
- **没有 checks 不能 verified**：`run` 在进入内核之前以 `CHECKS_EMPTY` 拦下；`validate_checks` 对
  「没有检查记录」和「检查数为 0」都改为 error（此前只是 warning，零检查任务可以走到 verified）。
- **被门禁拦下的运行也写验收报告**：preflight 阶段拦下时同样写出 `_validation/validation.json` 与 `VALIDATION.md`。
- **MCP 工具名断言**：`tests/unit/test_mcp_server.py` 改为精确集合比较；README 里的工具数量从错误的 9 改为实际的 11（改动前代码里是 10 个）。
- **引擎探测超时统一为 60 秒**：此前 `detect` 默认 25 秒，CLI、MCP 和 workflow 里还有 45 秒上限，操作本身的超时（如 `run` 的 900 秒）也会缩短探测。现在所有入口共用 `ENGINE_PROBE_TIMEOUT`。
- **WL 显式 UTF-8**：所有加载文件的 `Get` 都指定 `CharacterEncoding -> "UTF-8"`，因为 `$CharacterEncoding` 的默认值随平台变化，而 Python 写出的代码和库都是 UTF-8。入口脚本里的中文字符串改为 `\:xxxx` 转义，代码部分只剩 ASCII（有静态测试）。

- **compute 不再覆盖用户符号**：包装器的变量改为放在 `Module` 里，用户代码里的 `value`、`messages`、`args` 等不再被赋成包装器的内部值（此前 `Simplify[value + 1]` 会算出错误结果，且仍然 `ok: true`）。
- **图形导出失败不再静默成功**：结果里带上 `figure_error`；调用方要了 PNG 却拿不到时返回 `PLOT_EXPORT_FAILED`，没要图时作为 `FIGURE_NOT_WRITTEN` 警告返回。

### 新增
- `compute` 子命令与 `mathematica_compute` MCP 工具：在真实内核里执行一段代码，返回最后一个表达式的值、
  消息和可选 PNG。结果永远 `verified=false`，不进入 checks、Notebook 与复算流程。
- `wolfram/ComputeCode.wls`：快速计算的 WL 侧，结果走 `result.json`，图形只导出到内部目录。
- `mathematica_skill/policy.py`：危险调用扫描从 `workflow.py` 移出，`run` 与 `compute` 共用。
- `mathematica_skill/paths.py::unique_path`：目标已存在时加 `-2`，不静默覆盖。
- `tests/native/`：真实内核验收，没有许可证时明确 `skipped: no Wolfram engine`。
- `tests/integration/test_mcp_launch.py`：用配置里的 command/env 在干净环境启动 MCP。

- **建模库随 compute 预加载**：`DomainMethods.wl` 与 `PlotTheme.wl` 在计算前加载，参考文档里的 `ms*` 函数可以直接调用。结果的 `libraries` 字段报告每个库是否加载成功。`run` 的计算脚本和 Notebook 目前不预加载，见 `references/examples.md`。

### 删除
- `WolframscriptAdapter.evaluate_code`：没有调用方、没有测试，由 `compute_code` 替代。

### 验证范围
- **已验证**（本环境，无 Mathematica）：静态检查、Python 单元与集成测试（246 通过，3 个 native 测试 skip）、
  干净环境下按配置启动 MCP 并列出 11 个工具、零检查门禁在无内核时的拦截、安装器配置合并与 TOML 替换。
- **已验证（非原生路径，本环境实际执行）**：`run --allow-draft` 得到 draft（退出码 4）；无检查的 `run` 得到 blocked（退出码 3，在预检阶段停止）；`compute` 的无内核、策略拦截、语法错误分别返回 `ENGINE_NOT_FOUND`、`POLICY_BLOCKED`、`INVALID_TASK`；Claude 桌面版配置写入后，MCP 服务能列出 11 个工具并返回结构化错误。
- **未验证**：所有真内核与前端路径，包括 `compute`、`run`、`tests/native` 和 `ComputeCode.wls` 本身；
  macOS 与 Windows 实机均未运行。

## 0.1.0 — 首个可用版本

### 新增

**Python 调度层**
- `mathematica_skill/models.py`：`task.json` schema（tasks / checks / outputs / delivery / sources），
  含路径安全、Unicode 文件名、Windows 保留名、check 类型与容差校验。
- `mathematica_skill/workflow.py`：14 阶段状态机，逐阶段记录 `state.json`。
- `mathematica_skill/adapter_wolframscript.py`：wolframscript 与裸内核双通道，
  优先读结果文件、回退解析 stdout，进程组超时 kill。
- `mathematica_skill/validation.py`：产物、Notebook 结构、checks、复算、交付白名单五组门禁。
- `mathematica_skill/plotqa.py`：纯标准库 PNG 解析（IHDR/IDAT/滤波还原），只读检查尺寸、空白、单色。
- `mathematica_skill/reporting.py`：`validation.json` + `VALIDATION.md`，含验证边界声明。
- `mathematica_skill/installer.py`：安装/更新/回滚/卸载 + 五种客户端 MCP 配置合并，支持 `--dry-run`。
- `mathematica_skill/mcp_server.py`：标准库实现的 MCP stdio 服务，9 个 `mathematica_*` 工具，
  兼容换行 JSON 与 `Content-Length` 帧。
- `mathematica_skill/cli.py`：`doctor/plan/lint/run/build/evaluate/export/verify/install/update/uninstall/rollback/example/mcp`。

**Wolfram 原生侧**
- `wolfram/BuildNotebook.wls`：用真实解析器验证语法，再用源码原文建 Input 单元（保留注释与排版）。
- `wolfram/EvaluateNotebook.wls`：`UsingFrontEnd` + `NotebookEvaluate[InsertResults -> True]` +
  `NotebookSave` + 重开，统计 Output 单元与 `$Failed` 输出。
- `wolfram/ExportGraphics.wls`：等比缩放 + 白边补齐到声明像素，PNG/PDF/SVG/CSV/XLSX/JSON/TXT 原生导出。
- `wolfram/VerifyResults.wls`：干净内核执行 checks，支持与上一轮逐项比较。
- `wolfram/DomainMethods.wl`：Logistic、Lorenz（含变分方程 + QR 的 Lyapunov）、延迟嵌入、
  RQA（RR/DET/ENTR）、Hurst、GBM、对数收益率、年化波动率、盒计数维数，附带自检。
- `wolfram/PlotTheme.wl`：学术主题、色盲友好配色、常用像素预设、面板组合。

**Agent Skill**
- `skills/mathematica-native/SKILL.md` 与 9 篇 references（workflow / notebook / plotting /
  mathematics / validation / examples / macos / compatibility / security）。

**工程**
- 114 个单元测试，覆盖模型、路径、词法、PNG、安装器、MCP 协议、状态机、验证门禁。
- `scripts/check.py`：编译检查 + 未使用导入 + 行宽 + WL 括号平衡 + pytest。
- GitHub Actions：三平台静态检查与测试，原生测试标记为 `native` 并跳过（不伪造通过）。

### 0.1.0 追加

- `language: "auto"`：按题目与 `sources` 里的 `.nb` 自动判定中英文，英文作业出英文、
  中文模版出中文；`PlotTheme` 增加中文图字体选择（PingFang SC / 微软雅黑 / Noto CJK 回退）。
- `mathematica-skill edit` + MCP `mathematica_edit_notebook` +
  `wolfram/EditNotebook.wls`：在既有 `.nb` 上按单元序号替换/插入/追加/删除、改标题、
  翻转固定标题语言。写后重新 Import 核对每个字符串，Python 侧再查 UTF-8 与 U+FFFD，
  任一不满足即 `ENCODING_MISMATCH`，不产出乱码文件。默认另存新文件，`--in-place` 先备份。
- 新增 `examples/06-edit-notebook.json`。

### 0.1.0 安装与 macOS

- 新增 npm 包与 `bin/mathematica-skill.js`：`npx mathematica-skill ...`、`npm i -g mathematica-skill`
  装完即用。包装脚本自动寻找 Python 3.10+（含 macOS GUI 环境里的
  `/opt/homebrew/bin`、`/Library/Frameworks/Python.framework/...`），并设置 `PYTHONPATH`
  指向包内源码，不需要二次 `pip install`。
- `pip install` 现在会把 `wolfram/`、`skills/`、`assets/` 装到 `<prefix>/share/mathematica-skill/`；
  `wolfram_dir()` / `skill_dir()` 覆盖源码树、npm 包、venv、`--user`、`--target` 五种布局。
- 新增 `--mcp-client claude-desktop`：macOS 写
  `~/Library/Application Support/Claude/claude_desktop_config.json`，Windows 写 `%APPDATA%\Claude\...`。
- macOS：补全 `/etc/paths` 与 `/etc/paths.d/*` 到子进程 `PATH`（Finder 启动的进程 PATH 很短）；
  版本排序改读 `.app` 的 `Info.plist`；同版本优先带前端的 `Mathematica.app`；
  `doctor` 新增 `product`、`frontend_capable`、`arch_match`，Wolfram Engine 直接标记无前端，
  前端探活超时抬到 60-180 秒；`scripts/check.py` 增加版本一致性与 npm 布局检查。

### 验证范围

- 已用真实执行验证：词法检查、schema 校验、PNG 解析、安装器、MCP 协议、无内核/无前端时的失败路径。
- **未验证**：真实 Wolfram 内核计算、真实前端 Notebook 执行、原生 PNG 图面、macOS/Windows 实机端到端。
  详见 `docs/VALIDATION.md`。开发环境没有 Mathematica 许可证，因此这些链路一律标为未验证。
