(* ::Package:: *)
(* PlotTheme.wl — 学术风格原生绘图主题。
   只对真实 Wolfram Graphics 对象做样式增强，不改变数据，也不重绘。 *)

BeginPackage["MathematicaSkill`PlotTheme`"];

msAcademicOptions::usage = "msAcademicOptions[] 返回统一的学术图形选项；传 \"zh\" 使用中文字体。";
msAcademicFonts::usage = "msAcademicFonts[lang] 返回当前系统上可用的字体设置。";
msPickFont::usage = "msPickFont[list] 从候选字体里挑一个本机真有的。";
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

(* 中文图必须用带中文字形的字体，否则就是一片方框；按平台顺序挑第一个装了的。 *)
msCJKFonts = {"PingFang SC", "Hiragino Sans GB", "Heiti SC", "Songti SC",
              "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Source Han Sans SC",
              "WenQuanYi Micro Hei", "Arial Unicode MS"};
msLatinFonts = {"Helvetica", "Arial", "DejaVu Sans", "Liberation Sans"};

msPickFont[candidates_List] := Module[{available, hit},
  available = Quiet[Check[$FontFamilies, {}]];
  If[! ListQ[available] || available === {},
    Return[First[candidates]]
  ];
  hit = SelectFirst[candidates, MemberQ[available, #] &, ""];
  If[hit === "", First[candidates], hit]
];

msAcademicFonts[lang_String: "en"] := Module[{family},
  family = If[lang === "zh", msPickFont[msCJKFonts], msPickFont[msLatinFonts]];
  {FontFamily -> family, FontSize -> 11, GrayLevel[0.15]}
];

msAcademicOptions[lang_String: "en"] := {
  Frame -> True,
  FrameStyle -> Directive[AbsoluteThickness[0.8], GrayLevel[0.25]],
  FrameTicksStyle -> Directive[GrayLevel[0.25], FontSize -> 10],
  Axes -> False,
  BaseStyle -> msAcademicFonts[lang],
  LabelStyle -> msAcademicFonts[lang],
  PlotStyle -> msAcademicPalette[6],
  PlotRangePadding -> Scaled[0.02],
  ImagePadding -> {{55, 18}, {48, 18}},
  ImageSize -> 520,
  GridLines -> None,
  PlotLegends -> None
};

msAcademicFigure[g_Graphics, lang_String: "en"] := Show[g, Sequence @@ msAcademicOptions[lang]];
msAcademicFigure[g_Graphics3D, lang_String: "en"] := Show[g,
  Boxed -> True,
  Axes -> True,
  AxesLabel -> Automatic,
  BaseStyle -> msAcademicFonts[lang],
  ImageSize -> 520
];
msAcademicFigure[other_, _String: "en"] := other;

msPanelFigure[graphics_List, opts___Rule] := GraphicsGrid[
  Partition[Map[msAcademicFigure[#, "en"] &, graphics], UpTo[2]],
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
