from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException


@dataclass(frozen=True)
class TransportError:
    type: str
    message: str
    status_code: int

    def as_dict(self) -> dict[str, str]:
        return {"type": self.type, "message": self.message}


def map_exception(exc: Exception) -> TransportError:
    if isinstance(exc, HTTPException):
        if exc.status_code == 404:
            return TransportError(type="not_found", message=str(exc.detail), status_code=404)
        if exc.status_code in {401, 403}:
            return TransportError(type="permission_denied", message=str(exc.detail), status_code=exc.status_code)
        if exc.status_code == 400:
            return TransportError(type="invalid_input", message=str(exc.detail), status_code=400)
        return TransportError(type="internal_error", message=str(exc.detail), status_code=exc.status_code)

    if isinstance(exc, FileNotFoundError):
        return TransportError(type="not_found", message=str(exc), status_code=404)

    if isinstance(exc, PermissionError):
        error_type = "gate_blocked" if _looks_like_gate_failure(str(exc)) else "permission_denied"
        return TransportError(type=error_type, message=str(exc), status_code=403)

    if isinstance(exc, ValueError):
        if _looks_like_not_found(str(exc)):
            return TransportError(type="not_found", message=str(exc), status_code=404)
        return TransportError(type="invalid_input", message=str(exc), status_code=400)

    return TransportError(
        type="internal_error",
        message=str(exc) or exc.__class__.__name__,
        status_code=500,
    )


def error_payload(exc: Exception) -> dict[str, dict[str, str]]:
    return {"error": map_exception(exc).as_dict()}


def _looks_like_not_found(message: str) -> bool:
    lowered = message.lower()
    return lowered.startswith("unknown wiki_id") or lowered.startswith("unknown tool") or "not found" in lowered


def _looks_like_gate_failure(message: str) -> bool:
    lowered = message.lower()
    return "max_gate" in lowered or "required gate" in lowered
