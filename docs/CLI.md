# CLI 参考 / CLI reference

所有命令都支持 `--help`；输出默认是 UTF-8 JSON。

## doctor

```bash
mathematica-skill doctor [--frontend] [--timeout 25] [--json]
```

| 字段 | 含义 |
| --- | --- |
| `engine_usable` | 内核能算出 `1+1` 且许可证可用 |
| `kernel_version` / `installation` | `$Version`、`$InstallationDirectory` |
| `license_type` / `license_expiration` | `$LicenseType`、`$LicenseExpirationDate` |
| `frontend_available` | `UsingFrontEnd` 探活是否成功（需 `--frontend`） |
| `agenttools_version` | 已安装的官方 AgentTools 版本（只读检测） |

退出码：`0` 可用；`3` 不可用（`--json` 时始终 `0`，由字段判断）。

## plan

```bash
mathematica-skill plan task.json
```

只解析，不启动内核：任务、输出、sources 解析结果、交付目录名。

## lint

```bash
mathematica-skill lint task.json [--allow-external]
```

返回 `tasks[]`（每个任务 **和每个输出表达式** 各一条括号/行数记录）与 `findings[]`。
危险调用在未授权时是 error（`POLICY_BLOCKED`），授权后降级为 warning（`POLICY_ALLOWED`）。

## run

```bash
mathematica-skill run task.json \
  [--out DIR] [--timeout 900] [--frontend-timeout 240] \
  [--seed N] [--dry-run] [--allow-draft] [--allow-external] \
  [--no-frontend] [--no-rerun] [--overwrite]
```

| 参数 | 作用 |
| --- | --- |
| `--out` | 工作根目录，默认 `./work` 或 `$MATHEMATICA_SKILL_WORK` |
| `--timeout` | 单次内核调用上限（秒） |
| `--frontend-timeout` | 前端执行上限（秒），同时约束整段前端操作 |
| `--seed` | 覆盖随机种子（只改隔离副本） |
| `--dry-run` | 只走到 preflight，`status: dry_run` |
| `--allow-draft` | 无内核时生成 draft，`verified: false` |
| `--allow-external` | 允许危险调用（降级为 warning） |
| `--no-frontend` | 跳过前端执行，结果一定是 `blocked` |
| `--no-rerun` | 跳过第二轮复算，`all_reproduced` 缺失 → review 会拦 |
| `--overwrite` | 允许覆盖已有交付目录 |

退出码：`0` verified；`4` draft；`3` blocked；`1` 其他错误。

## build

```bash
mathematica-skill build task.json [--out DIR] [--draft]
```

`--draft` 不需要 Mathematica，用 Python 生成 token 化的草稿 Notebook（只用于预览，永远不是 verified）。

## evaluate

```bash
mathematica-skill evaluate notebook.nb [--out evaluate.json] [--timeout 240]
```

用前端打开、执行、保存、关闭，返回 `output_cells`、`failed_outputs`、`saved`、`messages`。

## edit

```bash
mathematica-skill edit notebook.nb --edits edits.json --out edited.nb
mathematica-skill edit notebook.nb --op "append_input:Plot[Sin[x],{x,0,1}]"
mathematica-skill edit notebook.nb --op "replace_cell:3=x = 1;" --in-place
mathematica-skill edit notebook.nb --language zh --out zh-version.nb
```

| 参数 | 作用 |
| --- | --- |
| `--edits` | 修改指令 JSON（`operations` / `title` / `language`） |
| `--op` | 快捷操作，可重复：`append_input:<code>`、`append_text:<text>`、`replace_cell:<n>=<code>`、`delete_cell:<n>`、`insert_after:<n>=<code>` |
| `--style` | `insert_after` 使用的单元样式，默认 `Input` |
| `--title` | 替换（或补上）标题单元 |
| `--language` | 只翻转工具生成的固定标题（Problem/题目、Assumptions/假设、Output:/输出：） |
| `--out` | 输出路径；省略时同目录 `-edited.nb` |
| `--in-place` | 覆盖源文件；会先写 `.nb.<stamp>.bak` 备份 |

