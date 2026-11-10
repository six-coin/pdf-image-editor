# PDF Image Editor

**PDF 图像编辑器** —— 在 PDF 里切分、移动、替换图片，保留原有文字层。

单机工具，Windows，双击即用，不需要联网。

---

## 它解决什么

扫描件和图文混排的 PDF 里，经常需要把一张大图切开、抠出中间一块、或者盖掉某个
水印。用通用 PDF 编辑器做这些事，要么得把整页栅格化（文字层就没了），要么得在
Illustrator 里折腾。

这个工具把每一页拆成「背景 + 独立的图片对象」：背景保留原文档的文字与矢量内容，
图片对象可以单独拖动、缩放、切分、删除。保存时只把图片换掉，其余内容原样不动。

---

## 安装

需要 Windows 10 1803 以上（或 Windows 11），并且系统里有 **WebView2 Runtime**。
Win11 与绝大多数 Win10 已自带；没有的话从微软官网装一次即可。

```bat
setup.bat
```

它会检查 `uv`，然后建 `.venv` 并装依赖。没装 uv 的话先看 https://docs.astral.sh/uv/ 。

## 运行

```bat
run.bat
```

`run.bat` 用 `pythonw.exe` 启动，不会弹控制台。从任何目录调用都行，工作目录不影响行为。

---

## 开发

```bash
uv sync                      # 装环境
uv run pytest                # 跑测试
uv run ruff check .          # 静态检查
uv run ruff format .         # 格式化
uv run python -m app.ui.web.app   # 临时起界面
```

提交前三项全绿：

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

### 目录

```
app/
├─ paths.py           路径推导（唯一允许拼路径的地方）
├─ errors.py          异常类型
├─ models.py          Rect / ImageObject / PageInfo / DocumentState
├─ settings.py        配置读写（夹取、原子写、损坏报错）
├─ i18n.py            文案查表
├─ logging_setup.py   loguru + excepthook + 致命错误弹窗
├─ locales/           zh-CN.json / en-US.json
├─ core/              纯逻辑，零界面依赖
├─ system/            剪贴板、资源服务、外部打开、预处理
└─ ui/web/            pywebview 窗口 + js_api + 静态页面
```

`core/` 不导入任何界面库，可以被纯 pytest 覆盖；这条由
`tests/test_source_hygiene.py` 用 AST 静态守住。

### 数据流

```
pdf_image_editor.pyw
      │
      ▼
 ui/web/app.py ──► ui/web/api.py ──► core/* ──► models/settings/errors/i18n/paths
      │                  │
      │                  ▼
      │            system/*
      ▼
 static/*（HTML/CSS/JS，只经 api.py 通信）
```

### 两条不能破的约定

1. **坐标一律是 PDF 点（pt）**，原点在页面左上角，y 向下。只有前端渲染时才乘缩放系数。
2. **图片按内容寻址存在 `ImageStore` 里**（sha1 → bytes）。撤销只改 `image_id`，不复制像素。

---

## 保存是怎么做的

| 模式 | 做什么 | 什么时候用 |
|---|---|---|
| `preserve`（默认） | 用 `apply_redactions` 把原图摘掉，再把画布上的图插回去。文字、矢量、注释、书签全部保留 | 所有情况 |
| `raster` | 整页重新成像，只留图片 | 纯扫描件，且明确接受丢失文字层 |

落盘先写临时文件再 `os.replace`；就地保存时第一次会留一份 `<文件名>.bak.pdf`。

---

## 日志

每次启动在 `logs/` 下新建一个 `pdf_image_editor_<时间戳>.log`。出问题先看这里，
启动期的致命错误会弹窗并给出日志路径。

`config/` 与 `logs/` 不进版本库，删掉会自动重建。
