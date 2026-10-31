# 工作流与状态机

## 1. 设计原则

这套 Skill 把「写代码」和「证明代码真的跑过」分开：

- Agent 负责理解题目、写 Wolfram Language、解释结果。
- Python 负责创建隔离工作区、复制输入、调用 `wolframscript`/内核、收集产物、比较数值、执行交付白名单。
- 最终数学结果只能来自 Wolfram 内核；最终图形只能来自 Wolfram 图形对象。
- 任何一步失败都保留失败状态和错误码，不能把 `draft` 伪装成 `verified`。

## 2. 目录

```text
work/<run-id>/
├── input/
│   ├── task.json          # 规范化后的内部任务（与 sources 同目录，Import 才找得到）
│   └── <sources…>         # 原任务 JSON 与声明的数据文件副本
├── computation.wl         # 从所有 task.code 拼出的计算脚本
├── <title>.nb             # 交付候选 Notebook
├── artifacts/             # 原生导出的 PNG/PDF/CSV/XLSX
├── rerun/                 # 独立复算用的 Notebook 副本
├── _validation/
│   ├── validation.json    # 机器可读验收报告
│   └── VALIDATION.md      # 人可读验收报告
└── deliver/<name>/        # 只有通过门禁才出现
```

`input/`、`artifacts/`、`rerun/`、`_validation/` 都是内部目录，不进入客户交付目录。

## 3. 阶段

| 阶段 | 输入 | 输出 | 失败后果 |
| --- | --- | --- | --- |
| intake | 原始任务 JSON | 源文件哈希、字节数 | 直接失败 |
| inspect | 隔离副本 | sources 清单、checks 数量 | 缺 source 或没有任何 check 阻断（`CHECKS_EMPTY`） |
| plan | tasks/outputs | 结构化计划 | 重名、未知 output 阻断 |
| lint | WL 代码 | 词法/括号/政策检查 | 有 error 阻断 |
| preflight | 环境 | doctor 结果 | 无内核只能 draft；前端不可用不能 verified |
| native_build | task.json + code.wl | 原生 `.nb` | 语法错误阻断 |
| native_evaluate | `.nb` | Output 单元、消息、耗时 | 前端失败阻断 |
| export | 真实表达式 | PNG/PDF/CSV/XLSX | 导出失败阻断 |
| close/reopen | 交付候选 `.nb` | 重新打开证据 | 打不开阻断 |
| rerun | `.nb` 副本 | 独立执行证据 | 失败阻断 |
| compare | 两次 checks | 逐项复现结果 | 不一致阻断 |
| review | 全部产物 | validation.json/md | error 阻断 |
| deliver | 白名单 | deliver 目录 + manifest | 不在白名单阻断 |

## 4. 断点与重试

- 每次运行有独立 `run-id`，不覆盖已完成的历史运行。
- `--out` 指向工作根目录；相同标题不会复用旧目录。
- `--overwrite` 只影响交付目录，不影响原始输入。
- 语法错误重试必须重新走 `lint`，不能直接改 `.nb` 内部结构绕过检查。
- 数值不一致不自动重试；先修模型、参数、容差或随机种子。
- 超时由 `--timeout`（内核）和 `--frontend-timeout`（前端）分别控制。

## 5. 常用调用

```bash
# 只看计划，不执行
mathematica-skill plan task.json

# 没有 Mathematica 时生成未验证草稿
mathematica-skill build task.json --draft

# 完整原生流水线
mathematica-skill run task.json --out work --seed 20261031

# 只重跑原生对账
mathematica-skill verify task.json --code work/run/computation.wl --out verify-2.json --previous verify-1.json
```

## 6. 错误码含义

| 错误码 | 含义 | 处理 |
| --- | --- | --- |
| `INVALID_TASK` | JSON 结构、id、output、check 不合法 | 修 JSON |
| `ENCODING_MISMATCH` | 编辑后文字无法原样读回 | 检查字体/编码，改回 UTF-8 |
| `UNSAFE_PATH` | 路径逃逸、绝对路径、Windows 保留名 | 改成相对路径/可移植名 |
| `ENGINE_NOT_FOUND` | 找不到内核或 wolframscript | 安装 Mathematica/Wolfram Engine |
| `LICENSE_UNAVAILABLE` | 内核存在但许可证不可用 | 在 Mathematica 里激活；不要绕过 |
| `FRONTEND_UNAVAILABLE` | 无桌面前端或无法启动 | 在登录的桌面会话运行，或只交 draft |
| `NOTEBOOK_OPEN_FAILED` | `.nb` 无法打开 | 检查生成器和文件完整性 |
| `EVALUATION_FAILED` | 代码执行失败/超时/`$Failed` | 看单元格、消息、日志 |
| `PLOT_EXPORT_FAILED` | 原生图/数据导出失败 | 检查表达式和 Export 格式 |
| `NUMERIC_MISMATCH` | check 不通过或复算不一致 | 修模型/容差/种子 |
| `DELIVERY_BLOCKED` | 白名单或门禁失败 | 看 validation 报告 |

## 7. 不做的事

- 不用 SymPy/NumPy/SciPy/Matplotlib 生成最终结果。
- 不把 PNG 塞进 `.nb` 冒充计算输出。
- 不把 `WriteNotebook` 的写入成功当成执行成功。
- 不在没有前端时把 `notebook_roundtrip_passed` 写成 true。
- 不删测试、不忽略消息来换绿色结果。
