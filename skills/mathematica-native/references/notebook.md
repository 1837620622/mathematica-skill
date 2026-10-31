# 原生 Notebook 规则

## 1. 生成路径

正式生成走 `wolfram/BuildNotebook.wls`：

1. 读 task JSON。
2. 每个 `task.code` 先用 `ToExpression[code, InputForm, HoldComplete]` 验证语法（这一步会暴露真正的语法错误）。
3. 验证通过后，用**源代码原文**建框符：按行切分，行与行之间用 `"\[IndentingNewLine]"` 分隔，包进 `RowBox`。
4. 写入 `Cell[BoxData[RowBox[...]], "Input"]`。
5. `Export[path, notebook, "NB"]`。

为什么用原文而不是 `MakeBoxes` 的结果：

- 注释、空行、缩进、对齐都会保留；助教看到的和他写的一样。
- `MakeBoxes` 会把注释丢掉，还会把长表达式重排成一行，可读性差。
- 原文框符在 Mathematica 里仍然是可编辑、可计算的 Input 单元。

不要用 `WriteNotebook` 当作「执行并写入输出」的 API；它只适合把 Markdown 转成 Notebook。

## 2. 执行路径

`wolfram/EvaluateNotebook.wls` 只做前端操作：

```wl
UsingFrontEnd[
  nbo = NotebookOpen[path, Visible -> False];
  NotebookEvaluate[nbo, InsertResults -> True];
  NotebookSave[nbo];
  NotebookClose[nbo];
]
```

要点：

- `NotebookEvaluate` 的语法错误不会中断后续单元，所以另外统计 Output 单元数和 `$Failed` 输出。
- `InsertResults -> True` 才会把结果写回单元格；`NotebookSave` 失败会被记为失败。
- 整段操作外层还有一层 `TimeConstrained`，防止前端卡死。
- 没有 `UsingFrontEnd` 时，纯内核可以算 `.wl`，但不能声称 `.nb` 已在前端执行。

## 3. 结构要求

- `Title` / `Section` / `Subsection` / `Text` 分层，不堆成一大段。
- 代码用普通 `Input` 单元，保留原文。
- 输出由执行产生，不能预置图片。
- 禁用 `InitializationCell -> True`、`Dynamic`、`NotebookDynamicExpression`。
- 不写本机绝对路径、用户名、token、开发说明。
- 需要读外部数据时用相对 Notebook 目录的路径，并把数据一起交付。

## 4. 修改旧 Notebook

当前版本优先「读结构 + 生成新 Notebook」。要原地改旧 `.nb`：

1. 先复制到隔离工作区，绝不改原件。
2. `NotebookOpen` → `NotebookGet`。
3. 只替换目标 `Cell`，保留其他单元、分组和样式。
4. 另存新文件。
5. 重新打开、执行、比较。

不要把自己拼的字符串覆盖回旧 Notebook，样式、分组、初始化属性都会丢。

## 5. 复算

- 新进程、新前端、新内核。
- 复制最终 `.nb` 到 `rerun/`，不改候选文件。
- 全量执行 Input 单元，再导出一次数据。
- 逐项比较 checks，容差来自 task JSON。
- 随机过程固定 `SeedRandom` 并记录种子。

## 6. 常见故障

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 打开只有文字，没有可执行代码 | 框符写成了 Text 或字符串拼错 | 用 `RowBox` + 原文重建 |
| 有 Input 但没有 Output | 没执行，或未 `InsertResults` | 检查前端和 `NotebookSave` |
| 中文变豆腐块 | 缺字体 | 用 PingFang SC / Noto Sans CJK |
| 重开路径失效 | 绝对路径 | 改相对路径并附数据 |
| 计算完保存丢失 | `NotebookSave` 失败 | 结果里 `saved=false`，按失败处理 |
| 复算不同 | 种子/全局状态/精度 | 固定种子、清 `$Context`、统一精度 |
