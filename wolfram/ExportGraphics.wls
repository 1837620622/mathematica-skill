#!/usr/bin/env wolframscript
(* ExportGraphics.wls — 从真实 Wolfram 表达式导出图和数据。
   PNG 由 Rasterize/Export 原生生成；Python 只负责检查文件，不重绘。 *)

$scriptDir = If[$InputFileName === "", Directory[], DirectoryName[ExpandFileName[$InputFileName]]];
Get[FileNameJoin[{$scriptDir, "MathematicaSkill.wl"}]];

args = msArgs[];
If[Length[args] < 4, msFail["INVALID_TASK", "usage: ExportGraphics.wls <task.json> <code.wl> <outDir> <result.json>"]];
{taskPath, codePath, outDir, resultPath} = Take[args, 4];

task = msReadJSON[taskPath];
If[! AssociationQ[task], msFail["INVALID_TASK", "task JSON must be an object"]];
If[! FileExistsQ[codePath], msFail["INVALID_TASK", "code file not found: " <> codePath]];
If[! DirectoryQ[outDir], CreateDirectory[outDir, CreateIntermediateDirectories -> True]];

taskDir = DirectoryName[ExpandFileName[taskPath]];
SetDirectory[taskDir];
SeedRandom[Lookup[task, "seed", 12345]];
$msArtifacts = ExpandFileName[outDir];
$msTaskDir = taskDir;
$MessageList = {};

(* 等比缩放后再用白边补齐到目标像素，绝不拉伸原图。 *)
fitImage[img_Image, width_Integer, height_Integer] := Module[
  {dims, scale, newDims, scaled, padX, padY},
  dims = ImageDimensions[img];
  If[! MatchQ[dims, {_Integer, _Integer}] || dims[[1]] <= 0 || dims[[2]] <= 0,
    Return[$Failed]
  ];
  scale = Min[width/dims[[1]], height/dims[[2]]];
  newDims = {Max[1, Round[dims[[1]] scale]], Max[1, Round[dims[[2]] scale]]};
  scaled = If[newDims === dims, img,
    Quiet[Check[ImageResize[img, newDims, "Bicubic"], $Failed]]
  ];
  If[scaled === $Failed || Head[scaled] =!= Image, Return[$Failed]];
  dims = ImageDimensions[scaled];
  If[dims === {width, height}, Return[scaled]];
  padX = width - dims[[1]];
  padY = height - dims[[2]];
  If[padX < 0 || padY < 0, Return[$Failed]];
  Quiet[Check[ImagePad[scaled,
    {{Floor[padX/2], Ceiling[padX/2]}, {Floor[padY/2], Ceiling[padY/2]}}, White], $Failed]]
];

load = Quiet[Check[Get[codePath], $Failed]];
If[load === $Failed, msFail["EVALUATION_FAILED", "loading computation code failed"]];

artifacts = {};
errors = {};
outputs = Lookup[task, "outputs", {}];

Do[
  Module[{id, filename, kind, expression, target, value, image, dimensions, exported, bytes,
          width, height},
    id = Lookup[output, "id", "output"];
    filename = Lookup[output, "filename", ""];
    kind = Lookup[output, "kind", "figure"];
    expression = Lookup[output, "expression", ""];
    width = Lookup[output, "width", 1600];
    height = Lookup[output, "height", 900];
    If[! IntegerQ[width] || width <= 0, width = 1600];
    If[! IntegerQ[height] || height <= 0, height = 900];
    If[filename === "" || expression === "",
      AppendTo[errors, <|"output" -> id, "message" -> "filename and expression are required"|>];
      Continue[]
    ];
    If[DirectoryName[filename] =!= "",
      AppendTo[errors, <|"output" -> id, "message" -> "filename must be flat: " <> filename|>];
      Continue[]
    ];
    target = FileNameJoin[{ExpandFileName[outDir], filename}];
    value = Quiet[Check[ToExpression[expression, InputForm], $Failed]];
    If[value === $Failed,
      AppendTo[errors, <|"output" -> id, "message" -> "expression did not evaluate: " <> expression|>];
      Continue[]
    ];
    (* 表达式自己 Export 过时返回值是文件名；这时绝不能拿路径当图去 Rasterize。 *)
    If[StringQ[value],
      If[FileExistsQ[value],
        value = Quiet[Check[Import[value, "Image"], $Failed]],
        AppendTo[errors, <|"output" -> id,
          "message" -> "expression returned a string, not graphics: " <> expression|>];
        Continue[]
      ]
    ];
    exported = $Failed;
    dimensions = Missing["NotApplicable"];
    Which[
      kind === "figure" && StringEndsQ[ToLowerCase[filename], ".png"],
        image = If[Head[value] === Image,
          fitImage[value, width, height],
          Quiet[Check[fitImage[
            Rasterize[value, "Image", Background -> White, ImageSize -> {width, height}],
            width, height], $Failed]]
        ];
        If[image === $Failed || Head[image] =!= Image,
          AppendTo[errors, <|"output" -> id, "message" -> "Rasterize did not produce an Image"|>];
          Continue[]
        ];
        dimensions = ImageDimensions[image];
        exported = Quiet[Check[Export[target, image, "PNG"], $Failed]],
      kind === "pdf" || StringEndsQ[ToLowerCase[filename], ".pdf"],
        exported = Quiet[Check[Export[target, value, "PDF"], $Failed]],
      kind === "csv" || StringEndsQ[ToLowerCase[filename], ".csv"],
        exported = Quiet[Check[Export[target, value, "CSV"], $Failed]],
      kind === "xlsx" || StringEndsQ[ToLowerCase[filename], ".xlsx"],
        exported = Quiet[Check[Export[target, value, "XLSX"], $Failed]],
      StringEndsQ[ToLowerCase[filename], ".svg"],
        exported = Quiet[Check[Export[target, value, "SVG"], $Failed]],
      StringEndsQ[ToLowerCase[filename], ".json"],
        exported = Quiet[Check[Export[target, msJsonSafe[value], "JSON"], $Failed]],
      StringEndsQ[ToLowerCase[filename], ".txt"],
        exported = Quiet[Check[Export[target, value, "Text"], $Failed]],
      True,
        exported = Quiet[Check[Export[target, value], $Failed]]
    ];
    If[exported === $Failed || ! FileExistsQ[target],
      AppendTo[errors, <|"output" -> id, "message" -> "native export failed"|>];
      Continue[]
    ];
    bytes = FileByteCount[target];
    AppendTo[artifacts, <|
      "id" -> id,
      "filename" -> filename,
      "kind" -> kind,
      "bytes" -> bytes,
      "width" -> If[ListQ[dimensions], dimensions[[1]], Null],
      "height" -> If[ListQ[dimensions], dimensions[[2]], Null]
    |>]
  ],
  {output, outputs}
];

result = <|
  "ok" -> errors === {},
  "error_code" -> If[errors === {}, "", "PLOT_EXPORT_FAILED"],
  "message" -> If[errors === {}, "all artifacts exported", "one or more artifacts failed"],
  "artifacts" -> artifacts,
  "errors" -> errors,
  "messages" -> msMessageText[$MessageList]
|>;
msWriteResult[resultPath, result];
