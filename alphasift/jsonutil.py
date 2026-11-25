# -*- coding: utf-8 -*-
"""Strict RFC-8259 JSON normalization and serialization helpers."""

from __future__ import annotations

from datetime import date, datetime
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any


def finite_float(value: object) -> float | None:
    """Coerce non-boolean numeric value to finite float, returning None otherwise."""
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def safe_int(value: object, *, default: int = 0) -> int:
    """Coerce numeric value to int without crashing on NaN, Inf, bool, or invalid strings."""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, float) and not math.isfinite(value):
        return default
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        num = finite_float(value)
        return int(num) if num is not None else default


def json_safe(obj: Any) -> Any:
    """Normalize NaN/Inf floats, NumPy scalars/arrays, and dates before strict JSON serialization."""
    if obj is None or isinstance(obj, (bool, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, str):
        return obj
    if type(obj).__name__ == "NaTType":
        return None
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    ndim = getattr(obj, "ndim", None)
    if isinstance(ndim, int) and ndim > 0 and hasattr(obj, "tolist") and callable(getattr(obj, "tolist")):
        try:
            return json_safe(obj.tolist())
        except Exception:
            pass
    if hasattr(obj, "item") and callable(getattr(obj, "item")):
        try:
            return json_safe(obj.item())
        except Exception:
            pass
    if hasattr(obj, "tolist") and callable(getattr(obj, "tolist")):
        try:
            return json_safe(obj.tolist())
        except Exception:
            pass
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [json_safe(v) for v in obj]
    return str(obj)


def dumps_strict_json(payload: Any, *, indent: int | None = 2) -> str:
    """Serialize payload as valid RFC-8259 JSON (NaN/Inf -> null, NumPy/date/Path normalized)."""
    return json.dumps(json_safe(payload), ensure_ascii=False, indent=indent, allow_nan=False)


def atomic_write_text(
    path: str | Path,
    content: str,
    *,
    encoding: str = "utf-8",
) -> Path:
    """Write text atomically via a same-directory temp file and os.replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o644
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, target)
        tmp_name = None
        return target
    finally:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)


def atomic_write_strict_json(
    path: str | Path,
    payload: Any,
    *,
    indent: int | None = 2,
    trailing_newline: bool = False,
) -> Path:
    """Serialize payload as strict RFC-8259 JSON and write atomically to disk."""
    serialized = dumps_strict_json(payload, indent=indent)
    if trailing_newline:
        serialized += "\n"
    return atomic_write_text(path, serialized, encoding="utf-8")