编辑在 Mathematica 里完成：按单元序号替换、插入、追加、删除，其余单元与样式原样保留。
写入后会重新 `Import` 回来，逐条核对用户提供的字符串是否原样存在；任何字符丢失或出现
替换字符（U+FFFD）都判 `ENCODING_MISMATCH`，不会产出乱码文件。

`edits.json` 示例：

```json
{
  "language": "zh",
  "title": "第三次作业",
  "operations": [
    {"op": "replace_cell", "index": 4, "content": "sol = NDSolveValue[{x'[t] == -x[t], x[0] == 1}, x, {t, 0, 5}];"},
    {"op": "insert_after", "index": 4, "style": "Text", "content": "改用解析解对照。"},
    {"op": "append_input", "content": "Plot[sol[t], {t, 0, 5}, Frame -> True]"},
    {"op": "delete_cell", "index": 2}
  ]
}
```

## export

```bash
mathematica-skill export task.json --code computation.wl --out artifacts/ \
  [--result export.json] [--timeout 600]
```

从真实表达式导出；PNG 会等比缩放并补白到声明像素，PDF/SVG/CSV/XLSX 直接原生导出。

## verify

```bash
mathematica-skill verify task.json --code computation.wl --out verify-2.json \
  [--previous verify-1.json] [--timeout 600]
```

给 `--previous` 时会额外比较每一项是否复现；`all_reproduced` 缺一即失败。

## install / update / uninstall / rollback

```bash
mathematica-skill install [--target DIR]... [--mcp-client CLIENT] [--config PATH] [--force] [--dry-run]
mathematica-skill update  [--force] [--dry-run]
mathematica-skill uninstall [--target DIR]... [--dry-run]
mathematica-skill rollback
```

- 目标目录必须已存在其父目录，或显式传 `--target`。
- 已有非本工具管理的同名目录 → `INSTALL_CONFLICT`，要 `--force`。
- 每次写入前备份到 `~/.mathematica-skill/backups/`。
- `uninstall` 只删带 `.mathematica-skill.json` 标记的目录。

`CLIENT` ∈ `claude`（Claude Code，`~/.claude.json`）`claude-desktop`（`~/Library/Application Support/Claude/claude_desktop_config.json`）`codex` `cursor` `opencode` `generic`。

## example

```bash
mathematica-skill example [--write task.json]
```

打印或写出一个可运行的最小任务。

## mcp

```bash
mathematica-skill mcp serve
```

stdio 服务。客户端配置示例：

```json
{
  "mcpServers": {
    "mathematica-skill": {
      "command": "/usr/bin/python3",
      "args": ["-m", "mathematica_skill.mcp_server"],
      "env": {}
    }
  }
}
```

## 任务字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `schema_version` | ✔ | 目前固定 `"1.0"` |
| `title` | ✔ | 用于目录名与 Notebook 标题 |
| `language` | | `en` / `zh` / `auto`；`auto` 从题目与 `sources` 里的 `.nb` 推断，影响小节标题与图内字体 |
| `subject` | | 学科说明，写在标题下方 |
| `seed` | | 整数，随机过程必须固定 |
| `assumptions` | | 字符串数组，写进 Notebook 的「假设」节 |
| `sources` | | 相对路径数组，运行前复制进隔离目录 |
| `tasks[].id` | ✔ | `[A-Za-z][A-Za-z0-9_-]{0,63}` |
| `tasks[].code` | ✔ | Wolfram Language 源码 |
| `tasks[].checks[]` | | `id` `kind` `expression` `expected` `abs_tol` `rel_tol` |
| `outputs[].filename` | ✔ | 扁平文件名，扩展名必须匹配 `kind` |
| `outputs[].width/height` | | 100–20000 像素，PNG 会按此校验 |
| `delivery.include` | | 只交付这些 output id |
| `metadata.deliver_code` | | 为 `true` 时才交付 `.wl` |
