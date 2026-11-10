# PDF Image Editor 重构计划：PySide6 → pywebview

> 状态：已完成。阶段 0–8 全部实施完毕，验收结果见 §17。
> 依据：根目录 `reference.md`（环境与结构参考）、`styles.css`（设计令牌与组件来源）、2026-11-10 的代码审计。
> 本文不含可运行代码。实施时按 §3 建目录、按 §6–§12 定接口，命名可改，结构不改。

---

## 0. 怎么用这份文档

- §1 划定范围，§2 是命名约定（改代码前先读这一节）。
- §3–§12 是目标结构与接口。
- §13 是 28 个已知缺陷的对照表：**旧问题 → 新落点 → 回归测试**。任何一条没落地，不算完成。
- §14–§15 是测试与阶段，每阶段有可验收的出口。
- §16 列风险，§17 是验收清单。

一句话概括：**把文档模型从 Qt 的图元树里拆出来变成纯数据，界面只做渲染和手势，保存不再靠"重新拼一份 PDF"。**

---

## 1. 结论与范围

### 1.1 保留 / 重写 / 丢弃

| 旧模块 | 行数 | 处置 | 说明 |
|---|---|---|---|
| `app/pdf_model.py` | 160 | **重写** | 拆成 `core/document.py` + `core/render.py` + `core/save.py`。"保存时重建整个 PDF"是 P0 缺陷，不复用 |
| `app/utils.py` | 57 | **部分保留** | `mm_to_pt` / `parse_page_range` 进 `core/units.py`；`snap_value`、`pt_to_px`、`px_to_pt` 是死代码，删 |
| `app/guide_config.py` | 34 | **重写** | 进 `app/settings.py`，补校验、夹取、原子写、`ConfigError` |
| `app/guide_overlay.py` | 83 | **改前端** | 参考线是纯视图元素，进 `js/guides.js` |
| `app/page_item.py` | 54 | **删除** | 页面 = 一个 `<section>` + 一张背景图 |
| `app/image_item.py` | 281 | **改前端** | 缩放/命中/手柄进 `js/interact.js`，几何计算进 `core/geometry.py` |
| `app/pdf_scene.py` | 190 | **删除** | 场景图被 DOM 取代 |
| `app/pdf_canvas.py` | 166 | **删除** | 视口被滚动容器 + `IntersectionObserver` 取代 |
| `app/split_tool.py` | 419 | **重写为纯函数** | 切分矩阵进 `core/split.py`（约 140 行，无状态）；交互进 `js/split.js` |
| `app/undo_commands.py` | 91 | **重写** | 进 `core/undo.py`；命令只存几何与图片 id，不存像素 |
| `app/main_window.py` | 717 | **重写** | 拆成 `ui/web/api.py` + 前端 JS |
| `app/dialogs/*` | 103 | **改前端** | 弹窗复用 `styles.css` 的 `.modal` 体系 |

旧代码 2355 行里约 2100 行消失。目标规模约 4900 行（Python 1900 / JS 1400 / CSS 900 / HTML 250 / 其余 450）。

### 1.2 明确不做

| 不做 | 理由 | 替代 |
|---|---|---|
| 任意角度旋转 | `Page.insert_image(rotate=)` 只接受 90 的倍数 | 只支持 0/90/180/270 |
| 页面增删与重排 | 会牵动 `src_rect` 的 redaction 映射，风险高收益低 | 「导出选中页」已覆盖拆分需求 |
| 拖放文件打开 | WebView2 下 HTML5 `drop` 拿不到真实路径，要绕 `CoreWebView2` 事件，未验证 | v1 不提供，也不留假开关 |
| 多文档标签 | 单文档工具 | 一个窗口一份文档 |
| 富文本 / 矢量编辑 | 本工具只动图片 | — |
| 150 页以上对象虚拟化 | 典型场景 10–30 页 | §8.5 留扩展点，超限降 DPI 并提示 |
| 应用图标 / 图标库 | 本软件没有图标 | 按钮一律文字标签，见 §2.3 |

---

## 2. 命名与标识

### 2.1 正式名称

| 场景 | 值 |
|---|---|
| 英文名 | `PDF Image Editor` |
| 中文名 | `PDF 图像编辑器` |
| 曾用名 | `Simple PDF Editor` —— **全部改掉，不得残留** |

`Simple PDF Editor` 目前出现在 `old/main.py:8`（`setApplicationName`）和 `old/app/main_window.py:27, 281, 302`（窗口标题）。新代码里一个都不留。

### 2.2 具体落点

| 位置 | 写法 |
|---|---|
| 窗口标题 | 跟随界面语言：中文 `PDF 图像编辑器`，英文 `PDF Image Editor`；有文件时追加 ` — <文件名>` |
| `pyproject.toml` 的 `name` | `pdf-image-editor` |
| 入口文件 | `pdf_image_editor.pyw` |
| 日志文件名前缀 | `pdf_image_editor_YYYY-MM-DD_HH-MM-SS.log` |
| `locales` 的 `app.title` | zh-CN: `PDF 图像编辑器`；en-US: `PDF Image Editor` |
| 致命错误弹窗标题 | `app.title` 的值 |
| README 首行 | `# PDF Image Editor` / 中文名紧随 |
| 卸载/关于信息 | 无（不做关于框） |

`run.bat` / `setup.bat` 的提示前缀用 `[PDF Image Editor]`。

### 2.3 没有图标

这条影响三处，实施时不要顺手加回来：

1. **不做应用图标**：没有 `.ico`，不设窗口图标，`create_window` 不传 `icon`。
2. **不引图标库**，也不用内联 SVG 图标代替文字按钮。工具栏、属性面板、弹窗按钮一律**文字标签**。
   - 主题切换用 `.seg` 分段控件（`浅色` / `深色`），不用月亮/太阳图标。
   - 撤销/重做用文字「撤销」「重做」，配 `kbd` 提示快捷键。
3. **空状态不放插图**：只有标题 + 一句说明 + 一个主按钮。`styles.css` 里的 `.placeholder-art`（96×96 线性图）不迁移。

唯一的例外是画布上的**几何标记**——缩放手柄、参考线、分割线、选框。它们不是图标，是画布内容的一部分，由 canvas 绘制。

---

## 3. 目录骨架

