# Changelog

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
