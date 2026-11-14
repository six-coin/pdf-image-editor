"""路径推导。

本模块是全项目唯一允许拼接路径的地方，其余模块一律从这里取常量。只负责
给出绝对路径，不判断文件是否存在。

四类位置：

| 位置 | 内容 | 默认 |
|---|---|---|
| 程序目录 | 代码与随程序分发的资源 | 仓库根目录 |
| 数据目录 | 配置、默认 PDF 目录 | ``%PROGRAMDATA%\\six-coin\\pdf-image-editor`` |
| 本地目录 | 日志、锁、数据目录指针 | ``%LOCALAPPDATA%\\six-coin\\pdf-image-editor`` |
| 临时目录 | 外部编辑的中间文件 | ``%TEMP%\\six-coin\\pdf-image-editor`` |

数据目录可在设置里改，指针写在本地目录；改完重启才生效。
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

VENDOR = "six-coin"
PROJECT = "pdf-image-editor"

PACKAGE_DIR = Path(__file__).resolve().parent
PROGRAM_DIR = PACKAGE_DIR.parent

_ENV_DATA = "SIXCOIN_DATA_DIR"
_ENV_LOCAL = "SIXCOIN_LOCAL_DIR"
_ENV_TEMP = "SIXCOIN_TEMP_DIR"


def _system_dir(variable: str, fallback: str) -> Path:
    raw = os.environ.get(variable, "").strip()
    return Path(raw) if raw else Path(fallback)


LOCAL_DIR = Path(
    os.environ.get(_ENV_LOCAL, "").strip()
    or _system_dir("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")) / VENDOR / PROJECT
)
TEMP_DIR = Path(
    os.environ.get(_ENV_TEMP, "").strip() or Path(tempfile.gettempdir()) / VENDOR / PROJECT
)
DATA_DIR_DEFAULT = _system_dir("PROGRAMDATA", "C:/ProgramData") / VENDOR / PROJECT

LOG_DIR = LOCAL_DIR / "logs"
LOCK_DIR = LOCAL_DIR / "locks"
DATA_POINTER = LOCAL_DIR / "data-dir.txt"


def read_data_dir() -> Path:
    """读数据目录指针；没设过、读不出来、不是绝对路径都回退默认值。"""
    override = os.environ.get(_ENV_DATA, "").strip()
    if override:
        return Path(override)
    try:
        text = DATA_POINTER.read_text(encoding="utf-8").strip()
    except OSError:
        return DATA_DIR_DEFAULT
    if not text:
        return DATA_DIR_DEFAULT
    path = Path(text)
    return path if path.is_absolute() else DATA_DIR_DEFAULT


DATA_DIR = read_data_dir()

#: 旧名字保留：配置现在在数据目录里。
CONFIG_DIR = DATA_DIR
# 打开 PDF 时的默认目录。软件启动时若不存在会自动创建。
PDFS_DIR = DATA_DIR / "pdfs"

LOCALES_DIR = PACKAGE_DIR / "locales"
WEB_DIR = PACKAGE_DIR / "ui" / "web" / "static"

APP_CONFIG_PATH = DATA_DIR / "app.json"
# 迁移用：早期版本把参考线边距放在这两个文件里，现在并入 app.json，读到就删。
REFERENCE_CONFIG_PATH = DATA_DIR / "reference.json"

# 更早的版本把边距写在 reference_line.json 里，键名是 *_cm。
LEGACY_REFERENCE_PATH = DATA_DIR / "reference_line.json"

MAIN_ENTRY = PROGRAM_DIR / "main.pyw"
PYTHONW = PROGRAM_DIR / ".venv" / "Scripts" / "pythonw.exe"


def write_data_dir(path: Path) -> None:
    """把新的数据目录写进指针文件。下次启动才生效。"""
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    temp = DATA_POINTER.with_suffix(".tmp")
    temp.write_text(str(path), encoding="utf-8", newline="\n")
    os.replace(temp, DATA_POINTER)


def resolve_user_path(raw: str | None) -> Path:
    """把配置里写下的路径解析成绝对路径，基准是数据目录而不是 cwd。"""
    text = (raw or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1]
    if not text:
        return PROGRAM_DIR
    path = Path(text)
    return path if path.is_absolute() else (DATA_DIR / path).resolve()


def session_temp_dir(session_id: str) -> Path:
    """本次运行的临时目录。只允许清理这个子目录，不碰 TEMP_DIR 本身。"""
    return TEMP_DIR / session_id


def ensure_pdfs_dir() -> Path:
    """确保 PDF 默认目录存在，返回它。"""
    PDFS_DIR.mkdir(parents=True, exist_ok=True)
    return PDFS_DIR


def migrate_legacy() -> list[str]:
    """把旧版本留在程序目录里的数据搬到新位置。

    只在目标位置还没有同名项时搬，绝不覆盖；搬完删掉空目录。临时目录不搬，
    直接删掉——里面的东西本来就是一次性的。
    """
    warnings: list[str] = []
    for source, target in (
        (PROGRAM_DIR / "config", DATA_DIR),
        (PROGRAM_DIR / "pdfs", PDFS_DIR),
        (PROGRAM_DIR / "logs", LOG_DIR),
    ):
        warnings.extend(_merge_move(source, target))
    legacy_temp = PROGRAM_DIR / "temp"
    if legacy_temp.is_dir():
        try:
            shutil.rmtree(legacy_temp)
        except OSError as error:
            warnings.append(f"清理旧临时目录失败：{error}")
    return warnings


def _merge_move(source: Path, target: Path) -> list[str]:
    if not source.is_dir():
        return []
    warnings: list[str] = []
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return [f"无法创建 {target}：{error}"]
    for item in list(source.iterdir()):
        if item.suffix == ".lock":
            # 旧锁文件没有迁移价值，留着还会让人以为锁在数据目录里。
            try:
                item.unlink()
            except OSError:
                pass
            continue
        destination = target / item.name
        if destination.exists():
            continue
        try:
            shutil.move(str(item), str(destination))
        except OSError as error:
            warnings.append(f"迁移 {item} 失败：{error}")
    try:
        source.rmdir()
    except OSError:
        pass
    return warnings
