# PDF Image Editor

**PDF 图像编辑器** —— 在 PDF 里切分、移动、替换图片，保留原有文字层。

单机工具，Windows，双击即用，不需要联网。

---

## 它解决什么

扫描件和图文混排的 PDF 里，经常需要把一张大图切开、抠出中间一块、或者盖掉某个
水印。用通用 PDF 编辑器做这些事，要么得把整页栅格化（文字层就没了），要么得在
Illustrator 里折腾。

这个工具把每一页拆成「背景 + 独立的图片对象」：背景保留原文档的文字、矢量与批注，
图片对象可以单独拖动、缩放、切分、删除。保存时只把图片换掉，其余内容原样不动。

---

## 功能

**看**
- 页面按目标 DPI 渲染，缩放不发虚；滚轮滚动、`Ctrl`+滚轮以指针为锚缩放
- 浅色 / 深色两套主题，跟随系统或手动切换
- 页边距参考线，边距可调

**改**
- 拖动、四角等比缩放（`Alt` 自由比例）、多选（`Shift` 加选）
- 跨页拖动：拖到另一页就归到那一页
- 切分：放几条切线，然后「仅保留此格 / 提取此格 / 按格切分」
- 置顶 / 置底、删除、方向键微调
- 从剪贴板粘贴图片（`Ctrl+V`）
- 用系统默认程序外部编辑某张图，改完回填

**存**
- **保留原文档**（默认）：只替换图片，文字、矢量、批注、书签全部保留
- **整页重建**：整页重新成像，仅用于纯扫描件（会丢文字层，界面上有明确提示）
- 先写临时文件再替换，就地保存时首次留一份 `.bak.pdf`
- 导出指定页为新 PDF

**其它**
- 撤销 / 重做，命令只存几何与图片 id，不复制像素
- PDF 黑白化预处理（去底灰）
- 中英文界面

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

用 `pythonw.exe` 启动，不会弹控制台。从任何目录调用都行，工作目录不影响行为。

---

## 快捷键

**全部可在「设置 → 快捷键」里改**，改完立刻生效，冲突会拦下来。

设置面板没有「保存」和「取消」：每一处改动都当场写进 `config/`，关掉弹窗不会撤销任何东西。面板最后有一个红色的「重置所有」，把设置、快捷键、参考线一起恢复默认。

| 键 | 作用 |
|---|---|
| `Ctrl+O` | 打开 |
| `Ctrl+S` / `Ctrl+Shift+S` | 保存 / 另存为 |
| `Ctrl+E` | 导出页 |
| `Ctrl+Z` / `Ctrl+Y` | 撤销 / 重做 |
| `Ctrl+A` | 全选 |
| `Ctrl+V` | 粘贴图片 |
| `Ctrl+0` / `Ctrl+=` / `Ctrl+-` / `Ctrl+1` | 适合宽度 / 放大 / 缩小 / 100% |
| `Delete` | 删除选中 |
| `Ctrl+U` / `Ctrl+L` | 置顶 / 置底 |
| `Ctrl+Shift+E` | 外部编辑当前图片 |
| `Ctrl+I` | 显示 / 隐藏属性栏 |
| `Ctrl+,` | 设置 |
| `E` | 进入分割模式 |
| `方向键`（`Shift` 加速） | 微调位置 |
| `Space` + 拖动 / 中键拖动 | 平移画布 |

**分割模式下是另一套键位**，全局快捷键暂停，所以两边可以绑同一个键：

| 键 | 作用 |
|---|---|
| `1` / `2` | 仅保留光标所在格 / 提取光标所在格 |
| `Enter` | 按格切分 |
| `Ctrl+Z` | 撤销上一刀（按落笔顺序） |
| `Esc` | 退出分割 |

---

## 开发

```bash
uv sync                            # 装环境
uv run pytest                      # 跑测试
uv run ruff check .                # 静态检查
uv run ruff format .               # 格式化
uv run python -m app.ui.web.app    # 临时起界面
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
│  ├─ units.py        pt/mm 换算、页码范围解析
│  ├─ geometry.py     夹取、等比缩放、命中、切分矩阵
│  ├─ imagestore.py   内容寻址的图片仓库
│  ├─ document.py     PDF 句柄、页信息、可编辑图片
│  ├─ render.py       页面光栅化 + LRU 缓存
│  ├─ split.py        切分与打孔（纯函数）
│  ├─ undo.py         命令栈
│  └─ save.py         双模式保存 + 保存报告
├─ system/            剪贴板、本地资源服务、外部打开、预处理
└─ ui/web/            窗口 + js_api + 静态页面（零构建，ES module）
```

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

### 四条不能破的约定

1. **坐标一律是 PDF 点（pt）**，原点在页面左上角，y 向下。只有前端渲染时才乘缩放系数。
2. **图片按内容寻址存在 `ImageStore` 里**（sha1 → bytes）。撤销只改 `image_id`，不复制像素。
3. **`ImageObject` 同时存 `rect` 与 `src_rect`**。前者是当前位置，后者是原文档里的原始位置——保存时按 `src_rect` redaction、按 `rect` 重新插入，否则「移动」只能表达成「整页重来」。
4. **`core/` 不导入任何界面库**，由 `tests/test_source_hygiene.py` 用 AST 静态守住。

---

## 保存是怎么做的

| 模式 | 做什么 | 什么时候用 |
|---|---|---|
| `preserve`（默认） | 用 `apply_redactions` 把原图摘掉，再把画布上的图插回去。文字、矢量、注释、书签全部保留 | 所有情况 |
| `raster` | 整页重新成像，只留图片 | 纯扫描件，且明确接受丢失文字层 |

两个细节值得知道：

- **批注**：`apply_redactions` 会连带删掉落在矩形里的批注，所以保存时先把页面的
  `/Annots` 数组临时摘下来，做完再挂回去。批注对象一个字节都不动。
- **旋转图片**：`insert_image` 只能按 90° 步进放置，所以非轴对齐的图片不参与编辑，
  原样保留在背景里。

---

## 日志

每次启动在 `logs/` 下新建一个 `pdf_image_editor_<时间戳>.log`。出问题先看这里，
启动期的致命错误会弹窗并给出日志路径。

`config/`、`logs/`、`temp/` 不进版本库，删掉会自动重建。