```
PDF Image Editor/
├─ pyproject.toml
├─ uv.lock
├─ uv.toml
├─ .python-version                3.11
├─ .gitignore
├─ README.md
├─ reference.md                   环境与结构参考
├─ refactor_plan.md               本文
├─ styles.css                     ★ 参考素材，阶段 2 提取后移入 docs/ 或删除
├─ setup.bat / run.bat
├─ pdf_image_editor.pyw           入口薄壳，< 30 行
├─ app/
│  ├─ __init__.py
│  ├─ paths.py                    唯一的路径推导处
│  ├─ errors.py                   AppError / ConfigError / PdfError / SaveError / ActionError
│  ├─ models.py                   Rect / ImageObject / PageInfo / DocumentState
│  ├─ settings.py                 app.json + reference.json 的读写、校验、夹取、原子写
│  ├─ i18n.py                     扫描 locales、查表、占位符
│  ├─ logging_setup.py            loguru + excepthook + fatal()
│  ├─ locales/
│  │  ├─ zh-CN.json
│  │  └─ en-US.json
│  ├─ core/
│  │  ├─ __init__.py
│  │  ├─ units.py                 pt/mm 换算、页码范围解析
│  │  ├─ geometry.py              矩形、夹取、等比缩放、命中、切分矩阵
│  │  ├─ imagestore.py            内容寻址的图片仓库
│  │  ├─ document.py              打开/关闭 PDF、页信息、对象集合
│  │  ├─ render.py                页面光栅化 + 预览 + LRU
│  │  ├─ split.py                 切分纯函数
│  │  ├─ undo.py                  命令栈
│  │  └─ save.py                  双模式保存 + 保存报告
│  ├─ system/
│  │  ├─ __init__.py
│  │  ├─ clipboard.py             ctypes + CF_DIB/PNG → PNG bytes
│  │  ├─ asset_server.py          127.0.0.1 资源服务
│  │  ├─ opener.py                os.startfile + cwd
│  │  └─ preprocess.py            灰度阈值化（无 numpy/Pillow）
│  └─ ui/
│     └─ web/
│        ├─ __init__.py
│        ├─ app.py                main()：装配窗口（约 80 行）
│        ├─ api.py                js_api 对象（约 420 行）
│        └─ static/
│           ├─ index.html
│           ├─ css/
│           │  ├─ tokens.css      ★ 逐字取自 styles.css 的 :root / [data-theme="dark"]
│           │  ├─ base.css        reset + 通用组件（.btn/.modal/.toast/.select/…）
│           │  └─ app.css         应用壳 + 画布 + 对象 + 手柄 + 分割层
│           └─ js/
│              ├─ main.js         初始化、装配
│              ├─ bridge.js       call() / T() / toast
│              ├─ state.js        快照缓存 + 视图状态
│              ├─ render.js       按快照重建 DOM
│              ├─ canvas.js       背景位图、DPI、可见性、缩放
│              ├─ interact.js     指针手势
│              ├─ split.js        分割模式
│              ├─ guides.js       参考线
│              ├─ modal.js        弹窗与关闭握手
│              └─ shortcuts.js    键位表
├─ config/                        不进版本库
├─ logs/                          不进版本库
├─ tests/
│  ├─ conftest.py
│  ├─ test_paths.py
│  ├─ test_settings.py
│  ├─ test_units.py
│  ├─ test_geometry.py
│  ├─ test_split.py
│  ├─ test_undo.py
│  ├─ test_save.py                ★ 文字保全的回归测试
│  ├─ test_document.py
│  ├─ test_api.py
│  ├─ test_i18n.py
│  └─ test_source_hygiene.py
└─ old/                           阶段 8 验收通过后整体删除（单独提交）
```

`pyproject.toml` 的 `dependencies` 只三项：

```toml
[project]
name = "pdf-image-editor"
version = "1.0.0"
description = "在 PDF 里切分、移动、替换图片，保留原有文字层。"
requires-python = ">=3.11"
dependencies = [
    "pywebview>=5.0",
    "pymupdf>=1.24",
    "loguru>=0.7",
]
```

不引入 numpy / Pillow / PySide6。前两个的功能用 `fitz.Pixmap` 和 `bytes.translate` 就能做掉（§7.4），少两个依赖。

> Windows 上 `pywebview` 会连带装上 `pythonnet`（调 WebView2 用），这是它的实现细节，不必单独列。

---

## 4. 分层与依赖方向

```
pdf_image_editor.pyw
      │
      ▼
 ui/web/app.py ──► ui/web/api.py ──► core/* ──► models/settings/errors/i18n/paths
      │                  │
      │                  ▼
      │            system/*（clipboard / asset_server / opener / preprocess）
      ▼
 static/*（HTML/CSS/JS，只经 api.py 通信）
```

硬约束（由 `tests/test_source_hygiene.py` 的 AST 扫描强制）：

| 约束 | 检查 |
|---|---|
| `core/` 不导入 `webview`、`PySide6` | AST 扫 import |
| `core/` 不导入 `app.ui.*`、`app.system.*` | AST 扫 import |
| `system/` 不导入 `webview`、`app.ui.*` | AST 扫 import |
| 全项目无 `os.chdir` | AST 扫 `Call` 节点 |
| 无 `print(` | AST 扫（`.pyw` 下 `print` 直接抛异常，见 B07） |
| 入口 < 30 行 | 行数断言 |
| 每个 `.py` 顶部有 docstring | AST 扫 |

`core/` 可以导入 `pymupdf`——它不是界面库，`document` / `render` / `save` 离开它无从实现。

---

## 5. 数据模型

坐标统一为 **PDF 点（pt）**，原点在页面左上角，y 向下。所有几何在 `core` 里都是 pt；只有前端渲染时才乘缩放系数。这条规则是修掉 B06、B16、B17 的前提。

```python
@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float
    # right / bottom 用属性算，不存冗余字段


@dataclass
class ImageObject:
    id: str  # 稳定 id，前端 DOM 的 data-id
    page: int
    rect: Rect  # 当前显示位置（pt，页内坐标）
    image_id: str  # imagestore 的 sha1
    src_xref: int | None  # 原文档里的 xref；None = 用户新增
    src_rect: Rect | None  # ★ 原文档里的放置位置，redaction 用它，不是 rect
    z: int
    rotation: int = 0  # 0 / 90 / 180 / 270
    opacity: float = 1.0


@dataclass(frozen=True)
class PageInfo:
    index: int
    width: float  # pt
    height: float
    has_text: bool  # page.get_text().strip() != ""
    locked_images: int  # 旋转/非轴对齐、不参与编辑的图片数


@dataclass
class DocumentState:
    path: Path | None
    pages: list[PageInfo]
    objects: list[ImageObject]  # 按 z 排序
    selection: list[str]
```

两个关键设计：

**`src_rect` 与 `rect` 分离。** 用户把一张图从 (100,200) 挪到 (300,400)，保存时必须在 **(100,200) 处 redaction 掉原图**、在 (300,400) 处插入新图。旧代码只有一个 `pos`，保存时按当前位置重建，所以"移动"永远无法表达为"移动"，只能整页重来。这是 B01 的根因之一。

**页面不维护图片列表。** 旧 `PageItem._images` 与 `scene.childItems()` 是两份真相，撤销命令一 `push` 就立刻 `redo()`，`add_image` 被调用两次，列表永久漂移（B13）。新模型里"某页有哪些图"= `[o for o in objects if o.page == i]`。

---

## 6. core 模块

### 6.1 `units.py`
`MM_TO_PT = 72 / 25.4`、`mm_to_pt`、`pt_to_mm`、`parse_page_range`（修好 `"3-1"` / `"-5"` 静默返回空的问题，改为返回 `(pages, errors)`）。

### 6.2 `geometry.py`

```python
def clamp_rect_to_page(rect: Rect, page_w: float, page_h: float) -> Rect
def fit_rect_into(rect: Rect, page_w: float, page_h: float) -> Rect
def scale_from_corner(rect: Rect, corner: str, dx: float, dy: float,
                      keep_ratio: bool) -> Rect
def hit_test(rects: list[Rect], x: float, y: float) -> str | None
def cell_matrix(cuts_x: list[float], cuts_y: list[float],
                w: float, h: float) -> list[tuple[int, int, Rect]]
```

`cell_matrix` 是 `core/split.py` 的地基：给定去重排序后的切分线与图片尺寸，返回 `(row, col, rect)` 完整矩阵。**行数列数由矩阵长度决定，调用方永远用 `(row, col)` 取格**——B11 的修法。

### 6.3 `imagestore.py`

