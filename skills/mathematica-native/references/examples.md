# 可运行示例

`examples/` 下的 JSON 都可以直接被 `mathematica-skill run` 执行。它们同时是回归测试的输入。

## 1. 最小闭环：正弦与定积分

文件：`examples/01-sine.json`

```bash
mathematica-skill run examples/01-sine.json --out work --seed 20261031
```

会得到：

- `computation.wl`：真实计算脚本
- `<title>.nb`：`Plot` 与 `Integrate` 的 Input 单元
- `artifacts/sine.png`：Wolfram `Rasterize` 导出的 1600×900 PNG
- `_validation/VALIDATION.md`：逐门禁记录

checks：

- `integral_exact`：`Integrate[Sin[x],{x,0,Pi}]` 等价于 `2`（符号比较）
- `sine_value`：`N[Sin[Pi/2]]` 等于 `1.0`（`1e-12` 容差）

## 2. 混沌系统：Lorenz 相图与 Lyapunov

文件：`examples/02-lorenz.json`

> 说明：`mathematica_compute` 与 `mathematica-skill compute` 启动时已经预加载 `DomainMethods.wl` 与 `PlotTheme.wl`，直接调用 `ms*` 函数即可，不需要下面的 `Get`。`run` 的计算脚本和 Notebook 目前都没有预加载；下面的 `Get` 写法只适用于在 Notebook 里手动运行，且要求库文件与 Notebook 位于同一目录，这一点尚未在真机验证。

```wl
Get["DomainMethods.wl"];
sol = msLorenzSolution[{10., 28., 8./3.}, {1., 1., 1.}, {0., 40.}];
series = msLorenzSeries[sol, 0., 40., 4000];
phase = ListLinePlot[series[[All, {1, 2}]], Frame -> True];
lyap = msLyapunovLorenz[{10., 28., 8./3.}, {1., 1., 1.}, 40., 0.01];
```

checks：

- `lyap_max`：最大 Lyapunov 指数落在 `[0.7, 1.1]`
- `series_length`：采样点数等于 4000
- `range_x`：`x` 的取值范围在 `[-30, 30]` 内

注意：Lyapunov 是统计量，容差要按 `tMax` 和 `dt` 放宽，别用 `1e-9`。

## 3. 时间序列：RQA 与 Hurst

文件：`examples/03-rqa.json`

```wl
Get["DomainMethods.wl"];
series = msLorenzSeries[msLorenzSolution[{10., 28., 8./3.}, {1., 1., 1.}, {0., 60.}], 0., 60., 2000];
x = series[[All, 1]];
rqa = msRqaMetrics[msRecurrenceMatrix[x, 3, 1]];
hurst = msHurstExponent[x, 64];
recPlot = msRecurrencePlot[msRecurrenceMatrix[x, 3, 1]];
```

checks：

- `rr_range`：`RR` 在 `[0.01, 0.5]`
- `det_range`：`DET` 在 `[0.5, 1.0]`（混沌序列对角线结构强）
- `hurst_range`：`H` 在 `[0.5, 1.0]`

## 4. 分形：盒计数维数

文件：`examples/04-boxcounting.json`

```wl
Get["DomainMethods.wl"];
img = Import["coastline.png"];          (* 通过 sources 一起带进来 *)
dim = msBoxCountingDimension[img, {2, 4, 8, 16, 32, 64}];
dim["dimension"]
```

checks：

- `dimension_range`：落在 `[1.0, 1.5]`（海岸线典型值）
- `rsquared`：`>= 0.98`

## 5. 数据导出

文件：`examples/05-data-export.json`

```wl
ts = Table[{t, Sin[t] Exp[-t/10]}, {t, 0, 20, 0.02}];
Export[FileNameJoin[{$msArtifacts, "series.csv"}], ts, "CSV"];
ListLinePlot[ts, Frame -> True]
```

`outputs` 里声明 `kind: "csv"` 和 `kind: "figure"`，两份都会检查（CSV 非空、PNG 尺寸）。

## 6. 失败示例（用来确认门禁真的会拦）

- `examples/bad-numeric.json`：期望值写错 → `NUMERIC_MISMATCH`
- `examples/bad-shell.json`：含 `RunProcess` → `POLICY_BLOCKED`
- `examples/bad-path.json`：`sources` 写成绝对路径 → `INVALID_TASK`

这些不该产生交付目录。用它们验证工具本身时，请确认 `work/` 下没有 `deliver/`。
