"""Validation gates: artifacts, notebook structure, native checks and reproduction."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from .jsonio import read_json
from .notebook import inspect_notebook
from .plotqa import validate_png

ALLOWED_DELIVERY_EXTENSIONS = {".nb", ".wl", ".wls", ".png", ".pdf", ".svg", ".csv", ".xlsx", ".txt", ".json"}


@dataclass(slots=True)
class Finding:
    severity: str
    code: str
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message, "path": self.path}


@dataclass(slots=True)
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    notebook: dict[str, Any] = field(default_factory=dict)
    checks: dict[str, Any] = field(default_factory=dict)
    reproduction: dict[str, Any] = field(default_factory=dict)
    native: dict[str, Any] = field(default_factory=dict)

    def add(self, severity: str, code: str, message: str, path: str = "") -> None:
        self.findings.append(Finding(severity, code, message, path))

    def errors(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "error"]

    def warnings(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": [finding.to_dict() for finding in self.errors()],
            "warnings": [finding.to_dict() for finding in self.warnings()],
            "findings": [finding.to_dict() for finding in self.findings],
            "artifacts": self.artifacts,
            "notebook": self.notebook,
            "checks": self.checks,
            "reproduction": self.reproduction,
            "native": self.native,
        }


def validate_artifacts(artifacts_dir: Path, output_specs: list[dict[str, Any]], *, report: ValidationReport) -> None:
    for spec in output_specs:
        filename = str(spec.get("filename", ""))
        path = artifacts_dir / filename
        record: dict[str, Any] = {"id": spec.get("id", ""), "filename": filename, "kind": spec.get("kind", "")}
        if not path.is_file():
            report.add("error", "ARTIFACT_MISSING", f"declared output was not produced: {filename}", filename)
            record["ok"] = False
            report.artifacts.append(record)
            continue
        record["bytes"] = path.stat().st_size
        if path.stat().st_size <= 0:
            report.add("error", "ARTIFACT_EMPTY", f"output is empty: {filename}", filename)
            record["ok"] = False
            report.artifacts.append(record)
            continue
        suffix = path.suffix.lower()
        if suffix == ".png":
            expected_width = int(spec.get("width", 0) or 0)
            expected_height = int(spec.get("height", 0) or 0)
            png = validate_png(path, min_width=max(200, min(expected_width, 400) if expected_width else 200),
                               min_height=max(150, min(expected_height, 300) if expected_height else 150))
            record.update(png)
            if not png.get("ok"):
                report.add("error", "PNG_INVALID", f"PNG failed integrity/content checks: {filename}", filename)
            elif expected_width and expected_height:
                actual = (int(png.get("width", 0)), int(png.get("height", 0)))
                if actual != (expected_width, expected_height):
                    report.add("error", "PNG_DIMENSIONS",
                               f"{filename}: expected {expected_width}x{expected_height}, got {actual[0]}x{actual[1]}",
                               filename)
        elif suffix == ".pdf":
            header = path.read_bytes()[:5]
            record["pdf_header"] = header.decode("latin-1", "replace")
            if not header.startswith(b"%PDF"):
                report.add("error", "PDF_INVALID", f"file does not start with a PDF header: {filename}", filename)
        elif suffix == ".svg":
            head = path.read_text(encoding="utf-8", errors="replace")[:2000]
            if "<svg" not in head:
                report.add("error", "SVG_INVALID", f"file does not contain an SVG root: {filename}", filename)
        record["ok"] = not any(f.path == filename and f.severity == "error" for f in report.findings)
        report.artifacts.append(record)


def validate_delivery_tree(delivery_dir: Path, *, report: ValidationReport) -> list[Path]:
    files: list[Path] = []
    for path in sorted(delivery_dir.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(delivery_dir)
        if any(part.startswith(".") for part in relative.parts):
            report.add("error", "DELIVERY_HIDDEN_FILE", f"hidden file in delivery: {relative}", relative.as_posix())
            continue
        if path.suffix.lower() not in ALLOWED_DELIVERY_EXTENSIONS:
            report.add("error", "DELIVERY_EXTRA_FILE", f"unexpected file type in delivery: {relative}",
                       relative.as_posix())
        files.append(path)
    if not files:
        report.add("error", "DELIVERY_EMPTY", "delivery directory contains no files")
    return files


def validate_notebook(notebook: Path, *, native_result: dict[str, Any] | None, report: ValidationReport,
                      require_frontend: bool = True) -> None:
    if not notebook.is_file():
        report.add("error", "NOTEBOOK_MISSING", "the notebook was not produced", notebook.name)
        return
    static = inspect_notebook(notebook)
    report.notebook = static
    if not static["well_formed"]:
        report.add("error", "NOTEBOOK_MALFORMED", "the notebook expression is not well formed", notebook.name)
    if static["input_cells"] == 0:
        report.add("error", "NOTEBOOK_NO_INPUT", "the notebook contains no Input cells", notebook.name)
    if static["auto_execution"]:
        report.add("error", "NOTEBOOK_AUTO_EXECUTION",
                   f"automatic evaluation markers found: {static['auto_execution']}", notebook.name)
    absolute = static.get("absolute_paths") or []
    if absolute:
        report.add("error", "NOTEBOOK_ABSOLUTE_PATH", f"absolute user paths found: {absolute[:3]}", notebook.name)
    markers = static.get("forbidden_markers") or []
    if markers:
        report.add("error", "NOTEBOOK_MARKER",
                   f"development markers found in the client notebook: {markers}", notebook.name)

    native = native_result or {}
    if not native:
        if require_frontend:
            report.add("error", "FRONTEND_UNAVAILABLE",
                       "the notebook was never opened by a Mathematica frontend", notebook.name)
    else:
        report.native.update({key: native.get(key) for key in
                              ("ok", "mode", "frontend_used", "output_cells", "messages", "seconds")})
        if not native.get("ok", False):
            report.add("error", "NOTEBOOK_OPEN_FAILED",
                       str(native.get("message") or "native notebook operation failed"), notebook.name)
        if require_frontend and not native.get("frontend_used", False):
            report.add("error", "FRONTEND_UNAVAILABLE",
                       "the notebook was not opened by a Mathematica frontend", notebook.name)
        if native.get("frontend_used") and int(native.get("output_cells", 0) or 0) == 0 and static["input_cells"] > 0:
            report.add("error", "NOTEBOOK_NO_OUTPUT",
                       "the notebook has Input cells but no evaluated Output cells", notebook.name)
        messages = [str(item) for item in native.get("messages", []) if item]
        serious = [item for item in messages if re.search(
            r"::(infy|indet|argx|argt|optx|setraw|partw|notnum|nnum|nonopt)", item)]
        if serious:
            report.add("error", "NOTEBOOK_MESSAGES",
                       f"notebook evaluation produced messages: {serious[:5]}", notebook.name)
        elif messages:
            report.add("warning", "NOTEBOOK_MESSAGES",
                       f"notebook evaluation produced messages: {messages[:5]}", notebook.name)


def validate_checks(checks: dict[str, Any] | None, *, report: ValidationReport,
                    expected_total: int | None = None) -> None:
    if not checks:
        report.add("warning", "CHECKS_NOT_RUN", "no native verification record was produced")
        return
    report.checks = {key: checks.get(key) for key in
                     ("ok", "total", "passed", "reproduced", "all_reproduced", "error_code", "message")}
    if not checks.get("ok", False):
        report.add("error", "CHECKS_FAILED", str(checks.get("message") or "native checks failed"))
    total = int(checks.get("total", 0) or 0)
    if total == 0:
        report.add("warning", "CHECKS_EMPTY", "the task defines no numeric or symbolic checks")
    if expected_total is not None and total != expected_total:
        report.add("error", "CHECKS_INCOMPLETE",
                   f"declared {expected_total} checks but only {total} were evaluated")
    for item in checks.get("checks") or []:
        if not isinstance(item, dict):
            report.add("error", "CHECK_MALFORMED", f"check record is not an object: {str(item)[:120]!r}")
            continue
        if not item.get("passed", False):
            report.add("error", "CHECK_FAILED",
                       f"{item.get('id')}: expected {item.get('expected')!r}, got {str(item.get('actual'))[:200]!r}")


def validate_reproduction(rerun: dict[str, Any] | None, *, report: ValidationReport) -> None:
    if not rerun:
        report.add("error", "REPRODUCTION_MISSING", "the independent re-run comparison did not run")
        return
    report.reproduction = {key: rerun.get(key) for key in
                           ("ok", "all_reproduced", "reproduced", "total", "error_code", "message")}
    if not rerun.get("ok", False):
        report.add("error", "REPRODUCTION_FAILED",
                   str(rerun.get("message") or "independent re-run did not reproduce the results"))
    if rerun.get("all_reproduced") is not True:
        report.add("error", "REPRODUCTION_INCOMPLETE",
                   "one or more checks were not reproduced in the independent run")


def load_optional(path: Path) -> dict[str, Any] | None:
    if path.is_file():
        data = read_json(path)
        return data if isinstance(data, dict) else None
    return None
