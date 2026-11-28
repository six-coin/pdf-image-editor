"""配置读写。

全部设置放在一个 ``app.json`` 里，参考线边距在 ``reference`` 子对象下。
读的时候夹取、不信任文件内容；未知键原样保留；结构损坏抛 ``ConfigError`` 而不是
静默重建——静默重建会把用户数据洗掉。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from app import i18n, logging_setup, paths
from app.errors import ConfigError
from app.system import theme as theme_tool

DEFAULT_REFERENCE: dict[str, Any] = {
    "left_mm": [10.0],
    "top_mm": [10.0],
    "right_mm": [10.0, 50.0],
    "bottom_mm": [10.0],
}

# 对齐线：移动元素时用来吸附的线，默认就是那五条参考线再加一条左边 85mm。
# 和参考线分开存：参考线是「看着舒服的版心」，对齐线是「吸附到哪里」，
# 两者可以不一样，改一个不该顺手改另一个。
DEFAULT_ALIGN: dict[str, Any] = {
    "left_mm": [10.0, 85.0],
    "top_mm": [10.0],
    "right_mm": [10.0, 50.0],
    "bottom_mm": [10.0],
}

# 字体键与颜色键在这里再列一遍：settings 是基础层，不该反过来 import core。
# 两边是否一致由 tests/test_settings.py 守。
FONT_KEYS = ("msyh", "simsun", "simfang", "simkai", "simhei", "times")
TEXT_COLOR_KEYS = ("blue", "red", "green", "black")
HIGHLIGHT_COLOR_KEYS = ("yellow",)

# 预处理会把灰度 >= 227 的像素直接压成纯白；裁白边默认用同一个值，
# 这样「预处理已经丢掉」的底灰，裁白边也会当成白边切掉。
PREPROCESS_THRESHOLD_DEFAULT = 227
# 表格框线最短长度（px）。默认 170，设置里可在 20–340（默认值的两倍）之间调。
TABLE_MIN_SPAN_DEFAULT = 170
TABLE_MIN_SPAN_RANGE = (20, TABLE_MIN_SPAN_DEFAULT * 2)
# 裁白边灰度阈值：>= 这个值算白。64 约等于 1/4 灰，255 是纯白。
TRIM_THRESHOLD_DEFAULT = PREPROCESS_THRESHOLD_DEFAULT
TRIM_THRESHOLD_RANGE = (64, 255)

DEFAULT_APP: dict[str, Any] = {
    "language": "zh-CN",
    "theme": "light",
    "undo_limit": 100,
    "render_dpi_cap": 300,
    "preprocess_threshold": PREPROCESS_THRESHOLD_DEFAULT,
    "table_min_span": TABLE_MIN_SPAN_DEFAULT,
    "trim_threshold": TRIM_THRESHOLD_DEFAULT,
    "show_guides": True,
    "show_inspector": True,
    # 图片选中时显示八个手柄（四角 + 四边中点）；关掉只留四角。
    "eight_handles": True,
    # 打开 PDF 时从哪个目录开始。空字符串表示用数据目录下的 pdfs。
    "open_dir": "",
    # 空表示用前端的默认键位表；用户改过才会写进来。
    "keybindings": {},
    # 日志三件套：级别、是否自动清空、保留天数。
    "log_level": logging_setup.DEFAULT_LEVEL,
    "log_cleanup": True,
    "log_retention_days": logging_setup.DEFAULT_RETENTION_DAYS,
    # 就地保存的备份保留天数。备份放在数据目录的 backup/ 里，启动时清掉过期的。
    "backup_retention_days": 30,
    # 参考线边距。每边可以有任意多条，存成列表。放在这里而不是单独一个文件：
    # 一处配置一条读写路径，少一处能不同步。
    "reference": {key: list(value) for key, value in DEFAULT_REFERENCE.items()},
    # 移动时的吸附线。结构同参考线：每边可以有任意多条，单位毫米。
    "align": {key: list(value) for key, value in DEFAULT_ALIGN.items()},
    # 新建文本框的默认样式。字号单位是 px（与 Edge 的批注一致，1px = 0.75pt）。
    "text_font": "msyh",
    "text_size_px": 14,
    "text_color": "blue",
    "text_width_mm": 45.0,
    "text_line_height": 1.15,
    # 新建文本框时自动填入的文本；空字符串表示不填。
    "text_default": "",
    # 荧光带默认高度（px）与颜色。
    "highlight_height_px": 15,
    "highlight_color": "yellow",
}

_THEMES = ("light", "dark")
# 一条边上最多几条参考线。手抖打一串逗号也不该把画布刷成栅栏。
MAX_GUIDES = 12


def default_app() -> dict[str, Any]:
    """出厂默认设置。

    语言与外观不是写死的常量：第一次启动按系统语言与系统主题定一次，之后
    以配置文件里的值为准。
    """
    config = dict(DEFAULT_APP)
    config["language"] = i18n.initial_language()
    config["theme"] = theme_tool.system_theme()
    config["reference"] = {key: list(value) for key, value in DEFAULT_REFERENCE.items()}
    config["align"] = {key: list(value) for key, value in DEFAULT_ALIGN.items()}
    return config


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


def _bindings(value: Any) -> dict[str, dict[str, str]]:
    """键位表：{scope: {command: accel}}。只接受非空字符串，其余原样丢弃。"""
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, dict[str, str]] = {}
    for scope, table in value.items():
        if not isinstance(table, dict):
            continue
        entries = {
            str(command): str(accel).strip()
            for command, accel in table.items()
            if isinstance(accel, str) and accel.strip()
        }
        if entries:
            cleaned[str(scope)] = entries
    return cleaned


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
        raw.get("language"), i18n.initial_language(), tuple(i18n.available())
    )
    merged["theme"] = theme_tool.resolve(raw.get("theme"))
    merged["undo_limit"] = _integer(raw.get("undo_limit"), DEFAULT_APP["undo_limit"], 10, 500)
    merged["render_dpi_cap"] = _integer(
        raw.get("render_dpi_cap"), DEFAULT_APP["render_dpi_cap"], 96, 400
    )
    merged["preprocess_threshold"] = _integer(
        raw.get("preprocess_threshold"), DEFAULT_APP["preprocess_threshold"], 0, 255
    )
    merged["table_min_span"] = _integer(
        raw.get("table_min_span"),
        DEFAULT_APP["table_min_span"],
        TABLE_MIN_SPAN_RANGE[0],
        TABLE_MIN_SPAN_RANGE[1],
    )
    merged["trim_threshold"] = _integer(
        raw.get("trim_threshold"),
        DEFAULT_APP["trim_threshold"],
        TRIM_THRESHOLD_RANGE[0],
        TRIM_THRESHOLD_RANGE[1],
    )
    merged["show_guides"] = _boolean(raw.get("show_guides"), DEFAULT_APP["show_guides"])
    merged["show_inspector"] = _boolean(raw.get("show_inspector"), DEFAULT_APP["show_inspector"])
    merged["eight_handles"] = _boolean(raw.get("eight_handles"), DEFAULT_APP["eight_handles"])
    merged["open_dir"] = str(raw.get("open_dir", "") or "").strip()
    merged["log_level"] = _choice(
        raw.get("log_level"), logging_setup.DEFAULT_LEVEL, logging_setup.LOG_LEVELS
    )
    merged["log_cleanup"] = _boolean(raw.get("log_cleanup"), DEFAULT_APP["log_cleanup"])
    merged["log_retention_days"] = _integer(
        raw.get("log_retention_days"),
        DEFAULT_APP["log_retention_days"],
        logging_setup.MIN_RETENTION_DAYS,
        logging_setup.MAX_RETENTION_DAYS,
    )
    merged["keybindings"] = _bindings(raw.get("keybindings"))
    merged["backup_retention_days"] = _integer(
        raw.get("backup_retention_days"), DEFAULT_APP["backup_retention_days"], 1, 3650
    )
    merged["text_font"] = _choice(raw.get("text_font"), DEFAULT_APP["text_font"], FONT_KEYS)
    merged["text_size_px"] = _integer(raw.get("text_size_px"), DEFAULT_APP["text_size_px"], 6, 200)
    merged["text_color"] = _choice(
        raw.get("text_color"), DEFAULT_APP["text_color"], TEXT_COLOR_KEYS
    )
    merged["text_width_mm"] = _number(
        raw.get("text_width_mm"), DEFAULT_APP["text_width_mm"], 10.0, 300.0
    )
    merged["text_line_height"] = _number(
        raw.get("text_line_height"), DEFAULT_APP["text_line_height"], 0.8, 3.0
    )
    merged["text_default"] = str(raw.get("text_default", "") or "")
    merged["highlight_height_px"] = _integer(
        raw.get("highlight_height_px"), DEFAULT_APP["highlight_height_px"], 4, 200
    )
    merged["highlight_color"] = _choice(
        raw.get("highlight_color"), DEFAULT_APP["highlight_color"], HIGHLIGHT_COLOR_KEYS
    )
    reference = raw.get("reference")
    merged["reference"] = _normalize_guides(
        reference if isinstance(reference, dict) else {}, DEFAULT_REFERENCE
    )
    align = raw.get("align")
    merged["align"] = _normalize_guides(align if isinstance(align, dict) else {}, DEFAULT_ALIGN)
    # 历史遗留键：结构版本已取消，save_mode 也不再使用，读到就丢掉。
    merged.pop("settings_version", None)
    merged.pop("save_mode", None)
    return merged


def _normalize_guides(raw: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """把 ``reference`` / ``align`` 这类「四边多值」子对象归一化。"""
    merged = dict(raw)
    for key, default in defaults.items():
        merged[key] = _mm_values(raw.get(key), default)
    return merged


def _mm_values(value: Any, default: list[float]) -> list[float]:
    """一条边上的参考线位置。

    接受逗号分隔的字符串（设置面板与手改文件）和列表（当前格式），统一成
    「升序、去重、夹在 0–300」的毫米列表。解析不出任何数字就退回默认值。
    """
    if isinstance(value, bool) or value is None:
        items: list[Any] = []
    elif isinstance(value, str):
        items = [part for part in re.split(r"[,，;；\s]+", value) if part.strip()]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        items = []

    cleaned: list[float] = []
    for item in items:
        number = _number(item, -1.0, 0.0, 300.0)
        if number < 0:
            continue
        rounded = round(number, 2)
        if rounded not in cleaned:
            cleaned.append(rounded)
    if not cleaned:
        return list(default)
    cleaned.sort()
    return cleaned[:MAX_GUIDES]


def load_app() -> dict[str, Any]:
    path = paths.APP_CONFIG_PATH
    if not path.is_file():
        config = default_app()
        save_app(config)
        return _normalize_app(config)
    return _normalize_app(_read_json(path))


def save_app(config: dict[str, Any]) -> None:
    _write_json(paths.APP_CONFIG_PATH, _normalize_app(config))


def apply_log_settings(config: dict[str, Any]) -> None:
    """把日志三件套交给 ``logging_setup``。

    启动读到设置时调一次，设置界面改完再调一次——所以改级别不用重启，写的是
    同一个日志文件。
    """
    logging_setup.configure(
        level=str(config.get("log_level", logging_setup.DEFAULT_LEVEL)),
        cleanup=bool(config.get("log_cleanup", True)),
        retention_days=int(config.get("log_retention_days", logging_setup.DEFAULT_RETENTION_DAYS)),
    )


def load_reference() -> dict[str, Any]:
    return dict(load_app()["reference"])


def save_reference(config: dict[str, Any]) -> None:
    app = load_app()
    app["reference"] = _normalize_guides(config, DEFAULT_REFERENCE)
    save_app(app)


def load_align() -> dict[str, Any]:
    return dict(load_app()["align"])


def save_align(config: dict[str, Any]) -> None:
    app = load_app()
    app["align"] = _normalize_guides(config, DEFAULT_ALIGN)
    save_app(app)
