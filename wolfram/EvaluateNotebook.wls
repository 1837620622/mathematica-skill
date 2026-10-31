#!/usr/bin/env wolframscript
(* EvaluateNotebook.wls — 用真实 Mathematica 前端打开 Notebook、执行、保存、关闭。
   三种模式：
     evaluate — 打开、执行全部 Input、写入 Output、保存、关闭
     rerun    — 与 evaluate 相同，用于独立复算
     reopen   — 只打开并读取结构，证明交付的 .nb 能被前端打开 *)

$scriptDir = If[$InputFileName === "", Directory[], DirectoryName[ExpandFileName[$InputFileName]]];
Get[FileNameJoin[{$scriptDir, "MathematicaSkill.wl"}]];

args = msArgs[];
If[Length[args] < 3, msFail["INVALID_TASK", "usage: EvaluateNotebook.wls <notebook.nb> <result.json> <evaluate|rerun|reopen> [maxSeconds]"]];
{notebookPath, resultPath, mode} = Take[args, 3];
maxSeconds = If[Length[args] >= 4, Quiet[Check[ToExpression[args[[4]]], 600]], 600];
If[! NumericQ[maxSeconds] || maxSeconds <= 0, maxSeconds = 600];
If[! MemberQ[{"evaluate", "rerun", "reopen"}, mode],
  msFail["INVALID_TASK", "mode must be evaluate, rerun or reopen"]
];
If[! FileExistsQ[notebookPath], msFail["NOTEBOOK_OPEN_FAILED", "notebook not found: " <> notebookPath]];

started = AbsoluteTime[];
$HistoryLength = 0;
frontendUsed = False;
opened = False;
saved = False;
failedOutputs = 0;
evaluated = False;
outputCells = 0;
resultValue = Null;
failureMessage = "";
$MessageList = {};

frontendResult = Quiet[Check[
  TimeConstrained[UsingFrontEnd[
    Module[{nbo, nbExpr},
      nbo = Quiet[Check[NotebookOpen[notebookPath, Visible -> False], $Failed]];
      If[nbo === $Failed,
        failureMessage = "NotebookOpen failed; no usable front end or the file is not a valid notebook.";
        Return[$Failed]
      ];
      opened = True;
      frontendUsed = True;
      If[mode =!= "reopen",
        resultValue = TimeConstrained[
          Quiet[Check[NotebookEvaluate[nbo, InsertResults -> True], $Failed]],
          maxSeconds,
          $Aborted
        ];
        If[resultValue === $Failed,
          failureMessage = "NotebookEvaluate returned $Failed.";
        ];
        If[resultValue === $Aborted,
          failureMessage = "Notebook evaluation exceeded the " <> ToString[maxSeconds] <> " second limit.";
        ];
        evaluated = FreeQ[{resultValue}, $Failed | $Aborted];
        saved = Quiet[Check[NotebookSave[nbo]; True, False]];
        If[! TrueQ[saved] && failureMessage === "",
          failureMessage = "NotebookSave failed; computed output was not persisted."
        ];
      ];
      nbExpr = Quiet[Check[NotebookGet[nbo], $Failed]];
      If[nbExpr =!= $Failed,
        outputCells = Count[nbExpr, Cell[_, "Output", ___], Infinity];
        failedOutputs = Count[nbExpr,
          c_Cell /; Length[c] >= 2 && MemberQ[Rest[c], "Output"] &&
            StringContainsQ[ToString[c], "$Failed" | "$Aborted"],
          Infinity]
      ];
      Quiet[Check[NotebookClose[nbo], $Failed]];
      True
    ]
  ], maxSeconds + 120, $Aborted],
  $Failed
], $Failed];

If[frontendResult === $Failed && failureMessage === "",
  failureMessage = "UsingFrontEnd failed; Mathematica front end is unavailable in this session."
];
If[frontendResult === $Aborted && failureMessage === "",
  failureMessage = "Front end operation exceeded the " <> ToString[maxSeconds + 120] <> " second limit."
];

messages = msMessageText[$MessageList];
ok = opened && (mode === "reopen" || (evaluated && saved)) && failedOutputs === 0 && failureMessage === "";
If[! ok && failureMessage === "", failureMessage = "notebook operation did not complete"];

result = <|
  "ok" -> ok,
  "mode" -> mode,
  "frontend_used" -> frontendUsed,
  "opened" -> opened,
  "evaluated" -> evaluated,
  "saved" -> saved,
  "output_cells" -> outputCells,
  "failed_outputs" -> failedOutputs,
  "messages" -> messages,
  "message_count" -> Length[messages],
  "seconds" -> Round[AbsoluteTime[] - started, 0.01],
  "notebook" -> ExpandFileName[notebookPath],
  "message" -> failureMessage
|>;
msWriteResult[resultPath, result];
