# 跨平台兼容边界

## 1. 代码层面

Python 调度层只用标准库，路径全部走 `pathlib`，没有 shell 拼接。三平台差异只在这几处：

| 位置 | 处理 |
| --- | --- |
| 可执行文件发现 | `discovery.py` 分别查 macOS / Windows / Linux 的安装目录 |
| 进程组终止 | POSIX 用 `killpg`，Windows 退回 `kill` |
| 文件名 | 统一拒绝 Windows 保留名与非法字符，允许 Unicode |
| 换行 | 写文件统一 `\n`，读 JSON 用 `utf-8-sig` 兼容 BOM |
| 临时文件 | 用 `tempfile`，不硬编码 `/tmp` |

## 2. 内核层面

| 平台 | 已验证范围 |
| --- | --- |
| macOS Apple Silicon | 主要目标平台；P0 端到端验收要求在这里跑通 |
| macOS Intel | 同一套脚本；未在当前仓库做原生验收 |
| Windows 10/11 | 路径与进程调用已适配；`.nb` 与 `.wl` 由 Mathematica 自己处理；未在本仓库验收 |
| Linux | 服务器上通常只有 Wolfram Engine，无前端；可以算、可以出图，不能声明 Notebook 已验证 |

**不要**声称「全平台通过」，除非你在那台机器上真的跑过 `run` 并留下 `_validation` 记录。

## 3. 文件交换

同一个 `.nb` 在三平台之间移动时：

- 不写绝对路径，数据文件随 Notebook 一起放，用相对路径读。
- 不要依赖某个平台特有的字体；缺字体时 Mathematica 会替换，图面会变。
- 保存后由目标平台的 Mathematica 重新打开、全量计算一次，比较 checks。

## 4. Python 版本

- 最低 3.10（用到 `X | None` 和 `slots=True`）。
- 不依赖 `wolframclient`；需要时可以另装，但核心链路不要求。
- Windows 上 `python` 可能是别名，安装脚本请用 `py -3` 或完整路径。
