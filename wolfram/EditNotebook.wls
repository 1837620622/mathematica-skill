#!/usr/bin/env wolframscript
(* EditNotebook.wls — 在既有 Notebook 上做定点修改，不破坏其余单元与样式。

   与 BuildNotebook.wls 的分工：
     BuildNotebook  从零生成新 Notebook
     EditNotebook   打开已有 Notebook，按索引替换/插入/追加单元，另存副本

   编码：Export[..., "NB"] 由 Mathematica 自己写转义，中文、日文、公式都不会乱码；
   脚本最后会重新 Import 回来，逐条核对写入的字符串是否原样存在。 *)

$scriptDir = If[$InputFileName === "", Directory[], DirectoryName[ExpandFileName[$InputFileName]]];
Get[FileNameJoin[{$scriptDir, "MathematicaSkill.wl"}]];

args = msArgs[];
If[Length[args] < 4,
  msFail["INVALID_TASK", "usage: EditNotebook.wls <in.nb> <edits.json> <out.nb> <result.json>"]
];
{inPath, editsPath, outPath, resultPath} = Take[args, 4];

If[! FileExistsQ[inPath], msFail["NOTEBOOK_OPEN_FAILED", "notebook not found: " <> inPath]];
If[! StringEndsQ[ToString[outPath], ".nb"], msFail["INVALID_TASK", "output path must end in .nb"]];
If[ExpandFileName[inPath] === ExpandFileName[outPath],
  (* 原地修改由 Python 侧先备份，再写临时文件替换；WL 侧始终只写新路径 *)
  msFail["UNSAFE_PATH", "refusing to overwrite the source notebook; write to a new path"]
];

edits = msReadJSON[editsPath];
If[! AssociationQ[edits], msFail["INVALID_TASK", "edits JSON must be an object"]];

notebook = Quiet[Check[Import[inPath, "NB"], $Failed]];
If[! MatchQ[notebook, _Notebook],
  msFail["NOTEBOOK_OPEN_FAILED", "Import did not return a Notebook expression: " <> inPath]
];

(* ---------- 单元定位 ---------- *)

(* 按文档顺序取出所有 Cell 的完整位置和样式。支持 CellGroupData 嵌套。 *)
cellPositions[nb_] := Position[nb, Cell[_, _String, ___], Infinity];
cellStyles[nb_] := Cases[nb, Cell[_, style_String, ___] :> style, Infinity];
cellStyleAt[nb_, pos_] := Module[{cell = Extract[nb, pos]},
  If[MatchQ[cell, Cell[_, _String, ___]], cell[[2]], ""]
];

cellCount[nb_] := Length[cellPositions[nb]];
inputCount[nb_] := Count[cellStyles[nb], "Input"];

(* ---------- 构造新单元 ---------- *)

codeBoxes[code_String] := Module[{held, lines},
  held = Quiet[Check[ToExpression[code, InputForm, HoldComplete], $Failed]];
  If[held === $Failed || ! MatchQ[held, _HoldComplete], Return[$Failed]];
  lines = StringSplit[StringReplace[code, "\r\n" -> "\n"], "\n"];
  RowBox[Riffle[lines, "\[IndentingNewLine]"]]
];

makeCell["Input", content_String] := Module[{boxes},
  boxes = codeBoxes[content];
  If[boxes === $Failed, Return[$Failed]];
  Cell[BoxData[boxes], "Input"]
];
makeCell[style_String, content_String] := Cell[content, style];
makeCell[_, _] := $Failed;

(* ---------- 具体操作 ---------- *)

applied = {};
errors = {};

validIndex[index_, n_] := IntegerQ[index] && 1 <= index <= n;

replaceCell[nb_, index_, content_] := Module[{positions, replacement},
  positions = cellPositions[nb];
  If[! validIndex[index, Length[positions]],
    AppendTo[errors, <|"op" -> "replace_cell", "index" -> index, "message" -> "index out of range"|>];
    Return[nb]
  ];
  replacement = makeCell["Input", content];
  If[replacement === $Failed,
    AppendTo[errors, <|"op" -> "replace_cell", "index" -> index, "message" -> "Wolfram syntax error"|>];
    Return[nb]
  ];
  AppendTo[applied, <|"op" -> "replace_cell", "index" -> index,
                     "style_before" -> cellStyleAt[nb, positions[[index]]]|>];
  ReplacePart[nb, positions[[index]] -> replacement]
];

deleteCell[nb_, index_] := Module[{positions, style},
  positions = cellPositions[nb];
  If[! validIndex[index, Length[positions]],
    AppendTo[errors, <|"op" -> "delete_cell", "index" -> index, "message" -> "index out of range"|>];
    Return[nb]
  ];
  style = cellStyleAt[nb, positions[[index]]];
  AppendTo[applied, <|"op" -> "delete_cell", "index" -> index, "style" -> style|>];
  Delete[nb, positions[[index]]]
];

