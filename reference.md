# Python 桌面项目执行标准

> 这是一份**可复制的规范**，不是某个项目的文档。新项目开工时把它复制到仓库根目录，之后所有环境、结构、界面的决定都以本文为准。
>
> 适用范围：Windows 上的 Python 桌面工具（单机、无服务端、双击即用）。Qt 原生界面与 pywebview 网页界面都覆盖。
>
> 三条使用规则：
> 1. 本文是默认值。要偏离，就在项目 README 里写一节「偏离标准」，说明哪一条、为什么。
> 2. 本文只写「怎么做」和「为什么」，不写改动历史。
> 3. 代码示例是模板，允许改名字，不允许改结构。

---

# 第一部分 环境标准

环境不一致是这类项目最大的隐性成本：换台机器跑不起来、CI 与本地行为不同、依赖版本漂移导致「昨天还好好的」。下面这套是硬性的。

## 1.1 三条不可协商的规定

| 规定 | 说明 | 违反后的症状 |
|---|---|---|
| **只用 uv 管理依赖** | 不用 pip、不用 poetry、不用 conda、不手工 `python -m venv` | 锁文件与虚拟环境对不上，`pip freeze` 与 `pyproject` 两套真相 |
| **虚拟环境只在项目根的 `.venv`** | 不建在用户目录、不共用、不提交 | 全局环境污染；两个项目互相顶掉依赖 |
| **依赖只写在 `pyproject.toml`** | 不保留 `requirements.txt` | 双轨制，改一处忘另一处 |

配套要求：`.venv/` 必须进 `.gitignore`，`uv.lock` 必须进版本库。

## 1.2 Python 版本策略

三处必须一致，改一处就要改三处：

| 位置 | 写法 | 含义 |
|---|---|---|
| `.python-version` | `3.11` | 开发用的**次版本**，不写补丁号（不写 `3.11.9`） |
| `pyproject.toml` 的 `requires-python` | `>=3.11` | 允许的最低版本，与上一行同一个次版本 |
| `uv.lock` | 由 uv 生成 | 记录实际解析结果，不手改 |

规则：

- 不要写 `>=3.11,<3.12`。除非确实用了会被移除的 API，否则上限只会带来麻烦。
- 不要为了「新特性」把版本抬到 3.13。桌面工具的价值在稳定，3.11 生态最全、WebView2 与 PySide6 的坑最少。
- 升级版本是一次**独立提交**：改 `.python-version` → 改 `requires-python` → `uv lock` → 跑全量测试 → 手工冒烟一遍界面。不要和功能改动混在一起。
- 不用 `from __future__ import annotations` 之外的兼容技巧；既然下限是 3.11，就直接用 `X | None`、`list[str]`、`match`。

## 1.3 `pyproject.toml` 模板

```toml
[project]
name = "my-tool"
version = "1.0.0"
description = "一句话说明这个工具做什么。"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "loguru>=0.7",
    "requests>=2.31",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff>=0.6",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B"]
# 个别规则要关就在这一行加，并写清原因；不要整组关掉。
# ignore = ["UP042"]

[tool.ruff.format]
quote-style = "double"
```

要点：

- **`dev` 分组里配了什么工具，就必须装什么工具。** 只写 `[tool.ruff]` 却不装 ruff，是最常见的假配置：文档说「提交前跑 ruff」，实际谁也没跑过。
- `pythonpath = ["."]` 让测试可以直接 `from app import ...`，不必装成包。
- `addopts = "-q"` 只是让输出干净；不要在这里塞 `--cov` 之类会影响所有人的参数。
- 需要 GUI 依赖时（PySide6、pywebview）注意它们体积大、平台相关，不要顺手放进 dev 分组。

## 1.4 依赖管理规则

| 操作 | 命令 | 备注 |
|---|---|---|
| 首次安装 | `uv sync` | 建 `.venv` 并按锁文件装依赖 |
| 加依赖 | `uv add requests` | 自动改 pyproject + 锁文件 + 装进 venv |
| 加开发依赖 | `uv add --dev ruff` | 落到 `dependency-groups.dev` |
| 删依赖 | `uv remove requests` | 三处一起改 |
| 升级单个包 | `uv lock --upgrade-package requests` | 不要整包 `--upgrade` |
| 跑命令 | `uv run pytest` | 保证用的是项目环境 |

写法约定：

- **依赖写下限（`>=x.y`），不写精确版本。** 精确版本由 `uv.lock` 负责，写进 pyproject 只会让升级更痛苦。
- 不写 `*`，不写 `latest`。
- 加依赖前先问：标准库能不能做？`urllib` 能发请求就不要 `requests`，`ctypes` 能调 Win32 就不要 `pywin32`。
- 每个依赖都要能说出用途。装进来没用到的包，一律删掉——它会在打包、审计、升级时持续收费。

## 1.5 镜像与锁文件（必须一致，容易踩）

`uv.lock` 会把**每个包的实际下载地址**写进去，而这个地址来自当时生效的索引。所以锁文件不是中立的：**它和索引是绑定的，两边必须一致。**

实测行为（uv 0.11）：

| 场景 | 结果 |
|---|---|
| 锁文件是官方地址，配置指向镜像 | `uv sync` 会**重新解析并改写锁文件**成镜像地址（工作区变脏） |
| 锁文件是官方地址，配置指向镜像，加 `--locked` | 直接失败：`The lockfile at uv.lock needs to be updated` |
| 锁文件是镜像地址，换台没配镜像的机器 | 仍会去镜像下载，慢或失败 |

结论与做法：

- **仓库里的 `uv.toml` 和 `uv.lock` 都写官方 PyPI。** 锁文件是分发物，应该指向所有人都能访问的规范源。
- 国内加速是**本机行为**，不进仓库：临时把 `uv.toml` 的 `url` 换成镜像，`uv lock` 之后**不要提交**这两处改动（或者干脆只改机器级配置，别碰仓库里的 `uv.toml`）。
- 换源之后必须 `uv lock` 重新生成，不能手改锁文件。

```toml
# uv.toml（与 pyproject.toml 同级，随仓库提交）
[[index]]
url = "https://pypi.org/simple"
default = true
```

自检：

```bash
grep -o 'https://[^/]*' uv.lock | sort | uniq -c
# 期望只看到 pypi.org / files.pythonhosted.org，看到镜像域名说明锁被本机配置改过
```

> 为什么不在锁里写镜像：镜像地址一换（换域名、换服务商、公司内网源下线），整个锁文件作废；而且别人 clone 下来拿到的是一个绑定你网络环境的文件。

## 1.6 目录骨架

```
<project>/
├─ pyproject.toml          依赖与工具配置
├─ uv.lock                 锁文件，进版本库
├─ uv.toml                 包索引（项目级，随仓库提交）
├─ .python-version         3.11
├─ .gitignore
├─ README.md               给人看：这是什么、怎么装、怎么用
├─ reference.md            本文件
├─ setup.bat               装环境
├─ run.bat                 启动主程序
├─ admin.bat               启动管理/配置界面（如果有第二个入口）
├─ <entry>.pyw             入口薄壳
├─ app/                    全部代码
│  ├─ paths.py
│  ├─ errors.py
│  ├─ models.py
│  ├─ settings.py
│  ├─ i18n.py
│  ├─ logging_setup.py
│  ├─ locales/             zh-CN.json / en-US.json
│  ├─ core/                纯逻辑
│  ├─ system/              操作系统集成
│  └─ ui/                  界面（qt/ 或 web/）
├─ config/                 运行时配置（不进版本库）
├─ logs/                   运行时日志（不进版本库）
└─ tests/                  test_*.py
```

`.gitignore` 最小集合：

```gitignore
__pycache__/
*.py[oc]
.venv/
.idea/
.vscode/
.pytest_cache/
.ruff_cache/
.mypy_cache/
logs/
config/
```

