"""Frontend adapter for notebook operations that need a desktop Mathematica."""

from __future__ import annotations

from pathlib import Path

from .adapter_base import NativeRun
from .adapter_wolframscript import WolframscriptAdapter
from .errors import FrontendUnavailable


class FrontendAdapter:
    def __init__(self, adapter: WolframscriptAdapter, *, available: bool, detail: str = "") -> None:
        self.adapter = adapter
        self.available = available
        self.detail = detail

    def _require(self) -> None:
        if not self.available:
            raise FrontendUnavailable("No Mathematica notebook frontend is available on this machine.",
                                      {"detail": self.detail})

    def evaluate(self, notebook: Path, result_json: Path, *, timeout: float | None = None) -> NativeRun:
        self._require()
        return self.adapter.evaluate_notebook(notebook, result_json, mode="evaluate", timeout=timeout)

    def reopen(self, notebook: Path, result_json: Path, *, timeout: float | None = None) -> NativeRun:
        self._require()
        return self.adapter.inspect_notebook(notebook, result_json, timeout=timeout)

    def rerun(self, notebook: Path, result_json: Path, *, timeout: float | None = None) -> NativeRun:
        self._require()
        return self.adapter.evaluate_notebook(notebook, result_json, mode="rerun", timeout=timeout)
