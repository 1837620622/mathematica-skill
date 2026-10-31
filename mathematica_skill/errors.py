"""Typed errors with stable machine-readable codes."""

from __future__ import annotations

from typing import Any


ERROR_CODES: dict[str, str] = {
    "INVALID_TASK": "The task document is malformed or violates the schema.",
    "UNSAFE_PATH": "A path escapes its allowed root or is not portable.",
    "ENGINE_NOT_FOUND": "No usable Wolfram kernel or wolframscript was found.",
    "LICENSE_UNAVAILABLE": "Mathematica/Wolfram Engine is installed but not licensed for use.",
    "FRONTEND_UNAVAILABLE": "No Mathematica notebook frontend could be started.",
    "NOTEBOOK_OPEN_FAILED": "Mathematica could not open the notebook.",
    "NOTEBOOK_EDIT_FAILED": "The notebook edit was rejected or produced an invalid notebook.",
    "ENCODING_MISMATCH": "Text did not survive a UTF-8 round trip (possible mojibake).",
    "EVALUATION_FAILED": "Wolfram Language evaluation failed.",
    "PLOT_EXPORT_FAILED": "A native figure or data export failed.",
    "NUMERIC_MISMATCH": "Recomputed results do not match the reference values.",
    "TIMEOUT": "The native run exceeded its time limit.",
    "MEMORY_LIMIT": "The native run exceeded its memory limit.",
    "POLICY_BLOCKED": "The request needs explicit approval before execution.",
    "DELIVERY_BLOCKED": "Verification gates failed; no verified delivery was produced.",
    "VERIFICATION_REQUIRED": "A native verification run is required first.",
    "INSTALL_FAILED": "Installation or configuration failed.",
    "INSTALL_CONFLICT": "An existing file or configuration conflicts with this install.",
    "MCP_ERROR": "The MCP server or client failed.",
    "UNEXPECTED": "An unexpected internal error occurred.",
}


class MskError(Exception):
    def __init__(self, code: str, message: str, hint: str = "", details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code if code in ERROR_CODES else "UNEXPECTED"
        self.message = message
        self.hint = hint
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
            "details": self.details,
        }


class InvalidTask(MskError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("INVALID_TASK", message, details=details)


class UnsafePath(MskError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("UNSAFE_PATH", message, details=details)


class EngineNotFound(MskError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("ENGINE_NOT_FOUND", message,
                         "Install Mathematica or Wolfram Engine, or run `mathematica-skill doctor`.",
                         details)


class FrontendUnavailable(MskError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("FRONTEND_UNAVAILABLE", message,
                         "Notebook execution needs a desktop Mathematica frontend on this machine.", details)


class DeliveryBlocked(MskError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("DELIVERY_BLOCKED", message, details=details)