> 结尾必须有换行符。没有换行的最后一行在某些工具里会被吞掉。

## 1.7 启动脚本规范

三个 `.bat`，职责单一，模板照抄。

**`setup.bat`** —— 装环境，可以交互（有 `pause`）：

```bat
@echo off
chcp 65001 >nul
rem 安装或更新运行环境：创建虚拟环境并安装依赖。
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo [项目名] 没有找到 uv。
    echo [项目名] 请先安装 uv：https://docs.astral.sh/uv/
    pause
    exit /b 1
)

uv sync
if errorlevel 1 (
    echo [项目名] 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
)

echo [项目名] 环境已就绪，可以双击 run.bat。
pause
```

**`run.bat`** —— 启动 GUI，不弹控制台：

```bat
@echo off
chcp 65001 >nul
rem 在虚拟环境里运行入口脚本，不弹控制台窗口。
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo [项目名] 还没有安装运行环境。
    echo [项目名] 请先双击 setup.bat，或在命令行执行：uv sync
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "<entry>.pyw"
```

规则：

| 规则 | 原因 |
|---|---|
| 第一行 `@echo off`，第二行 `chcp 65001 >nul` | 否则中文提示是乱码 |
| `setlocal` | 不污染调用者的环境变量 |
| `cd /d "%~dp0"` | 双击时工作目录是 `System32`，不切会全部相对路径失效 |
| 用 `pythonw.exe` 而不是 `python.exe` | GUI 程序不该挂一个黑框 |
| `start ""` 且引号紧跟 | 否则标题被当成路径 |
| 检查 `.venv\Scripts\pythonw.exe` 是否存在 | 用户没装环境时给一句人话，而不是一串 traceback |
| 错误分支 `pause` + `exit /b 1` | 双击运行时窗口一闪而过，什么都看不到 |
| 提示统一前缀 `[项目名]` | 一眼看出是哪个程序在说话 |
| 文件保存为 **UTF-8 无 BOM + CRLF** | cmd 对 LF 和 BOM 都不友好 |

## 1.8 开发命令

```bash
uv sync                    # 装环境
uv run pytest              # 跑测试
uv run ruff check .        # 静态检查
uv run ruff format .       # 格式化
uv run python -m app.ui.web.app   # 临时起界面（按项目实际入口改）
```

不要用 `.venv\Scripts\python -m pytest` 这种写法——它跳过了 uv 的同步检查，容易在「改了 pyproject 但忘了 sync」时给出错误结果。

## 1.9 环境验收清单

新项目建好后，按顺序过一遍：

- [ ] `uv sync` 在干净目录能一次成功
- [ ] `uv run python -V` 输出与 `.python-version` 一致的次版本
- [ ] `uv run pytest` 能跑（哪怕只有一条空测试）
- [ ] `uv run ruff check .` 零报错
- [ ] `setup.bat` 双击能装、`run.bat` 双击能起
- [ ] 从别的目录用绝对路径调用 `run.bat`，程序行为不变
- [ ] `.venv`、`logs`、`config` 都没被 git 跟踪
- [ ] `uv.lock` 已提交，且 `grep registry uv.lock` 的结果符合预期

---

# 第二部分 代码结构标准

## 2.1 分层模型

```
        入口薄壳（<entry>.pyw）
                │
        ┌───────┴────────┐
        ▼                ▼
   ui/qt 或 ui/web    （第二个界面）
        │                │
        └───────┬────────┘
                ▼
             core            纯逻辑：解析、匹配、计算、执行语义
                │
                ▼
   models / settings / errors / i18n / paths     基础层
                ▲
                │
            system           系统集成：进程、注册表、剪贴板、热键
```

四层的定义：

| 层 | 内容 | 依赖谁 | 谁依赖它 |
|---|---|---|---|
| 入口 | `.pyw` 薄壳、`.bat` | ui | 无 |
| 界面 `ui/` | 窗口、渲染、事件、状态机 | core、基础层、system | 入口 |
| 核心 `core/` | 纯函数与纯类，零 I/O 依赖（除明确的服务调用） | 基础层、标准库 | ui |
| 系统 `system/` | Win32 / 注册表 / 子进程 / 剪贴板 | 标准库 | ui、core（单向） |
| 基础 | 路径、异常、模型、配置、文案、日志 | 标准库 | 所有人 |

## 2.2 依赖方向与硬约束

| 约束 | 原因 | 怎么强制 |
|---|---|---|
| `core` 不导入任何界面库 | 核心逻辑要能被纯 pytest 覆盖，也要能被两个界面共用 | AST 静态测试 |
| `system` 不导入界面库 | 系统能力是基础设施，不该知道谁在调用 | AST 静态测试 |
| 全项目不调用 `os.chdir` | 工作目录是进程级全局状态，被所有线程共享；切换后其他线程的相对路径就落到别处 | AST 静态测试 |
| 入口文件 < 30 行 | 装配集中在一处，入口只负责「把 app 叫起来」 | 行数测试 |
| 内部路径一律来自 `paths.py` | 不允许模块里自己拼 `Path("config")` | 代码评审 + 路径测试 |

前三条约 20 行代码就能钉死，性价比极高：

```python
def _sources(directory: Path):
    for path in directory.rglob("*.py"):
        yield path, path.read_text(encoding="utf-8")


def _imported(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_core_has_no_ui_imports():
    forbidden = ("PySide6", "PyQt5", "PyQt6", "webview")
    for path, text in _sources(paths.PACKAGE_DIR / "core"):
        modules = _imported(ast.parse(text, filename=str(path)))
        assert not [m for m in modules if m.split(".")[0] in forbidden], path.name
```

## 2.3 模块职责

| 模块 | 只做 | 不做 |
|---|---|---|
| `paths` | 由 `__file__` 推导全部绝对路径；解析配置里的相对路径 | 不判断文件是否存在 |
| `settings` | 读写 JSON、校验结构、夹取数值、原子写入 | 不缓存、不持有界面状态 |
| `models` | 数据结构、常量、字段校验、写盘前归一化 | 不读写文件 |
| `i18n` | 扫描语言目录、查表、填占位符 | 不关心调用者是谁 |
| `errors` | 异常类型定义 | 不含任何逻辑 |
| `logging_setup` | 配置 loguru、装钩子、致命错误弹窗退出 | 不写业务日志 |
| `core.*` | 纯逻辑 | 不弹窗、不写文件、不碰控件 |
| `system.*` | 与操作系统打交道 | 不做业务判断 |
| `ui.*` | 渲染与事件 | 不实现业务规则 |

判断一个函数该放哪层，问一句：**它需要知道「用户看到什么」吗？** 需要就是 ui，不需要就是 core。

## 2.4 入口薄壳

```python
"""<项目名> 主程序入口。

双击 ``run.bat`` 时由虚拟环境里的 ``pythonw.exe`` 执行本文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _run() -> None:
    from app.ui.app import main

    main()


if __name__ == "__main__":
    _run()
```

- 延迟导入 `app.ui.app`：让入口在 import 阶段不碰任何重量级依赖，报错时更干净。
- `sys.path.insert` 是保险，不是必需（脚本目录本来就在 `sys.path[0]`），但在被快捷方式、计划任务、其他进程以奇怪方式拉起时能省掉一类「找不到 app」的报错。
- 入口里**不写**任何业务、不读配置、不建窗口。

## 2.5 路径与工作目录

`paths.py` 是唯一允许推导路径的地方：

```python
PACKAGE_DIR = Path(__file__).resolve().parent
PROGRAM_DIR = PACKAGE_DIR.parent

CONFIG_DIR = PROGRAM_DIR / "config"
LOG_DIR = PROGRAM_DIR / "logs"
APP_CONFIG_PATH = CONFIG_DIR / "app.json"


def resolve_user_path(raw: str) -> Path:
    """把配置里写下的路径解析成绝对路径，基准是程序目录而不是 cwd。"""
    text = (raw or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1]
    if not text:
        return PROGRAM_DIR
    path = Path(text)
    return path if path.is_absolute() else (PROGRAM_DIR / path).resolve()
```