insertAfter[nb_, index_, style_, content_] := Module[{positions, pos, cell},
  positions = cellPositions[nb];
  If[! validIndex[index, Length[positions]],
    AppendTo[errors, <|"op" -> "insert_after", "index" -> index, "message" -> "index out of range"|>];
    Return[nb]
  ];
  cell = makeCell[style, content];
  If[cell === $Failed,
    AppendTo[errors, <|"op" -> "insert_after", "index" -> index, "message" -> "invalid cell"|>];
    Return[nb]
  ];
  pos = positions[[index]];
  If[! IntegerQ[Last[pos]] || ! ListQ[Extract[nb, Most[pos]]] || Most[pos] === {},
    AppendTo[errors, <|"op" -> "insert_after", "index" -> index,
                       "message" -> "cannot insert into this container"|>];
    Return[nb]
  ];
  AppendTo[applied, <|"op" -> "insert_after", "index" -> index, "style" -> style|>];
  Insert[nb, cell, ReplacePart[pos, -1 -> Last[pos] + 1]]
];

appendCells[nb_, cells_List] := Module[{body, opts},
  (* Notebook[{cell}] 只有一个参数；这时 opts 必须是空，绝不能把 body 丢掉。 *)
  body = If[Length[nb] >= 1, nb[[1]], {}];
  opts = If[Length[nb] >= 2, Rest[nb], {}];
  If[! ListQ[body], body = {body}];
  AppendTo[applied, <|"op" -> "append", "count" -> Length[cells]|>];
  Notebook[Join[body, cells], Sequence @@ opts]
];

setTitle[nb_, text_String] := Module[{positions, n},
  positions = cellPositions[nb];
  n = Length[positions];
  Do[
    If[cellStyleAt[nb, positions[[i]]] === "Title",
      AppendTo[applied, <|"op" -> "set_title", "index" -> i|>];
      Return[ReplacePart[nb, positions[[i]] -> Cell[text, "Title"]]]
    ],
    {i, 1, n}
  ];
  AppendTo[applied, <|"op" -> "set_title", "inserted" -> True|>];
  Notebook[Prepend[If[ListQ[nb[[1]]], nb[[1]], {nb[[1]]}], Cell[text, "Title"]],
    Sequence @@ Drop[nb, 1]]
];

(* 只翻我们自己的固定标题，不擅自改用户正文。 *)
headingPairs = {<|"en" -> "Problem", "zh" -> "题目"|>,
                <|"en" -> "Assumptions", "zh" -> "假设"|>};
outputPrefixes = <|"en" -> "Output: ", "zh" -> "输出："|>;

(* 前端保存的 Text 单元是 Cell[TextData[{"..."}], "Text"]，不能只看 cell[[1]] 是字符串。 *)
cellText[cell_] := Which[
  Length[cell] >= 2 && StringQ[cell[[1]]], cell[[1]],
  Length[cell] >= 2 && MatchQ[cell[[1]], TextData[{__String}]], StringJoin @@ cell[[1, 1]],
  Length[cell] >= 2 && MatchQ[cell[[1]], TextData[{___}]], StringJoin @@ Cases[cell[[1]], _String, Infinity],
  True, $Failed
];

rewriteCell[cell_, original_TextData, replacement_String] :=
  ReplacePart[cell, 1 -> TextData[{replacement}]];
rewriteCell[cell_, _String, replacement_String] := ReplacePart[cell, 1 -> replacement];
rewriteCell[cell_, _, _] := cell;

retitle[nb_, target_String] := Module[
  {positions, n, from, to, cell, text, changed = 0, newText, source},
  positions = cellPositions[nb];
  n = Length[positions];
  Do[
    cell = Extract[nb, positions[[i]]];
    text = cellText[cell];
    If[StringQ[text],
      newText = text;
      Do[
        from = If[target === "zh", Lookup[pair, "en"], Lookup[pair, "zh"]];
        to = Lookup[pair, target];
        If[newText === from, newText = to],
        {pair, headingPairs}
      ];
      If[StringStartsQ[newText, outputPrefixes[If[target === "zh", "en", "zh"]]],
        newText = outputPrefixes[target] <> StringDrop[newText,
          StringLength[outputPrefixes[If[target === "zh", "en", "zh"]]]]
      ];
      If[newText =!= text,
        source = If[StringQ[cell[[1]]], "String", "TextData"];
        nb = ReplacePart[nb, positions[[i]] ->
          rewriteCell[cell, If[source === "String", text, "TextData"], newText]];
        changed++
      ]
    ],
    {i, 1, n}
  ];
  AppendTo[applied, <|"op" -> "set_language", "language" -> target, "rewritten" -> changed|>];
  nb
];

(* ---------- 执行 ---------- *)