```python
class ImageStore:
    def put(self, data: bytes) -> str                        # 返回 sha1
    def get(self, image_id: str) -> bytes
    def preview(self, image_id: str, max_px: int) -> bytes   # WebP/PNG 预览
    def gc(self, alive: set[str]) -> None
```

内容寻址带来三个好处：
1. 撤销不复制像素——分割出的 9 块、撤销前的原图，只是不同 sha1；
2. 同一张图放到多处不重复占内存；
3. 保存时按 sha1 判断用原始 JPEG 字节还是重新编码。

`preview()` 输出 WebP（无 alpha，质量 0.82）或 PNG（有 alpha），只用于显示，不参与保存。

### 6.4 `document.py`

```python
class PdfDocument:
    @classmethod
    def open(cls, path: Path) -> PdfDocument
    def close(self) -> None                                   # 幂等
    @property
    def page_count(self) -> int
    def page_info(self, index: int) -> PageInfo
    def editable_images(self, index: int) -> list[ImageObject]
    def page_pt_size(self, index: int) -> tuple[float, float]
```

**打开前必须 `close()` 上一个文档**（B10）。异常路径也关。

**旋转/非轴对齐图片判定**：`page.get_image_info(xrefs=True)` 返回的 `transform` 若 `abs(b) > 1e-6 or abs(c) > 1e-6`，或该页 `/Rotate != 0`，记为 locked——不提取为可编辑对象、不在背景上涂白、保存时原样保留。**不假装能编辑自己表示不了的东西**（B16、B17）。

### 6.5 `render.py`

```python
class RenderCache:
    def page_png(self, index: int, dpi: int) -> bytes
    def prefetch(self, indices: list[int], dpi: int) -> None
    def invalidate(self, index: int | None = None) -> None
```

- 背景 = `page.get_pixmap(matrix=Matrix(s, s), alpha=False)` → 对每个**可编辑**图片的 quad 涂白 → PNG。
- 涂白用多边形而非矩形（B17）。虽然 locked 图不涂白，但轴对齐图在极端缩放下仍可能带 1px 边缘。
- 缓存键 `(page_index, dpi)`，LRU 按**字节数**上限（默认 256MB），不按条数。
- DPI：`min(300, max(96, round(72 * css_px_per_pt * devicePixelRatio)))`，前端算好传进来。

### 6.6 `split.py`

```python
def split_matrix(w, h, cuts_x, cuts_y) -> list[tuple[int, int, Rect]]
def build_split(objects, obj_id, matrix) -> list[ImageObject]          # 全部保留
def keep_cell(objects, obj_id, matrix, row, col) -> list[ImageObject]  # 只留一格
def punch_cell(objects, obj_id, matrix, row, col) -> list[ImageObject] # 挖掉一格
```

四个纯函数：输入对象列表，输出新对象列表，不碰场景、不碰撤销栈。`(row, col)` 由前端显式传入，**硬编码索引彻底消失**（B11）。

### 6.7 `undo.py`
见 §10。

### 6.8 `save.py`
见 §11。

---

## 7. system 模块

### 7.1 `clipboard.py`
`ctypes` 调 Win32，按 `CF_DIBV5` → `CF_DIB` → `"PNG"` → `"JFIF"` 顺序取，转 PNG bytes。
- `CF_DIB` 手工解析 `BITMAPINFOHEADER`（24/32bpp、行 4 字节对齐、自下而上），拼 samples 后交给 `fitz.Pixmap(fitz.csRGB, w, h, samples)` 再 `tobytes("png")`。
- `"PNG"` / `"JFIF"` 直接是文件字节，透传。
- 返回 `bytes | None`。不引入 Pillow。约 120 行，用假剪贴板注入测试。

### 7.2 `asset_server.py`
`ThreadingHTTPServer`，绑 `127.0.0.1:0`，启动时生成 16 字节随机 token 作路径前缀。

| 路由 | 返回 |
|---|---|
| `/a/<token>/page/<n>.png?dpi=150&v=7` | `render.page_png(n, dpi)`，带 `ETag` + `Cache-Control: private, max-age=31536000, immutable` |
| `/a/<token>/img/<sha1>?w=320` | `store.preview(sha1, w)` |
| `/a/<token>/static/*` | `ui/web/static/` 下的文件，`no-store`（改 CSS 刷新即见） |

只绑 loopback；token 不符返回 404。`v` 是文档代次号，换文档后 URL 变化，浏览器缓存自然失效。`page_png` 内部有锁。

### 7.3 `opener.py`
`os.startfile(path, cwd=str(path.parent))`。工作目录必须作为参数传，不能依赖进程 cwd。

### 7.4 `preprocess.py`
不用 numpy / Pillow：

```python
table = bytes(255 if i >= threshold else i for i in range(256))
samples = bytearray(pix.samples).translate(table)
new_pix = fitz.Pixmap(
    pix.colorspace or fitz.csGRAY, pix.width, pix.height, bytes(samples), pix.alpha
)
page.replace_image(xref, pixmap=new_pix)
```

`bytes.translate` 是 C 实现，比逐像素快两个数量级。灰度化用 `fitz.Pixmap(fitz.csGRAY, pix)`。
逐页产出进度 `(done, total)`，由线程池驱动，不阻塞界面（B09）。`fitz.open` 用 `try/finally`。

---

## 8. 前端结构

### 8.1 文件划分与加载方式

`index.html` 通过 `http://127.0.0.1:<port>/a/<token>/static/index.html` 加载，`<script type="module" src="./js/main.js">`。

必须走 HTTP：ES module 在 `file://` 下被 CORS 拦死。既然为了资源服务已经起了 loopback server（§7.2），顺带解决。

**CSP 注意**：pywebview 会向页面注入内联桥接脚本，`script-src` 不能只写 `'self'`，否则桥接被拦、`window.pywebview` 永远不出现。

```html
<meta http-equiv="Content-Security-Policy"
      content="default-src 'self' http://127.0.0.1:*; img-src 'self' http://127.0.0.1:* data:;
               style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' 'unsafe-eval'">
```

### 8.2 样式体系（来自 `styles.css`）

根目录的 `styles.css` 拆成三层，**令牌块逐字照搬，不改值**：

**`css/tokens.css`** —— `:root` 与 `[data-theme="dark"]` 两个块，原样迁移。已有的令牌一个不删，因为画布要用到 `--surface-*` 的全套灰阶。在此之上补一组画布专用令牌（原文件没有，两边都要给值）：

```css
:root {
  /* 画布 */
  --canvas-bg: #e4e7ec;
  --canvas-gap: 24px;
  --page-shadow: 0 1px 2px rgba(15, 23, 42, .06), 0 6px 18px rgba(15, 23, 42, .10);
  --page-edge: #dfe3e9;

  /* 对象 */
  --obj-outline: var(--blue);
  --obj-outline-soft: rgba(59, 130, 246, .55);
  --handle-fill: #ffffff;
  --handle-stroke: var(--blue);
  --handle-size: 9px;

  /* 参考线 */
  --guide: rgba(59, 130, 246, .45);
  --guide-active: var(--blue);

  /* 分割 */
  --split-line: var(--green);
  --split-fill: rgba(16, 185, 129, .14);
  --split-cell-hover: rgba(16, 185, 129, .22);

  /* 选框 */
  --marquee-fill: rgba(59, 130, 246, .10);
  --marquee-stroke: var(--blue);
}

[data-theme="dark"] {
  --canvas-bg: #0f1115;
  --page-shadow: 0 1px 2px rgba(0, 0, 0, .5), 0 8px 24px rgba(0, 0, 0, .55);
  --page-edge: #262a31;

  --obj-outline-soft: rgba(76, 141, 246, .6);
  --handle-fill: #1c1f24;
  --handle-stroke: var(--blue);

  --guide: rgba(76, 141, 246, .5);

  --split-fill: rgba(47, 191, 143, .16);
  --split-cell-hover: rgba(47, 191, 143, .26);

  --marquee-fill: rgba(76, 141, 246, .12);
}
```

