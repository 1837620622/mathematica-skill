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

## 4. 修改旧 Notebook（`edit`）

`wolfram/EditNotebook.wls` 在既有 `.nb` 上做定点修改，其余单元与样式原样保留：

| 操作 | 含义 |
| --- | --- |
| `replace_cell` | 把第 n 个单元换成新的 Input 单元 |
| `insert_after` | 在第 n 个单元后插入指定样式的单元 |
| `delete_cell` | 删除第 n 个单元 |
| `append_input` / `append_text` / `append_section` / `append_subsection` | 追加到文末 |
| `title` | 替换或补上标题单元 |
| `language` | 只翻转固定标题（Problem↔题目、Assumptions↔假设、Output:↔输出：） |

序号按**文档顺序**数，支持 `CellGroupData` 嵌套；越界会返回 `INVALID_TASK` 而不是乱改。

### 语言判定（`language: "auto"`）

`.nb` 是 7-bit ASCII 格式，中文存成 `\:4e2d` 这样的转义；判语言前必须先解码。
判定规则：

- 题目（`prompt` / `notes` / `subject` / `title` / `assumptions`）：汉字 >= 8 且占比 >= 15% 判中文。
- `sources` 里的 `.nb`：汉字 >= 8，且「中文片段 vs 英文句子」占比 >= 25% 判中文，
  这样英文作业里引用一句中文不会翻转语言。
- 代码字符串不算英文正文（含 `[]{};=<>|&_$` 的字面量被排除），所以代码很多的中文作业仍然判中文。

### 不乱码的三道保险

1. 写 `.nb` 用 `Export[..., "NB"]`，由 Mathematica 自己生成转义，中文/日文/公式都不会坏。
2. 写完立刻 `Import` 回来，确认用户提供的每个字符串（含多行代码）都能原样读到；
   比较时忽略空白与换行，只比可见字符。
3. Python 侧再检查一遍：文件必须是合法 UTF-8、不能含 U+FFFD、Input 单元数不能凭空消失、
   不能新增本机绝对路径或开发标记。任一不满足 → `ENCODING_MISMATCH` / `EVALUATION_FAILED`。

### 安全

- 默认另存新文件；`--in-place` 才覆盖，且先写 `.nb.<stamp>.bak`。
- 源文件不是 UTF-8 时直接拒绝，不做「尽力修复」。
- 图片、样式、单元选项不重建，只替换目标单元。

## 5. 修改旧 Notebook（手工流程）

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
