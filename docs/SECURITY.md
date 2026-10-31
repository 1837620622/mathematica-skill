# 安全模型 / Security model

## 威胁模型

任务代码来自 Agent 或用户，属于**不可信输入**。可能的滥用：

- 执行系统命令（`RunProcess`、`Run`、`SystemOpen`）；
- 读取本机文件（`Import["/Users/..."]`）；
- 外联下载（`URLDownload`、`URLExecute`）；
- 加载本地库或编译 C 代码（`LibraryLoad`、`CompilationTarget -> "C"`）；
- 覆盖用户文件（`Export["/path/outside"]`）。

## 防线

1. **schema 层**：`sources` 必须是相对路径，`..`、绝对路径、驱动器号一律拒绝；输出文件名必须扁平，
   拒绝 Windows 保留名与非法字符。
2. **词法层**：括号、字符串、注释闭合检查；不平衡直接 `WL_SYNTAX` 失败，不进入内核。
3. **策略层**：危险调用正则扫描，默认 `POLICY_BLOCKED`；`--allow-external` 降级为
   `POLICY_ALLOWED` warning，仍然写进 `findings`。
4. **执行层**：工作目录固定为隔离 run 目录；进程组超时 kill；内核只接收绝对路径参数。
5. **交付层**：白名单扩展名 + 隐藏文件阻断 + SHA-256 manifest。

## 不做的事

- 不尝试用沙箱限制 Wolfram 内核（那是操作系统的职责）；工具只做**可见的、可审计的**拦截。
- 不自动关闭 Notebook 安全警告来「让流程跑通」。
- 不把 `--allow-external` 当成默认值。
- 不记录、不传输凭据；报告里只出现路径与哈希。

## 操作建议

- 处理不熟悉的作业材料时，先 `lint`，再 `run --dry-run` 看计划。
- 需要读外部数据时，把数据放到任务同级目录并写进 `sources`，不要用绝对路径。
- 交付前用 `validate_delivery_tree` 的同一套规则自查客户目录。