**`css/base.css`** —— reset、字体、滚动条、`.hidden`、`prefers-reduced-motion`，加上这些组件类，基本照搬：

| 类 | 用途 | 迁移 |
|---|---|---|
| `.btn` + `.primary/.ghost/.soft/.danger/.danger-ghost/.block` | 全部按钮 | 原样 |
| `.icon-btn` | 图标按钮 | **保留但不用**（无图标），留着给将来 |
| `.seg` / `.seg-item` | 主题切换、保存模式 | 原样 |
| `.pill` | 页码范围快捷选项 | 原样 |
| `.switch` / `.switch-track` | 设置里的开关 | 原样 |
| `.modal` / `.modal-card` / `.modal-head` / `.modal-text` / `.modal-actions` | 全部弹窗 | 原样 |
| `.toast` / `.toast.error` | 操作结果提示 | 原样 |
| `.select` 全套 | 保存模式、语言选择 | 原样 |
| `.field` / `.hint` / `.chip` / `.card` / `.divider` / `kbd` | 属性面板与设置 | 原样 |

**不迁移**：`.app` 的 360px 双栏壳、`.sidebar` / `.group` / `.group-head` / `.group-ops` / `.item` / `.dot` / `.item-body` / `.item-title` / `.item-sub` / `.list` / `.list-empty` / `.search` / `.picker` / `.secret` / `.tabs` / `.detail` / `.editor` / `.placeholder-art`。这些是"列表 + 详情"型应用的骨架，与画布无关。

**`css/app.css`** —— 新写：应用壳、画布、页面、对象、手柄、参考线、分割覆盖层、空状态、加载骨架。

### 8.3 DOM 结构

```html
<div id="app" class="app">
  <header class="topbar">
    <button class="btn" data-i18n="toolbar.open">打开</button>
    <button class="btn" data-i18n="toolbar.save">保存</button>
    <span class="topbar-sep"></span>
    <button class="btn ghost" data-i18n="toolbar.undo">撤销</button>
    <button class="btn ghost" data-i18n="toolbar.redo">重做</button>
    <span class="topbar-sep"></span>
    <div class="zoom-box">
      <button class="btn ghost" data-act="zoom-out">−</button>
      <button class="zoom-value" id="zoomValue">100%</button>
      <button class="btn ghost" data-act="zoom-in">+</button>
      <button class="btn ghost" data-i18n="toolbar.fit_width">适合宽度</button>
    </div>
    <span class="spacer"></span>
    <button class="btn primary" data-i18n="toolbar.save" hidden>保存</button>
    <div class="seg" id="themeSeg">
      <button class="seg-item" data-theme-value="light" data-i18n="theme.light">浅色</button>
      <button class="seg-item" data-theme-value="dark" data-i18n="theme.dark">深色</button>
    </div>
  </header>

  <main class="viewport" id="viewport">
    <div class="pages" id="pages">
      <section class="page" data-page="0" style="width:…px;height:…px">
        <img class="page-bg" alt="">
        <div class="objects">
          <div class="obj" data-id="o1" style="transform:translate(…px,…px) scale(…,…)">
            <img src="…" draggable="false" alt="">
            <div class="handles"><i data-corner="tl"></i><i data-corner="tr"></i>
                                 <i data-corner="bl"></i><i data-corner="br"></i></div>
          </div>
        </div>
        <canvas class="overlay"></canvas>
        <span class="page-no">1</span>
      </section>
    </div>
  </main>

  <aside class="inspector" id="inspector">…</aside>
  <div class="modal-root" id="modalRoot"></div>
  <div class="toast-root" id="toastRoot"></div>
</div>
```

三层分离：

| 层 | 技术 | 为什么 |
|---|---|---|
| 页面背景 | `<canvas>`，尺寸 = `pt × k × dpr` | 位图必须按目标 DPI 重渲染；CSS `transform: scale` 会发虚 |
| 图片对象 | `<div>` + CSS `transform` | 拖动只改 transform，走合成器，不触发布局与重绘 |
| 参考线/选框/分割线 | `<canvas>`，2D，按 `dpr` 缩放 | 1px 线在 DOM 里会 subpixel 抖动，canvas 可控 |

**这就是"为什么这次不卡"的答案**：旧实现在 `QGraphicsView` 里，任何一次鼠标移动都触发视口内 `paint()`，每张 150 DPI 位图被重新采样一遍。新实现里拖动一张图 = 改一个元素的 `transform`，合成器直接把已有纹理挪位置，一个像素都不重绘。

### 8.4 坐标系与缩放

- 单一真值：pt。`k = css_px_per_pt`（100% 时 1pt 显示为 96/72 css px）。
- 对象定位：静止时用 `left / top / width / height`（CSS 像素，直接等于 `pt × k`），图片 `width: 100%`。**拖拽期间**改用 `transform: translate(dx, dy)`，只走合成器；`pointerup` 时把结果写回 `left / top` 再提交。这样静止时不必知道图片的原始像素尺寸，拖拽时仍然零重绘。
- 缩放锚点：`Ctrl + 滚轮` 以指针为锚，**乘法步长**（×1.1 / ÷1.1），范围 10%–800%。锚点换算 `scrollLeft += (px - vpRect.left) * (k2/k1 - 1)`。修 B18。
- 滚轮处理 `deltaMode` 三态（0=像素、1=行、2=页），修 B25。
- `devicePixelRatio` 变化（拖到另一块屏）用 `matchMedia('(resolution: …dppx)')` 监听 → 重算 DPI → 重渲染可见页。

### 8.5 渲染与懒加载

- 所有 `<section class="page">` 一开始就建好（只有宽高，无内容），100 页也就 100 个空 div。
- `IntersectionObserver`（`rootMargin: '150% 0px'`）决定哪些页需要背景位图。进入范围 → `canvas.js` 设 `src`，浏览器自己去 `asset_server` 拉；离开范围 → 释放。
- 对象 DOM 全部常驻（30 页 × 5 图 = 150 节点，可忽略）。超过 150 页启用对象虚拟化——留扩展点，本次不做。
- 渲染期间显示骨架（`.page.loading` 用 `--surface-muted` 打底 + 一个 1.2s 的 `pulse`），保证"加载中"状态有界面。

### 8.6 指针手势

统一 Pointer Events，`setPointerCapture` 保证拖出窗口也能收到 `pointerup`。

| 手势 | 行为 |
|---|---|
| 左键点对象 | 选中；`Shift` 加选 |
| 左键拖对象 | 移动；实时 `clamp_rect_to_page`；跨页按**中心点所在页**迁移，落点为空隙则回弹最近页 |
| 四角手柄 | 等比缩放；`Alt` 自由缩放 |
| 左键拖空白 | 框选 |
| 中键拖 / `Space`+左键 | 平移画布 |
| `Ctrl`+滚轮 | 以指针为锚缩放 |

