"""Whitelisted client delivery, kept separate from internal work data."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .errors import DeliveryBlocked
from .jsonio import file_record, write_json
from .models import TaskDocument
from .paths import safe_filename, slugify
from .validation import ValidationReport, validate_delivery_tree


def delivery_folder_name(task: TaskDocument) -> str:
    return slugify(task.delivery_name or task.title, fallback="mathematica-delivery")


def plan_delivery(task: TaskDocument, *, notebook: Path, artifacts_dir: Path,
                  include_code: Path | None = None) -> list[tuple[Path, str]]:
    plan: list[tuple[Path, str]] = []
    notebook_name = safe_filename(str(task.metadata.get("notebook_name") or f"{slugify(task.title, 'notebook')}.nb"))
    plan.append((notebook, notebook_name))
    for output in task.selected_outputs():
        plan.append((artifacts_dir / output.filename, output.filename))
    if include_code is not None and task.metadata.get("deliver_code") is True:
        plan.append((include_code, safe_filename(str(task.metadata.get("code_name") or "computation.wl"))))
    return plan


def stage_delivery(run_dir: Path, task: TaskDocument, *, notebook: Path, artifacts_dir: Path,
                   include_code: Path | None = None, report: ValidationReport,
                   overwrite: bool = False) -> Path:
    delivery_dir = run_dir / "deliver" / delivery_folder_name(task)
    if delivery_dir.exists() and any(delivery_dir.iterdir()) and not overwrite:
        raise DeliveryBlocked(f"A delivery already exists and will not be overwritten: {delivery_dir}",
                              {"delivery_dir": str(delivery_dir)})
    if delivery_dir.exists():
        shutil.rmtree(delivery_dir)
    delivery_dir.mkdir(parents=True, exist_ok=True)

    plan = plan_delivery(task, notebook=notebook, artifacts_dir=artifacts_dir, include_code=include_code)
    manifest: list[dict[str, Any]] = []
    for source, name in plan:
        if not source.is_file():
            report.add("error", "DELIVERY_SOURCE_MISSING", f"source missing for delivery: {source}", name)
            continue
        target = delivery_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        manifest.append({"delivered": name, **file_record(target)})

    validate_delivery_tree(delivery_dir, report=report)
    write_json(run_dir / "_validation" / "manifest.json", {
        "delivery_dir": str(delivery_dir),
        "files": manifest,
        "task": task.title,
        "verified": False,
        "note": "verified is set after every native gate passes",
    })
    return delivery_dir