规则：

- 配置里的相对路径以**程序目录**为基准，不是 cwd。这样从任何地方启动，配置都指向同一个位置。
- 启动子进程时，工作目录用参数传：`subprocess.Popen(..., cwd=...)`、`os.startfile(path, cwd=...)`、`ShellExecuteW(..., lpDirectory=...)`。
- 日志、配置永远写绝对路径。
- 用户输入的路径要 `strip()`、去首尾引号、`/` 转 `\`。

## 2.6 配置

**两个文件，职责分开**：

| 文件 | 内容 | 谁改 |
|---|---|---|
| `config/app.json` | 应用级设置：语言、外观、上限、密钥 | 设置界面 |
| `config/<domain>.json` | 业务数据 | 主界面 |

规则：

- **首次启动自动生成**一份可用内容，用户不需要先手写 JSON。
- **原子写入**：临时文件 + `os.replace`。中途崩溃不会留下半个文件。

```python
def _write_json(path: Path, payload: Any) -> None:
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
```

- **读的时候夹取，不信任文件**：数字越界就夹到范围内，非数字就回退默认值，字符串一律 `strip()`。
- **未知键原样保留**：以后加字段不会让旧配置报错，也不会在保存时丢掉用户手写的扩展字段。
- **结构损坏要报错，不要静默重建**：抛 `ConfigError`，由上层弹窗告知日志路径。静默重建会把用户数据洗掉。
- 内存里用扁平结构（`max_depth`），写盘时还原成嵌套（`navigation.max_depth`），调用方不必层层取属性。

## 2.7 领域模型与校验

- 用 `dataclass`，配 `from_dict` / `to_dict`，JSON 结构是对外硬约定。
- `to_dict()` **只输出约定的键**，不把内部字段（uid、缓存、临时状态）写进文件。
- 校验顺序固定：**先归一化，再校验**。

```python
def save(self) -> Result:
    for item in self._items:
        item.normalize()  # 清理输入，可能把 "|||" 变成 ""
    error = validate(self._items)
    if error is not None:  # 只报第一个错误
        ...
```

顺序反了会漏掉一类错误：`"|||"` 归一化后为空，但校验发生在归一化之前就会放行。

- **只报第一条错误**，并把选中项跳到出错的那一项。一次给用户十几个红框，他只会放弃。
- 错误定位用**显式坐标**（`(group, index)` 二元组），不要「当前项」这种隐含状态。任何方法都必须说明它作用在谁身上。

## 2.8 异常体系

一个基类 + 少量子类，够用就好：

```python
class AppError(Exception):
    """本程序抛出的所有异常的基类。"""