cellsBefore = cellCount[notebook];
inputsBefore = inputCount[notebook];

If[StringQ[Lookup[edits, "title", Null]],
  notebook = setTitle[notebook, Lookup[edits, "title"]]
];

If[StringQ[Lookup[edits, "language", Null]] && MemberQ[{"en", "zh"}, Lookup[edits, "language"]],
  notebook = retitle[notebook, Lookup[edits, "language"]]
];

operations = Lookup[edits, "operations", {}];
If[! ListQ[operations], msFail["INVALID_TASK", "operations must be a list"]];

Do[
  Module[{op, index, content, style},
    op = Lookup[operation, "op", ""];
    index = Lookup[operation, "index", 0];
    content = Lookup[operation, "content", ""];
    style = Lookup[operation, "style", "Input"];
    Switch[op,
      "replace_cell", notebook = replaceCell[notebook, index, ToString[content]],
      "delete_cell", notebook = deleteCell[notebook, index],
      "insert_after", notebook = insertAfter[notebook, index, ToString[style], ToString[content]],
      "append_input",
        Module[{cell = makeCell["Input", ToString[content]]},
          If[cell === $Failed,
            AppendTo[errors, <|"op" -> "append_input", "message" -> "Wolfram syntax error"|>],
            notebook = appendCells[notebook, {cell}]
          ]
        ],
      "append_text", notebook = appendCells[notebook, {Cell[ToString[content], "Text"]}],
      "append_section", notebook = appendCells[notebook, {Cell[ToString[content], "Section"]}],
      "append_subsection", notebook = appendCells[notebook, {Cell[ToString[content], "Subsection"]}],
      _,
        AppendTo[errors, <|"op" -> ToString[op], "message" -> "unknown operation"|>]
    ]
  ],
  {operation, operations}
];

If[! MatchQ[notebook, _Notebook],
  msFail["EVALUATION_FAILED", "edit operations corrupted the notebook expression"]
];

outDir = DirectoryName[ExpandFileName[outPath]];
If[outDir =!= "" && ! DirectoryQ[outDir],
  CreateDirectory[outDir, CreateIntermediateDirectories -> True]
];

exported = Quiet[Check[Export[outPath, notebook, "NB"], $Failed]];
If[! StringQ[exported] || ! FileExistsQ[outPath],
  msFail["EVALUATION_FAILED", "Export of edited notebook failed: " <> outPath]
];

(* ---------- 回读校验：编码与内容 ---------- *)

reloaded = Quiet[Check[Import[outPath, "NB"], $Failed]];
If[! MatchQ[reloaded, _Notebook],
  msFail["NOTEBOOK_OPEN_FAILED", "edited notebook cannot be re-imported: " <> outPath]
];

cellsAfter = cellCount[reloaded];
inputsAfter = inputCount[reloaded];

(* 用户提供的每个字符串都必须能原样读回，这是「不乱码」的硬证据。 *)
expected = DeleteCases[
  Join[
    If[StringQ[Lookup[edits, "title", Null]], {Lookup[edits, "title"]}, {}],
    Cases[operations, KeyValuePattern[{"content" -> content_String}] :> content],
    Cases[operations, KeyValuePattern[{"text" -> text_String}] :> text]
  ],
  ""
];
(* 框符会把多行代码拆成多个字符串，比较时先去掉所有空白与换行，只比较可见字符。 *)
squeeze[text_String] := StringDelete[text, WhitespaceCharacter];
flatText = squeeze[StringRiffle[ToString /@ Cases[reloaded, _String, Infinity], "\n"]];
encodingChecks = Table[
  <|"text" -> StringTake[item, UpTo[80]], "found" -> StringContainsQ[flatText, squeeze[item]]|>,
  {item, expected}
];
encodingOk = AllTrue[Lookup[encodingChecks, "found"], TrueQ];

result = <|
  "ok" -> errors === {} && encodingOk,
  "error_code" -> Which[
    errors =!= {}, "INVALID_TASK",
    ! encodingOk, "ENCODING_MISMATCH",
    True, ""
  ],
  "message" -> Which[
    errors =!= {}, "one or more operations were rejected",
    ! encodingOk, "edited notebook did not round-trip the supplied text",
    True, "notebook edited"
  ],
  "source" -> ExpandFileName[inPath],
  "notebook" -> ExpandFileName[outPath],
  "bytes" -> FileByteCount[outPath],
  "cells_before" -> cellsBefore,
  "cells_after" -> cellsAfter,
  "input_cells_before" -> inputsBefore,
  "input_cells_after" -> inputsAfter,
  "applied" -> applied,
  "errors" -> errors,
  "encoding_checks" -> encodingChecks,
  "encoding_ok" -> encodingOk,
  "messages" -> msMessageText[$MessageList]
|>;
msWriteResult[resultPath, result];
