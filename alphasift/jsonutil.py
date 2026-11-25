# -*- coding: utf-8 -*-
"""Strict RFC-8259 JSON normalization and serialization helpers."""

from __future__ import annotations

from datetime import date, datetime
import json
import math
from pathlib import Path
from typing import Any


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