拖拽全程只改 DOM 的 `transform`，`pointerup` 时把 `{id, before:{x,y,w,h}, after:{x,y,w,h}}` 一次性提交。**服务端仍然夹取一次**（前端算错了不至于把图存到页外）。

手柄样式：`--handle-size: 9px` 的方块，白底蓝边，位于四角外侧偏移 4px；`cursor` 用 `nwse-resize` / `nesw-resize`。因为手柄在 DOM 里，位置由 CSS 算，不再需要旧代码那套 `lod = zoom * sceneTransform` 的换算（旧实现的手柄错位就是这么来的）。

### 8.7 分割交互

旧版：`E`/`R` 进入、点击放线、`T` 完成、`Q`/`I` 取中间——五个键、三种模式、靠"第 4 格"猜意图。重做：

1. 选中一张图 → 工具栏「分割」或按 `S`，进入分割模式（覆盖层出现，四周半透明遮罩）。
2. 鼠标在图上移动显示一条跟随的切线；点击放置。水平/竖直由 `Shift` 切换（默认跟随移动方向）。
3. 放够线后每格 hover 高亮，格子上浮出三个文字按钮：**仅保留此格** / **提取此格** / **按格切分**。
4. `Enter` 对当前高亮格执行「按格切分」；`Esc` 退出；`Ctrl+Z` 撤销上一根线。

后端只需三个方法，参数带 `row`/`col`（§6.6）。前端自己维护"切了哪几刀"这个纯视图状态。

---

## 9. 前后端契约

### 9.1 方法表

| 类别 | 方法 | 参数 | 返回 |
|---|---|---|---|
| 读取 | `get_state` | — | 快照 |
| 读取 | `get_strings` | — | `{key: text}` |
| 文档 | `browse_pdf` | — | `str \| None` |
| 文档 | `open_path` | `path, force=False` | `{ok, task} \| {ok:false, reason:"dirty"}` |
| 文档 | `close_document` | — | 快照 |
| 渲染 | `load_page` | `index, dpi` | `{ok, url, w, h, objects}` |
| 编辑 | `add_white_rect` | `page, rect` | 快照 |
| 编辑 | `paste_image` | `page, rect` | 快照 |
| 编辑 | `delete_objects` | `ids` | 快照 |
| 编辑 | `commit_transform` | `items[{id,x,y,w,h}]` | 快照 |
| 编辑 | `reorder_objects` | `ids, mode:"front"\|"back"` | 快照 |
| 编辑 | `split_object` | `id, cuts_x, cuts_y` | 快照 |
| 编辑 | `keep_cell` | `id, cuts_x, cuts_y, row, col` | 快照 |
| 编辑 | `punch_cell` | `id, cuts_x, cuts_y, row, col` | 快照 |
| 编辑 | `replace_image` | `id` | `{ok, task}` |
| 历史 | `undo` / `redo` | — | 快照 |
| 选择 | `select` | `ids` | 快照 |
| 设置 | `update_settings` | `patch` | 快照 |
| 设置 | `set_language` | `code` | 快照 |
| 系统 | `browse_save` | `suggested` | `str \| None` |
| 系统 | `save_document` | `mode, path` | `{ok, report}` |
| 系统 | `export_pages` | `text, path` | `{ok, path, pages, errors}` |
| 系统 | `paste_image` | `page` | 快照 |
| 系统 | `edit_external` | `object_id` | `{ok, path}` |
| 系统 | `replace_image` | `object_id, path` | 快照 |
| 系统 | `preprocess_pdf` | — | `{ok, task}` |
| 设置 | `update_reference` | `values` | 快照 |
| 任务 | `poll_task` | `task_id` | `{state, progress, result}` |
| 关闭 | `ask_close` | — | — |
| 关闭 | `answer_close` | `action` | — |

**铁律：越界或非法参数不抛异常，原样返回当前快照。** 网页拿到 Python traceback 是最难排查的一类问题。每个方法统一用装饰器兜底：

```python
def guarded(fn):
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except AppError as exc:
            logger.warning("{}: {}", fn.__name__, exc)
            return {**self._snapshot(), "ok": False, "message": str(exc)}
        except Exception:
            logger.exception("{} 未捕获", fn.__name__)
            return {**self._snapshot(), "ok": False, "message": i18n.t("error.unexpected")}

    return wrapper
```

`test_api.py` 对每个方法喂一遍非法参数。

### 9.2 快照结构

```json
{
  "ok": true,
  "message": "",
  "doc": {
    "path": "D:/x/a.pdf", "name": "a.pdf", "dirty": false,
    "page_count": 12, "save_mode": "preserve", "generation": 7
  },
  "pages": [{"index": 0, "w": 595.3, "h": 841.9, "has_text": true, "locked": 2}],
  "objects": [{
    "id": "o1", "page": 0, "x": 72.0, "y": 72.0, "w": 200.0, "h": 150.0,
    "z": 10, "rotation": 0, "image": "3f2a…", "thumb": "/a/<t>/img/3f2a…?w=320"
  }],
  "selection": ["o1"],
  "history": {"can_undo": true, "can_redo": false, "label": "edit.split"},
  "busy": {"task": "open-3", "progress": {"done": 4, "total": 12}},
  "language": "zh-CN",
  "theme": "light"
}
```

不含像素、不含缩略图字节（走 URL）。30 页 100 个对象约 40KB JSON，全量重绘完全够用。

### 9.3 线程与任务

- `api.py` 内所有对 `DocumentState` 的读写包在 `threading.RLock` 里。pywebview 给每个 JS 调用起一个线程，不加锁必然出现"拖到一半快照是半截"。
- 长任务（`open_path` / `save_document` / `preprocess_pdf` / `replace_image`）→ `ThreadPoolExecutor(max_workers=2)`，立即返回 `{ok: true, task: "open-3"}`。
- 前端 80ms 轮询 `poll_task`，`state: "ready"` 后调 `get_state`。
- **代次号**：每次 open/close `generation += 1`；worker 回包时若 `generation` 已变，直接丢弃，不写模型、不写缓存。
- 单页渲染不进线程池：命中缓存立即返回；未命中同步渲染（≤400ms），同时触发相邻页预取。

### 9.4 关闭握手

```
用户点 X
  └─ window.events.closing（UI 线程）
       ├─ 不脏 → return True
       └─ 脏 → api.request_close_prompt()（内部起线程）→ return False
                 └─ 工作线程：window.evaluate_js("host.askUnsaved()")
                       └─ 页面弹 .modal（保存 / 另存为 / 不保存 / 取消）
                             └─ answer_close("save"|"discard"|"cancel")
                                   ├─ save   → 保存成功后 force_close()
                                   ├─ discard→ force_close()
                                   └─ cancel → 什么都不做
```

`force_close()` = 置 `close_confirmed = True` 后 `window.destroy()`。

**兜底**：`evaluate_js` 返回假值（渲染进程崩了、脚本报错）时，退回 `ctypes.windll.user32.MessageBoxW` 弹原生三选一，保证窗口永远关得掉。

**桥接全局名**用 `window.host`，不用 `app`——页面里有 `id="app"`，`window.app` 已被那个 div 占用。

---

## 10. 撤销设计

旧实现把像素和场景图都塞进了命令对象：`SplitCommand` 持有 `QPixmap`，`TransformCommand` 持有 `QTransform` + `parentItem()`，`apply_state` 还要处理 `setParentItem` 的副作用。新设计把这两样都拿掉。

### 10.1 三类命令，仅此三类

