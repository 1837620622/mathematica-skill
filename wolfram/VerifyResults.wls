#!/usr/bin/env wolframscript
(* VerifyResults.wls — 在干净内核中加载计算代码，逐项执行 checks。
   第二次运行时额外读取第一次的 checks，逐项比较，证明结果可复现。 *)

$scriptDir = If[$InputFileName === "", Directory[], DirectoryName[ExpandFileName[$InputFileName]]];
Get[FileNameJoin[{$scriptDir, "MathematicaSkill.wl"}]];

args = msArgs[];
If[Length[args] < 3, msFail["INVALID_TASK", "usage: VerifyResults.wls <task.json> <code.wl> <result.json> [previous.json]"]];
{taskPath, codePath, resultPath} = Take[args, 3];
previousPath = If[Length[args] >= 4, args[[4]], ""];
previousProvided = previousPath =!= "" && FileExistsQ[previousPath];

task = msReadJSON[taskPath];
If[! AssociationQ[task], msFail["INVALID_TASK", "task JSON must be an object"]];
If[! FileExistsQ[codePath], msFail["INVALID_TASK", "code file not found: " <> codePath]];

tasks = Lookup[task, "tasks", {}];
checkSpecs = Flatten[Table[Lookup[taskItem, "checks", {}], {taskItem, tasks}], 1];
previous = If[previousProvided, msReadJSON[previousPath], <||>];
previousChecks = If[AssociationQ[previous], Lookup[previous, "checks", {}], {}];

taskDir = DirectoryName[ExpandFileName[taskPath]];
SetDirectory[taskDir];
SeedRandom[Lookup[task, "seed", 12345]];
$HistoryLength = 0;
$msSkillDir = $scriptDir;
messages = {};
loadOk = False;
loadValue = Null;
checkResults = {};

msNumericEqual[a_, b_, absTol_, relTol_] := NumberQ[a] && NumberQ[b] &&
  TrueQ[Abs[a - b] <= absTol + relTol Abs[b]];

