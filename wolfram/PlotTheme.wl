(* ::Package:: *)
(* PlotTheme.wl — 学术风格原生绘图主题。
   只对真实 Wolfram Graphics 对象做样式增强，不改变数据，也不重绘。 *)

BeginPackage["MathematicaSkill`PlotTheme`"];

msAcademicOptions::usage = "msAcademicOptions[] 返回统一的学术图形选项。";
msAcademicFigure::usage = "msAcademicFigure[g] 给真实 Graphics 应用学术样式。";
msAcademicPalette::usage = "msAcademicPalette[n] 返回色盲友好的 n 色配色。";
msExportFigure::usage = "msExportFigure[g, path, width, height] 原生栅格化并导出 PNG。";
msPanelFigure::usage = "msPanelFigure[list, opts] 把多个真实图形排成对齐的面板。";
msFigurePresets::usage = "msFigurePresets 是常用像素尺寸。";

Begin["`Private`"];

msFigurePresets = <|
  "hd" -> {1920, 1080},
  "fullhd" -> {1920, 1080},
  "4k" -> {3840, 2160},
  "4k-portrait" -> {2160, 3840},
  "a4-300" -> {2480, 3508},
  "a4-landscape-300" -> {3508, 2480}
|>;

msAcademicPalette[n_Integer] := Take[
  {
    RGBColor[0.121, 0.466, 0.705],
    RGBColor[0.890, 0.466, 0.109],
    RGBColor[0.172, 0.627, 0.172],
    RGBColor[0.839, 0.152, 0.156],
    RGBColor[0.580, 0.403, 0.741],
    RGBColor[0.549, 0.337, 0.294],
    RGBColor[0.890, 0.467, 0.761],
    RGBColor[0.498, 0.498, 0.498],
    RGBColor[0.737, 0.741, 0.133],
    RGBColor[0.090, 0.745, 0.811]
  },
  Min[Max[n, 1], 10]
];

msAcademicOptions[] := {
  Frame -> True,
  FrameStyle -> Directive[AbsoluteThickness[0.8], GrayLevel[0.25]],
  FrameTicksStyle -> Directive[GrayLevel[0.25], FontSize -> 10],
  Axes -> False,
  BaseStyle -> {FontFamily -> "Helvetica", FontSize -> 11, GrayLevel[0.15]},
  LabelStyle -> {FontFamily -> "Helvetica", FontSize -> 11, GrayLevel[0.15]},
  PlotStyle -> msAcademicPalette[6],
  PlotRangePadding -> Scaled[0.02],
  ImagePadding -> {{55, 18}, {48, 18}},
  ImageSize -> 520,
  GridLines -> None,
  PlotLegends -> None
};

msAcademicFigure[g_Graphics] := Show[g, Sequence @@ msAcademicOptions[]];
msAcademicFigure[g_Graphics3D] := Show[g,
  Boxed -> True,
  Axes -> True,
  AxesLabel -> Automatic,
  BaseStyle -> {FontFamily -> "Helvetica", FontSize -> 11},
  ImageSize -> 520
];
msAcademicFigure[other_] := other;

msPanelFigure[graphics_List, opts___Rule] := GraphicsGrid[
  Partition[Map[msAcademicFigure, graphics], UpTo[2]],
  Spacings -> {0.8, 0.8},
  Frame -> None,
  opts
];

msExportFigure[g_, path_String, width_Integer, height_Integer] := Module[{styled, image, directory},
  styled = msAcademicFigure[g];
  image = Rasterize[styled, "Image", RasterSize -> {width, height}, Background -> White];
  If[Head[image] =!= Image,
    Return[$Failed]
  ];
  directory = DirectoryName[path];
  If[directory =!= "" && ! DirectoryQ[directory],
    CreateDirectory[directory, CreateIntermediateDirectories -> True]
  ];
  Export[path, image, "PNG"];
  image
];

End[];
EndPackage[];
