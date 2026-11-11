"""路径推导。

本模块是全项目唯一允许拼接路径的地方，其余模块一律从这里取常量。
只负责给出绝对路径，不判断文件是否存在。
"""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROGRAM_DIR = PACKAGE_DIR.parent

CONFIG_DIR = PROGRAM_DIR / "config"
LOG_DIR = PROGRAM_DIR / "logs"
TEMP_DIR = PROGRAM_DIR / "temp"
# 打开 PDF 时的默认目录。软件启动时若不存在会自动创建。
PDFS_DIR = PROGRAM_DIR / "pdfs"

LOCALES_DIR = PACKAGE_DIR / "locales"
WEB_DIR = PACKAGE_DIR / "ui" / "web" / "static"

APP_CONFIG_PATH = CONFIG_DIR / "app.json"
# 迁移用：早期版本把参考线边距放在这两个文件里，现在并入 app.json，读到就删。
REFERENCE_CONFIG_PATH = CONFIG_DIR / "reference.json"

# 更早的版本把边距写在 reference_line.json 里，键名是 *_cm。
LEGACY_REFERENCE_PATH = CONFIG_DIR / "reference_line.json"


def resolve_user_path(raw: str | None) -> Path:
    """把配置里写下的路径解析成绝对路径，基准是程序目录而不是 cwd。"""
    text = (raw or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1]
    if not text:
        return PROGRAM_DIR
    path = Path(text)
    return path if path.is_absolute() else (PROGRAM_DIR / path).resolve()


def session_temp_dir(session_id: str) -> Path:
    """本次运行的临时目录。只允许清理这个子目录，不碰 TEMP_DIR 本身。"""
    return TEMP_DIR / session_id


def ensure_pdfs_dir() -> Path:
    """确保 PDF 默认目录存在，返回它。"""
    PDFS_DIR.mkdir(parents=True, exist_ok=True)
    return PDFS_DIR
