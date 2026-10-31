(* ::Package:: *)
(* MathematicaSkill.wl — 本 Skill 的 WL 侧公共工具。
   只提供参数、JSON、错误和序列化辅助；数学计算一律由用户代码在真实内核里完成。 *)

BeginPackage["MathematicaSkill`"];

msReadJSON::usage = "msReadJSON[path] 读取 UTF-8 JSON 文件。";
msWriteJSON::usage = "msWriteJSON[path, expr] 以 UTF-8 写出 JSON，自动创建父目录。";
msWriteResult::usage = "msWriteResult[path, assoc] 写出结果并向 stdout 打印紧凑 JSON。";
msFail::usage = "msFail[code, message, details] 输出失败 JSON 并以非零状态退出。";
msJsonSafe::usage = "msJsonSafe[expr] 把 Wolfram 表达式转换成可稳定 JSON 化的形式。";
msArgs::usage = "msArgs[] 返回 $ScriptCommandLine 中脚本名之后的参数。";
msAbsolute::usage = "msAbsolute[path] 返回绝对路径。";
msNow::usage = "msNow[] 返回 UTC 时间字符串。";
msMessageText::usage = "msMessageText[list] 把消息名转成可读文本。";

Begin["`Private`"];

msArgs[] := Module[{fromEnv, args, first},
  If[Length[$ScriptCommandLine] > 0,
    args = $ScriptCommandLine;
    first = First[args];
    If[StringQ[first] && (StringEndsQ[first, ".wls"] || StringEndsQ[first, ".wl"] ||
        StringEndsQ[first, ".m"]),
      args = Rest[args]
    ];
    If[args =!= {} && First[args] === "--", args = Rest[args]];
    Return[args]
  ];
  fromEnv = Environment["MSK_SCRIPT_ARGS"];
  If[StringQ[fromEnv] && fromEnv =!= "",
    DeleteCases[StringSplit[fromEnv, "\n"], ""],
    {}
  ]
];

msAbsolute[path_String] := ExpandFileName[path];

msNow[] := DateString[TimeZone -> "UTC"];

msJsonSafe[_Missing | Missing[___]] := Null;
msJsonSafe[Null] := Null;
msJsonSafe[True] := True;
msJsonSafe[False] := False;
msJsonSafe[i_Integer] := i;
msJsonSafe[r_Real] := If[TrueQ[Abs[r] < Infinity], r, ToString[r, InputForm]];
msJsonSafe[x : (Infinity | -Infinity | ComplexInfinity | Indeterminate | DirectedInfinity[___])] :=
  ToString[x, InputForm];
msJsonSafe[r_Rational] := ToString[r, InputForm];
msJsonSafe[c_Complex] := ToString[c, InputForm];
msJsonSafe[q_Quantity] := ToString[q, InputForm];
msJsonSafe[s_String] := s;
msJsonSafe[a_Association] := AssociationMap[msJsonSafe, a];
msJsonSafe[l_List] := msJsonSafe /@ l;
msJsonSafe[g_Graphics | g_Graphics3D | g_Legended] := <|"type" -> "WolframGraphics", "head" -> ToString[Head[g]]|>;
msJsonSafe[img_Image] := <|
   "type" -> "WolframImage",
   "width" -> ImageDimensions[img][[1]],
   "height" -> ImageDimensions[img][[2]]
|>;
msJsonSafe[f_Failure] := <|"type" -> "Failure", "message" -> ToString[f[[1]]]|>;
msJsonSafe[s_Symbol] := ToString[s];
msJsonSafe[other_] := If[LeafCount[Unevaluated[other]] > 20000,
  "<expr:" <> ToString[Head[Unevaluated[other]]] <> ">",
  ToString[other, InputForm]
];

msWriteJSON[path_String, expr_] := Module[{directory, data},
  directory = DirectoryName[path];
  If[directory =!= "" && ! DirectoryQ[directory],
    CreateDirectory[directory, CreateIntermediateDirectories -> True]
  ];
  data = ExportString[msJsonSafe[expr], "JSON", "Compact" -> False];
  Export[path, data, "Text", CharacterEncoding -> "UTF-8"];
  path
];

msWriteResult[path_String, assoc_Association] := Module[{safe, text},
  safe = msJsonSafe[assoc];
  msWriteJSON[path, safe];
  text = ExportString[safe, "JSON", "Compact" -> True];
  WriteString["stdout", text, "\n"];
  Exit[If[TrueQ[safe["ok"]], 0, 1]]
];

msFail[code_String, message_String, details_: <||>] := Module[{payload},
  payload = <|"ok" -> False, "error_code" -> code, "message" -> message, "details" -> details|>;
  WriteString["stdout", ExportString[msJsonSafe[payload], "JSON", "Compact" -> True], "\n"];
  Exit[1]
];

(* Import[..., "JSON"] 把对象读成规则列表，不是 Association；这里递归转一次，
   否则 Lookup / assoc["key"] 全部失效。空列表保持为 {}。 *)
msToAssoc[x_Association] := AssociationMap[msToAssoc, x];
msToAssoc[r : {__Rule}] := Association @@ Map[Rule[#[[1]], msToAssoc[#[[2]]]] &, r];
msToAssoc[l_List] := msToAssoc /@ l;
msToAssoc[x_] := x;

msReadJSON[path_String] := Module[{data},
  If[! FileExistsQ[path], msFail["INVALID_TASK", "JSON file not found: " <> path]];
  data = Quiet[Check[Import[path, "JSON"], $Failed]];
  If[data === $Failed, msFail["INVALID_TASK", "Cannot parse JSON: " <> path]];
  msToAssoc[data]
];

msMessageText[list_List] := ToString /@ DeleteDuplicates[list];
msMessageText[other_] := {ToString[other]};

End[];
EndPackage[];
