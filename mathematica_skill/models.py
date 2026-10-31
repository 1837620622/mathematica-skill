"""Task document model.

The task JSON is the contract between the agent and the native engine. It
contains prose, Wolfram Language code, explicit expected checks, and the
artifacts to export. The Python layer validates it; it never evaluates it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Iterable

from . import SCHEMA_VERSION
from .errors import InvalidTask, UnsafePath
from .langdetect import resolve_language
from .paths import resolve_inside, safe_filename, safe_relative

CHECK_KINDS = {"numeric", "boolean", "exact", "expression", "matrix", "list",
               "string", "symbolic", "contains", "range"}
OUTPUT_KINDS = {"figure", "pdf", "csv", "xlsx", "data"}
LANGUAGES = {"en", "zh", "auto"}
ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
EXTENSIONS = {
    "figure": {".png", ".pdf", ".svg"},
    "pdf": {".pdf"},
    "csv": {".csv"},
    "xlsx": {".xlsx"},
    "data": {".csv", ".xlsx", ".txt", ".json"},
}


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@dataclass(slots=True)
class CheckSpec:
    id: str
    kind: str
    expression: str
    expected: Any = None
    abs_tol: float = 1e-9
    rel_tol: float = 1e-9
    description: str = ""

    @classmethod
    def from_dict(cls, data: Any, task_id: str, index: int, errors: list[str]) -> "CheckSpec":
        if not isinstance(data, dict):
            errors.append(f"tasks[{task_id}].checks[{index}] must be an object")
            return cls(id=f"{task_id}.check{index + 1}", kind="boolean", expression="False")
        check_id = data.get("id") or f"{task_id}-check{index + 1}"
        _require(isinstance(check_id, str) and bool(ID_PATTERN.match(check_id)),
                 f"invalid check id: {check_id!r}", errors)
        kind = data.get("kind", "numeric")
        _require(kind in CHECK_KINDS, f"check {check_id}: kind must be one of {sorted(CHECK_KINDS)}", errors)
        expression = data.get("expression")
        _require(isinstance(expression, str) and bool(expression.strip()),
                 f"check {check_id}: expression is required", errors)
        abs_tol = data.get("abs_tol", 1e-9)
        rel_tol = data.get("rel_tol", 1e-9)
        _require(_number(abs_tol) and abs_tol >= 0, f"check {check_id}: abs_tol must be >= 0", errors)
        _require(_number(rel_tol) and rel_tol >= 0, f"check {check_id}: rel_tol must be >= 0", errors)
        expected = data.get("expected")
        if kind in {"numeric", "matrix", "list", "range"} and expected is None:
            errors.append(f"check {check_id}: expected is required for kind={kind}")
        if kind == "numeric":
            _require(_number(expected), f"check {check_id}: numeric expected must be a number", errors)
        if kind in {"matrix", "list"}:
            _require(isinstance(expected, list), f"check {check_id}: {kind} expected must be a JSON array", errors)
        if kind == "range":
            _require(isinstance(expected, list) and len(expected) == 2 and all(_number(x) for x in expected),
                     f"check {check_id}: range expected must be [min, max]", errors)
        if kind == "boolean":
            _require(isinstance(expected, bool), f"check {check_id}: boolean expected must be true or false", errors)
        if kind in {"string", "contains", "symbolic", "exact", "expression"}:
            _require(isinstance(expected, str), f"check {check_id}: expected must be a string for kind={kind}", errors)
        if kind in {"symbolic", "exact", "expression"} and not isinstance(expected, str):
            errors.append(f"check {check_id}: expected must be a Wolfram Language expression string for kind={kind}")
        return cls(
            id=str(check_id), kind=str(kind), expression=str(expression or ""), expected=expected,
            abs_tol=float(abs_tol) if _number(abs_tol) else 0.0,
            rel_tol=float(rel_tol) if _number(rel_tol) else 0.0,
            description=str(data.get("description", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {"id": self.id, "kind": self.kind, "expression": self.expression,
                   "abs_tol": self.abs_tol, "rel_tol": self.rel_tol}
        if self.expected is not None:
            payload["expected"] = self.expected
        if self.description:
            payload["description"] = self.description
        return payload


@dataclass(slots=True)
class TaskSpec:
    id: str
    prompt: str
    code: str
    checks: list[CheckSpec] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, data: Any, index: int, errors: list[str]) -> "TaskSpec":
        prefix = f"tasks[{index}]"
        if not isinstance(data, dict):
            errors.append(f"{prefix} must be an object")
            return cls(id=f"task{index + 1}", prompt="", code="")
        task_id = data.get("id")
        _require(isinstance(task_id, str) and bool(ID_PATTERN.match(task_id)),
                 f"{prefix}.id is invalid: {task_id!r}", errors)
        prompt = data.get("prompt", "")
        _require(isinstance(prompt, str), f"{prefix}.prompt must be a string", errors)
        code = data.get("code")
        _require(isinstance(code, str) and bool(code.strip()), f"{prefix}.code is required", errors)
        _require(len(code or "") <= 200_000, f"{prefix}.code is too long (max 200000 characters)", errors)
        checks_data = data.get("checks", [])
        _require(isinstance(checks_data, list), f"{prefix}.checks must be a list", errors)
        checks: list[CheckSpec] = []
        if isinstance(checks_data, list):
            for check_index, item in enumerate(checks_data):
                checks.append(CheckSpec.from_dict(item, str(task_id or f"task{index + 1}"), check_index, errors))
        return cls(id=str(task_id or f"task{index + 1}"), prompt=str(prompt or ""), code=str(code or ""),
                   checks=checks, notes=str(data.get("notes", "")))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": self.id, "prompt": self.prompt, "code": self.code}
        if self.checks:
            payload["checks"] = [check.to_dict() for check in self.checks]
        if self.notes:
            payload["notes"] = self.notes
        return payload


@dataclass(slots=True)
class OutputSpec:
    id: str
    task: str
    kind: str
    filename: str
    expression: str
    width: int = 1600
    height: int = 900
    dpi: int = 300
    title: str = ""
    options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Any, index: int, task_ids: set[str], errors: list[str]) -> "OutputSpec":
        prefix = f"outputs[{index}]"
        if not isinstance(data, dict):
            errors.append(f"{prefix} must be an object")
            return cls(id=f"output{index + 1}", task="", kind="figure",
                       filename=f"output{index + 1}.png", expression="")
        output_id = data.get("id")
        _require(isinstance(output_id, str) and bool(ID_PATTERN.match(output_id)), f"{prefix}.id is invalid", errors)
        task = data.get("task")
        _require(isinstance(task, str) and task in task_ids, f"{prefix}.task must reference a declared task", errors)
        kind = data.get("kind", "figure")
        _require(kind in OUTPUT_KINDS, f"{prefix}.kind must be one of {sorted(OUTPUT_KINDS)}", errors)
        filename = data.get("filename")
        _require(isinstance(filename, str) and bool(filename), f"{prefix}.filename is required", errors)
        if isinstance(filename, str) and filename:
            try:
                filename = safe_filename(filename, field=f"{prefix}.filename")
            except UnsafePath as exc:
                errors.append(exc.message)
        expression = data.get("expression", "")
        _require(isinstance(expression, str) and bool(expression.strip()), f"{prefix}.expression is required", errors)
        width = data.get("width", 1600)
        height = data.get("height", 900)
        dpi = data.get("dpi", 300)
        _require(isinstance(width, int) and 100 <= width <= 20000, f"{prefix}.width must be 100..20000", errors)
        _require(isinstance(height, int) and 100 <= height <= 20000, f"{prefix}.height must be 100..20000", errors)
        _require(isinstance(dpi, int) and 72 <= dpi <= 1200, f"{prefix}.dpi must be 72..1200", errors)
        if isinstance(filename, str) and kind in EXTENSIONS:
            suffix = Path(filename).suffix.lower()
            allowed = sorted(EXTENSIONS[str(kind)])
            _require(suffix in EXTENSIONS[str(kind)],
                     f"{prefix}.filename extension must be one of {allowed}", errors)
        return cls(id=str(output_id or f"output{index + 1}"), task=str(task or ""), kind=str(kind),
                   filename=str(filename or f"output{index + 1}.png"), expression=str(expression or ""),
                   width=int(width) if isinstance(width, int) else 1600,
                   height=int(height) if isinstance(height, int) else 900,
                   dpi=int(dpi) if isinstance(dpi, int) else 300,
                   title=str(data.get("title", "")),
                   options=dict(data.get("options", {})) if isinstance(data.get("options", {}), dict) else {})

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": self.id, "task": self.task, "kind": self.kind,
                                   "filename": self.filename, "expression": self.expression,
                                   "width": self.width, "height": self.height, "dpi": self.dpi}
        if self.title:
            payload["title"] = self.title
        if self.options:
            payload["options"] = self.options
        return payload


@dataclass(slots=True)
class TaskDocument:
    title: str
    tasks: list[TaskSpec]
    outputs: list[OutputSpec] = field(default_factory=list)
    language: str = "en"
    subject: str = ""
    seed: int = 12345
    assumptions: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    delivery_name: str = ""
    delivery_include: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    path: Path | None = None

    @classmethod
    def from_dict(cls, data: Any) -> "TaskDocument":
        errors: list[str] = []
        if not isinstance(data, dict):
            raise InvalidTask("The task document must be a JSON object.")
        schema_version = data.get("schema_version", SCHEMA_VERSION)
        _require(schema_version == SCHEMA_VERSION, f"schema_version must be {SCHEMA_VERSION!r}", errors)
        title = data.get("title")
        _require(isinstance(title, str) and bool(title.strip()), "title is required", errors)
        language = data.get("language", "en")
        _require(language in LANGUAGES, f"language must be one of {sorted(LANGUAGES)}", errors)
        seed = data.get("seed", 12345)
        _require(isinstance(seed, int) and not isinstance(seed, bool), "seed must be an integer", errors)
        assumptions = data.get("assumptions", [])
        _require(isinstance(assumptions, list) and all(isinstance(x, str) for x in assumptions),
                 "assumptions must be a list of strings", errors)
        tasks_data = data.get("tasks")
        _require(isinstance(tasks_data, list) and bool(tasks_data), "tasks must be a non-empty list", errors)
        tasks: list[TaskSpec] = []
        if isinstance(tasks_data, list):
            for index, item in enumerate(tasks_data):
                tasks.append(TaskSpec.from_dict(item, index, errors))
        task_ids = [task.id for task in tasks]
        _require(len(task_ids) == len(set(task_ids)), "task ids must be unique", errors)
        outputs_data = data.get("outputs", [])
        _require(isinstance(outputs_data, list), "outputs must be a list", errors)
        outputs: list[OutputSpec] = []
        if isinstance(outputs_data, list):
            for index, item in enumerate(outputs_data):
                outputs.append(OutputSpec.from_dict(item, index, set(task_ids), errors))
        output_ids = [output.id for output in outputs]
        _require(len(output_ids) == len(set(output_ids)), "output ids must be unique", errors)
        filenames = [output.filename.lower() for output in outputs]
        _require(len(filenames) == len(set(filenames)), "output filenames must be unique (case-insensitive)", errors)
        check_ids = [check.id for task in tasks for check in task.checks]
        _require(len(check_ids) == len(set(check_ids)), "check ids must be unique across tasks", errors)
        sources = data.get("sources", [])
        _require(isinstance(sources, list) and all(isinstance(x, str) for x in sources),
                 "sources must be a list of strings", errors)
        if isinstance(sources, list):
            for source in sources:
                try:
                    safe_relative(source, field="sources")
                except UnsafePath as exc:
                    errors.append(exc.message)
        delivery = data.get("delivery", {})
        _require(isinstance(delivery, dict), "delivery must be an object", errors)
        delivery = delivery if isinstance(delivery, dict) else {}
        include = delivery.get("include", [])
        _require(isinstance(include, list) and all(isinstance(x, str) for x in include),
                 "delivery.include must be a list of output ids", errors)
        if isinstance(include, list):
            unknown = [item for item in include if item not in set(output_ids)]
            _require(not unknown, f"delivery.include references unknown outputs: {unknown}", errors)
        if errors:
            raise InvalidTask("Task validation failed.", {"errors": errors})
        return cls(
            title=str(title), tasks=tasks, outputs=outputs, language=str(language),
            subject=str(data.get("subject", "")), seed=int(seed),
            assumptions=list(assumptions) if isinstance(assumptions, list) else [],
            sources=list(sources) if isinstance(sources, list) else [],
            delivery_name=str(delivery.get("name", "")),
            delivery_include=list(include) if isinstance(include, list) else [],
            metadata=dict(data.get("metadata", {})) if isinstance(data.get("metadata", {}), dict) else {},
            schema_version=str(schema_version),
        )

    @classmethod
    def load(cls, path: Path) -> "TaskDocument":
        try:
            with path.open("r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
        except FileNotFoundError as exc:
            raise InvalidTask(f"Task file not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise InvalidTask(f"Task file is not valid JSON: {exc}") from exc
        document = cls.from_dict(data)
        document.path = path.resolve()
        return document

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "title": self.title, "language": self.language, "subject": self.subject,
            "seed": self.seed, "assumptions": self.assumptions, "sources": self.sources,
            "tasks": [task.to_dict() for task in self.tasks],
            "outputs": [output.to_dict() for output in self.outputs],
            "delivery": {"name": self.delivery_name, "include": self.delivery_include},
            "metadata": self.metadata,
        }

    def save(self, path: Path, *, resolve_language: bool = False) -> Path:
        from .jsonio import write_json

        payload = self.to_dict()
        if resolve_language:
            payload["language"] = self.effective_language()
        return write_json(path, payload)

    def language_materials(self) -> list[str]:
        """用于语言判定的自然语言材料，按题目 → 主题 → 假设的顺序。"""
        parts: list[str] = []
        for task in self.tasks:
            parts.append(task.prompt)
            parts.append(task.notes)
        parts.extend([self.subject, self.title, *self.assumptions])
        return [part for part in parts if part]

    def effective_language(self) -> str:
        """`auto` 时跟随材料语言（例如用户喂的是英文 .nb 就出英文）。"""
        if self.language != "auto":
            return self.language
        materials = self.language_materials()
        for relative in self.sources:
            if relative.lower().endswith(".nb"):
                from .langdetect import notebook_prose, notebook_text

                raw = notebook_text(str(self.base_dir / relative))
                materials.append(notebook_prose(raw))
        return resolve_language("auto", *materials)

    @property
    def base_dir(self) -> Path:
        return self.path.parent if self.path else Path.cwd()

    def source_paths(self) -> list[Path]:
        return [resolve_inside(self.base_dir, item, field="sources") for item in self.sources]

    def selected_outputs(self) -> list[OutputSpec]:
        if not self.delivery_include:
            return list(self.outputs)
        allowed = set(self.delivery_include)
        return [output for output in self.outputs if output.id in allowed]

    def all_checks(self) -> Iterable[CheckSpec]:
        for task in self.tasks:
            yield from task.checks

    def output_dir_name(self) -> str:
        return self.delivery_name or self.title


def example_document() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "title": "Sine and its integral",
        "language": "en",
        "subject": "Calculus",
        "seed": 12345,
        "assumptions": ["x is real", "angles are in radians"],
        "sources": [],
        "tasks": [
            {
                "id": "plot_sine",
                "prompt": "Plot sin(x) on [-pi, pi] and compute the exact integral on [0, pi].",
                "code": ('msSinPlot = Plot[Sin[x], {x, -Pi, Pi}, PlotLabel -> "y = sin(x)", '
                         'AxesLabel -> {"x", "y"}];\n'
                         "msIntegral = Integrate[Sin[x], {x, 0, Pi}];\n"
                         "msAtPiOver2 = Sin[Pi/2];"),
                "checks": [
                    {"id": "integral_exact", "kind": "symbolic", "expression": "msIntegral",
                     "expected": "2", "description": "The exact integral of sin on [0, pi] is 2."},
                    {"id": "sine_value", "kind": "numeric", "expression": "N[msAtPiOver2]",
                     "expected": 1.0, "abs_tol": 1e-12},
                ],
            }
        ],
        "outputs": [
            {"id": "sine_figure", "task": "plot_sine", "kind": "figure", "filename": "sine.png",
             "expression": "msSinPlot", "width": 1600, "height": 900, "dpi": 300, "title": "Sine curve"}
        ],
        "delivery": {"name": "sine-delivery", "include": ["sine_figure"]},
        "metadata": {"deliver_code": False},
    }
