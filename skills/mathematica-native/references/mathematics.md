# 数学方法与参考基准

这一页列出 `wolfram/DomainMethods.wl` 里的原生实现、参数含义和基准值。所有函数都在真实内核里运行，
Python 从不实现这些算法。

```wl
Get["wolfram/PlotTheme.wl"];
Get["wolfram/DomainMethods.wl"];
```

## 1. 基础运算

直接用 Wolfram 自带函数，不重写：`Integrate`、`DSolve`、`NDSolve`、`Solve`、`Eigenvalues`、
`NIntegrate`、`Minimize`、`LinearModelFit`。要求是给出明确的工作精度和误差控制，例如

```wl
NIntegrate[Exp[-x^2], {x, -Infinity, Infinity}, WorkingPrecision -> 30, PrecisionGoal -> 20]
```

## 2. Logistic 映射与 Lyapunov 指数

```wl
msLogisticMap[r, x0, n, skip]        (* 轨道，跳过前 skip 个瞬态 *)
msLogisticLyapunov[r, x0, n, skip]   (* 一维映射的 Lyapunov 指数 *)
```

基准：`r = 4` 时 Lyapunov 指数 = `Log[2] ≈ 0.6931`。测试容差 `1e-3`。
注意 `r = 4` 时 `x = 0` 与 `x = 1` 会落到不动点，必须避开这类初值。

## 3. Lorenz 系统

```wl
msLorenzSolution[{sigma, rho, beta}, {x0, y0, z0}, {t0, t1}, opts]
msLorenzSeries[sol, t0, t1, n]
msPhaseSpace[series, {1, 2}]
msLyapunovLorenz[{sigma, rho, beta}, init, tMax, dt]
```

- 默认 `MaxStepSize -> 0.01`，可用 `opts` 覆盖。
- 经典参数 `{10, 28, 8/3}` 是混沌区，Lyapunov 谱约为 `{0.906, 0, -14.57}`（数量级参考，随积分长度变化）。
- `msLyapunovLorenz` 用变分方程 + 每步 QR 分解（Gram-Schmidt 等价），避免切向量模长发散。
  参数敏感：`tMax` 太短会低估，`dt` 太大在 `rho = 28` 时不稳定。建议 `tMax >= 50`、`dt <= 0.01`。

## 4. 延迟嵌入与递归定量分析（RQA）

```wl
msDelayEmbed[series, emb, tau]
msRecurrenceMatrix[series, emb, tau, eps, theiler]
msRecurrencePlot[matrix]
msRqaMetrics[matrix, lmin]
```

- `emb` 嵌入维数，`tau` 延迟，常用 `emb = 3`、`tau = 1`；选取应参照互信息/虚假近邻法，不要拍脑袋。
- `eps` 默认取距离分布的 10% 分位数，这是可解释的固定规则，不是「最优阈值」。
- `theiler` 默认 1，用于排除主对角线附近的自匹配。
- 指标定义：
  - `RR = 递归点数 / (N(N-1))`
  - `DET = 长度 >= lmin 的对角线总长度 / 全部对角线长度`
  - `ENTR` = 对角线段长度分布的 Shannon 熵
- 边界：`msRqaMetrics` 的 `RR` 对完全周期信号接近 1，对白噪声接近 `eps` 决定的水平。

## 5. Hurst 指数

```wl
msHurstExponent[series, maxLag]
```

用结构函数 `tau(lag) = sqrt(mean((x(t+lag)-x(t))^2))`，对 `log tau` 与 `log lag` 做线性拟合，
斜率即 `H`。基准：标准布朗运动 `H ≈ 0.5`；分数布朗运动按自身 `H` 生成时应在 `±0.05` 内。
`maxLag` 不要超过 `Length[series]/2`，否则样本太少、拟合虚高。

## 6. 几何布朗运动与金融时间序列

```wl
msGeometricBrownianMotion[mu, sigma, s0, tMax, steps, seed]
msReturns[series]
msAnnualizedVolatility[series, periodsPerYear]
```

- 路径按 `S(t+dt) = S(t) exp((mu - sigma^2/2) dt + sigma sqrt(dt) Z)` 生成。
- 固定 `SeedRandom`，并把 seed 写进 task JSON；跨机器复现要求同一内核版本与同一随机数实现。
- 年化波动率用对数收益率标准差乘 `sqrt(periodsPerYear)`，`periodsPerYear` 必须与数据频率一致。

## 7. 盒计数维数

```wl
msBoxCounts[image, sizes, foreground]
msBoxCountingDimension[image, sizes, foreground]
```

- 图像先转灰度，按阈值二值化，然后统计每个尺度下被占用的盒子数。
- 基准：填满的 256×256 黑图，`sizes = {2,4,8,16,32}` 时应得到维度 `≈ 2.00`（容差 0.02）。
- 海岸线这类真实分形要在 log-log 图上挑线性区间，`rsquared` 会一并返回。
- 有限尺度偏差真实存在：小尺度受像素量化限制，大尺度受图像边界限制，报告里要写出所选区间。

## 8. 组合用法

时间序列作业的典型链路：

```wl
data = Import["coastline.png"];
dim = msBoxCountingDimension[data, {2, 4, 8, 16, 32, 64}];

series = msLorenzSeries[msLorenzSolution[{10., 28., 8./3.}, {1., 1., 1.}, {0., 100.}], 0., 100., 2000];
lyap = msLyapunovLorenz[{10., 28., 8./3.}, {1., 1., 1.}, 60., 0.01];
rqa = msRqaMetrics[msRecurrenceMatrix[series[[All, 1]], 3, 1]];
```

## 9. 不做的事

- 不把「曲线看起来像」当作算法正确。
- 不隐藏发散、`$Failed`、`Indeterminate` 或数值警告；这些必须出现在验收报告里。
- 不在没有基准的情况下宣称自研算法有效；至少要和一个可靠方法对照。
