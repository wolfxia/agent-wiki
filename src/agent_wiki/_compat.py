"""Python 3.10 compatibility: datetime.UTC backport."""

from datetime import datetime, timezone

# datetime.UTC was added in Python 3.11; use timezone.utc on 3.10
try:
    from datetime import UTC  # type: ignore[attr-defined]
except ImportError:
    UTC = timezone.utc

__all__ = ["UTC", "datetime", "timezone"]
