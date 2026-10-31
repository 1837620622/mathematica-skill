"""危险调用策略：只在 Python 侧做静态扫描，WL 脚本不重复实现。

命中即 POLICY_BLOCKED；只有操作员显式 allow_external 才会降级为 warning，并写进报告。
"""

from __future__ import annotations

import re

POLICY_PATTERNS: dict[str, str] = {
    "process execution": r"\bRun(?:Process)?\s*\[",
    "remote retrieval": r"\b(?:URLDownload|URLSubmit|URLExecute|URLFetch|URLRead|URLSave)\s*\[",
    "external file read": r'\b(?:Get|Import|ReadList|FilePrint|OpenRead)\s*\[\s*"(?:/|~|[A-Za-z]:[\\/]|\\\\)',
    "shell escape": r"\b(?:SystemOpen|StartProcess|CreateProcess)\s*\[",
    "dynamic code loading":
        r"\b(?:LibraryLoad|LoadModule|Compile\s*\[[^,]+,\s*[^,]+,\s*CompilationTarget\s*->\s*\"C\")",
}


def scan_policy(code: str, unit_id: str) -> list[dict[str, str]]:
    """返回代码里所有命中的危险调用；unit_id 用来在报告里指明来源。"""
    findings: list[dict[str, str]] = []
    for label, pattern in POLICY_PATTERNS.items():
        for match in re.finditer(pattern, code):
            findings.append({"task": unit_id, "kind": label, "match": match.group(0)[:120]})
    return findings