| 命令 | 存什么 | 大小 |
|---|---|---|
| `ObjectsChanged(before, after)` | 受影响对象的**完整 dataclass 副本**（几何 + image_id + z + page） | 每个对象约 200 字节 |
| `StructureChanged(before, after)` | 整份 `objects` 列表（增删/切分/打孔） | 100 个对象约 20KB |
| `ImageReplaced(id, old_image_id, new_image_id)` | 三个 id | 几十字节 |

**不存像素。** 图片字节在 `ImageStore` 里按 sha1 常驻，撤销只是把 `image_id` 指回去。一次 9 格切分产生 9 个新 sha1，撤销后它们变孤儿，`gc()` 在保存时或栈深超限时清理。

### 10.2 栈行为

- 深度上限 100（可配），超限丢最旧的并 `gc()`。
- `begin_macro(label)` / `end_macro()`：切分+删除、打孔+新增合并成一条，`Ctrl+Z` 一次全退。旧代码这里用 `beginMacro` + 两次 `push`，而 `push` 会立刻 `redo()`，导致 `add_image` 重复调用（B13）——新实现 `push` 只入栈并 `apply()`，`apply` 是**幂等**的（按 id 覆盖，不是 append）。
- 每次 `undo/redo` 后返回快照，前端整体重绘。不做增量同步：全量重绘的代价（40KB JSON + 100 节点）远小于维护增量一致性的成本。
- `label` 存 i18n key（`edit.split`），不存中文。旧代码 `QUndoStack` 里塞硬编码"移动/缩放""添加矩形"，还出现过给粘贴图片挂"添加矩形"命令的错位（B20）。

### 10.3 dirty 判定

`dirty = (undo_stack.depth != saved_depth)`。保存成功时记 `saved_depth`。比 `QUndoStack.isClean()` 明确，也避免"保存失败但栈被 setClean"（B03）。

---

## 11. 保存设计

这是整个重构里**唯一必须做对**的部分。旧实现每次保存都 `fitz.open()` 一个空文档，逐页 `new_page()` 后只插图片——**原文档的文字、矢量、注释、书签、链接全部消失**，没有图片的页面存出来是全白页。`pdfs/20261005-0928.pdf` 的 Producer 是 ReportLab、带 13 处字体对象，按一次 Ctrl+S 就是不可逆的毁文档（B01）。

### 11.1 两种模式

**模式 A：`preserve`（默认）**

```
src = fitz.open(源文件)                    # 每次从磁盘读，不复用内存句柄
for 每页:
    for 每个 src_xref 非空的对象:
        page.add_redact_annot(src_rect)     # 用原位置，不是当前位置
    page.apply_redactions(
        images=PDF_REDACT_IMAGE_REMOVE,
        graphics=PDF_REDACT_LINE_ART_NONE,  # 矢量不动
        text=PDF_REDACT_TEXT_NONE,          # 文字不动
    )
    for 对象（按 z 升序）:
        page.insert_image(rect, stream=..., rotate=rotation, overlay=True)
保存到临时文件 → os.replace
```

- 文字层、矢量图、注释、书签、元数据全部保留。
- `src_rect` 保证"移动"被正确表达为"在原位删除 + 在新位插入"。
- 按 `z` 升序插入，置顶/置底终于生效（B15）。
- 逐页 `try/except`：某页 redaction 失败 → 记入 `report.warnings`，回退为"该页不 redaction、只叠加新图"（原图会残留在下层，但不会丢内容），界面明确提示。**绝不静默 `pass`**（B27）。

**模式 B：`raster`**

每页 = 去掉可编辑图片后的背景 PNG（300 DPI）+ 图片对象。只用于纯扫描件。UI 上写明"会丢失文字层与书签"，且**仅当该页 `has_text == False` 且无注释时才允许勾选**。

### 11.2 落盘安全

| 规则 | 修的是 |
|---|---|
| 先写 `<dst>.tmp-<pid>`，`fitz` 保存成功后再 `os.replace` | 中途失败不留半个文件 |
| 目标 == 源时，先把源复制为 `<name>.bak.pdf`（仅首次） | 误覆盖可回滚 |
| 默认动作「另存为副本」，除非用户显式「保存」 | B02 |
| 保存前检查目标是否可写，只读文件直接给一句人话而不是 WinError 5 | 只读的 PDF 很常见（下载件、共享盘） |
| 保存失败时只把句柄接回来，**不重建状态**——文件没动，编辑必须还在 | 失败后不能把用户的改动洗掉 |
| 保存成功后：关内存文档 → 重开新文件 → 重建对象与 `src_rect` → 清空撤销栈 → `invalidate` 缓存 | B10、B27 |
| `save_document` 返回 `SaveReport`，前端**按 `ok` 提示** | B03 |

### 11.3 `SaveReport`

```json
{
  "ok": true, "path": "D:/x/a.pdf", "mode": "preserve",
  "pages": 12, "replaced": 34,
  "warnings": [
    {"page": 3, "code": "redact_partial", "detail": "该页有 2 张旋转图片，已原样保留"},
    {"page": 7, "code": "image_out_of_page", "detail": "1 张图片被夹取到页内"}
  ]
}
```

`warnings` 非空时前端弹一个可滚动的结果面板，而不是一句 toast——用户需要知道哪一页降级了。

---

## 12. 配置与本地化

### 12.1 配置

两个文件：

| 文件 | 内容 |
|---|---|
| `config/app.json` | `language`、`theme`、`zoom`、`save_mode`、`undo_limit`、`render_dpi_cap`、`preprocess_threshold` |
| `config/reference.json` | `left_mm`、`top_mm`、`right_mm`、`bottom_mm`（由旧 `reference_line.json` 首次启动迁移） |

`settings.py` 必须做到：

- **首次启动生成**可用内容，用户不用手写 JSON。
- **原子写**：`mkstemp` + `os.replace`。
- **读时夹取**：`left_mm` 非数字 → 回退默认；负数 → 夹到 0；超过页宽一半 → 夹到一半。旧代码 `cfg["left_cm"] * 10` 遇到字符串 `"1.0"` 会得到重复字符串，随后 `mm_to_pt` 抛 `TypeError`，崩在主窗口构造期间，连弹框都来不及（B12）。
- **未知键保留**。
- **结构损坏抛 `ConfigError`**，不静默重建。上层捕获 → 记日志 → `MessageBoxW` 告知日志路径 → 退出。

### 12.2 本地化

- `app/locales/zh-CN.json`、`en-US.json`，文件名即语言代码。
- 静态文案用 `data-i18n` / `data-i18n-placeholder` / `data-i18n-title` / `data-i18n-aria`。
- 动态文案 `T("key", {name: value})`，缺键返回键名，不抛异常。
- 键名分域：`app.*` `toolbar.*` `edit.*` `split.*` `save.*` `dialog.*` `error.*` `fatal.*` `theme.*`。
- `test_i18n.py` 两条守卫：键集合完全相等、占位符集合完全相等。

旧代码 60 余处硬编码中文（含 `QMessageBox` 标题、状态栏提示、`print` 输出）全部迁进键表。`app.title` 是 `PDF 图像编辑器` / `PDF Image Editor`。

---

## 13. 缺陷修复对照表

编号沿用审计报告。**每条都必须有对应测试，否则视为未修复。**

### P0 数据丢失

