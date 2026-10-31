# macOS 深度适配

Apple Silicon 是主要开发和验收平台。这一页写清楚 macOS 上会踩的坑。

## 1. 安装位置

常见三种：

| 安装方式 | 内核 | wolframscript |
| --- | --- | --- |
| Mathematica.app | `/Applications/Mathematica.app/Contents/MacOS/WolframKernel` | 同目录 `wolframscript` |
| Wolfram Engine.app | `/Applications/Wolfram Engine.app/Contents/MacOS/WolframKernel` | 同目录 `wolframscript` |
| 用户目录安装 | `~/Applications/Mathematica.app/...` | 同目录 |

发现顺序：环境变量 → `PATH` → `/Applications` 通配 → `~/Applications` → `/opt/homebrew/bin` → `/usr/local/bin`。

可用环境变量覆盖：

```bash
export MATHEMATICA_KERNEL="/Applications/Mathematica.app/Contents/MacOS/WolframKernel"
export WOLFRAMSCRIPT="/Applications/Mathematica.app/Contents/MacOS/wolframscript"
```

不要写死版本号（例如 `Mathematica 14.1.app`），自动发现会按路径里的数字排序取最高版本。

## 2. 前端与许可证

- `UsingFrontEnd` 需要**登录的图形会话**。SSH、launchd 后台任务、无头环境里通常拿不到前端。
- 判断真假：`doctor --frontend` 会跑 `UsingFrontEnd[Print[...]]`，超时或失败都会明确写出来。
- Wolfram Engine（免费内核）没有 Notebook 前端，只能算 `.wl`；这时 `.nb` 不能标 verified。
- 不要试图绕过激活；`LICENSE_UNAVAILABLE` 就是结束，交给用户处理。

## 3. 首次启动的坑

- 第一次运行内核可能弹窗、请求文件访问权限、或花 20-60 秒初始化。`doctor --timeout 90` 更适合首次检查。
- Gatekeeper 对从网络下载的 App 会隔离；用户需要自己允许。
- macOS 的临时目录是 `/var/folders/...`，路径很长，脚本里一律用 `ExpandFileName`。

## 4. 路径与编码

- 支持中文、日文、韩文路径；文件名非法字符限制见 `safe_filename`。
- 交付 Notebook 里不能出现 `/Users/<name>/...`。静态检查会扫 `RowBox` 文本和原始字符串两处。
- 相对路径基准是 Notebook 所在目录，不是当前工作目录。需要读数据时用 `NotebookDirectory[]`。

## 5. 字体

- 英文/数字：`Helvetica`（系统自带，渲染稳定）。
- 中文：`PingFang SC`；没有时退回 `Heiti SC`、`Songti SC`、`Noto Sans CJK SC`。
- 混排时统一 `FontSize`，不要局部放大，否则 Rasterize 后基线会错位。
- 4K 出图前先小图预览一次，确认没有缺字形（豆腐块）。

## 6. Apple Silicon 注意

- 原生 arm64 内核比 Rosetta 快很多；`arch` 应当显示 `arm64`。
- 如果 Python 是 arm64 而 Mathematica 是 x86（或反过来），进程调用仍能工作，但文件路径大小写敏感度不同（默认 APFS 不区分大小写），不要依赖大小写区分文件。
- 用 `timeout` 控制长任务时，终止整个进程组，避免内核进程残留（`run_process` 已用 `start_new_session` + `killpg`）。

## 7. 推荐流程

```bash
python3 -m pip install -e .
mathematica-skill doctor --frontend --json     # 确认 engine_usable 和 frontend_available
mathematica-skill run task.json --out ~/math-work --seed 20261031
open ~/math-work/<run>/deliver/<name>/         # 用 Mathematica 亲手再打开一次
```

最后这一步不是形式主义：交付前用真人在 Mathematica 里打开、点“全部计算”，是唯一能证明
Notebook 对最终用户可用的方式。
