(* ::Package:: *)
(* DomainMethods.wl — 课程与科研常用的原生方法库。
   所有方法都给出明确的输入、参数和参考检验；不假装是官方算法，也不伪造结果。 *)

BeginPackage["MathematicaSkill`DomainMethods`"];

msLogisticMap::usage = "msLogisticMap[r, x0, n, skip] 生成 Logistic 轨道。";
msLogisticLyapunov::usage = "msLogisticLyapunov[r, x0, n, skip] 计算 Logistic 映射的 Lyapunov 指数。";
msLorenzSolution::usage = "msLorenzSolution[params, init, {t0, t1}] 求解 Lorenz 方程。";
msLorenzSeries::usage = "msLorenzSeries[sol, t0, t1, n] 在等距时间点采样 Lorenz 解。";
msPhaseSpace::usage = "msPhaseSpace[series, indices] 提取相空间坐标。";
msLyapunovLorenz::usage = "msLyapunovLorenz[params, init, tMax, dt] 用变分方程和 QR 分解估计三个 Lyapunov 指数。";
msRecurrenceMatrix::usage = "msRecurrenceMatrix[series, emb, tau, eps, theiler] 生成递归矩阵。";
msRecurrencePlot::usage = "msRecurrencePlot[matrix] 画原生递归图。";
msRqaMetrics::usage = "msRqaMetrics[matrix, lmin] 计算 RR、DET、ENTR。";
msHurstExponent::usage = "msHurstExponent[series, maxLag] 用结构函数估计 Hurst 指数。";
msGeometricBrownianMotion::usage = "msGeometricBrownianMotion[mu, sigma, s0, tMax, steps] 生成 GBM 路径。";
msReturns::usage = "msReturns[series] 计算对数收益率。";
msAnnualizedVolatility::usage = "msAnnualizedVolatility[series, periodsPerYear] 计算年化波动率。";
msBoxCounts::usage = "msBoxCounts[image, sizes, foreground] 统计盒计数。";
msBoxCountingDimension::usage = "msBoxCountingDimension[image, sizes, foreground] 拟合盒计数维数。";
msDomainSelfTest::usage = "msDomainSelfTest[] 用已知参考值跑原生自检。";

Begin["`Private`"];