| # | 旧问题 | 新落点 | 修法 | 回归测试 |
|---|---|---|---|---|
| B01 | 保存重建空文档，文字/矢量/注释/书签全丢 | `core/save.py` | 模式 A 用 `apply_redactions` 只摘图片 | `test_save::test_text_survives_roundtrip` |
| B02 | Ctrl+S 原地覆写源文件 | `core/save.py` | 临时文件 + `os.replace` + 首次 `.bak`；默认另存副本 | `test_save::test_source_untouched_on_failure` |
| B03 | 另存失败仍改标题、改 `_current_file` | `api.save_document` | 只有 `report.ok` 才更新 `doc.path` | `test_api::test_save_failure_keeps_path` |
| B04 | 打开新文件不检查未保存 | `api.open_path` | `dirty` 时返回 `{ok:false, reason:"dirty"}` | `test_api::test_open_blocks_when_dirty` |
| B05 | `rmtree(os.getcwd()/temp)`，可能删用户目录 | `paths.TEMP_DIR` + `system/opener.py` | 固定 `PROGRAM_DIR/temp/<session-id>/`，只删本会话目录；`os.startfile(cwd=...)` | `test_paths::test_temp_dir_under_program_dir` |
| B06 | 图片可拖出页面，落点在页间距时归属错乱，输出 PDF 里消失 | `core/geometry.py` + `js/interact.js` | 拖动实时夹取；跨页按中心点判定，落空回弹最近页；保存前再夹一次并写 warning | `test_geometry::test_clamp_*`、`test_save::test_no_out_of_page_images` |

### P1 崩溃 / 结果错误

| # | 旧问题 | 新落点 | 修法 | 回归测试 |
|---|---|---|---|---|
| B07 | `print()` 在 `pythonw` 下抛 `AttributeError`，预处理"成功却报失败" | `logging_setup` | 全项目禁用 `print`，静态测试强制 | `test_source_hygiene::test_no_print` |
| B08 | `numpy`/`PIL` 不在 requirements 里 | `pyproject.toml` + `system/preprocess.py` | 改用 `fitz.Pixmap` + `bytes.translate`，**删掉这两个依赖** | `test_preprocess::test_threshold_*` |
| B09 | 预处理跑在 UI 线程，`fitz.open` 无 `try/finally` | `system/preprocess.py` + 线程池 | 任务化 + 进度轮询 + `try/finally` | `test_api::test_preprocess_returns_task` |
| B10 | `load()` 不关闭上一个文档，句柄泄漏并锁文件 | `core/document.py` | `open()` 前 `close()`；`close()` 幂等；异常路径也关 | `test_document::test_reopen_closes_previous` |
| B11 | `confirm_keep_middle` 硬编码 `middle_idx = 4`，去重或跳格后删错/全删 | `core/split.py` | `keep_cell(id, cuts, row, col)` 显式传格号 | `test_split::test_keep_cell_explicit` |
| B12 | 配置里的字符串数字导致启动崩溃 | `settings.py` | 夹取 + 类型校验 + `ConfigError`；启动期捕获后 `MessageBoxW` | `test_settings::test_clamp_and_type_guard` |
| B13 | `_images` 重复追加（`push` 立刻 `redo()` 再 `add_image`） | `models.py` | 页面不维护图片列表，单一真相 | `test_undo::test_apply_is_idempotent` |
| B14 | 分割后页面残留悬挂引用 | 同上 | 对象只存在于 `DocumentState.objects` | `test_undo::test_no_dangling_after_split` |
| B15 | Z 序在保存时丢失（按 `childItems()` 顺序） | `core/save.py` | 按 `z` 升序 `insert_image` | `test_save::test_z_order_preserved` |
| B16 | 旋转图片/页面错位、放大 | `core/document.py` | `transform` 非轴对齐或页 `/Rotate != 0` → 标记 locked，原样保留 | `test_document::test_locked_images` |
| B17 | 白色遮罩盖住图片旁的文字 | `core/render.py` | 只对可编辑图涂白，用 quad；locked 图不涂 | `test_render::test_whiteout_only_editable` |

### P2 行为与工程债

| # | 旧问题 | 新落点 | 修法 |
|---|---|---|---|
| B18 | Ctrl+滚轮不跟光标，步长加法 | `js/canvas.js` | 乘法步长 + 锚点换算 |
| B19 | `setAcceptDrops` 但没有 `dropEvent` | — | 不做（§1.2），不保留假开关 |
| B20 | 粘贴图片挂"添加矩形"命令 | `core/undo.py` | 命令 `label` 是 i18n key，由命令类型决定 |
| B21 | `show_guides` 死参数 | — | 参考线是纯视图状态 |
| B22 | E/R/T/I 双绑定，T 只有一条路 | `js/shortcuts.js` | 单张键位表，单点分发 |
| B23 | 菜单助记符冲突（预处理 &V vs 视图 &V） | `index.html` | 菜单重排 + DOM 断言测试 |
| B24 | `_flash_timer` 抹掉状态栏提示 | `js/bridge.js` | toast 与状态栏分离 |
| B25 | `wheelEvent` 忽略 `pixelDelta` | `js/canvas.js` | 处理 `deltaMode` 三态 |
| B26 | 打开时全量渲染所有页，界面假死 | `core/render.py` + `IntersectionObserver` | 懒渲染 + LRU + 预取 |
| B27 | 零日志，失败分支静默 | `logging_setup` | loguru + 每处失败都有日志或 toast |
| B28 | 死代码与无用导入 | — | ruff `F401/F841` 覆盖；`itemChange`、`snap_value` 随重写消失 |

另外两处小的：`export_pages` 在文档未打开时返回 `{ok:false, reason:"no_document"}`，不再静默成功；`parse_page_range("3-1")`、`"-5"` 返回明确错误提示而不是空列表。

---

## 14. 测试计划

**`test_save.py`** —— 最重要的一个。夹具用 PyMuPDF 现场生成：

```python
doc.new_page() → page.insert_text((72, 72), "Hello 文字") → page.insert_image(rect, pixmap=…)
```

保存后重新打开，断言：`get_text()` 含"Hello 文字"；图片数量正确；页尺寸不变；z 序正确。**这一条挡住的是整个项目最贵的那个 bug。**

**`test_split.py`** —— 纯函数，最容易覆盖全：
- 0 刀 → 1 格；2+2 刀 → 9 格；
- 两条线重合 → 去重后仍取正确的 `(row, col)`；
- 某格宽 0 → 矩阵里没有它，`keep_cell` 传越界 `(row,col)` 返回原样（不抛）；
- 与旧实现对照：3×3 取中心，新实现 `keep_cell(..., 1, 1)` 与旧 `new_items[4]` 结果一致。

**`test_api.py`** —— 对每个 `js_api` 方法喂非法参数（`None`、负索引、超大 rect、不存在的 id、`ids=[]`），断言返回 `dict` 且 `ok in (True, False)`，**绝不抛**。

**`test_source_hygiene.py`** —— AST 守卫：core 无界面库、无 `chdir`、无 `print`、入口 < 30 行、每模块有 docstring。

其余：`test_geometry`（夹取/等比/命中）、`test_undo`（往返/宏/深度上限）、`test_settings`（夹取/未知键保留/损坏抛错/原子写）、`test_i18n`（键与占位符对齐）、`test_paths`（相对路径以程序目录为基准）、`test_units`（`parse_page_range` 的边界）。

目标：`uv run pytest` 约 90–110 个用例，跑完 < 15 秒（不启动 webview，不渲染真实大 PDF）。

---

## 15. 实施阶段

每阶段结束都能运行、能验收。**不跳阶段合代码。**

