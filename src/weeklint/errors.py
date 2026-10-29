"""Errors and exit codes for Weeklint.

Every user-facing failure is a WeeklintError with a stable machine code.
The CLI prints ``{"error": "...", "code": "...", "detail": {...}}`` and exits 2
(or 3 for unexpected internal errors, which are raised as plain exceptions and
wrapped by the CLI).
"""

from __future__ import annotations

from typing import Any


class WeeklintError(Exception):
    """A user/input/config error with a stable code and optional detail."""

    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}
        self.exit_code = 2


def fail(code: str, message: str, **detail: Any) -> "NoReturn":  # type: ignore[name-defined]
    raise WeeklintError(code, message, detail)