msListEqual[a_List, b_List, absTol_, relTol_] := Length[a] === Length[b] &&
  And @@ MapThread[msListEqual[#1, #2, absTol, relTol] &, {a, b}];
msListEqual[a_, b_, absTol_, relTol_] /; NumberQ[a] && NumberQ[b] :=
  msNumericEqual[a, b, absTol, relTol];
msListEqual[a_, b_, _, _] := TrueQ[Quiet[Simplify[a == b]]];

msRange[a_, range_List] := NumberQ[a] && Length[range] === 2 &&
  TrueQ[range[[1]] <= a <= range[[2]]];

(* 上一轮把 Rational / Complex / 大表达式序列化成 InputForm 字符串，
   比较前先还原，否则精确数学的结果永远「不可复现」。

   previous.json 可能来自外部（verify --previous），所以只还原「看起来像数学表达式」
   的字符串；含 RunProcess / Import 之类的字符串一律按字面比较，不执行。 *)
msLooksLikeMath[x_String] := StringLength[x] <= 4000 &&
  ! StringContainsQ[x, {"RunProcess", "Run[", "Import[", "Get[", "URL", "LibraryLoad",
                        "SystemOpen", "StartProcess", "CreateProcess"}] &&
  StringMatchQ[x, RegularExpression["^[0-9A-Za-z .,;:{}()\\[\\]^*/+=<>!@#$%&|~'\"`_-]*$"]];

msRehydrate[x_String] := Module[{parsed},
  If[! msLooksLikeMath[x], Return[x]];
  parsed = Quiet[Check[ToExpression[x, InputForm], $Failed]];
  If[parsed === $Failed, x, parsed]
];
msRehydrate[x_List] := msRehydrate /@ x;
msRehydrate[x_] := x;

msSameExpression[a_, b_] := Module[{left = msRehydrate[a], right = msRehydrate[b]},
  TrueQ[Quiet[Simplify[left == right]]] ||
    StringTrim[ToString[left, InputForm]] === StringTrim[ToString[right, InputForm]]
];

msReproduced[a_, b_, kind_, absTol_, relTol_] := Which[
  kind === "numeric", msNumericEqual[msRehydrate[a], msRehydrate[b], absTol, relTol],
  kind === "matrix" || kind === "list", msListEqual[msRehydrate[a], msRehydrate[b], absTol, relTol],
  kind === "range", msNumericEqual[msRehydrate[a], msRehydrate[b], absTol, relTol],
  MemberQ[{"boolean"}, kind], TrueQ[a] === TrueQ[b],
  MemberQ[{"symbolic", "exact", "expression"}, kind], msSameExpression[a, b],
  True, StringTrim[ToString[a]] === StringTrim[ToString[b]]
];

Block[{$MessageList = {}},
  loadValue = Quiet[Check[
    TimeConstrained[Get[codePath], 600, $Aborted],
    $Failed
  ]];
  loadOk = loadValue =!= $Failed && loadValue =!= $Aborted;
  If[loadOk,
    checkResults = Table[
      Module[{id, kind, expression, expected, absTol, relTol, actual, expectedValue, passed, note},
        id = Lookup[check, "id", "check"];
        kind = Lookup[check, "kind", "numeric"];
        expression = Lookup[check, "expression", ""];
        expected = Lookup[check, "expected", Null];
        absTol = Lookup[check, "abs_tol", 1.*^-9];
        relTol = Lookup[check, "rel_tol", 1.*^-9];
        expectedValue = If[MemberQ[{"symbolic", "exact", "expression"}, kind] && StringQ[expected],
          Quiet[Check[ToExpression[expected, InputForm], $Failed]],
          expected
        ];
        actual = If[expectedValue === $Failed,
          $Failed,
          Quiet[Check[ToExpression[expression, InputForm], $Failed]]
        ];
        passed = Which[
          actual === $Failed, False,
          kind === "numeric", msNumericEqual[actual, expectedValue, absTol, relTol],
          kind === "matrix" || kind === "list", msListEqual[actual, expectedValue, absTol, relTol],
          kind === "boolean", TrueQ[actual] === TrueQ[expectedValue],
          kind === "range", msRange[actual, expectedValue],
          kind === "string", ToString[actual] === ToString[expectedValue],
          kind === "contains", StringContainsQ[ToString[actual], ToString[expectedValue]],
          MemberQ[{"symbolic", "exact", "expression"}, kind],
            TrueQ[Quiet[Simplify[actual == expectedValue]]],
          True, False
        ];
        <|
          "id" -> id,
          "kind" -> kind,
          "expression" -> expression,
          "expected" -> msJsonSafe[expectedValue],
          "actual" -> msJsonSafe[actual],
          "passed" -> TrueQ[passed],
          "abs_tol" -> absTol,
          "rel_tol" -> relTol
        |>
      ],
      {check, checkSpecs}
    ]
  ];
  messages = msMessageText[$MessageList];
];

reproduced = If[previousProvided,
  Table[
    Module[{current, prior},
      current = checkResults[[index]];
      prior = SelectFirst[previousChecks, Lookup[#, "id", ""] === current["id"] &, Missing["NotFound"]];
      If[MissingQ[prior], False,
        msReproduced[current["actual"], prior["actual"], current["kind"],
          current["abs_tol"], current["rel_tol"]]
      ]
    ],
    {index, Length[checkResults]}
  ],
  {}
];

passedCount = Total[Boole[Lookup[#, "passed"] & /@ checkResults]];
allPassed = Length[checkResults] > 0 && And @@ (TrueQ[Lookup[#, "passed"]] & /@ checkResults);
allReproduced = If[previousProvided, And @@ reproduced, Null];
ok = loadOk && allPassed && (! previousProvided || TrueQ[allReproduced]);

errorCode = Which[
  ! loadOk, "EVALUATION_FAILED",
  ! allPassed, "NUMERIC_MISMATCH",
  previousProvided && ! TrueQ[allReproduced], "NUMERIC_MISMATCH",
  True, ""
];
message = Which[
  ! loadOk, "loading computation code failed or timed out",
  ! allPassed, "one or more checks did not pass",
  previousProvided && ! TrueQ[allReproduced], "independent re-run did not reproduce every check",
  True, "all checks passed"
];

result = <|
  "ok" -> ok,
  "error_code" -> errorCode,
  "message" -> message,
  "seed" -> Lookup[task, "seed", 12345],
  "total" -> Length[checkResults],
  "passed" -> passedCount,
  "previous_provided" -> previousProvided,
  "reproduced" -> If[previousProvided, Total[Boole[reproduced]], 0],
  "all_reproduced" -> allReproduced,
  "checks" -> checkResults,
  "messages" -> messages
|>;
msWriteResult[resultPath, result];
