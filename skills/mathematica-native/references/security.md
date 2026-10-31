# 安全边界

## 1. 默认不信任任务里的代码

`task.json` 的 `code` 是不可信输入。执行前做两件事：

1. **词法检查**：括号、字符串、注释是否闭合（`mathematica_skill/wlsyntax.py`）。
2. **策略检查**：扫描危险调用，默认阻断。

| 危险类别 | 匹配（示例） | 默认 |
| --- | --- | --- |
| 进程执行 | `Run[...]`、`RunProcess[...]` | 阻断 |
| 网络访问 | `URLDownload`、`URLFetch`、`URLExecute` … | 阻断 |
| 读本机绝对路径 | `Import["/Users/..."]`、`Get["C:\\..."]` | 阻断 |
| 打开外部程序 | `SystemOpen`、`StartProcess`、`CreateProcess` | 阻断 |
| 动态加载 | `LibraryLoad`、`LoadModule`、编译到 C | 阻断 |

操作员确认后可以传 `--allow-external`：危险调用降级为 **warning**，仍然写进报告，绝不静默。

## 2. 工作区隔离

- 原始任务文件和 `sources` 先复制到 `work/<run>/input/`，后续只读副本。
- `sources` 必须是相对路径，`..` 和绝对路径在 schema 层就被拒绝。
- 交付目录只允许 `.nb .wl .wls .png .pdf .svg .csv .xlsx .txt .json`，隐藏文件直接算失败。

## 3. 资源保护

- `--timeout` 控制单次内核调用，`--frontend-timeout` 控制前端执行。
- 超时用进程组 kill，避免残留内核占用 CPU。
- 输出体积：`msJsonSafe` 对超大表达式只保留头部摘要，不把整个 `InterpolatingFunction` 塞进 JSON。

## 4. Notebook 安全

- 交付 Notebook 不含 `InitializationCell -> True`、`Dynamic`、`NotebookDynamicExpression`。
- 不含本机绝对路径、token、用户名。
- 不复制用户原始 Notebook 后再“就地修改”；修改一律另存新文件。
- 打开用户提供的旧 Notebook 时，先看有没有初始化单元和危险调用，再决定是否执行。

## 5. 密钥与隐私

- 工具本身不读、不传任何密钥。
- 所有计算默认本地；不上传题目、数据、Notebook。
- 环境变量里的令牌不会写进日志；报告里只记录路径和哈希。
- 提交到 GitHub 前，`work/` 和 `_validation/` 已在 `.gitignore`，客户资料不会进仓库。

## 6. 许可证

- 不内置、不分享、不破解激活信息。
- 检测到 `LICENSE_UNAVAILABLE` 就停，不尝试绕过。
- Community/免费版是否可用于商业项目由用户自己判断；工具只如实报告许可证类型。
