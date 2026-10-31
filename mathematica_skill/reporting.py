"""Internal machine-readable and human-readable reports."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .jsonio import write_json


def _yes(value: Any) -> str:
    return "yes" if value else "no"


def render_markdown(state: dict[str, Any], validation: dict[str, Any], doctor: dict[str, Any]) -> str:
    lines = [
        f"# Validation report — {state.get('title', 'task')}",
        "",
        f"- Run id: `{state.get('run_id', '')}`",
        f"- Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- Status: **{state.get('status', 'unknown')}**",
        f"- Verified: {_yes(state.get('verified'))}",
        f"- Delivery: `{state.get('delivery_dir', '')}`",
        "",
        "## Environment",
        "",
        f"- Platform: {doctor.get('platform_system', '')} {doctor.get('platform_release', '')} "
        f"({doctor.get('machine', '')})",
        f"- Kernel: {doctor.get('kernel_version', '') or 'not found'}",
        f"- Engine usable: {_yes(doctor.get('engine_usable'))}",
        f"- Frontend: {_yes(doctor.get('frontend_available'))} ({doctor.get('frontend_detail', '')})",
        f"- AgentTools: {doctor.get('agenttools_version', '') or 'not detected'}",
        "",
        "## Native checks",
        "",
        f"- Checks total: {validation.get('checks', {}).get('total', 0)}",
        f"- Checks passed: {validation.get('checks', {}).get('passed', 0)}",
        f"- Independent re-run reproduced: {_yes(validation.get('reproduction', {}).get('all_reproduced'))}",
        "",
        "## Findings",
        "",
    ]
    findings = validation.get("findings", [])
    if not findings:
        lines.append("No findings.")
    else:
        lines += ["| Severity | Code | Message |", "| --- | --- | --- |"]
        for finding in findings:
            message = str(finding.get("message", "")).replace("|", "\\|")
            lines.append(f"| {finding.get('severity')} | {finding.get('code')} | {message} |")
    lines += ["", "## Notebook", ""]
    notebook = validation.get("notebook", {})
    if notebook:
        lines += [
            f"- Cells: {notebook.get('cells')}",
            f"- Input cells: {notebook.get('input_cells')}",
            f"- Output cells: {notebook.get('output_cells')}",
            f"- Frontend used: {_yes(validation.get('native', {}).get('frontend_used'))}",
            f"- Well formed: {_yes(notebook.get('well_formed'))}",
        ]
    else:
        lines.append("Notebook validation was not run.")
    lines += ["", "## Artifacts", ""]
    artifacts = validation.get("artifacts", [])
    if artifacts:
        lines += ["| File | Kind | Bytes | Dimensions | OK |", "| --- | --- | --- | --- | --- |"]
        for item in artifacts:
            dimensions = f"{item['width']}x{item['height']}" if item.get("width") and item.get("height") else ""
            lines.append(
                f"| {item.get('filename')} | {item.get('kind')} | {item.get('bytes', 0)} "
                f"| {dimensions} | {_yes(item.get('ok'))} |"
            )
    else:
        lines.append("No artifacts.")
    lines += [
        "",
        "## Verification boundary",
        "",
        "This report only claims what the recorded native runs actually prove.",
        "If the frontend was unavailable, the notebook has not been opened in Mathematica",
        "and the run is not deliverable as verified.",
        "",
    ]
    return "\n".join(lines)


def write_reports(run_dir: Path, state: dict[str, Any], validation: dict[str, Any],
                  doctor: dict[str, Any]) -> dict[str, str]:
    validation_dir = run_dir / "_validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    json_path = write_json(validation_dir / "validation.json", validation)
    markdown_path = validation_dir / "VALIDATION.md"
    markdown_path.write_text(render_markdown(state, validation, doctor), encoding="utf-8")
    return {"validation_json": str(json_path), "validation_markdown": str(markdown_path)}