### 阶段 0：骨架（约半天） ✅
`pyproject.toml` / `uv.toml` / `.python-version` / `.gitignore` / `setup.bat` / `run.bat` / `pdf_image_editor.pyw` / `app/paths.py` / `errors.py` / `i18n.py` / `logging_setup.py` / `settings.py` / `tests/` 骨架。

**出口**：`uv sync` 一次成功；`uv run pytest` 绿；`run.bat` 起一个只有空状态的窗口；窗口标题是 `PDF Image Editor`；从别的目录用绝对路径调 `run.bat` 行为不变。

### 阶段 1：core（约两天） ✅
`models` / `units` / `geometry` / `imagestore` / `document` / `render` / `split` / `undo` / `save` + 全部单测。

**出口**：`test_save.py` 全绿（**全项目第一个里程碑**）；`core/` 的 AST 守卫通过；不开界面也能跑通"打开 → 切分 → 保存 → 重新打开校验"。

### 阶段 2：前端骨架与样式（约一天） ✅
从根目录 `styles.css` 提取 `css/tokens.css`（逐字）与 `css/base.css`（只保留 §8.2 表里的组件），新写 `css/app.css`；`index.html` 应用壳；`main.js` / `bridge.js` / `state.js` / `render.js` / `modal.js`；深浅色；空状态；工具栏。

**出口**：静态界面在 1920×1080 与 1280×720 下都不溢出；深浅色切换无残留色块；令牌值与 `styles.css` 逐条比对一致；提取完成后根目录 `styles.css` 移入 `docs/reference-styles.css`。

### 阶段 3：打开与渲染（约一天半） ✅
`asset_server` + `api.open_path` + 线程池 + 代次号 + `canvas.js` + `IntersectionObserver` + 缩放/滚动。

**出口**：打开 `pdfs/` 里的 12MB 扫描件首屏 < 1.5s；滚动 30 页不卡；缩放 25%–400% 不发虚；打开第二个文件时句柄不泄漏。

### 阶段 4：对象交互（约两天） ✅
选中、拖动、四角缩放、框选、z 序、删除、夹取、跨页迁移、`commit_transform`。

**出口**：拖动 60fps（DevTools Performance 无长帧）；图拖不出页；跨页拖动归属正确；撤销一次回到拖动前。

### 阶段 5：分割与打孔（约一天） ✅
`js/split.js` + 三个 core 函数接线。

**出口**：3×3 取任意一格都正确；连续撤销三次回到原图；`Shift` 切换切向；`Esc` 干净退出。

### 阶段 6：保存（约一天半） ✅
双模式 + `SaveReport` + 结果面板 + `export_pages`。

**出口**：`pdfs/20261005-0928.pdf` 走模式 A 保存后文字可选中、可搜索；`.bak` 生成；故意让目标目录只读，界面显示失败且源文件未变。

### 阶段 7：系统功能（约一天） ✅
剪贴板、外部编辑、预处理、未保存握手、设置面板。

**出口**：截图 Ctrl+V 能贴进来；外部编辑改完尺寸后能替换且不变形；预处理 20 页扫描件有进度且界面不假死；改完不保存点 X，四个分支都对。

### 阶段 8：打磨与收尾（约一天） ✅
快捷键表、ARIA、`prefers-reduced-motion`、README、配置迁移、删除 `old/`。

**出口**：§17 清单逐条过；三项命令全绿；`old/` 删除后全功能回归一遍。

总计约 11 个工作日。阶段 1 与阶段 6 是风险集中区。

---

## 16. 风险与备选

**16.1 WebView2 缺失**（高影响、低概率）
Win11 与绝大多数 Win10 自带。启动时读注册表 `HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}` 的 `pv` 值，失败再试 HKCU。缺失 → `MessageBoxW` 提示下载地址 + 退出。README 写明依赖。

**16.2 大文件内存**（中影响、中概率）
300 DPI 的 A4 位图约 8.7MB/页。渲染缓存按字节上限 256MB，LRU 淘汰；DPI 上限 300，只渲染可见页 ±1。100 页扫描件应在 600MB RSS 以内，超了降 DPI 并在状态栏提示。

**16.3 `apply_redactions` 的版本行为**（中影响、中概率）
`PDF_REDACT_TEXT_NONE` 在 1.24.x 才有。对策：`pymupdf>=1.24`；保存前做能力探测（`hasattr(fitz, "PDF_REDACT_TEXT_NONE")`），不支持则整体退回模式 B 并明确告知；逐页 `try/except` + `warnings`，单页失败不影响其他页。

**16.4 传输瓶颈**（低影响）
若实测单页 400KB PNG 在 `asset_server` 上仍有可感知延迟，退路是背景改 WebP（质量 0.9，体积降 60%），前端 `<img>` 解码。不改架构。

**16.5 DOM 节点数**（低影响）
150 页以上、每页 10 个对象 = 1500 节点，Chrome 能扛但滚动会掉帧。缓解：对象虚拟化（`IntersectionObserver` 卸载视野外 `.objects`），已留接口，本次不做。

---

## 17. 验收清单

**功能**
- [ ] 打开 12MB 扫描件首屏 < 1.5s，滚动 30 页不掉帧
- [ ] 拖动/缩放/框选/多选/删除/置顶置底可用且都能撤销
- [ ] 3×3 分割取任意格正确；打孔后原图留白
- [ ] 截图 Ctrl+V 能贴入并自由缩放
- [ ] 外部编辑器改完能替换，尺寸变化不变形
- [ ] 预处理 20 页有进度、界面不假死
- [ ] 保存后文字可选中可搜索（模式 A）
- [ ] 保存失败时源文件字节不变，界面明确报错
- [ ] 未保存点 X，四个分支都正确
- [ ] 导出选中页正常

**工程**
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run pytest` 全绿
- [ ] `core/` 无界面库导入、无 `os.chdir`、无 `print`
- [ ] 入口文件 < 30 行
- [ ] `.venv` / `logs` / `config` 均未被 git 跟踪
- [ ] `uv.lock` 指向官方 PyPI
- [ ] `config/reference_line.json` 自动迁移到 `config/reference.json`
- [ ] 日志里有本次会话完整记录，异常有 traceback
- [ ] 中英文切换后无裸露键名
- [ ] 全项目搜不到 `Simple PDF Editor`

**界面**
- [ ] 1920×1080 / 1280×720 都不溢出
- [ ] 窗口拉到最小尺寸布局不塌
- [ ] 深浅色各看一遍，无白底白字
- [ ] hover / active / focus / disabled 四态可辨
- [ ] Tab 走完全界面，焦点环不被裁
- [ ] 弹窗 Tab 出不去，Esc 能关
- [ ] 空状态 / 加载中 / 错误三种状态都有界面
- [ ] 系统字体缩放 125% 下不错位
- [ ] `prefers-reduced-motion` 下动效归零
- [ ] 界面上没有任何图标，按钮全是文字

---

## 附：为什么这次不会卡

旧实现：鼠标移动 → `QGraphicsView` 视口重绘 → 每张 150 DPI 位图重新采样 → 屏幕。
新实现：鼠标移动 → 改一个 DOM 元素的 `transform` → 合成器挪纹理 → 屏幕，**零重绘**。

位图只在"页面进入视野"或"缩放级别变化"时渲染一次，之后命中 LRU 缓存。卡顿不是换工具包自动消失的，是**渲染模型从"每帧重画"换成"一次成像 + 合成"**带来的。
