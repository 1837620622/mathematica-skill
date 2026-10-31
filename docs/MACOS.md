# macOS 指南 / macOS guide

Apple Silicon 是主要开发和验收平台。这一页只写 macOS 上真实会踩的坑。

## 1. 安装位置与发现顺序

| 安装方式 | 内核 | wolframscript |
| --- | --- | --- |
| Mathematica.app | `/Applications/Mathematica.app/Contents/MacOS/WolframKernel` | 同目录 `wolframscript` |
| Wolfram Engine.app | `/Applications/Wolfram Engine.app/Contents/MacOS/WolframKernel` | 同目录 `wolframscript` |
| 用户目录 | `~/Applications/Mathematica.app/...` | 同目录 |
| 带版本号 | `/Applications/Mathematica 14.1.app/...` | 同目录 |

发现顺序：环境变量 → `PATH` → wolframscript 配置文件里的 `KERNELPATH` → `/Applications` 通配
→ `~/Applications` → `/opt/homebrew/bin` → `/usr/local/bin`。

覆盖方式：

```bash
export MATHEMATICA_KERNEL="/Applications/Mathematica.app/Contents/MacOS/WolframKernel"
export WOLFRAMSCRIPT="/Applications/Mathematica.app/Contents/MacOS/wolframscript"
```

**版本排序优先读 `Info.plist`**（`CFBundleShortVersionString`），再看路径里的数字。
原因：`Mathematica 14.1.app` 版本在路径里，`Wolfram Engine.app` 不在；只看路径会把引擎永远排最后。
同版本时 `Mathematica.app`（带前端）优先于 `Wolfram Engine.app`。

## 2. PATH 问题（最容易踩）

从 Finder、Dock 或 GUI 里的 Agent 客户端启动的进程，`PATH` 通常只有
`/usr/bin:/bin:/usr/sbin:/sbin`。而官方 wolframscript 装在 `/usr/local/bin`，
Homebrew Python 在 `/opt/homebrew/bin` —— 两者都不在这个最小 PATH 里。

本工具的处理：

- `doctor` / `run` 内部调 `_which()` 和 `augmented_env()`，会读 `/etc/paths` 与 `/etc/paths.d/*`
  把系统声明的目录补回去，再传给子进程。
- npx/npm 包装脚本自己扫 `/opt/homebrew/bin`、`/usr/local/bin`、
  `/Library/Frameworks/Python.framework/Versions/{3.12,3.11,3.10}/bin` 找 Python。

仍然找不到时显式指定：

```bash
export MATHEMATICA_SKILL_PYTHON=/opt/homebrew/bin/python3.12
npx mathematica-skill doctor
```

## 3. 前端与许可证

- `UsingFrontEnd` 需要**登录的图形会话**。SSH、launchd 后台任务、无头 CI 通常拿不到。
- Wolfram Engine（免费内核）**没有 Notebook 前端**。`doctor` 会读 `.app` 名字直接给出
  `frontend_capable: false`，不再白等 60 秒探活。
- 冷启动 + 许可证校验可能要 30-60 秒；默认探活超时已抬到 60-180 秒，首次检查建议
  `doctor --frontend --timeout 90`。
- 不要试图绕过激活；`LICENSE_UNAVAILABLE` 就停，交给用户处理。

## 4. 架构

`doctor --json` 的 `arch_match` 比较内核的 `$ProcessorType` 与 `platform.machine()`：

- Apple Silicon + arm64 内核 → 原生，最快。
- Apple Silicon + x86 内核（Rosetta）→ `arch_match: false`，会给出 warning；每次调用都慢一倍以上。
- 检查方法：`uname -m` 应为 `arm64`。

## 5. 路径、编码、文件名

- 支持中文、日文、韩文路径；`.nb` 文件名保留原文（`作业一-edited.nb`），只有出现非法字符才退回 slug。
- APFS 默认大小写不敏感，不要靠大小写区分文件。
- 交付 Notebook 里不允许出现 `/Users/<name>/...`；静态检查会同时扫原始文本和 `RowBox` 解码后的代码。
- `.nb` 是 7-bit ASCII 格式，中文存成 `\:4e2d`；判语言、比对内容前必须先解码
  （`langdetect.decode_wl_escapes`）。

## 6. 字体

图内文字走 `wolfram/PlotTheme.wl` 的 `msAcademicFonts`：

| 语言 | macOS 首选 |
| --- | --- |
| 中文 | PingFang SC → Hiragino Sans GB → Heiti SC → Songti SC → Arial Unicode MS |
| 英文 | Helvetica → Arial → DejaVu Sans |

无前端时 `$FontFamilies` 是 `{}`，此时按 `$OperatingSystem` 选择平台常用顺序，
不会在 Linux 上写死 PingFang。混排统一 `FontSize`，避免 Rasterize 后基线错位。
4K 出图前先小图预览一次，确认没有豆腐块。

## 7. 推荐流程

```bash
brew install python@3.12
npx mathematica-skill doctor --frontend --json     # 确认 engine_usable / frontend_available
npx mathematica-skill run task.json --out ~/math-work --seed 20261031
open ~/math-work/<run>/deliver/<name>/             # 用 Mathematica 亲手再打开一次
```

最后一步不是形式主义：交付前用真人在 Mathematica 里打开、点「全部计算」，
是唯一能证明 Notebook 对最终用户可用的方式。
