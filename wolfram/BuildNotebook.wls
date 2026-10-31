#!/usr/bin/env wolframscript
(* BuildNotebook.wls — 用真实 Wolfram 解析器把计算代码变成原生 Input 单元。
   只建 Notebook，不执行代码；执行由 EvaluateNotebook.wls 负责。

   代码单元保存的是源代码原文（由解析器先验证语法），因此注释、空行和用户
   自己的排版都会保留，Mathematica 打开后可以重新解析并计算。 *)

$scriptDir = If[$InputFileName === "", Directory[], DirectoryName[ExpandFileName[$InputFileName]]];
Get[FileNameJoin[{$scriptDir, "MathematicaSkill.wl"}]];

args = msArgs[];
If[Length[args] < 4,
  msFail["INVALID_TASK", "usage: BuildNotebook.wls <task.json> <out.nb> <code.wl> <result.json>"]
];
{taskPath, notebookPath, codePath, resultPath} = Take[args, 4];

task = msReadJSON[taskPath];
If[! AssociationQ[task], msFail["INVALID_TASK", "task JSON must be an object"]];

title = ToString[Lookup[task, "title", "Mathematica Notebook"]];
language = ToString[Lookup[task, "language", "en"]];
subject = ToString[Lookup[task, "subject", ""]];
tasks = Lookup[task, "tasks", {}];
outputs = Lookup[task, "outputs", {}];
assumptions = Lookup[task, "assumptions", {}];

problemHeading = If[language === "zh", "题目", "Problem"];
assumptionHeading = If[language === "zh", "假设", "Assumptions"];

textCell[text_String] := Cell[TextData[{text}], "Text"];
sectionCell[text_String] := Cell[text, "Section"];
subsectionCell[text_String] := Cell[text, "Subsection"];
titleCell[text_String] := Cell[text, "Title"];

(* 解析器只用来验证语法；框符由原始文本生成，以保留注释与排版。 *)
codeBoxes[code_String] := Module[{held, lines},
  held = Quiet[Check[ToExpression[code, InputForm, HoldComplete], $Failed]];
  If[held === $Failed || ! MatchQ[held, _HoldComplete], Return[$Failed]];
  lines = StringSplit[StringReplace[code, "\r\n" -> "\n"], "\n"];
  RowBox[Riffle[lines, "\[IndentingNewLine]"]]
];

inputCells[code_String] := Module[{boxes},
  If[StringTrim[code] === "", Return[{}]];
  boxes = codeBoxes[code];
  If[boxes === $Failed, Return[$Failed]];
  {Cell[BoxData[boxes], "Input"]}
];

cells = {titleCell[title]};
If[subject =!= "", AppendTo[cells, textCell[subject]]];
AppendTo[cells, sectionCell[problemHeading]];

Do[
  Module[{id, prompt, code, notes, input, taskOutputs, caption, display},
    id = ToString[Lookup[taskItem, "id", "task"]];
    prompt = ToString[Lookup[taskItem, "prompt", ""]];
    code = ToString[Lookup[taskItem, "code", ""]];
    notes = ToString[Lookup[taskItem, "notes", ""]];
    AppendTo[cells, subsectionCell[id]];
    If[prompt =!= "", AppendTo[cells, textCell[prompt]]];
    input = inputCells[code];
    If[input === $Failed,
      msFail["EVALUATION_FAILED", "Wolfram syntax error while building cell for task " <> id]
    ];
    cells = Join[cells, input];
    If[notes =!= "", AppendTo[cells, textCell[notes]]];
    taskOutputs = Select[outputs, ToString[Lookup[#, "task", ""]] === id &];
    Do[
      caption = ToString[Lookup[output, "title", Lookup[output, "filename", "Output"]]];
      AppendTo[cells, textCell[If[language === "zh", "输出：" <> caption, "Output: " <> caption]]];
      display = inputCells[ToString[Lookup[output, "expression", ""]]];
      If[display === $Failed,
        msFail["EVALUATION_FAILED",
          "Wolfram syntax error while building output cell " <> ToString[Lookup[output, "id", ""]]]
      ];
      cells = Join[cells, display],
      {output, taskOutputs}
    ]
  ],
  {taskItem, tasks}
];

If[Length[assumptions] > 0,
  AppendTo[cells, sectionCell[assumptionHeading]];
  Do[AppendTo[cells, textCell["- " <> ToString[assumption]]], {assumption, assumptions}]
];

nb = Notebook[
  cells,
  WindowSize -> {1280, 900},
  WindowMargins -> {{Automatic, Automatic}, {Automatic, Automatic}},
  StyleDefinitions -> "Default.nb",
  Saveable -> True,
  TrackCellChangeTimes -> False,
  (* ShowChatbar 是 15.0 才有的选项；低版本不能传，否则 Notebook::optx。 *)
  Sequence @@ If[TrueQ[$VersionNumber >= 15.], {ShowChatbar -> False}, {}]
];

If[! StringQ[notebookPath] || ! StringEndsQ[notebookPath, ".nb"],
  msFail["INVALID_TASK", "notebook path must end in .nb"]
];
notebookDir = DirectoryName[notebookPath];
If[notebookDir =!= "" && ! DirectoryQ[notebookDir],
  CreateDirectory[notebookDir, CreateIntermediateDirectories -> True]
];

exported = Quiet[Check[Export[notebookPath, nb, "NB"], $Failed]];
If[! StringQ[exported] || ! FileExistsQ[notebookPath],
  msFail["EVALUATION_FAILED", "Export of notebook failed: " <> notebookPath]
];

result = <|
  "ok" -> True,
  "mode" -> "native",
  "notebook" -> ExpandFileName[notebookPath],
  "bytes" -> FileByteCount[notebookPath],
  "cells" -> Length[Cases[nb, Cell[__], Infinity]],
  "input_cells" -> Count[nb, Cell[_, "Input", ___], Infinity],
  "tasks" -> Length[tasks],
  "outputs" -> Length[outputs]
|>;
msWriteResult[resultPath, result];
