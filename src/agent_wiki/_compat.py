"""Python 3.10 compatibility shims."""

from datetime import datetime, timezone

# datetime.UTC was added in Python 3.11; use timezone.utc on 3.10
try:
    from datetime import UTC  # type: ignore[attr-defined]
except ImportError:
    UTC = timezone.utc

# StrEnum was added in Python 3.11; provide a minimal shim on 3.10
try:
    from enum import StrEnum  # type: ignore[attr-defined]
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        """Compatibility shim for Python 3.10 (StrEnum added in 3.11)."""

        def __str__(self) -> str:
            return str(self.value)


__all__ = ["StrEnum", "UTC", "datetime", "timezone"]
