"""词法检查与路径安全。"""

from __future__ import annotations

import pytest

from mathematica_skill.errors import UnsafePath
from mathematica_skill.paths import safe_filename, safe_relative, slugify
from mathematica_skill.wlsyntax import check_syntax, strip_literals


def test_balanced_expression_is_clean() -> None:
    report = check_syntax("Plot[Sin[x], {x, 0, 1}]")
    assert report.errors == []
    assert report.balanced


def test_unclosed_bracket_reports_line() -> None:
    report = check_syntax("a = 1;\nb = f[2;")
    assert not report.balanced
    assert any("line 2" in message for message in report.errors)


def test_mismatched_bracket_is_reported() -> None:
    report = check_syntax("f[1, 2}")
    assert not report.balanced
    assert any("does not match" in message for message in report.errors)


def test_unterminated_string_is_reported() -> None:
    report = check_syntax('s = "abc')
    assert any("unterminated string" in message for message in report.errors)


def test_nested_comments_are_ignored() -> None:
    report = check_syntax("(* outer (* inner *) still *) x = 1;")
    assert report.errors == []


def test_bracket_inside_string_is_ignored() -> None:
    report = check_syntax('s = "]";')
    assert report.errors == []


def test_strip_literals_blanks_strings_and_keeps_lines() -> None:
    stripped = strip_literals('RunProcess["rm -rf /"];\nImport["/etc/passwd"]')
    assert "RunProcess" in stripped
    assert "rm -rf" not in stripped
    assert stripped.count("\n") == 1


def test_safe_relative_rejects_absolute() -> None:
    with pytest.raises(UnsafePath):
        safe_relative("/tmp/x")


def test_safe_filename_allows_space_and_dash() -> None:
    assert safe_filename("figure 01-final.png") == "figure 01-final.png"


@pytest.mark.parametrize("name", ["a/b.png", "../a.png", "a:b.png", "", ".hidden", "trailing."])
def test_safe_filename_rejects_unsafe(name: str) -> None:
    with pytest.raises(UnsafePath):
        safe_filename(name)


def test_slugify_keeps_ascii_only() -> None:
    assert slugify("Héllo World 题") == "h-llo-world"
    assert slugify("   ", fallback="x") == "x"