class ConfigError(AppError):    # 配置缺失 / 读不出来 / 结构不合法
class ServiceError(AppError):   # 远程服务调用失败
class ActionError(AppError):    # 动作执行失败
class CalcError(AppError):      # 计算失败
```

| 场景 | 策略 |
|---|---|
| 配置损坏 | `ConfigError` → 记日志 → 弹窗给日志路径 → 退出 |
| 网络失败 | `ServiceError` → 写进对应那一行的文案，程序继续 |
| 单个动作失败 | 记 warning，不打断其他条目 |
| 写配置失败 | 记日志 + 界面提示条，不崩 |
| 未捕获异常 | `sys.excepthook` / `threading.excepthook` 记录后弹窗 |

原则：**能降级的降级，不能降级的必须留下可读的原因。任何静默失败都算缺陷。**

关于「异常里放本地化文案」的取舍：

- 放（`raise ConfigError(i18n.t("config.bad_json", name=...)` )：界面层直接 `str(error)` 就能显示，代码最短。代价是 core 层绑定了文案层，且切换语言后已抛出的异常文案不会变。
- 不放：异常带结构化字段，界面层负责翻译。更干净，但每个调用点都要多写一段映射。

单机小工具选**放**，因为文案要在异常发生的那一刻就确定，界面层不需要知道字段名。但要在 `errors.py` 里写清这个取舍，避免后来者以为是疏忽。

## 2.9 日志

用 loguru，理由：线程/进程安全的队列、轮转与保留内置、不涉及相对路径。

```python
def setup(name: str) -> Path:
    paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = paths.LOG_DIR / f"{name}_{datetime.now():%Y-%m-%d_%H-%M-%S}.log"
    logger.remove()
    logger.add(
        str(log_file),
        level="DEBUG",
        encoding="utf-8",
        enqueue=True,  # 多线程安全
        backtrace=True,
        diagnose=False,  # 不把局部变量写进日志，避免泄露密钥
        rotation="5 MB",
        retention="14 days",
        format="[{level}] [{time:YYYY-MM-DD HH:mm:ss}] {message}",
    )
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    return log_file
```

规则：

- 每次启动新建一个文件，文件名带时间戳。不要追加到同一个文件——出问题时能一眼定位是哪次运行。
- `diagnose=False`：默认会把局部变量全打进日志，密钥会跟着泄露。
- 致命错误要**弹窗**，因为 `.pyw` 进程没有控制台：

```python
def fatal(message: str) -> None:
    try:
        logger.critical(message)
        logger.complete()
    except Exception:
        pass
    ctypes.windll.user32.MessageBoxW(None, str(message), i18n.t("fatal.title"), 0x10)
    os._exit(1)
```

- `logger.complete()` 之后再退出，否则队列里的最后几条会丢。
- 用 `os._exit(1)` 而不是 `sys.exit()`：后者会等所有非 daemon 线程，可能永远退不掉。
- 日志内容写「发生了什么 + 关键参数」，不写「进入函数」这类噪音。

## 2.10 本地化

- 文案放 `app/locales/{语言代码}.json`，**文件名就是语言代码**（`zh-CN`、`en-US`，BCP-47）。
- 启动时扫描目录，放进去什么语言就支持什么语言，不加代码。
- `t("键", 占位符=值)` 查表；缺键回退默认语言；再缺就返回键名本身（绝不抛异常）。
- 占位符格式统一 `{name}`，不允许中文占位符。
- 列举多个项目时分隔符要按语言走（中文 `、`，英文 `, `）。

键命名：

```
<域>.<对象>_<属性>
manager.count            界面域 + 字段
settings.max_depth_hint  设置域 + 字段 + 用途后缀
type.file                枚举值
field.path               字段名
debug.restart            动作名
fatal.config             致命错误
```

前端约定：

| 属性 | 用途 |
|---|---|
| `data-i18n="key"` | 替换 `textContent` |
| `data-i18n-placeholder="key"` | 替换 `placeholder` |
| `data-i18n-title="key"` | 替换 `title` |
| `data-i18n-aria="key"` | 替换 `aria-label` |

动态文案用 `T("key", {name: value})`，键表由后端一次性下发。

必须有的守卫测试：

```python
def test_every_locale_has_the_same_keys(): ...  # 键集合完全相等
def test_placeholders_match_the_default_language(): ...  # {name} 集合完全相等
```

这两条能挡住 90% 的文案事故（界面出现裸露键名、占位符对不上导致 `KeyError`）。

## 2.11 线程模型

| 线程 | 做什么 | 禁止 |
|---|---|---|
| UI 主线程 | 全部控件操作、动画、渲染 | 禁止阻塞（网络、磁盘遍历、`sleep`） |
| 后台/线程池 | 网络、计算、目录扫描 | 禁止直接碰控件 |
| 系统回调线程（热键等） | 只发信号 | 禁止任何界面调用 |

- 跨线程**只传数据，不传控件**。Qt 用信号，pywebview 用返回值。
- 异步结果用**代次号**丢弃过期回包，不要试图取消正在跑的请求：

```python
self._generation += 1
generation = self._generation
# 回包时
if generation != self._generation:
    return  # 过期，直接丢
```

- 线程池提交的 `QRunnable` 要显式持有引用，否则 Qt 还在跑、Python 包装对象已被回收，进程直接崩。

## 2.12 命名与注释

| 对象 | 规则 | 例 |
|---|---|---|
| 模块 | 全小写、单数、下划线 | `navigation.py` 不是 `navigations.py` |
| 类 | PascalCase | `DirectoryNavigator` |
| 函数/变量 | snake_case | `resolve_user_path` |
| 常量 | UPPER_SNAKE | `MAX_EXPLORE_DEPTH` |
| 私有 | 单下划线前缀 | `_read_json` |
| 文案键 | 点分小写 | `manager.count` |
| CSS 类 | kebab-case | `.modal-actions` |
| JS 函数 | camelCase | `applyStrings` |
| JS 常量 | UPPER_SNAKE | `MODAL_EXIT_MS` |

注释规则：

- **用中文写，标点也用中文。** 变量名、函数名保持英文。
- **只写「现在为什么这样」，不写「从 X 改成 Y」。** 版本历史归 git。
- 每个模块顶部一句 docstring，说明它负责什么、不负责什么。
- 捕获异常必须写清理由：为什么这里能吞、吞掉之后用户看到什么。空 `except: pass` 一律视为缺陷。
- 不写「进入函数」「开始处理」这类复述代码的注释。

## 2.13 测试

结构：

```
tests/
├─ conftest.py              路径与语言固定
├─ test_paths.py            路径解析
├─ test_settings.py         配置读写、夹取、归一化
├─ test_<domain>.py         每个 core 模块一份
├─ test_<ui>_api.py         界面后端的接口层
├─ test_source_hygiene.py   静态守卫
└─ test_i18n.py             文案完整性
```

约定：

- 涉及文件系统一律用 `tmp_path`，不碰真实配置。
- 涉及系统能力注入假实现（假剪贴板、假 opener、假目录列举），测试里不起真实进程。
- 断言文案时用中文，`conftest.py` 把语言固定住。
- `conftest.py` 里放一个 `autouse` 的 fixture 做环境归一化，别在每个测试里重复。

```python
@pytest.fixture(autouse=True)
def fixed_locale():
    i18n.set_language("zh-CN")
    yield
    i18n.set_language("zh-CN")
```

必测的四类：

1. **归一化/校验**的边界（空串、全分隔符、越界数字、非数字）。
2. **路径解析**：相对路径以程序目录为基准、带引号、带空格。
3. **状态机/优先级链**：每个分支至少一条。
4. **静态守卫**：没有 `chdir`、core 没混进界面库、入口够薄。

## 2.14 提交前检查

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

- 三项全绿才提交。
- 改动界面后额外手工冒烟一遍（自动化测试覆盖不到视觉）。
- 改了配置结构就顺手更新 `docs/configuration.md`；文档和代码不一致比没有文档更糟。

---

# 第三部分 pywebview 界面设计标准

## 3.1 选型判断

| 维度 | Qt（PySide6） | pywebview |
|---|---|---|
| 启动速度 | 快（进程内） | 慢（WebView2 冷启动 300–800ms） |
| 常驻/需要热键秒开 | ✅ 选它 | ❌ |
| 表单密集、列表复杂、要深色模式 | 一般 | ✅ 选它 |
| 界面迭代速度 | 改样式要重跑 | 改 CSS 刷新即可 |
| 打包体积 | 大（Qt 运行时） | 小（依赖系统 WebView2） |
| 无边框/透明/异形窗口 | ✅ 支持 | ❌ Windows 不支持 `transparent` |

结论：**常驻的快速唤起窗口用 Qt，按需打开的配置/管理界面用 pywebview。** 两者共用 `core`，只有渲染层不同。

## 3.2 窗口装配

```python
_BACKGROUND = {"light": "#f0f2f5", "dark": "#14161a"}


def main() -> None:
    logging_setup.setup("manage")

    api = ManagerApi()  # 先建 API：配置错误在这里就能报
    theme = api.get_state()["theme"]

    window = webview.create_window(
        i18n.t("app.title"),
        str(paths.WEB_DIR / "index.html"),
        js_api=api,
        width=...,
        height=...,
        min_size=(...),
        background_color=_BACKGROUND.get(theme, _BACKGROUND["light"]),
    )
    api.attach(window)
    window.events.closing += _make_closing_handler(api)

    webview.start()
```

参数规则：

| 参数 | 规则 |
|---|---|
| `width/height` | 屏幕的 85%，不要写死像素 |
| `min_size` | 屏幕的 50%，低于这个尺寸布局会挤坏 |
| `background_color` | 与网页 `--bg` 同色，否则首帧会闪白 |
| `js_api` | 一个对象，方法名即前端可调用的名字 |
| `text_select` | 默认关闭；需要复制的区域单独开 |

## 3.3 前后端契约

### 3.3.1 状态快照

**每个改变状态的方法都返回完整快照**，前端拿到就整体重绘。前端不维护业务数据，只保留纯视图状态（折叠了哪些、搜索词是什么）。

```json
{
  "ok": true,
  "message": "",
  "items": [{ "index": 0, "name": "…", "enabled": true }],
  "selection": { "kind": "item", "group": 0, "index": 1 },
  "dirty": false,
  "errors": [{ "group": 0, "index": 1, "field": "name", "label": "名称" }],
  "language": "zh-CN",
  "theme": "light"
}
```

好处：后端不需要知道 DOM，前端不需要知道规则；一个 `apply()` 就能覆盖所有情况，不会出现「改了一半」的中间态。

例外：**逐字符触发的字段写入**只返回 `{"ok": bool}`。返回整份快照太重，而且前端已经知道自己改了什么。

### 3.3.2 方法分类

| 类别 | 例 | 返回 |
|---|---|---|
| 读取 | `get_state` `get_strings` | 完整数据 |
| 选择 | `select_item` | 快照 |
| 结构编辑 | `add_item` `delete_item` `move_item` | 快照 |
| 字段编辑 | `set_field` `set_argument` | `{"ok": bool}` |
| 设置 | `update_settings` `set_language` | 快照 |
| 系统 | `browse_file` `browse_dir` `save` | 值 / 快照 |

铁律：**越界或非法参数不抛异常**，原样返回当前快照。网页拿到 Python traceback 是最难排查的一类问题。

### 3.3.3 线程

pywebview 给每次 JS 调用起一个线程执行 `js_api` 方法。所以：

- API 对象的状态会被多个线程同时改 → 只做「读-改-写」的小步操作，不做长耗时任务。
- 需要在界面线程上做的事（`evaluate_js`、`create_file_dialog`）必须显式切线程。
- `js_api` 方法返回前必须结束，不要在里面 `sleep` 或等网络。

### 3.3.4 关闭握手（必读）

`window.events.closing` 在 **UI 线程**执行。在这个回调里调用 `evaluate_js` 会等待同一个正在执行回调的消息循环 → **死锁**。

正确做法是三步：

```
closing 回调（UI 线程）
  → 起一个工作线程去弹页面里的确认框
  → return False（取消这次关闭）

工作线程
  → evaluate_js("window.host.askUnsaved()")
  → 页面弹自己的对话框

页面
  → answer_close("close" | "cancel")
  → force_close() 或什么都不做
```

```python
def _make_closing_handler(api):
    def on_closing():
        if not api.dirty or api.close_confirmed:
            return True
        api.request_close_prompt()  # 内部起线程
        return False

    return on_closing
```

页面不可用（渲染进程崩了、脚本报错）时 `evaluate_js` 返回假值，必须能退回原生 `MessageBoxW`，保证窗口永远关得掉。

不要用长期阻塞的 long-poll 线程做这件事：pywebview 的 js_api 线程不是 daemon，会拖住进程退出。

**桥接全局名要避开元素 id。** 浏览器会把每个带 `id` 的元素挂成 `window.<id>`，所以页面里有 `<div id="app">` 时，`window.app` 已经被那个 div 占住了。桥接对象用 `window.host`、`window.quickRun` 这类不会和 id 撞车的名字。

## 3.4 前端工程结构

三个静态文件，**没有构建步骤**：

```
ui/web/
├─ index.html     结构与静态文案（data-i18n*）
├─ styles.css     全部样式，颜色走 CSS 变量
└─ app.js         渲染与事件，无框架
```

不引入打包器、不引入框架。理由：这类界面规模在 1000–2000 行以内，构建链带来的复杂度远大于收益；改完刷新即可见，是 pywebview 最大的效率优势。

### 3.4.1 初始化时序

```js
async function init() {
  bind();                     // 先绑事件，避免首帧前点击丢失
  await loadStrings();        // 拉文案表
  applyStrings();             // 替换静态标记
  apply(await call('get_state'));  // 拉状态并整体渲染
}

if (bridge()) {
  init();
} else {
  window.addEventListener('pywebviewready', init, { once: true });
}
```

`window.pywebview` 不是立刻存在的，必须等 `pywebviewready`；但脚本也可能在桥就绪后才执行，所以两条路都要走。

### 3.4.2 桥接封装

```js
function bridge() {
  return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
}

async function call(method) {
  const api = bridge();
  if (!api) return null;
  const args = Array.prototype.slice.call(arguments, 1);
  try {
    return await api[method].apply(api, args);
  } catch (error) {
    console.error(method, error);
    toast(T('app.action_failed', { error: error }), false);
    return null;              // 统一返回 null，调用方只需判空
  }
}
```

所有 Python 调用都走 `call()`，不要在业务代码里直接写 `window.pywebview.api.xxx`。

### 3.4.3 渲染

```js
function apply(data) {
  if (!data) return;
  state.data = data;
  if (data.theme && document.documentElement.dataset.theme !== data.theme) {
    document.documentElement.dataset.theme = data.theme;
  }
  renderList();
  renderDetail();
  renderDirty(data.dirty);
  clearInvalid();
  (data.errors || []).forEach(e => markInvalid(e.field));
  if (data.message) toast(data.message, data.ok);
}
```

### 3.4.4 防抖写回

输入框逐字符触发写入，必须合并：

```js
function queue(key, exec, delay) {
  const existing = pending.get(key);
  if (existing) clearTimeout(existing.timer);
  const timer = setTimeout(() => { pending.delete(key); exec(); }, delay || 80);
  pending.set(key, { timer, exec });
}

async function flushPending() {
  const jobs = [];
  pending.forEach(item => { clearTimeout(item.timer); jobs.push(item.exec()); });
  pending.clear();
  await Promise.all(jobs);
}
```

**结构性操作（保存、增删、拖动、切换类型）之前必须 `await flushPending()`**，否则用户刚敲的字会被丢掉。

### 3.4.5 重建列表时保住焦点

每次状态变化都重建 DOM，焦点会丢。重建前记 `data-focus-id`，重建后恢复：

```js
const active = document.activeElement;
const activeId = active && list.contains(active) ? active.dataset.focusId : null;
list.innerHTML = '';
// ... 重建 ...
restoreFocus(activeId);
```

## 3.5 设计令牌

### 3.5.1 三条设计原则

1. **中性灰底 + 单一强调色。** 界面 90% 是灰阶，只有主操作、选中态、焦点环用蓝色。多色只用于类型标识（小圆点、胶囊），且必须同时有文字，不能只靠颜色传达信息。
2. **8px 网格。** 所有间距、高度、圆角都取 2 的倍数或 8 的倍数（4/6/8/10/12/14/16/18/20/22/28/32/44）。不要出现 7px、13px、23px。
3. **两套变量，一套结构。** 深色模式只覆盖 CSS 变量，不改任何布局规则。任何新增颜色都必须同时在 `[data-theme="dark"]` 里给值。

### 3.5.2 颜色令牌

| 变量 | 浅色 | 深色 | 用途 |
|---|---|---|---|
| `--bg` | `#f0f2f5` | `#14161a` | 应用底色 |
| `--panel` | `#ffffff` | `#1c1f24` | 卡片、侧栏、弹窗 |
| `--border` | `#e5e7eb` | `#2a2e35` | 常规描边 |
| `--border-strong` | `#d1d5db` | `#3a3f47` | 输入框描边 |
| `--border-soft` | `#edf1f6` | `#24282e` | 分隔线、树形缩进线 |
| `--text` | `#374151` | `#d7dbe2` | 正文 |
| `--text-strong` | `#111827` | `#f0f2f5` | 标题 |
| `--text-soft` | `#6b7280` | `#9aa1ac` | 次级说明 |
| `--muted` | `#9ca3af` | `#6f7681` | 弱化文字、图标 |
| `--placeholder` | `#c3c9d4` | `#5b626d` | 占位符 |
| `--surface-sunken` | `#f9fafb` | `#191c21` | 内凹区域（搜索框底） |
| `--surface-hover` | `#f8fafc` | `#24282f` | hover 底 |
| `--surface-active` | `#f1f5f9` | `#2b3038` | active / 图标按钮底 |
| `--surface-muted` | `#f3f4f6` | `#21252b` | 分段控件槽底 |
| `--blue` | `#3b82f6` | `#4c8df6` | 主色（填充） |
| `--blue-dark` | `#2563eb` | `#6aa2f9` | 主色 hover |
| `--blue-text` | `#2563eb` | `#8ab4f8` | 主色文字 |
| `--blue-soft` | `#eff6ff` | `#1b2a44` | 选中底 |
| `--blue-border` | `#bfdbfe` | `#2f4a74` | 选中描边 |
| `--red` / `--danger-text` | `#ef4444` / `#dc2626` | `#e5484d` / `#fca5a5` | 危险操作 |
| `--amber` | `#f59e0b` | `#f5a524` | 警告、未保存 |
| `--green` | `#10b981` | `#2fbf8f` | 成功、完成态 |
| `--violet` | `#8b5cf6` | `#a78bfa` | 第四类标识 |
| `--shadow` | `rgba(15,23,42,.12)` | `rgba(0,0,0,.45)` | 常规投影 |
| `--shadow-strong` | `rgba(15,23,42,.18)` | `rgba(0,0,0,.6)` | 弹窗投影 |
| `--backdrop` | `rgba(15,23,42,.32)` | `rgba(0,0,0,.55)` | 遮罩 |
| `--focus-ring` | `rgba(59,130,246,.14)` | `rgba(76,141,246,.25)` | 焦点外发光 |
| `--scrollbar` | `#d3d8e0` | `#3a4048` | 滚动条 |

深色模式的关键：**不要简单反转**。深色下主色要提亮（`#3b82f6` → `#4c8df6`），文字要降到 `#d7dbe2` 而不是纯白（纯白在深底上会晕光），阴影要更重、范围更大。

### 3.5.3 字体

```css
font-family: "Microsoft YaHei", "Segoe UI", "Helvetica Neue", sans-serif;
```

中文优先微软雅黑，英文回退 Segoe UI。等宽场景（路径、快捷键、代码）用 `Consolas, "Courier New", monospace`。

| 场景 | 字号 | 行高 | 字重 |
|---|---|---|---|
| 正文基准 | 15px | 1.55 | 400 |
| 详情页大标题 | 21px | 1.35 | 500 |
| 侧栏标题 | 15.5px | 1.35 | 500 |
| 列表项标题 | 14px | — | 400（选中 500） |
| 按钮 | 14px | — | 400 |
| 输入框 | 14px | — | 400 |
| 表单标签 | 13px | — | 400 |
| 列表项副标题 | 12px | — | 400 |
| 提示文字 | 12.5px | 1.65 | 400 |
| 计数/徽标 | 11.5px | 1.7 | 400 |
| 快捷键 `kbd` | 11px | — | 400 |

规则：**字号只用这十档**，不要出现 13.7px。中文在 15px 以下要谨慎，12px 以下只用于非关键信息。

### 3.5.4 尺寸与间距

| 元素 | 高度 | 内边距 | 圆角 |
|---|---|---|---|
| 主按钮 | 36px | `0 15px` | 8px |
| 块级按钮 | 40px | `0 12px 0 16px` | 8px |
| 小按钮（工具栏） | 32px | `0 13px` | 8px |
| 输入框 / 下拉框 | 38px | `0 11px` | 8px |
| 胶囊按钮 | 34px | `0 15px` | 999px |
| 图标按钮 | 28px | 0 | 6px |
| 开关 | 36×21px | — | 999px |
| 开关（迷你） | 28×16px | — | 999px |
| 卡片 | — | `20px 22px 22px` | 12px |
| 弹窗（窄） | — | 见 3.7.6 | 12px |

间距档位：`2 4 6 8 10 12 14 16 18 20 22 28 32 44`。

典型组合：

- 表单字段内：标签与控件 `6–7px`，字段之间 `16–18px`。
- 卡片内：标题与内容 `10px`，区块之间 `20px`，卡片之间 `16px`。
- 页面：`28px 32px 44px`（上/左右/下），底部留 44px 是给滚动到底的呼吸空间。

### 3.5.5 阴影与动效

| 用途 | 值 |
|---|---|
| 弹窗 | `0 18px 48px var(--shadow-strong)` |
| 下拉菜单 | `0 12px 28px var(--shadow)` |
| 分段控件选中块 | `0 1px 3px var(--shadow)` |
| Toast | `0 10px 30px var(--shadow-strong)` |

缓动统一 `--ease: cubic-bezier(0.2, 0.7, 0.3, 1)`（快出慢入，接近系统级手感）。

### 3.5.6 变量模板

```css
:root {
  color-scheme: light;
  --bg: #f0f2f5;        --panel: #ffffff;
  --border: #e5e7eb;    --border-strong: #d1d5db;   --border-soft: #edf1f6;
  --text: #374151;      --text-strong: #111827;
  --text-soft: #6b7280; --muted: #9ca3af;           --placeholder: #c3c9d4;
  --surface-sunken: #f9fafb; --surface-hover: #f8fafc;
  --surface-active: #f1f5f9; --surface-muted: #f3f4f6;
  --blue: #3b82f6;      --blue-dark: #2563eb;       --blue-text: #2563eb;
  --blue-soft: #eff6ff; --blue-border: #bfdbfe;
  --red: #ef4444;       --danger-text: #dc2626;     --danger-soft: #fef2f2;
  --amber: #f59e0b;     --amber-soft: #fef3c7;      --amber-text: #92400e;
  --green: #10b981;     --green-soft: #d1fae5;      --green-text: #065f46;
  --shadow: rgba(15,23,42,.12);      --shadow-strong: rgba(15,23,42,.18);
  --backdrop: rgba(15,23,42,.32);
  --focus-ring: rgba(59,130,246,.14);
  --radius: 8px;        --radius-lg: 12px;
  --ease: cubic-bezier(0.2, 0.7, 0.3, 1);
}

[data-theme="dark"] {
  color-scheme: dark;
  --bg: #14161a;        --panel: #1c1f24;
  --border: #2a2e35;    --border-strong: #3a3f47;   --border-soft: #24282e;
  --text: #d7dbe2;      --text-strong: #f0f2f5;
  --text-soft: #9aa1ac; --muted: #6f7681;           --placeholder: #5b626d;
  --surface-sunken: #191c21; --surface-hover: #24282f;
  --surface-active: #2b3038; --surface-muted: #21252b;
  --blue: #4c8df6;      --blue-dark: #6aa2f9;       --blue-text: #8ab4f8;
  --blue-soft: #1b2a44; --blue-border: #2f4a74;
  --red: #e5484d;       --danger-text: #fca5a5;     --danger-soft: #3a1d1f;
  --amber: #f5a524;     --amber-soft: #3a2e12;      --amber-text: #fcd34d;
  --green: #2fbf8f;     --green-soft: #12352b;      --green-text: #6ee7b7;
  --shadow: rgba(0,0,0,.45);         --shadow-strong: rgba(0,0,0,.6);
  --backdrop: rgba(0,0,0,.55);
  --focus-ring: rgba(76,141,246,.25);
}
```

## 3.6 布局骨架

### 3.6.1 应用壳

```css
.app {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  height: 100vh;
}
```

`minmax(0, 1fr)` 不能写成 `1fr`：默认的 `min-width: auto` 会让右栏被内容撑开，长路径一多就横向溢出。

### 3.6.2 侧栏（上中下固定、中间滚动）

```css
.sidebar {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  gap: 14px;
  min-height: 0;          /* 关键 */
  padding: 20px 18px 18px;
  border-right: 1px solid var(--border);
}
.list {
  min-height: 0;          /* 关键 */
  overflow-y: auto;
}
```

**这是最容易出错的地方**，症状是「列表越来越长，底部按钮被顶出屏幕」：

- grid/flex 的滚动子项必须同时有 `minmax(0, 1fr)`（或 `flex: 1` + `min-height: 0`）和 `overflow-y: auto`。
- 只写 `overflow-y: auto` 不给高度约束，等于没写。
- `min-height: 0` 是必需的：flex/grid 子项的默认 `min-height: auto` 会阻止收缩。

### 3.6.3 详情区

```css
.detail {
  min-width: 0;
  padding: 28px 32px 44px;
  overflow-y: auto;
}
.editor {
  max-width: 860px;
  margin: 0 auto;          /* 大屏居中，不拉成一行字 */
}
```

### 3.6.4 空状态

没有数据时不要留白屏，给一个居中的占位块：一个大号线性图标（96×96，`stroke: var(--art-stroke)`，`stroke-width: 2`）+ 一句标题 + 一句说明 + 一个主按钮。图标用 SVG 手写，不引图标库。

## 3.7 组件规范

### 3.7.1 按钮层级

| 类 | 外观 | 用在哪 |
|---|---|---|
| `.btn.primary` | 蓝底白字 | 一屏只有一个，主操作 |
| `.btn` | 白底 + `--border-strong` 描边 | 常规操作 |
| `.btn.ghost` | 无底无边，hover 出 `--surface-active` | 次要操作（上移/下移/取消） |
| `.btn.soft` | 无底无边，hover 出 `--blue-soft` + `--blue-text` | 轻量引导（切换到组） |
| `.btn.danger` | 红底白字 | 破坏性确认（弹窗里的「删除」） |
| `.btn.danger-ghost` | 红字无底，hover 出 `--danger-soft` | 破坏性入口（页面上的「删除该分组」） |

规则：

- **同一区域只能有一个 primary。** 两个蓝按钮等于没有主次。
- 破坏性操作：入口用 `danger-ghost`（轻），确认弹窗里的最终按钮用 `danger`（重）。
- `:active` 统一 `transform: translateY(1px)`，给物理反馈。
- `:disabled` 统一灰底 + `--muted` 文字 + `cursor: default`，且取消位移。

### 3.7.2 输入框

```css
input[type="text"] {
  width: 100%;
  height: 38px;
  padding: 0 11px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  background: var(--panel);
  font-family: inherit;   /* 必须显式继承，否则用浏览器默认字体 */
  font-size: 14px;
}
input:focus {
  outline: none;
  border-color: var(--blue);
  box-shadow: 0 0 0 3px var(--focus-ring);
}
```

**选择器必须收窄。** 写 `input[type="text"] { ... }` 这种全局规则时，任何例外都要靠更高特异性去覆盖；一旦忘了，就会出现「密码框继承了搜索框的 34px 左内边距」这类问题。正确做法：

```css
/* 搜索框的样式只在搜索框里生效 */
.search input[type="text"] { padding: 0 32px 0 34px; }
```

带后缀图标的输入框（如密码可见切换）：

```css
.secret { position: relative; display: flex; align-items: center; }
.secret input { padding-right: 38px; }
.secret-toggle { position: absolute; right: 5px; width: 26px; height: 26px; }
```

### 3.7.3 开关

```css
.switch-track {
  position: relative;
  width: 36px; height: 21px;
  border-radius: 999px;
  background: var(--switch-track);
  transition: background 0.18s ease;
}
.switch-track::after {
  content: ""; position: absolute; top: 2px; left: 2px;
  width: 17px; height: 17px; border-radius: 50%;
  background: var(--knob);
  transition: transform 0.18s var(--ease);
}
.switch input:checked + .switch-track { background: var(--blue); }
.switch input:checked + .switch-track::after { transform: translateX(15px); }
```

真实 `<input type="checkbox">` 用 `opacity: 0` 隐藏但保留在 DOM 里（保留键盘可达性和 `:focus-visible`），不要用 `display: none`。

### 3.7.4 分段控件 / 胶囊 / 标签

| 组件 | 结构 | 用途 |
|---|---|---|
| `.seg` + `.seg-item` | 灰槽（`--surface-muted`）+ 白块选中态 | 二选一（语言、主题） |
| `.pill` | 圆角 999、独立边框、选中填充主色 | 多选一（类型选择，数量不定） |
| `.chip` | 小圆角标签，按 `data-*` 换色 | 只读标识（当前类型） |

分段控件与胶囊的区别：**选项固定 2–4 个用分段控件，5 个以上或会增长用胶囊。**

### 3.7.5 自绘下拉框

原生 `<select>` 的弹出层由操作系统渲染，CSS 无法美化，在深色模式下会白得刺眼。要统一外观就自己画：

```html
<div class="select" data-value="a" tabindex="0" role="combobox"
     aria-expanded="false" aria-haspopup="listbox">
  <span class="select-value">—</span>
  <svg class="select-arrow">…</svg>
  <div class="select-menu" role="listbox"></div>
</div>
```

必须处理：点击外部关闭、`Escape` 关闭、`Enter`/`Space` 开关、`aria-expanded` 同步、箭头 180° 旋转（160ms）、菜单 `top: calc(100% + 6px)` + `max-height: 240px` + 自身滚动。

### 3.7.6 弹窗

```css
.modal {
  position: fixed; inset: 0; z-index: 50;
  display: flex; align-items: center; justify-content: center;
  padding: 24px;
  background: var(--backdrop);
  animation: fade-in 0.16s ease;
}
.modal-card {
  display: flex; flex-direction: column;
  width: min(440px, 100%);      /* 常规内容用 720px */
  max-height: 82vh;             /* 不要用固定高度 */
  background: var(--panel);
  border-radius: var(--radius-lg);
  box-shadow: 0 18px 48px var(--shadow-strong);
  overflow: hidden;             /* 圆角裁切 + 阻止内容溢出 */
  animation: card-in 0.2s var(--ease);
}
```

内部三段式，**中间滚动，头尾固定**：

| 段 | 内边距 | 说明 |
|---|---|---|
| `.modal-head` | `18px 22px 12px` | 标题 + 右上角关闭 |
| `.modal-text` / 滚动区 | `0 22px 18px` | `flex: 1; min-height: 0; overflow-y: auto` |
| `.modal-actions` | `0 22px`，卡片补 `padding-bottom: 18px` | 右对齐，`gap: 8px` |

**按钮上方必须留白**：`.modal-actions` 只写左右内边距时，滚动区最后一行会紧贴按钮。给 `padding-top: 14px`，或在滚动区补 `padding-bottom`。

进出场：

```css
@keyframes card-in { from { opacity: 0; transform: scale(.97) translateY(6px); } }
@keyframes card-out { to { opacity: 0; transform: scale(.98) translateY(5px); } }
```

关闭要**等动画结束再 `hidden`**：

```js
function hideModal(id) {
  const el = $(id);
  el.classList.add('leaving');
  setTimeout(() => {
    el.classList.add('hidden');
    el.classList.remove('leaving');
  }, 170);            // 略大于动画时长，避免闪一下
}
```

打开时要清掉未完成的计时器，否则「快速开关」会让弹窗卡在 `leaving` 状态。

### 3.7.7 Toast

```css
.toast {
  position: fixed; left: 50%; bottom: 28px;
  max-width: 70vw;
  padding: 10px 18px;
  border-radius: 999px;
  background: var(--toast-bg);   /* 深色下用 #33383f，不要用纯黑 */
  color: #fff;
  font-size: 13px;
  box-shadow: 0 10px 30px var(--shadow-strong);
  transform: translateX(-50%);
}
```

- 只用于**操作结果**（已保存 / 保存失败），不用于校验错误——校验错误标在字段上。
- 2400ms 自动消失，出场 200ms。
- 重新触发时要清掉上一个计时器，否则第二次提示会提前消失。

### 3.7.8 滚动条

```css
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb {
  background: var(--scrollbar);
  border: 3px solid transparent;
  background-clip: content-box;
  border-radius: 999px;
}
::-webkit-scrollbar-track { background: transparent; }
```

`border: 3px solid transparent` + `background-clip: content-box` 是让滚动条「看起来细、点起来宽」的标准做法。

## 3.8 动效规范

| 场景 | 时长 | 缓动 |
|---|---|---|
| hover / 颜色变化 | 140ms | `ease` |
| 按下位移 | 80ms | `ease` |
| 开关滑动 | 180ms | `var(--ease)` |
| 弹窗淡入 / 卡片进入 | 160 / 200ms | `ease` / `var(--ease)` |
| 弹窗淡出 | 160ms | `ease forwards` |
| 面板切换（详情区） | 220–240ms | `var(--ease)` |
| Toast 进出 | 200ms | `ease` |

规则：

- **只动 `opacity` 和 `transform`**，不要动 `width`/`height`/`top`（会触发布局重排）。
- 超过 250ms 的动效一律砍短。工具类软件的动效是「确认感」，不是「表演」。
- 面板切换重放动画：先 `style.animation = 'none'`，读一次 `offsetWidth`，再清空——这是强制重排的标准写法。
- 必须给 `prefers-reduced-motion` 兜底：

```css
@media (prefers-reduced-motion: reduce) {
  * { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
```

## 3.9 深色模式

三件事，顺序不能错：

**1. 首帧之前定外观**（`<head>` 内联脚本，不能等 CSS）：

```html
<script>
  (function () {
    var saved = null;
    try { saved = localStorage.getItem('appTheme'); } catch (e) {}
    if (saved !== 'dark' && saved !== 'light') {
      saved = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    document.documentElement.dataset.theme = saved;
  })();
</script>
```

**2. 只用变量覆盖**，不改布局：

```css
[data-theme="dark"] { /* 只写变量 */ }
```

**3. 后端也要知道**：窗口 `background_color` 用对应色，否则首帧闪白；后端状态里带 `theme` 字段，切换后写盘。

细节：

- `color-scheme: light/dark` 要跟着设，否则原生滚动条、输入框自动填充色不跟随。
- 切换只应用一次：`apply()` 里比较 `dataset.theme !== data.theme` 再写，避免用户手动切换后被下一次状态刷新改回去。
- 深色下 `--knob` 用 `#e9edf3` 而不是纯白，`--switch-track` 用 `#3a3f47` 而不是浅灰。
- 深色下阴影要更黑更散：`rgba(0,0,0,.6)` + 48px 模糊。

## 3.10 键盘与可访问性

### 3.10.1 焦点环

```css
.btn:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.group-head:focus-visible, .item:focus-visible { outline-offset: -2px; }
.modal-card:focus { outline: none; }
```

用 `:focus-visible` 而不是 `:focus`：鼠标点击和程序设置的焦点不该留框，键盘导航才需要。

`outline-offset` 的取舍：**溢出容器边缘的元素用负值**（`-2px`），否则焦点环会被 `overflow: hidden` 裁掉或顶出侧栏。

### 3.10.2 列表：roving tabindex

一张列表只留**一个** Tab 停靠点，进入后用方向键移动：

```js
function focusNode(node) {
  listNodes().forEach(n => { n.tabIndex = n === node ? 0 : -1; });
  node.focus();
}
```

两个坑：

1. **隐藏节点必须排除。** 折叠的分组里，操作是 `display: none` 但仍在 DOM 里。如果 `tabIndex=0` 落在隐藏节点上，整张列表就没有可聚焦元素了（表现为「全折叠后 Tab 什么也进不去」）。用 `offsetParent !== null` 过滤。
2. **重建后要恢复焦点。** 每次状态变化都重建 DOM，不恢复的话键盘操作一步就断。重建前存 `data-focus-id`，重建后按 id 找回来。

键盘映射：

| 键 | 行为 |
|---|---|
| ↑ / ↓ | 上/下一项 |
| Home / End | 首项 / 末项 |
| → | 展开；或从子项进到父级 |
| ← | 折叠；或从子项退回父级 |
| Enter / Space | 选中并展开 |
| Tab | 离开列表（不进入列表内部） |
| Esc | 关闭弹窗 / 清空搜索 |
| Ctrl+S | 保存 |
| Ctrl+F | 聚焦搜索框 |

### 3.10.3 弹窗

```js
$('app').inert = true;                    // 背景整体不可交互，Tab 自动进不去
element.querySelector('.modal-card').focus();   // 焦点落在卡片上
```

`inert` 比「给每个背景元素加 tabindex=-1」可靠得多。关闭时记得还原。

Tab 循环（`inert` 已挡住背景，但焦点仍会从最后一个按钮跳到浏览器 UI）：

```js
if (event.key === 'Tab') { trapTab(event); return; }
```

### 3.10.4 ARIA 最小集

| 元素 | 属性 |
|---|---|
| 列表容器 | `role="tree"` + `aria-label` |
| 分组标题 | `role="treeitem"` + `aria-level="1"` + `aria-expanded` + `aria-owns` |
| 列表项 | `role="treeitem"` + `aria-level="2"` + `aria-selected` |
| 下拉框 | `role="combobox"` + `aria-expanded` + `aria-haspopup="listbox"` |
| 分段控件项 | `aria-pressed` |
| 纯图标按钮 | `aria-label` + `title` |
| 弹窗 | `role="dialog"` + `aria-modal="true"` + `aria-labelledby` |

图标一律 `aria-hidden="true"`，语义靠旁边的文字或 `aria-label`。

## 3.11 前端文案

- 静态文案用 `data-i18n*` 标记，启动时统一替换；**HTML 里写默认语言的兜底文字**，脚本挂了也不至于一片空白。
- 动态文案用 `T("key", {name: value})`，占位符替换失败时返回原文，不抛异常。
- 数字与计数类文案必须能处理单复数差异（中文不区分，英文要 `1 item` / `2 items`——需要时用两个键，不要拼字符串）。
- 列举多个项目用后端下发的分隔符，不要在 JS 里写死 `,`。

## 3.12 pywebview 陷阱清单

| 陷阱 | 症状 | 正确做法 |
|---|---|---|
| `closing` 里调 `evaluate_js` | 窗口关不掉，进程卡死 | 起工作线程，`return False` 取消关闭（见 3.3.4） |
| `js_api` 里做长任务 | 界面卡住、连续点击排队 | 只做轻操作，重的丢线程池 |
| `window.pywebview` 未就绪就调用 | `undefined is not an object` | 等 `pywebviewready`，并同时处理「已就绪」的情况 |
| 静态资源缓存 | 改了 CSS 看不到效果 | 开发时强制刷新；发布时给 `<link>` 加版本参数 |
| 文件对话框返回值 | 有时是 `str`，有时是 `list` | 统一 `if isinstance(result, (list, tuple)): result[0]` |
| 首帧闪白 | 深色模式下先白一下 | 窗口 `background_color` + `<head>` 内联脚本 |
| `transparent=True` | Windows 上直接报错 | 不支持，改用不透明背景 |
| 依赖 WebView2 | 干净系统上打不开 | README 里写明需要 WebView2 Runtime，或首次启动检测并提示 |
| 高 DPI | 文字发虚 | 不要用 `transform: scale` 模拟缩放；用系统缩放 |
| `document.title` | 窗口标题不跟随页面 | 标题由 `create_window` 决定，页面里改 `document.title` 无效 |

## 3.13 视觉验收清单

改完界面，逐条过：

- [ ] 1920×1080 与 1280×720 两档都不溢出、不出现横向滚动条
- [ ] 窗口拉到最小尺寸，侧栏与详情区都不挤压变形
- [ ] 列表 50 条以上时，底部按钮仍在原位（滚动区约束正确）
- [ ] 长文本（60 字符以上路径）正确省略号，不撑破容器
- [ ] 浅色/深色各看一遍，无「白底白字」「灰底灰字」
- [ ] 深色模式下没有残留的浅色块（尤其是下拉菜单、滚动条、原生控件）
- [ ] 所有 hover / active / focus / disabled 四态都有可见差异
- [ ] Tab 能走完整个界面，焦点环不被裁切
- [ ] 弹窗打开时 Tab 出不去，Esc 能关
- [ ] 空状态、加载中、错误三种非正常状态都有对应界面
- [ ] 系统字体缩放 125% 下不错位

---

# 附录 A 新建项目清单

按顺序执行，30 分钟能起一个合规的骨架：

1. 建目录，`git init`
2. 写 `.python-version`（`3.11`）、`pyproject.toml`（照 1.3）、`.gitignore`（照 1.6）
3. `uv sync` → `uv add loguru` → `uv add --dev pytest ruff`
4. 建 `app/` 骨架：`paths.py`、`errors.py`、`models.py`、`settings.py`、`i18n.py`、`logging_setup.py`、`core/`、`system/`、`ui/`
5. 建 `tests/conftest.py` + `tests/test_source_hygiene.py`（照 2.2）
6. 写 `setup.bat` / `run.bat`（照 1.7）
7. 写入口薄壳（照 2.4）
8. 写 `locales/zh-CN.json`，先只放一条 `app.title`
9. `uv run pytest` 全绿 → 首次提交
10. 复制本文件为 `reference.md`，在 README 里加一行「本项目遵循 reference.md」

# 附录 B 常见退化模式

这些是实际会发生的，遇到就按右列改：

| 退化 | 表现 | 修法 |
|---|---|---|
| 全局选择器 | 一处样式改动，另一处莫名其妙跟着变 | 选择器收窄到容器（`.search input`） |
| 滚动区没有高度约束 | 列表越长，底部按钮越往下跑 | `minmax(0,1fr)` + `min-height: 0` |
| 弹窗固定高度 | 内容少时大片空白，内容多时溢出 | `max-height: 82vh` + 中间滚动 |
| 状态双写 | 前端存一份、后端存一份，两边不一致 | 只信后端快照，前端只留视图状态 |
| 静默失败 | 点了没反应，日志里也没有 | 每个失败分支都要有 toast 或日志 |
| 文案硬编码 | 切到英文后一半中文一半英文 | `data-i18n*` + `T()` |
| 注释写历史 | 「原来用 A，现在改成 B」 | 只写「为什么是 B」 |
| 依赖只加不减 | `pyproject` 里躺着三个没用到的包 | 每次重构后清一遍 |
| 配置直接覆盖写 | 断电后 JSON 变成空文件 | 临时文件 + `os.replace` |
| 忽略返回值 | `save()` 失败但界面显示「已保存」 | 判断 `ok` 再提示 |
