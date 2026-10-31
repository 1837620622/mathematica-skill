#!/usr/bin/env wolframscript
(* ComputeCode.wls — 快速计算：执行一段 Wolfram Language，返回最后一个表达式的值。
   结果写入 result.json；图形结果只导出到内部工作目录，是否复制出去由 Python 决定。
   这里不做策略检查（那是 Python 的职责），也不生成任何交付物。 *)

$scriptDir = If[$InputFileName === "", Directory[], DirectoryName[ExpandFileName[$InputFileName]]];
Get[FileNameJoin[{$scriptDir, "MathematicaSkill.wl"}]];

args = msArgs[];
If[Length[args] < 4,
  msFail["INVALID_TASK", "usage: ComputeCode.wls <code.wl> <result.json> <figure.png> <workdir> [maxSeconds]"]
];
{codePath, resultPath, figurePath, workDir} = Take[args, 4];
maxSeconds = If[Length[args] >= 5, Quiet[Check[ToExpression[args[[5]]], 120]], 120];
If[! NumericQ[maxSeconds] || maxSeconds <= 0, maxSeconds = 120];
If[! FileExistsQ[codePath], msFail["INVALID_TASK", "code file not found: " <> codePath]];
If[! DirectoryQ[workDir], msFail["INVALID_TASK", "working directory not found: " <> workDir]];

SetDirectory[workDir];
SeedRandom[12345];
$HistoryLength = 0;
$msSkillDir = $scriptDir;
started = AbsoluteTime[];

value = $Failed;
messages = {};
Block[{$MessageList = {}},
  value = Quiet[Check[TimeConstrained[Get[codePath], maxSeconds, $Aborted], $Failed]];
  messages = msMessageText[$MessageList];
];

evaluated = value =!= $Failed && value =!= $Aborted;
failure = Which[
  value === $Aborted, "evaluation exceeded the " <> ToString[maxSeconds] <> " second limit",
  value === $Failed, "evaluation failed; see messages",
  True, ""
];

(* 结果文本过长时截断并标记，避免把整张大表打进 JSON。 *)
maxChars = 20000;
resultText = "";
resultHead = "";
resultTeX = "";
truncated = False;
If[evaluated,
  resultText = ToString[value, InputForm];
  If[StringLength[resultText] > maxChars,
    resultText = StringTake[resultText, maxChars];
    truncated = True
  ];
  resultHead = ToString[Head[value]];
  resultTeX = Quiet[Check[ToString[TeXForm[value]], ""]];
  If[StringLength[resultTeX] > maxChars,
    resultTeX = StringTake[resultTeX, maxChars];
    truncated = True
  ];
];

(* 图形结果用 Wolfram 自己的 Rasterize/Export 导出；不是图形时不生成文件。 *)
figureWritten = False;
If[evaluated && MatchQ[value, _Graphics | _Graphics3D | _Graph | _Image | _Legended],
  figureWritten = TrueQ[Quiet[Check[
    Export[figurePath, Rasterize[value, ImageResolution -> 200], "PNG"];
    FileExistsQ[figurePath],
    False
  ]]]
];

msWriteResult[resultPath, <|
  "ok" -> evaluated,
  "result" -> resultText,
  "result_head" -> resultHead,
  "result_tex" -> resultTeX,
  "truncated" -> truncated,
  "figure_written" -> figureWritten,
  "messages" -> messages,
  "message_count" -> Length[messages],
  "seconds" -> Round[AbsoluteTime[] - started, 0.01],
  "message" -> failure
|>];
