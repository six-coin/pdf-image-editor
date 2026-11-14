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

数据目录可在设置里改，落点恒以项目代号结尾；改完在下次启动时把旧目录的内容
搬过去，指针跟着改。搬迁只认「待搬迁标记」，不会去改写历史指针——把指针改写成
它自己的子目录，永远搬不成，那是死循环而不是修复。
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

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
#: 「更改数据目录」留下的待搬迁标记。指针只在搬完之后才改，中途断电也不会让
#: 程序在一个空目录里找数据。
DATA_PENDING = LOCAL_DIR / "data-dir.pending"


def normalize_data_dir(raw: str, base: Path | None = None) -> Path:
    """把用户给的路径收敛成绝对路径，并保证最后一层是项目代号。

    选 ``D:\\Data`` 时实际落点是 ``D:\\Data\\pdf-image-editor``；已经以项目
    代号结尾就原样用。相对路径以 ``base``（默认是默认数据目录）为基准。
    """
    text = (raw or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1].strip()
    if not text:
        return DATA_DIR_DEFAULT
    path = Path(os.path.expandvars(text)).expanduser()
    if not path.is_absolute():
        path = (base or DATA_DIR_DEFAULT) / path
    path = Path(os.path.normpath(str(path)))
    if path.name.lower() != PROJECT:
        path = path / PROJECT
    return path


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


def write_data_dir(path: Path) -> None:
    """把数据目录写进指针文件。"""
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    temp = DATA_POINTER.with_suffix(".tmp")
    temp.write_text(str(path), encoding="utf-8", newline="\n")
    os.replace(temp, DATA_POINTER)


def pending_data_dir() -> Path | None:
    """上次「更改数据目录」记下的落点；没有就是 ``None``。"""
    try:
        text = DATA_PENDING.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else None


def _invalid(key: str, **params: Any) -> Exception:
    """造一个带本地化文案的数据目录错误。

    局部导入：``errors`` 依赖 ``i18n``，而 ``i18n`` 又依赖本模块，模块级导入会绕成
    一个环。这个函数只在用户点按钮时才走到，代价可以忽略。
    """
    from app.errors import DataDirError

    return DataDirError(key=key, **params)


def _same_dir(left: Path, right: Path) -> bool:
    """Windows 路径不分大小写，比较前统一成规范形式。"""
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
        os.path.normpath(str(right))
    )


def _ensure_writable(target: Path) -> None:
    """目标目录建得出来、写得进去，否则当场报错。

    校验必须发生在用户点按钮的那一刻：留到下次启动，失败就只剩一条没人看见的
    日志，界面还在说「重启后生效」。
    """
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".sixcoin-write-probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        raise _invalid("about.data_dir_failed", error=error) from error


def request_data_dir(raw: str, base: Path | None = None) -> Path:
    """记下新的数据目录，等下次启动搬过去。

    只写标记不搬文件：搬发生在下次启动、在所有业务模块打开文件之前，运行中的
    进程不会遇到「文件被搬走了」。目标当场建出来并写一次探针文件，把路径打错、
    盘符不存在、没权限这类问题留在点按钮的这一刻暴露。

    返回**实际**的数据目录：用户输入的就是当前目录（包括少写了项目代号这一层）
    时返回当前目录，并且不留下待搬迁标记。
    """
    target = normalize_data_dir(raw, base)
    current = read_data_dir()
    # 少了项目代号的历史指针会让 normalize 算出一个「当前目录的子目录」；那不是
    # 用户想换地方，只是同一处地方的另一种写法，按「没有变化」处理。
    if _same_dir(target, current) or _same_dir(target, normalize_data_dir(str(current))):
        clear_pending_data_dir()
        return current
    if _is_nested(target, current):
        raise _invalid("about.data_dir_nested", path=str(current))
    _ensure_writable(target)
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    temp = DATA_PENDING.with_suffix(".tmp")
    temp.write_text(str(target), encoding="utf-8", newline="\n")
    os.replace(temp, DATA_PENDING)
    return target


def clear_pending_data_dir() -> None:
    """丢掉待搬迁标记。"""
    try:
        DATA_PENDING.unlink()
    except OSError:
        pass


def _is_nested(inner: Path, outer: Path) -> bool:
    """``inner`` 是否在 ``outer`` 里（不含相等）。"""
    left = os.path.normcase(os.path.normpath(str(inner)))
    right = os.path.normcase(os.path.normpath(str(outer)))
    if left == right:
        return False
    return left.startswith(right.rstrip("\\/") + os.sep)


