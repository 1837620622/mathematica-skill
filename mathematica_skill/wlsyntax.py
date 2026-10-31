"""Conservative Wolfram Language lexical checks.

This is not a parser. It checks bracket balance, string termination and
comment nesting, and can blank literals before policy scans.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PAIRS = {")": "(", "]": "[", "}": "{"}
OPENERS = {"(", "[", "{"}


@dataclass(slots=True)
class SyntaxReport:
    balanced: bool
    errors: list[str] = field(default_factory=list)
    stack: list[str] = field(default_factory=list)
    lines: int = 0

    def to_dict(self) -> dict[str, object]:
        return {"balanced": self.balanced, "errors": self.errors, "lines": self.lines}


def strip_literals(code: str) -> str:
    """Replace strings and comments with spaces while preserving newlines."""
    output: list[str] = []
    index = 0
    length = len(code)
    comment_depth = 0
    in_string = False
    while index < length:
        char = code[index]
        nxt = code[index + 1] if index + 1 < length else ""
        if comment_depth:
            if char == "(" and nxt == "*":
                comment_depth += 1
                output.extend("  ")
                index += 2
                continue
            if char == "*" and nxt == ")":
                comment_depth -= 1
                output.extend("  ")
                index += 2
                continue
            output.append("\n" if char == "\n" else " ")
            index += 1
            continue
        if in_string:
            if char == "\\":
                output.append(" ")
                if nxt:
                    output.append("\n" if nxt == "\n" else " ")
                    index += 2
                    continue
                index += 1
                continue
            if char == '"':
                in_string = False
                output.append('"')
                index += 1
                continue
            output.append("\n" if char == "\n" else " ")
            index += 1
            continue
        if char == "(" and nxt == "*":
            comment_depth = 1
            output.extend("  ")
            index += 2
            continue
        if char == '"':
            in_string = True
            output.append('"')
            index += 1
            continue
        output.append(char)
        index += 1
    return "".join(output)


def check_syntax(code: str) -> SyntaxReport:
    errors: list[str] = []
    stack: list[tuple[str, int]] = []
    index = 0
    line = 1
    length = len(code)
    comment_depth = 0
    in_string = False
    while index < length:
        char = code[index]
        nxt = code[index + 1] if index + 1 < length else ""
        if char == "\n":
            line += 1
        if comment_depth:
            if char == "(" and nxt == "*":
                comment_depth += 1
                index += 2
                continue
            if char == "*" and nxt == ")":
                comment_depth -= 1
                index += 2
                continue
            index += 1
            continue
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == "(" and nxt == "*":
            comment_depth = 1
            index += 2
            continue
        if char == '"':
            in_string = True
            index += 1
            continue
        if char in OPENERS:
            stack.append((char, line))
            index += 1
            continue
        if char in PAIRS:
            if not stack:
                errors.append(f"line {line}: unmatched closing {char!r}")
            elif stack[-1][0] != PAIRS[char]:
                opener, opener_line = stack.pop()
                errors.append(f"line {line}: closing {char!r} does not match {opener!r} opened on line {opener_line}")
            else:
                stack.pop()
            index += 1
            continue
        index += 1
    if in_string:
        errors.append(f"line {line}: unterminated string")
    if comment_depth:
        errors.append(f"line {line}: unterminated comment (depth {comment_depth})")
    for opener, opener_line in stack:
        errors.append(f"line {opener_line}: unclosed {opener!r}")
    return SyntaxReport(balanced=not errors, errors=errors,
                        stack=[item[0] for item in stack], lines=line)
