from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TransportError:
    type: str
    message: str
    status_code: int

    def as_dict(self) -> dict[str, str]:
        return {"type": self.type, "message": self.message}


def map_exception(exc: Exception) -> TransportError:
    status_code = getattr(exc, "status_code", None)
    detail = getattr(exc, "detail", None)
    if isinstance(status_code, int) and detail is not None:
        if status_code == 404:
            return TransportError(type="not_found", message=str(detail), status_code=404)
        if status_code in {401, 403}:
            return TransportError(type="permission_denied", message=str(detail), status_code=status_code)
        if status_code == 400:
            return TransportError(type="invalid_input", message=str(detail), status_code=400)
        return TransportError(type="internal_error", message=str(detail), status_code=status_code)

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