def _merge_into(source: Path, target: Path, notes: list[str], failures: list[str]) -> int:
    """把 ``source`` 里的东西并进 ``target``，返回搬走的条数。

    目录递归合并：同名**文件**保留目标那一份，同名**目录**继续往下并——否则目标
    里只要先有了 ``pdfs/``，源里的 PDF 就整目录被跳过，数据当场分家。

    ``notes`` 是「没搬但不算失败」的说明（目标已有同名文件），``failures`` 是真正
    搬不动的项。两者分开：只要有一项失败，这次迁移就不算成功，指针不动、下次再来。
    """
    moved = 0
    for item in sorted(source.iterdir()):
        if item.suffix == ".lock":
            # 锁恒在本地目录，数据目录里的锁文件没有搬运价值。
            try:
                item.unlink()
            except OSError:
                pass
            continue
        destination = target / item.name
        if item.is_dir() and destination.is_dir():
            moved += _merge_into(item, destination, notes, failures)
            try:
                item.rmdir()
            except OSError:
                # 还有搬不走的文件（被占用、权限不足），空壳留着即可。
                pass
            continue
        if destination.exists():
            notes.append(f"{item.name} 在目标里已存在，保留目标那一份")
            continue
        try:
            shutil.move(str(item), str(destination))
        except OSError as error:
            failures.append(f"迁移 {item.name} 失败：{error}")
            continue
        moved += 1
    return moved


def _move_contents(source: Path, target: Path) -> tuple[list[str], list[str], int]:
    """把 ``source`` 里的东西搬到 ``target``，返回（说明, 失败, 条数）。"""
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return [], [f"无法创建 {target}：{error}"], 0
    if not source.is_dir():
        return [], [], 0

    notes: list[str] = []
    failures: list[str] = []
    moved = _merge_into(source, target, notes, failures)
    try:
        source.rmdir()
    except OSError:
        # 还有搬不走的文件（被占用、权限不足），目录留着即可。
        pass
    return notes, failures, moved


def _migration(status: str, **fields: Any) -> dict[str, Any]:
    """一次搬迁的结果。``status`` 只会是下面五种之一。"""
    result: dict[str, Any] = {
        "status": status,  # none | same | nested | done | failed
        "moved": 0,
        "warnings": [],
        "source": "",
        "target": "",
    }
    result.update(fields)
    return result


def _reconcile_data_dir() -> None:
    """启动时执行上次「更改数据目录」留下的搬迁。

    只有存在待搬迁标记才动手：指针本身就是权威。旧版本会在这里顺手「把没补项目
    代号的指针补上」，于是算出「把目录搬进它自己的子目录」，被嵌套检查拦下又不肯
    丢掉标记——每次启动都卡在同一条警告上，界面永远显示「重启后生效」。现在这种
    情况按「没有变化」收敛掉。

    测试用 ``SIXCOIN_DATA_DIR`` 指定了目录，一律不碰。
    """
    global MIGRATION
    if os.environ.get(_ENV_DATA, "").strip():
        return
    pending = pending_data_dir()
    if pending is None:
        return
    source = read_data_dir()
    if _same_dir(pending, source) or _same_dir(pending, normalize_data_dir(str(source))):
        MIGRATION = _migration("same", source=str(source), target=str(pending))
        clear_pending_data_dir()
        return
    if _is_nested(pending, source) or _is_nested(source, pending):
        MIGRATION = _migration("nested", source=str(source), target=str(pending))
        clear_pending_data_dir()
        return

    had_config = (source / "app.json").is_file()
    notes, failures, moved = _move_contents(source, pending)
    # 有东西没搬过去，或者配置文件没跟过来：指针留在原处，下次启动再试。搬了一半
    # 就改指针，等于让程序在一个残缺的目录里跑，用户的设置会凭空消失。重试是幂等
    # 的：已经搬过去的文件会被当成「目标已有」跳过。
    if failures or not pending.is_dir() or (had_config and not (pending / "app.json").is_file()):
        MIGRATION = _migration(
            "failed", source=str(source), target=str(pending), warnings=[*notes, *failures]
        )
        return
    try:
        write_data_dir(pending)
    except OSError as error:
        MIGRATION = _migration(
            "failed", source=str(source), target=str(pending), warnings=[*notes, str(error)]
        )
        return
    clear_pending_data_dir()
    MIGRATION = _migration(
        "done", source=str(source), target=str(pending), moved=moved, warnings=notes
    )


#: 本次启动的搬迁结果，由 ``bootstrap.prepare()`` 写日志、由快照交给设置页显示。
MIGRATION: dict[str, Any] = _migration("none")

_reconcile_data_dir()

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
