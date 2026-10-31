# 验证门禁与容差

## 1. 什么叫「验证通过」

只有下面每一项都是真的，`verified` 才能为 `true`：

| 门禁 | 检查内容 | 失败码 |
| --- | --- | --- |
| 内核 | 许可证可用，`1+1` 能算 | `ENGINE_NOT_FOUND` / `LICENSE_UNAVAILABLE` |
| 构造 | 每个 `task.code` 被 Mathematica 解析器接受 | `EVALUATION_FAILED` |
| 前端 | `.nb` 被真实前端打开、执行、保存、关闭、再打开 | `FRONTEND_UNAVAILABLE` / `NOTEBOOK_OPEN_FAILED` |
| 输出 | Input 单元执行后产生 Output 单元 | `NOTEBOOK_NO_OUTPUT` |
| 复算 | 新进程重新执行，逐项 checks 一致 | `NUMERIC_MISMATCH` |
| 图 | PNG 尺寸等于声明值，非空白，非单色，文件完整 | `PNG_INVALID` / `PNG_DIMENSIONS` |
| 数据 | PDF 有 `%PDF` 头，SVG 有根节点，CSV/XLSX 非空 | `PDF_INVALID` / `SVG_INVALID` |
| 交付 | 目录里只有白名单扩展名，无隐藏文件 | `DELIVERY_BLOCKED` |

任何一项失败都不产生“已验证”目录。

## 2. 检查类型与判定

| kind | 期望值 | 判定方式 |
| --- | --- | --- |
| `numeric` | 数字 | `Abs[a-b] <= abs_tol + rel_tol*Abs[b]` |
| `matrix` / `list` | 嵌套数组 | 形状相同 + 逐元素数值比较 |
| `range` | `[min, max]` | 落在闭区间内 |
| `boolean` | `true/false` | 布尔一致 |
| `string` | 字符串 | 精确相等 |
| `contains` | 字符串 | 子串包含 |
| `symbolic` / `exact` / `expression` | WL 表达式字符串 | `Simplify[a == b]` 为 `True` |

容差要按模型写，不要一律 `1e-9`：

- 精确整数/有理数 → `0`
- 双精度浮点 → `1e-10` 到 `1e-12`
- 长时 ODE 积分 → `1e-6` 到 `1e-4`
- 混沌系统（Lyapunov、RQA）→ 取决于采样长度，`1e-3` 到 `1e-2`

## 3. 复算策略

1. 第一次：`VerifyResults.wls task.json code.wl verify-1.json`
2. 第二次：`VerifyResults.wls task.json code.wl verify-2.json verify-1.json`
3. 第二次会额外比较每一项 `actual` 与第一次是否一致（`all_reproduced`）。

两次都在独立进程里执行，不复用全局状态。随机过程必须固定种子。

## 4. 随机过程的处理

- `SeedRandom[seed]`，seed 写进 task JSON。
- 跨平台比较用统计量（均值、方差、分位数）或固定容差，不比较逐像素。
- 记录内核版本：不同版本的随机数实现可能不同，这属于真实差异，不是“测试不稳定”。

## 5. 图像比较的正确方式

不要比较 PNG 字节哈希。正确做法：

- 图形先由真实表达式导出数据（`artifacts/data.csv`）。
- 对数据做数值比较。
- 对 PNG 只做结构性检查：尺寸、是否空白、颜色数、暗像素比例。
- 需要人眼判断的（文字重叠、图例压线）由 Agent 看真实截图后修复，并在报告里备注。

## 6. 报告

每次运行都会写：

```
work/<run>/_validation/validation.json
work/<run>/_validation/VALIDATION.md
```

`validation.json` 是机器可读的，包含 `findings`、`artifacts`、`checks`、`reproduction`、`native`。
`VALIDATION.md` 是给人看的，末尾固定有一段「Verification boundary」，说明这次到底证明了什么、
没证明什么。

## 7. 未验证时怎么写

- 没有 Mathematica：状态 `draft`，`verified=false`。
- 有内核无前端：可以出 `.wl` 计算和 PNG，但 `.nb` 不能标 verified。
- 有前端但复算不一致：状态 `blocked`，保留第一轮和第二轮的全部 JSON。
- 不要把 `--no-rerun` 的结果说成已验证。
