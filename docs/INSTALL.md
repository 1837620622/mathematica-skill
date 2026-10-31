# 安装与接入 / Installation

三种入口，装完立刻能用；不需要再单独 `pip install`，也不需要联网下载第二次。

| 方式 | 命令 | 适合 |
| --- | --- | --- |
| npx（不装） | `npx mathematica-skill doctor` | 试一下、临时用 |
| npm 全局 | `npm i -g mathematica-skill` | 长期用，`mathematica-skill` 直接可用 |
| pip | `pip install mathematica-skill` | Python 项目里用，或想锁版本 |

三者的行为完全一致：同一套 Python 调度层 + 同一批 Wolfram 脚本 + 同一个 Skill。

## 前置条件

| 需要 | 说明 |
| --- | --- |
| Python 3.10+ | 仅用于调度；npx/npm 方式会自动寻找本机 Python |
| Mathematica 或 Wolfram Engine | 真正算数学、生成 `.nb`；没有它只能出 `draft` |
| Node 16+ | 只有 npx / npm 方式需要 |

macOS 上 `python3` 来自 Xcode 命令行工具时是 3.9，不够用：

```bash
brew install python@3.12
# 或从 python.org 下载安装包
```

## npx

```bash
npx mathematica-skill doctor --frontend
npx mathematica-skill example --write task.json
npx mathematica-skill run task.json --out work
npx mathematica-skill install --mcp-client claude
```

想固定版本写 `npx mathematica-skill@0.1.0 ...`。

## npm 全局

```bash
npm i -g mathematica-skill
mathematica-skill doctor --frontend
```

Apple Silicon 上全局 bin 在 `/opt/homebrew/bin`，Intel Mac 在 `/usr/local/bin`。
终端能找到但 GUI 里的 Agent 找不到时，直接用 `npx`，或在 MCP 配置里写绝对路径。

## pip

```bash
pip install mathematica-skill
mathematica-skill doctor --frontend
```

安装时会把 `wolfram/`、`skills/`、`assets/` 一起装到 `<prefix>/share/mathematica-skill/`，
所以 `install` 和 `run` 都能找到它们。从源码装：

```bash
git clone https://github.com/1837620622/mathematica-skill.git
cd mathematica-skill
pip install -e ".[dev]"
```

## 装完立刻能用

```bash
mathematica-skill doctor --frontend        # 内核 / 许可证 / 前端
mathematica-skill example --write task.json
mathematica-skill run task.json --out work
ls work/*/deliver/*                        # 交付目录
```

没有 Mathematica 时 `engine_usable=false`，`run --allow-draft` 只出草稿，
`verified` 永远是 `false`。

## 接入 Agent

```bash
mathematica-skill install --mcp-client claude          # Claude Code
mathematica-skill install --mcp-client claude-desktop  # Claude 桌面版
mathematica-skill install --mcp-client codex
mathematica-skill install --mcp-client opencode
mathematica-skill install --mcp-client cursor
mathematica-skill install --target ~/.claude/skills      # 只装 Skill，不配 MCP
mathematica-skill install --dry-run                      # 先看会写哪些文件
```

`install` 做两件事：

macOS 上 Claude 桌面版的配置文件在
`~/Library/Application Support/Claude/claude_desktop_config.json`，
`--mcp-client claude-desktop` 会写到那里；Windows 是 `%APPDATA%\Claude\claude_desktop_config.json`。

1. 把 `mathematica-native` 这一个 Skill 复制到宿主的技能目录；目录里带
   `.mathematica-skill.json` 标记，卸载时只删带标记的目录。
2. 往宿主 MCP 配置里合并一个 `mathematica-skill` 键，不覆盖其他 MCP。

已有同名目录且不是本工具装的 → `INSTALL_CONFLICT`，要 `--force`；`--force` 前会先备份。

## 升级与卸载

```bash
mathematica-skill update            # 已安装目标原地更新
mathematica-skill rollback          # 回到上一次备份
mathematica-skill uninstall         # 只删本工具装的目录
mathematica-skill uninstall --dry-run
```

## macOS 特别注意

1. **前端需要登录的桌面会话。** `UsingFrontEnd` 在 SSH、launchd 后台任务、无头 CI 里通常失败。
   先在 Finder 里手动打开一次 Mathematica，再在同一个用户会话里跑 `doctor --frontend`。
2. **Wolfram Engine 没有 Notebook 前端。** 免费引擎只能算 `.wl` 和出图，`.nb` 无法标记 verified；
   `doctor` 会直接给出 `frontend_capable: false`，不会让你白等一轮探活。
3. **架构要匹配。** Apple Silicon 上跑 x86 内核会走 Rosetta，慢好几倍；`doctor` 的 `arch_match`
   会提示不一致。
4. **首次检查给足时间。** 冷启动加许可证校验可能要 30-60 秒，`doctor --timeout 90` 更稳。

详细说明见 `docs/MACOS.md`。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `找不到 Python 3.10 或更高版本` | 装新版 Python，或 `MATHEMATICA_SKILL_PYTHON=/path/to/python3 npx mathematica-skill ...` |
| `ENGINE_NOT_FOUND` | 装 Mathematica/Wolfram Engine；或设 `MATHEMATICA_KERNEL` 指向 `WolframKernel` |
| `FRONTEND_UNAVAILABLE` | 见上面 macOS 第 1、2 条 |
| `LICENSE_UNAVAILABLE` | 在 Mathematica 里激活后再试；本工具不碰激活信息 |
| MCP 客户端看不到工具 | 重启客户端；确认配置里 command 用绝对路径 |
