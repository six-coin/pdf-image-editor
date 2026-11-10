"""配置读写。

两个文件，职责分开：``app.json`` 放应用级设置，``reference.json`` 放参考线边距。
读的时候夹取、不信任文件内容；未知键原样保留；结构损坏抛 ``ConfigError`` 而不是
静默重建——静默重建会把用户数据洗掉。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app import i18n, paths
from app.errors import ConfigError

DEFAULT_APP: dict[str, Any] = {
    "language": "zh-CN",
    "theme": "light",
    "zoom": 1.0,
    "save_mode": "preserve",
    "undo_limit": 100,
    "render_dpi_cap": 300,
    "preprocess_threshold": 235,
    "show_guides": True,
}

DEFAULT_REFERENCE: dict[str, Any] = {
    "left_mm": 10.0,
    "top_mm": 10.0,
    "right_mm": 50.0,
    "bottom_mm": 10.0,
}

_THEMES = ("light", "dark")
_SAVE_MODES = ("preserve", "raster")

# 旧版本用厘米作单位，键名也不同。
_LEGACY_MARGIN_KEYS = {
    "left_cm": "left_mm",
    "top_cm": "top_mm",
    "right_cm": "right_mm",
    "bottom_cm": "bottom_mm",
}


def _number(value: Any, default: float, low: float, high: float) -> float:
    """非数字回退默认值，越界夹到范围内，NaN 视为非法。"""
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return min(max(number, low), high)


def _integer(value: Any, default: int, low: int, high: int) -> int:
    return int(_number(value, float(default), float(low), float(high)))


def _choice(value: Any, default: str, allowed: tuple[str, ...]) -> str:
    text = str(value).strip() if value is not None else ""
    return text if text in allowed else default


def _boolean(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(key="error.config_unreadable", name=path.name) from exc
    if not isinstance(raw, dict):
        raise ConfigError(key="error.config_not_object", name=path.name)
    return raw


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """临时文件 + os.replace，中途崩溃不会留下半个文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=4, ensure_ascii=False)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _normalize_app(raw: dict[str, Any]) -> dict[str, Any]:
    merged = dict(raw)
    merged["language"] = _choice(
        raw.get("language"), DEFAULT_APP["language"], tuple(i18n.available())
    )
    merged["theme"] = _choice(raw.get("theme"), DEFAULT_APP["theme"], _THEMES)
    merged["zoom"] = _number(raw.get("zoom"), DEFAULT_APP["zoom"], 0.1, 8.0)
    merged["save_mode"] = _choice(raw.get("save_mode"), DEFAULT_APP["save_mode"], _SAVE_MODES)
    merged["undo_limit"] = _integer(raw.get("undo_limit"), DEFAULT_APP["undo_limit"], 10, 500)
    merged["render_dpi_cap"] = _integer(
        raw.get("render_dpi_cap"), DEFAULT_APP["render_dpi_cap"], 96, 400
    )
    merged["preprocess_threshold"] = _integer(
        raw.get("preprocess_threshold"), DEFAULT_APP["preprocess_threshold"], 0, 255
    )
    merged["show_guides"] = _boolean(raw.get("show_guides"), DEFAULT_APP["show_guides"])
    return merged


def _normalize_reference(raw: dict[str, Any]) -> dict[str, Any]:
    merged = dict(raw)
    for key, default in DEFAULT_REFERENCE.items():
        merged[key] = _number(raw.get(key), default, 0.0, 300.0)
    return merged


def _migrate_legacy_reference() -> dict[str, Any] | None:
    legacy = paths.LEGACY_REFERENCE_PATH
    if not legacy.is_file():
        return None
    try:
        raw = _read_json(legacy)
    except ConfigError:
        return None
    migrated: dict[str, Any] = {}
    for old_key, new_key in _LEGACY_MARGIN_KEYS.items():
        if old_key in raw:
            migrated[new_key] = _number(raw[old_key], DEFAULT_REFERENCE[new_key], 0.0, 300.0) * 10
    return migrated or None


def load_app() -> dict[str, Any]:
    path = paths.APP_CONFIG_PATH
    if not path.is_file():
        config = dict(DEFAULT_APP)
        save_app(config)
        return config
    return _normalize_app(_read_json(path))


def save_app(config: dict[str, Any]) -> None:
    _write_json(paths.APP_CONFIG_PATH, _normalize_app(config))


def load_reference() -> dict[str, Any]:
    path = paths.REFERENCE_CONFIG_PATH
    if path.is_file():
        return _normalize_reference(_read_json(path))
    migrated = _migrate_legacy_reference()
    config = _normalize_reference(migrated or dict(DEFAULT_REFERENCE))
    save_reference(config)
    return config


def save_reference(config: dict[str, Any]) -> None:
    _write_json(paths.REFERENCE_CONFIG_PATH, _normalize_reference(config))