msLogisticMap[r_, x0_, n_Integer, skip_Integer: 1000] := Drop[
  NestList[r # (1 - #) &, N[x0], n + skip],
  skip
];

msLogisticLyapunov[r_, x0_, n_Integer, skip_Integer: 1000] := Module[{orbit, derivatives},
  orbit = msLogisticMap[r, x0, n, skip];
  derivatives = r (1 - 2 Most[orbit]);
  Mean[Log[Abs[Select[derivatives, Abs[#] > 1.*^-12 &]]]]
];

msLorenzSolution[{sigma_, rho_, beta_}, init_List, {t0_, t1_}, opts___Rule] := NDSolveValue[
  {
    x'[t] == sigma (y[t] - x[t]),
    y'[t] == x[t] (rho - z[t]) - y[t],
    z'[t] == x[t] y[t] - beta z[t],
    x[t0] == init[[1]], y[t0] == init[[2]], z[t0] == init[[3]]
  },
  {x, y, z},
  {t, t0, t1},
  Sequence @@ Join[{MaxStepSize -> 0.01}, {opts}]
];

msLorenzSeries[sol_, t0_, t1_, n_Integer] := Table[
  Through[sol[t]],
  {t, t0, t1, (t1 - t0)/Max[n - 1, 1]}
];

msPhaseSpace[series_List, indices_List: {1, 2}] := series[[All, indices]];

msLyapunovLorenz[{sigma_, rho_, beta_}, init_List, tMax_, dt_] := Module[
  {state, q, sums, steps, end, qr, i, localState, matrix},
  state = N[init];
  q = IdentityMatrix[3];
  sums = {0., 0., 0.};
  steps = Max[1, Round[tMax/dt]];
  Do[
    (* 每一步同时积分状态和三个切向量；切向量组成 3x3 矩阵 Q。
       用 QR 分解正交化，累加 log|R 对角线|，避免切向量长度爆炸。 *)
    localState = NDSolveValue[
      {
        x'[t] == sigma (y[t] - x[t]),
        y'[t] == x[t] (rho - z[t]) - y[t],
        z'[t] == x[t] y[t] - beta z[t],
        x[0] == state[[1]], y[0] == state[[2]], z[0] == state[[3]],
        d1'[t] == (-sigma) d1[t] + sigma d2[t],
        d2'[t] == (rho - z[t]) d1[t] - d2[t] - x[t] d3[t],
        d3'[t] == y[t] d1[t] + x[t] d2[t] - beta d3[t],
        e1'[t] == (-sigma) e1[t] + sigma e2[t],
        e2'[t] == (rho - z[t]) e1[t] - e2[t] - x[t] e3[t],
        e3'[t] == y[t] e1[t] + x[t] e2[t] - beta e3[t],
        f1'[t] == (-sigma) f1[t] + sigma f2[t],
        f2'[t] == (rho - z[t]) f1[t] - f2[t] - x[t] f3[t],
        f3'[t] == y[t] f1[t] + x[t] f2[t] - beta f3[t],
        d1[0] == q[[1, 1]], d2[0] == q[[2, 1]], d3[0] == q[[3, 1]],
        e1[0] == q[[1, 2]], e2[0] == q[[2, 2]], e3[0] == q[[3, 2]],
        f1[0] == q[[1, 3]], f2[0] == q[[2, 3]], f3[0] == q[[3, 3]]
      },
      {x, y, z, d1, d2, d3, e1, e2, e3, f1, f2, f3},
      {t, 0, dt}
    ];
    end = Through[localState[dt]];
    state = end[[1 ;; 3]];
    matrix = Transpose[Partition[end[[4 ;; 12]], 3]];
    qr = QRDecomposition[matrix];
    sums = sums + Log[Abs[Diagonal[qr[[2]]]] + 1.*^-30];
    q = qr[[1]];
    , {i, steps}
  ];
  sums/(steps dt)
];

msDelayEmbed[series_List, emb_Integer, tau_Integer] := Table[
  series[[i ;; i + (emb - 1) tau]],
  {i, 1, Length[series] - (emb - 1) tau}
];

msRecurrenceMatrix[series_List, emb_Integer: 3, tau_Integer: 1, eps_: Automatic, theiler_Integer: 1] := Module[
  {embedded, threshold, distances, matrix},
  embedded = msDelayEmbed[series, emb, tau];
  If[Length[embedded] < 3, Return[$Failed]];
  distances = Outer[Norm[#1 - #2] &, embedded, embedded, 1];
  threshold = If[eps === Automatic, 0.1 Quantile[Flatten[distances], 0.1], eps];
  matrix = Boole[Map[# <= threshold &, distances, {2}]];
  Do[
    matrix[[i, j]] = 0;
    matrix[[j, i]] = 0,
    {i, 1, Length[matrix]}, {j, Max[1, i - theiler], Min[Length[matrix], i + theiler]}
  ];
  matrix
];

msRecurrencePlot[matrix_?MatrixQ] := MatrixPlot[
  matrix,
  ColorFunction -> (If[# == 1, RGBColor[0.09, 0.22, 0.36], White] &),
  ColorFunctionScaling -> False,
  Frame -> True,
  FrameLabel -> {"i", "j"},
  ImageSize -> 480
];

msRunLengths[line_List] := Module[{runs = {}, current = 0},
  Do[
    If[line[[i]] == 1,
      current++,
      If[current > 0, AppendTo[runs, current]; current = 0]
    ],
    {i, Length[line]}
  ];
  If[current > 0, AppendTo[runs, current]];
  runs
];

msRqaMetrics[matrix_?MatrixQ, lmin_Integer: 2] := Module[
  {n, rr, diagonals, lengths, kept, counts, probabilities, det, enTR},
  n = Length[matrix];
  rr = Total[Flatten[matrix]]/(n (n - 1));
  diagonals = Table[Diagonal[matrix, k], {k, -(n - 1), n - 1}];
  lengths = Flatten[msRunLengths /@ diagonals];
  kept = Select[lengths, # >= lmin &];
  det = If[Total[lengths] == 0, 0., Total[kept]/Total[lengths]];
  counts = Tally[kept];
  probabilities = If[Total[kept] == 0, {}, counts[[All, 2]]/Total[kept]];
  enTR = If[probabilities === {}, 0., -Total[probabilities Log[probabilities]]];
  <|"RR" -> rr, "DET" -> det, "ENTR" -> enTR, "lmin" -> lmin,
    "diagonal_lengths" -> kept, "n" -> n|>
];

msHurstExponent[series_List, maxLag_Integer: 64] := Module[
  {values, lags, taus, fit},
  values = N[series];
  lags = Range[2, Min[maxLag, Quotient[Length[values], 2]]];
  taus = Table[
    Sqrt[Mean[(values[[lag + 1 ;;]] - values[[;; -lag - 1]])^2]],
    {lag, lags}
  ];
  fit = LinearModelFit[Transpose[{Log[lags], Log[taus]}], x, x];
  <|"H" -> fit["BestFitParameters"][[2]], "lags" -> lags,
    "tau" -> taus, "fit" -> fit["BestFitParameters"]|>
];

msGeometricBrownianMotion[mu_, sigma_, s0_, tMax_, steps_Integer, seed_Integer: 12345] := Module[
  {dt, shocks, increments, path},
  SeedRandom[seed];
  dt = N[tMax/steps];
  shocks = RandomVariate[NormalDistribution[], steps];
  increments = (mu - sigma^2/2) dt + sigma Sqrt[dt] shocks;
  path = s0 Exp[Accumulate[increments]];
  Prepend[path, s0]
];

msReturns[series_List] := Differences[Log[N[series]]];

msAnnualizedVolatility[series_List, periodsPerYear_: 252] :=
  StandardDeviation[msReturns[series]] Sqrt[periodsPerYear];

msBoxCounts[image_Image, sizes_List, foreground_String: "Dark"] := Module[
  {gray, mask, height, width},
  gray = ImageData[ColorConvert[image, "Grayscale"]];
  mask = Boole[If[ToLowerCase[foreground] === "light", gray, 1. - gray] > 0.5];
  {height, width} = Dimensions[mask];
  Table[
    Total[Flatten[Table[
      If[Total[Flatten[mask[[i ;; Min[i + size - 1, height],
                              j ;; Min[j + size - 1, width]]]]] > 0, 1, 0],
      {i, 1, height, size}, {j, 1, width, size}
    ]]],
    {size, sizes}
  ]
];

msBoxCountingDimension[image_Image, sizes_List, foreground_String: "Dark"] /; Length[sizes] >= 2 := Module[
  {counts, usable, fit},
  counts = msBoxCounts[image, sizes, foreground];
  usable = Select[Transpose[{sizes, counts}], #[[2]] > 0 &];
  If[Length[usable] < 2, Return[Missing["NotEnoughScales"]]];
  fit = LinearModelFit[
    Transpose[{Log[1./usable[[All, 1]]], Log[N[usable[[All, 2]]]]}], x, x
  ];
  <|"dimension" -> -fit["BestFitParameters"][[2]],
    "intercept" -> fit["BestFitParameters"][[1]],
    "rsquared" -> fit["RSquared"],
    "sizes" -> usable[[All, 1]], "counts" -> usable[[All, 2]]|>
];

msDomainSelfTest[] := Module[{checks = {}, logisticExponent, squareImage, boxResult, lorenz, gbm},
  SeedRandom[12345];
  logisticExponent = msLogisticLyapunov[4., 0.123456, 200000, 1000];
  AppendTo[checks, <|"name" -> "logistic_lyapunov", "value" -> logisticExponent,
    "expected" -> Log[2.], "tolerance" -> 1.*^-3,
    "passed" -> TrueQ[Abs[logisticExponent - Log[2.]] < 1.*^-3]|>];

  squareImage = Image[ConstantArray[0., {256, 256}]];
  boxResult = msBoxCountingDimension[squareImage, {2, 4, 8, 16, 32}];
  AppendTo[checks, <|"name" -> "box_counting_square", "value" -> boxResult["dimension"],
    "expected" -> 2., "tolerance" -> 0.02,
    "passed" -> TrueQ[Abs[boxResult["dimension"] - 2.] < 0.02]|>];

  lorenz = msLorenzSeries[msLorenzSolution[{10., 28., 8./3.}, {1., 1., 1.}, {0., 1.}], 0., 1., 101];
  AppendTo[checks, <|"name" -> "lorenz_length", "value" -> Length[lorenz],
    "expected" -> 101, "tolerance" -> 0,
    "passed" -> Length[lorenz] === 101 && MatrixQ[lorenz, NumberQ]|>];

  gbm = msGeometricBrownianMotion[0.05, 0.2, 100., 1., 252];
  AppendTo[checks, <|"name" -> "gbm_length", "value" -> Length[gbm],
    "expected" -> 253, "tolerance" -> 0,
    "passed" -> Length[gbm] === 253 && AllTrue[gbm, Positive]|>];

  <|"ok" -> And @@ Lookup[checks, "passed"], "checks" -> checks|>
];

End[];
EndPackage[];
