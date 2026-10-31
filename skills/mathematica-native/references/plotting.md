# 原生绘图与 4K 输出

## 1. 主题

`wolfram/PlotTheme.wl` 提供三套主题：

- `"Academic"`：白底、细线、Frame、色盲友好、论文风。
- `"Report"`：白底、略粗线、适合课程报告。
- `"Presentation"`：更大字号、更高对比度。

```wl
Get["PlotTheme.wl"];
g = msAcademicFigure[
  Plot[{Sin[x], Cos[x]}, {x, 0, 2 Pi},
    Frame -> True,
    FrameLabel -> {"x", "y"},
    PlotLegends -> {"sin x", "cos x"}],
  "Academic"];
msExportFigure[g, "/absolute/path/figure.png", 3840, 2160];
```

## 2. 基本规范

- 默认白底，不用渐变、阴影、3D 装饰。
- 统一字体：英文/数字用系统无衬线；中文用 PingFang SC / Noto Sans CJK。
- 轴标签写清变量和单位：`"时间 t / s"`、`"速度 v / (m s^-1)"`。
- 刻度有效数字和量级合理；必要时用 `ScientificForm`。
- 曲线颜色色盲友好，线型也能区分。
- 图例放空白处，避免压曲线。
- 多面板用 `GraphicsGrid`/`Grid`，统一 `ImagePadding` 和字号。
- 不通过平滑掩盖离散突变。

## 3. 4K 与向量

- 4K 按实际像素验收：`ImageDimensions[image] == {3840, 2160}`。
- 不要用低分辨率图放大；`Rasterize` 时直接给目标尺寸。
- PNG 走 `Rasterize[graphic, "Image", RasterSize -> {w, h}, Background -> White]`，再 `Export[..., "PNG"]`。
- PDF/SVG 走 `Export[..., graphic, "PDF"/"SVG"]`。
- 图中有位图元素时，不要宣称「全矢量」。

## 4. 自动检查

`mathematica_skill/plotqa.py` 只读检查：

- PNG 签名、IHDR、CRC、IDAT 可解压。
- 实际宽高是否等于声明尺寸。
- 是否几乎空白（单一颜色占比过高）。
- 是否有足够多的颜色/暗像素。
- 文件是否 0 字节或损坏。

它不会重绘、不会改图、不会用 Python 生成最终图。

## 5. 人工/Agent 视觉复核

自动检查通过后，仍应看真实导出的 PNG：

- 文字有没有被裁切。
- 图例有没有压线。
- 坐标轴标签是否完整。
- 数学符号是否显示。
- 多图是否对齐。
- 曲线是否在合理范围。

截图只用于检查界面效果，不代替原生数据检查。
