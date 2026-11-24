# 架构设计

本文给维护者看：程序怎么分层、依赖朝哪个方向走、关键流程如何串起来，以及哪些约定由测试强制保证。

[返回项目首页](../README.md) · [使用手册](readme/zh-CN.md) · [配置与数据格式](configuration.md) · [扩展指南](extending.md)

---

## 1. 目标与约束

一句话：**只替换图片，其余内容一个字节都不动。**

围绕这句话，程序被切成三层：纯逻辑（`core`）、系统集成（`system`）、界面（`ui/web`）。界面用 pywebview 起一个 WebView2 窗口，页面是零构建的原生 HTML/CSS/ES module。

硬约束：

| 约束 | 原因 | 谁在守 |
|---|---|---|
| 只在启动最早期调用一次 `os.chdir` | 工作目录是进程级全局状态，被所有线程共享；多改一次，相对路径就会落到别处 | `test_cwd_is_pinned_in_one_place` |
| 所有内部路径由 `__file__` 推导 | 从任何目录、任何快捷方式启动行为一致 | `app/paths.py` + 代码评审 |
| `core` 不导入界面库，也不反向依赖 `ui` / `system` | 核心逻辑要能被纯 pytest 覆盖 | `test_core_has_no_ui_imports`、`test_core_does_not_reach_up` |
| 全项目不用 `print` | `.pyw` 进程没有控制台，输出等于丢失 | `test_no_print_anywhere` |
| 入口文件 < 30 行 | 装配集中在一处 | `test_entry_is_thin` |
| 每个模块都要有 docstring | 说明它负责什么、不负责什么 | `test_every_module_has_a_docstring` |

这些不是风格偏好，是硬性的：工作目录是进程级全局状态，被所有线程共享；一旦切换，别的线程写相对路径就会落到别处，日志和配置会随机出现在目标文件夹里。所以启动时由 `bootstrap.ensure_cwd()` 钉一次，之后谁都不许再动。

## 2. 目录结构

```
main.pyw                      入口薄壳
main.bat / setup.bat          启动与装环境
uv.toml / uv.lock             包索引（阿里云镜像）与锁文件

app/
├─ paths.py                   全部路径的唯一来源
├─ errors.py                  异常类型（文案在抛出时本地化）
├─ models.py                  Rect / ImageObject / PageInfo / DocumentState
├─ settings.py                app.json 读写、夹取、迁移
├─ i18n.py                    文案查表
├─ logging_setup.py           loguru + 钩子 + 致命错误弹窗
├─ locales/                   zh-CN.json / en-US.json
├─ core/                      纯逻辑，零界面依赖
│  ├─ units.py                pt/mm 换算、页码范围解析
│  ├─ geometry.py             夹取、手柄缩放、命中、切分矩阵
│  ├─ imagestore.py           内容寻址的图片仓库
│  ├─ document.py             PDF 句柄、页信息、可编辑图片、覆盖层
│  ├─ render.py               页面光栅化 + LRU 缓存
│  ├─ split.py                切分与打孔（纯函数）
│  ├─ merge.py                多张图合成一张（numpy 双三次、预乘 alpha）
│  ├─ fonts.py                六种字体的路径表与懒加载缓存
│  ├─ textlayout.py           换行、行高、基线（纯函数）
│  ├─ palette.py              文字与荧光笔的调色板
│  ├─ overlay.py              文本框与荧光笔的落盘、读回、回收
│  ├─ tablelines.py           表格框线检测、拉直、重绘（numpy）
│  ├─ undo.py                 命令栈
│  └─ save.py                 保存 + 保存报告
├─ system/                    唯一直接接触 Windows 的地方
│  ├─ clipboard.py            剪贴板取图（Win32 + DIB 解析）
│  ├─ asset_server.py         本地资源服务（页面位图 / 图片 / 静态文件）
│  ├─ opener.py               用系统默认程序打开
│  └─ preprocess.py           黑白化预处理
└─ ui/web/                    pywebview 界面
   ├─ app.py                  窗口装配与关闭拦截
   ├─ api.py                  暴露给网页的全部接口
   └─ static/                 index.html + css/ + js/（无构建）
```

## 2.5 路径、版本与首次运行

| 位置 | 内容 | 默认 |
|---|---|---|
| 程序目录 | 代码与 `docs/` | 仓库根目录 |
| 数据目录 | `app.json`、`pdfs/`、`backup/` | `%PROGRAMDATA%\six-coin\pdf-image-editor` |
| 本地目录 | `logs/`、`locks/`、`data-dir.txt` | `%LOCALAPPDATA%\six-coin\pdf-image-editor` |
| 临时目录 | 外部编辑的中间文件 | `%TEMP%\six-coin\pdf-image-editor` |

- 数据目录可改：设置页当场校验目标（建目录 + 写一次探针文件），通过后写 `data-dir.pending`，**重启后**在启动早期把旧目录的内容**复制**过去、改 `data-dir.txt`，成功后再删掉旧目录。落点恒以项目代号结尾，`paths.normalize_data_dir()` 负责补齐。`paths.resolve_user_path()` 的相对路径以数据目录为基准。
- 复制而不是移动：`app.json` 是「这里是不是数据目录」的判据，先搬走再失败，指针还留在旧目录，下次启动就会被当成第一次运行——用户看到的是设置和说明书全没了。删旧目录只发生在切换成功之后。
- 启动时 `paths._reconcile_data_dir()` 只做一件事：有 `data-dir.pending` 就复制到那里并改指针。有文件没复制过去（目标不可用、被占用、只读）就**不动指针、保留标记**，下次启动再试（重试幂等：已存在的文件跳过）；结果写进 `paths.MIGRATION`，由设置页说明原因。
- 目标落在源目录里面（旧版本把「没补项目代号的指针」规范化后正是这种标记）按「没有变化」收敛：保留当前目录并丢掉标记。留着标记就是每次启动卡在同一条警告上，永远好不了。
- **指针是权威**：只有「用户选新目录」时才做规范化，不会去改写历史指针——把指针改写成它自己的子目录，永远搬不成。
- 改完目录由设置页的「立即重启」拉起新进程（释放单实例锁 → `pythonw main.pyw`）。搬迁只发生在启动早期，重开窗口是搬不动的。
- `bootstrap.prepare()` 建齐数据目录、`pdfs/`、本地目录与日志目录；打开对话框的默认落点不存在时不会停在一个空目录上。
- 版本号只有 `pyproject.toml` 一处，`app/version.py` 读它。
- `bootstrap.is_first_run()` 的判据是数据目录里没有 `app.json`；首次运行时网页依次弹语言选择与使用说明。这两步用 `openModal({dismissible: false})` 打开：Esc 与点空白都不关，必须按按钮走完。
- `main` 是唯一入口，持 `Local\SixCoin.PdfImageEditor.Main` 互斥量；重复启动**只**把已有窗口提到前面，提不到也只留一条日志——多开的意思就是「让我看到那个窗口」，弹一个「已经打开」的框只会让人以为双击失败了。

## 3. 分层与依赖方向

```
        main.pyw
            │
            ▼
            ui/web/app.py ──► ui/web/api.py
                                   │
                 ┌─────────────────┼─────────────────┐
                 ▼                 ▼                 ▼
              core/*           system/*        models / settings
                 │                                   errors / i18n / paths
                 └──────────────► 基础层 ◄───────────┘
```

规则：

1. **依赖只朝下。** `core` 不知道 `ui` 与 `system` 的存在；`system` 不知道谁在调用它。
2. **`core` 只依赖基础层与标准库**（外加 `pymupdf`，它是纯计算库，不起窗口）。
3. **`system` 不依赖界面库**，可以被任意一侧复用。
4. **跨层只传数据**，不传控件、不传窗口。`EditorApi` 是唯一知道 `webview.Window` 的类。
5. **前端只认快照**，不自己合并业务数据（见第 7 节）。

`settings.py` 会读 `i18n.available()` 来校验语言代码，这是基础层内部的一次调用，不构成反向依赖。

`pymupdf` 要求 **2.x**：1.x 有已知安全问题，且 2.x 把 `keep_proportion` 的行为统一到了所有图片格式（见 6.8）。2.1 会带入 `numpy` / `onnxruntime` 等依赖；`numpy` 现在由表格框线处理直接使用，已在 `pyproject.toml` 里显式声明。

## 4. 数据模型

### 4.1 坐标与单位

**所有几何量都是 PDF 点（pt），原点在页面左上角，y 向下。**

- 1 pt = 1/72 英寸；1 mm ≈ 2.8346 pt（`core/units.py` 里有换算函数）。
- 只有前端渲染时才乘缩放系数：`pxPerPt = zoom × 96/72`。
- 属性栏显示的位置和尺寸也是 pt，不做单位切换。

选左上原点而不是 PDF 原生的左下原点，是因为浏览器、Canvas、DOM 全是这个方向；只在 `insert_image` 那一刻转成 PyMuPDF 的 `Rect`，转换点只有一个。

### 4.2 `Rect`

不可变（`frozen=True`）的四个浮点数：`x, y, w, h`。带 `right` / `bottom` / `area` / `contains` / `translated`，以及和 JSON 互转的两个方法。

不可变是刻意的：几何计算到处在传矩形，可变对象会让「算一半被人改掉」这类 bug 极难定位。

### 4.3 `ImageObject`

画布上的一张图。

| 字段 | 含义 |
|---|---|
| `id` | 稳定标识，形如 `p0-x12-0`（页-资源序号）或 `paste-1a2b3c4d` |
| `page` | **当前**所在的页 |
| `rect` | **当前**显示位置 |
| `image_id` | 指向 `ImageStore` 的内容哈希 |
| `src_xref` | 原文档里的图片资源号，没有则为 `None`（粘贴进来的图） |
| `src_rect` | 它在原文档里的**原始**位置 |
| `src_page` | `src_rect` 属于哪一页 |
| `z` | 同页内的叠放顺序，10 起递增 |
| `rotation` / `opacity` | 预留，当前界面不暴露 |

**`rect` 与 `src_rect` 必须分开存。** 保存时要「在原位擦掉、在新位插入」：如果只有一个矩形，移动一张图就只能表达成整页重来。`src_page` 同理——跨页拖动后 `page` 变了，`src_page` 不能跟着变，否则保存时去错的页面擦。

### 4.4 `PageInfo`

`index / width / height / has_text / locked_images`。

`locked_images` 是这一页有几张「看得见但不可编辑」的图（页面被旋转，或图片非轴对齐）。属性栏用它给用户解释「为什么这张选不中」。

### 4.5 `DocumentState`

内存里的文档，界面只读它，撤销栈只改它。

| 字段 | 说明 |
|---|---|
| `path` | 当前文件 |
| `pages` | `PageInfo` 列表 |
| `objects` | 所有画布对象：`ImageObject` / `TextObject` / `HighlightObject` |
| `selection` | 选中的 id 列表 |
| `removed` | 墓碑表：`{页号: [被删掉的原图位置]}` |

`objects` 是**一个**列表，靠 `kind`（`image` / `text` / `highlight`）区分。多选、一起拖动、撤销、z 序因此全部复用同一套代码；`overlays_on(page)` 取某页的文本框与荧光带，`images_on(page)` 取图片。

**墓碑表**是保存正确性的关键：对象删了，但它在 PDF 里还占着位置，不记下来就擦不掉，保存完它又回来了。

`upsert` 按 id 覆盖（幂等，重复调用结果相同），`replace_all` 整份替换，`renormalize(page)` 把某页的 z 重排成 10、11、12…，`drop` 同时清理选择集。

### 4.6 `TextObject` / `HighlightObject`

| 字段 | 含义 |
|---|---|
| `id` | `t-1a2b3c4d` / `h-1a2b3c4d` |
| `rect` | 文本框：`w` 是用户能拖的宽度、`h` 由排版算出；荧光带：`w/h` 都定死 |
| `runs` | 只有文本有：`[{text, font}]`，一段一种字体，可以混排 |
| `size_px` | 字号（px，整数）。落盘时 ×0.75 变 pt |
| `line_height` | 行高是字号的倍数（默认 1.15） |
| `color` | 调色板的键，不是色值 |
| `z` | 同页叠放顺序 |

**尺寸规则**：文本框只接受宽度（`commit_transform` 里忽略客户端给的高度，一律重排），荧光带连宽度都不接受。组缩放时两者只按 `sx/sy` 变换位置，尺寸不动。

### 4.7 z 序

- 同一页内按 `z` 升序叠放，DOM 顺序即视觉顺序。
- 新建对象取 `next_z(page)`（当前最大值 + 1）。
- 切分、打孔这类结构变化后调用 `renormalize`，避免出现重复层级。
- 置顶 / 置底是「把选中的挪到同页列表的末尾 / 开头」，然后整页重编号。

## 5. 模块职责

| 模块 | 只做 | 不做 |
|---|---|---|
| `paths` | 由 `__file__` 推导绝对路径；解析配置里的相对路径 | 不判断文件是否存在 |
| `settings` | 读写 `app.json`、夹取数值、迁移旧格式、原子写入 | 不缓存、不持有界面状态 |
| `models` | 数据结构与形状运算 | 不读写文件 |
| `i18n` | 扫描语言目录、查表、填占位符 | 不关心调用者是谁 |
| `errors` | 异常类型；抛出时把文案取好 | 不含逻辑 |
| `logging_setup` | 配置 loguru、装 `sys.excepthook` 与 `threading.excepthook`、致命错误弹窗 | 不写业务日志 |
| `core.units` | pt/mm 换算、页码范围解析 | 不认识 PDF 也不认识界面 |
| `core.geometry` | 夹取、手柄缩放（角等比 / 边单向）、命中测试、切分矩阵 | 不碰 PyMuPDF 页面 |
| `core.imagestore` | 内容寻址存取、缩略图、垃圾回收 | 不知道图属于谁 |
| `core.document` | 打开 / 关闭、页信息、抽取可编辑图片（软遮罩并进 alpha） | 不渲染、不保存 |
| `core.render` | 页面光栅化 + 涂白 + LRU 缓存；渲染时临时摘掉本项目覆盖层 | 不决定显示在哪一页 |
| `core.split` | 五个纯函数：切分、保留、打孔、涂白、像素裁切 | 不碰撤销栈 |
| `core.merge` | 并集画布、最高像素密度、双三次放大、按 z 序预乘合成 | 不碰撤销栈、不知道结果放在哪一层 |
| `core.fonts` | 六种字体的路径、懒加载与缓存 | 不排版、不画 |
| `core.textlayout` | 换行、行高、基线；输出「第几行、每个字段从哪开始」 | 不碰 PDF、不知道字号是 px 还是 pt |
| `core.palette` | 文字三色与荧光四色的键表 | 不认识 PDF |
| `core.overlay` | 草稿页绘制、`/BM /Multiply`、子集化、嫁接、标记读写 | 不决定存到哪、不认识撤销栈 |
| `core.tablelines` | 长游程分离、可靠线支撑、固定 3px、纯黑重绘、corner/T 收放 | 不碰撤销栈、不知道图片在页面哪 |
| `core.undo` | 命令栈、宏、dirty 判定 | 不知道命令的业务含义 |
| `core.save` | redaction + 重插 + 原子落盘 + 校验 | 不决定保存到哪 |
| `system.asset_server` | 把位图、缩略图、静态文件喂给 WebView2 | 不是业务服务端 |
| `ui.web.api` | 每个用户意图一个方法，返回快照；加锁、起任务 | 不拼 HTML |
| `ui.web.static` | 渲染与交互，状态全部来自快照 | 不维护业务数据 |

## 6. 关键流程

### 6.1 启动装配

```
bootstrap.ensure_cwd()              cwd 钉在程序目录，只此一次
bootstrap.prepare()                建目录；把数据目录搬迁的结果交给日志
logging_setup.setup("main")        默认级别先开文件，崩溃路径也留得下日志
  → EditorApi()                     读配置；配置损坏在这里就抛；读完调
                                    settings.apply_log_settings() 按用户设置重配
  → AssetServer(api, store, WEB_DIR).start()
  → i18n.set_language(config["language"])
  → webview.create_window(..., js_api=api, background_color=主题底色)
  → window.events.closing += 关闭拦截
  → webview.start()
  → 退出时 server.stop() + api.shutdown()
  → 用户点过「立即重启」就释放单实例锁之后拉新进程
```

窗口尺寸取屏幕的 85%，最小 960×640。`background_color` 必须和页面的 `--bg` 一致，否则深色模式下首帧会闪一下白。

### 6.2 打开文档

```
前端 open_path(path)
  → 落在 backup/ 里：直接拒绝（{reason: "backup"}），备份是只读快照
  → 有未保存修改且没 force：直接返回 {reason: "dirty"}
  → generation += 1，建 task，丢进线程池
后台线程 _open_worker
  → PdfDocument.open()，逐页读 pt 尺寸
  → 回到锁内：代次没变才替换 _doc / RenderCache / DocumentState / UndoStack
  → 清空已装载页集合
前端轮询 poll_task，ready 后刷新快照
```

代次号（`generation`）解决「连续打开两个文件，先发的后到」：晚到的结果直接丢弃并关闭自己的句柄。

拖进来的文件走另一条入口：WebView2 只把真实路径交给宿主，页面自己拿不到，所以由 `app/ui/web/app.py` 在页面 `loaded` 之后接上 `window.dom.document` 的 `drop` 事件（`DOMEventHandler(prevent_default=True)` 顺手挡住「把 PDF 当网页打开」）。拿到路径后调 `api.offer_drop()`，它再 `evaluate_js("window.host.dropPath(...)")` 把活交回页面——**打开动作必须在页面里做**，那里才有未保存修改的三选一询问。

### 6.3 渲染与缓存

背景图永远是「原文档去掉可编辑图片」的样子，与用户后来怎么拖、怎么删无关。所以：

- 缓存键只需要 `(页号, dpi)`；
- 每次渲染都按 `src_rect` 把原图位置**涂白**（向外扩一个设备像素，否则抗锯齿的半覆盖像素会留下一条边）；
- 页面被旋转或图片非轴对齐时，这些图不参与编辑，也就不会被涂白。

`RenderCache` 是字节数上限 256MB 的 LRU，DPI 夹在 36–300。前端按 `96 × zoom × devicePixelRatio` 取整到 24 的倍数作为档位，所以连续缩放不会反复请求新图。

### 6.4 一次拖动的往返

```
pointerdown  → 记下起点，进入手势状态
pointermove  → 只改元素的 left/top（不重排布局、不请求快照）
pointerup    → 一次性 commit_transform(items, selection)
后端         → 夹到页内、过滤掉没实际变化的项、push ObjectsChanged
             → 返回新快照
前端 apply   → 按 rev 判断新鲜度，重绘
```

**手势期间禁止任何快照落地**（`state.view.gesture`）。否则后端返回的快照会重建 DOM，把正在拖的节点换掉，表现就是「元素突然被拉回原位」。手势期间被丢弃的快照会在松手后补一次。

### 6.5 跨页拖动

`commit_transform` 会先调 `_ensure_pages`：把这次涉及、但还没装载过的页的原图读进模型。

不这么做的话，拖过去的那张会成为该页唯一被模型知晓的图，而文件里还有这一页原有的图——模型和文件对不上，保存时只能整页重建。

### 6.6 切分与打孔

四个纯函数，输入对象列表，输出新对象列表：

| 函数 | 结果 |
|---|---|
| `build_split` | 所有格子各成一个对象 |
| `keep_cell` | 只留 `(row, col)` 那一格 |
| `punch_cell` | 原图挖一个白洞，抠出来的格子独立成对象 |
| `fill_cell` | 原图挖一个白洞，**不**产出小块（切分模式里的「3」） |

格子一律用 `(row, col)` 显式指定，行列号是**去重之后**的真实网格坐标——不存在「第 4 格就是中心」这种硬编码索引。

像素级细节：

- 页内矩形按比例换算成原图像素矩形，再逐行拷贝裁切（不依赖版本相关的裁剪 API）；
- 洞是直接挖在原图像素上的，不叠白色矩形——叠层在缩放时会被插值成半透明；
- 切分线是纯视图状态，按落笔顺序存在前端数组里，撤销就是弹最后一条。

### 6.7 文本框与荧光笔的落盘

两者都不画成 PDF 批注，而是画进**页面内容流**：打印、复制文字、任何阅读器都按普通内容处理，不依赖各家对批注外观流的支持。

```
每页：
  1. overlay.clear(page)         撤掉上一版（摘内容流 + 只删标记点名的那一个 XObject）
  2. redaction + insert_image    现有图片流程
  3. overlay.draw(page, items)
       草稿文档（mediabox 尺寸）
         → 荧光带：裸操作符 + /ExtGState <</BM /Multiply>>
         → 文字：TextWriter，一种颜色一个，混排字体在同一条流里
         → scratch.subset_fonts()      只子集化我们自己的字体
       page.show_pdf_page(mediabox, scratch, 0)   → 一个 Form XObject
       内容流首行写标记 `% sixcoin-overlay v1 <xobj名>`
       该页对象 JSON 写进 XObject 的 /SixCoin 流
```

三条必须守住的：

1. **顺序**：`apply_redactions()` 会把整页内容流合并成一条，所以覆盖层只能在它之后写；上一版必须在它之前撤。
2. **回收**：撤旧时只删标记里点名的那一个 XObject。遍历删整个 `/Resources/XObject` 会把页面上的图片（`fzImg0`）一起删掉，下一次保存就报 `cannot find XObject resource`。
3. **字体**：子集化只发生在草稿文档里。主文档一次 `subset_fonts()` 都不能调——那会把原文档所有字体一起子集化，违背「其余内容一个字节都不动」。

标记是唯一的身份凭据：`garbage=4` 会重编号对象，xref 存不住。重新打开时按内容流首行认出自己，再从 `/SixCoin` 还原对象；别的 PDF 里的文字没有这个标记，自然就是「烘焙在背景里、不可编辑」。

### 6.8 撤销栈

只有三类命令：

| 命令 | 适用 | 存什么 |
|---|---|---|
| `ObjectsChanged` | 移动、缩放、改 z、改页码 | 前后两份对象列表（按 id 覆盖） |
| `StructureChanged` | 增、删、切分、打孔、粘贴 | 前后两份完整对象列表 |
| `ImageReplaced` | 外部编辑回填 | 两个 `image_id` |

外加 `MacroCommand` 把多条合并成一次撤销。

- **命令只存几何与图片 id，不存像素**：图片字节在 `ImageStore` 里按 sha1 常驻，撤销只是把 `image_id` 指回去。
- `apply` 必须幂等：按 id 覆盖，不是追加。
- 栈上限默认 100（设置里 10–500）。挤出栈外的记录会让「已保存位置」失效，此时 `dirty` 永远为真——这是有意的：回不到存档点，就该提醒用户保存。

### 6.9 保存

```
api.save_document(path?)
  → 只读文件提前拦下
  → doc.close()（Windows 上 os.replace 覆盖不了仍被打开的文件）
  → core.save.save(src, dst, state, store)
       → 逐页：摘 /Annots → add_redact_annot(src_rect) → apply_redactions
                → 挂回 /Annots → 按 z 插入当前图片
       → doc.save(临时文件, garbage=4, deflate=True)
       → 重新打开校验页数
       → 就地保存时先把原文件复制进 <数据目录>/backup/
         （YYYYMMDD-原标题.bak.pdf；同名已存在就跳过，失败只记警告）
       → os.replace(临时文件, 目标)
  → 成功：以新文件为基线；失败：把句柄接回去，编辑不丢
```

`apply_redactions` 的参数是刻意的：`images=REMOVE` 只摘图，`graphics=LINE_ART_NONE`、`text=TEXT_NONE` 保证文字与矢量不动。

`insert_image` 也必须显式写 `keep_proportion=False`。默认值 `True` 会按图片原始比例把图居中塞进目标矩形，中心与短边不变，看起来就是「用户调过的长宽比被还原了」。PyMuPDF 2.x 起这条对所有格式一致生效（1.x 只对 JPEG 生效，PNG 重新编码时会被忽略），所以样本里必须带上 JPEG 才能覆盖到。

单页失败不拖累其他页，只记一条警告，最后汇总成一份报告（见使用手册第 11 节）。

### 6.10 保存后的基线重建

保存完不能整份重建——那样界面会闪一下，撤销栈也会清空。所以先试「就地重定基线」：

1. 重新打开新文件，逐页抽出可编辑图片；
2. 和模型里该页的对象按 z 排序后**数量比对**；
3. 对得上：把每张图的 `src_xref` / `src_rect` / `image_id` 更新成新文件里的值，清空墓碑表，保留对象、撤销栈、DOM；
4. 对不上（切分粒度不同、有图被跳过）：退回完整重建，`generation += 1` 让前端重新加载页面。

墓碑表必须清空：被删的图已经在文件里彻底消失，留着的话下次保存会照着旧坐标去擦，可能擦掉刚放进去的新图。

### 6.11 导出页

读的是**磁盘上的文件**，不是内存模型，所以有未保存修改时直接拒绝。

页码解析在后端（`parse_page_range`），支持 `1-3,5,7-9`、中文逗号、空格。非法片段不静默丢弃，返回 `(错误码, 原始片段)` 由界面列出。

### 6.12 外部编辑

```
edit_external(id)   → 图片写到 temp/edit-<随机>/image.png → os.startfile 打开
用户在外部程序里改完、保存、关闭
前端弹确认框
replace_image(id, path) → 校验能解析成图片 → push ImageReplaced → 删临时目录
```

临时目录只允许删 `TEMP_DIR` 下自己建的那一层；启动时还会清理一天前的残留。

### 6.13 预处理

把页内每张图转灰度、把亮于阈值的像素压成纯白（扫描件去底灰），结果另存为新文件。

入口在顶栏的「预处理」：先弹说明框，里面两条路——「处理当前打开的文档」（要求没有未保存修改，因为处理的是磁盘版本）或「处理其他文档」（另选文件）；确认后再选目标文件。跑完会问要不要立刻打开结果，打开走的是和「打开」同一条路径，所以未保存修改照样会被拦下。

预处理本身不用 numpy / Pillow：`bytes.translate` 是 C 实现，逐字节查表比逐像素循环快两个数量级；灰度转换交给 `pymupdf.Pixmap(csGRAY, pix)`。表格框线处理（6.14）才直接用 numpy。带 alpha 的图跳过——压成二值会把透明区域变成黑块。

落盘同样是「临时文件 + `os.replace`」，目标与源相同时直接拒绝：源文件正被自己打开着，写回去只会得到半个坏文件。任务在线程池里跑，通过 `progress` 回调更新任务进度。

### 6.14 表格框线拉直

选中一张图，属性栏「表格框线处理」→ `api.straighten_table`：锁内取字节 → 锁外算 →
锁内确认 `image_id` 没被换掉 → 压一条 `ImageReplaced`。算法在 `core/tablelines.py`，
纯 numpy：

1. 灰度 + Otsu 二值化；白底时给阈值一个下限，避免细黑线把阈值压到 0。
2. 长游程过滤（核长 = max(24, 2% 图宽/高)），**只保留原游程、不做膨胀**，端点才不会被撑出去。
3. 游程连通域 + 逐列/逐行墨迹重心拟合中心线（只用线芯 ≤100，抗锯齿边不参与）。
4. 认线：贯穿 75% 图宽/高的线直接收；其余线只有两端都搭在「可靠线」（≥8% 且几何合格）
   上才收。手写长横线两端不搭线，不会被误检。
5. 同一条线被竖线切开的段按「中心差 ≤2px、间隙 ≤8px」合并，绘制时用同一个中心，
   切口不会差出一个像素的台阶。
6. 线宽固定 3px（`_THICKNESS`），不再做任何宽度统计。
7. 擦除只擦每条线自己的窄带（逐列跟随原始中心，带宽 = 3 + 4px），文字不受影响。
8. 重绘：线心对到像素栅格（奇数宽对半像素），纯黑 `(0,0,0)`。交叉口按
   corner / T 型收放：corner 延到对面线的外像素边，T 型只收到对面线的中心线；
   端点判定容差 9px，扫描件里多出几像素的线头也按同一个交叉口收掉。

没有识别到线时返回 `applied=False, reason="no_lines"`，图片不变。整页倾斜 >0.5°
不在保证范围内。

### 6.15 图片合并

多选同一页的两张以上图片，属性栏「合并图片」→ `api.merge_images`。与表格框线
同一个套路：**锁内冻结输入 → 锁外算像素 → 锁内确认对象没变 → 压一条
`StructureChanged`**。合并要读几张原图、做插值，不能攥着文档锁不放。

算法在 `core/merge.py`，纯 numpy：

1. **分辨率取最高**：每张图的密度 = `max(像素宽 / rect.w, 像素高 / rect.h)`，即
   每 pt 有多少像素。取最大值作为画布密度——它对应「每个像素在页面上占的面积
   最小」的那张。并集矩形 × 密度 = 画布像素尺寸。
2. **其余图放大**：每张图按同一密度换算目标矩形，用 Keys 双三次核（a = -0.5）
   放大。只有画布上限（4000 万像素 / 边长 12000）触发时才会整体缩小。
3. **按 z 序叠**：对象按 z 升序逐张合成，先画在下。合成在**预乘 alpha** 空间里
   做（PyMuPDF 的带 alpha 位图本来就是预乘的），公式 `src + dst × (1 − src_a)`；
   透明区域保留，不会出现彩边。
4. **相邻边严丝合缝**：目标边由页面坐标直接换算，而不是「起点 + 宽」，共边的
   两张图不会差出 1px 的缝或叠。
5. **分条计算**：画布只留一份 uint8 RGBA，插值与叠加按 128 行一条推进，工作
   内存与条高成正比；最后整张编码成 PNG 进 `ImageStore`。

结果对象取选中图里**最大的 z**：合并把多层压成一层，放在最上层与「最前面那张
图」的观感一致。被合并的原图位置全部记进墓碑表，保存时按 `removed` 擦掉，再
插入这一张——模型里少 N 张、文件里多 1 张，`_rebase_after_save` 的张数对得上。

合并用的是 `ImageStore` 里的字节，也就是画布上显示的那张位图。抽取时 PDF 的软遮罩
（smask，独立 xref）已经并进 alpha（`document._with_soft_mask`），所以透明区域在
合并结果里原样保留。

## 7. 前后端契约

### 7.1 快照

每个读取或修改文档状态的方法都返回**完整快照**（文案表与任务轮询除外）：

```json
{
  "ok": true,
  "rev": 42,
  "message": "",
  "doc": { "path": "…", "name": "…", "dirty": false, "page_count": 12,
           "generation": 1, "can_save": true },
  "pages": [{ "index": 0, "w": 595, "h": 842, "has_text": true, "locked": 0 }],
  "objects": [
    { "id": "p0-x12-0", "kind": "image", "page": 0, "x": 100, "y": 100, "w": 200, "h": 150,
      "z": 10, "rotation": 0, "image": "sha1…", "thumb": "…", "src": "…" },
    { "id": "t-1a2b3c4d", "kind": "text", "page": 0, "x": 60, "y": 300, "w": 113.4, "h": 24,
      "z": 11, "size": 14, "line_height": 1.15, "color": "blue", "hex": "#0078D4",
      "runs": [["正文", "simsun"], [" Latin", "times"]],
      "lines": [{ "baseline": 9.8, "runs": [["正文", "simsun", 0, 21.0], [" Latin", "times", 21.0, 30.5]] }] },
    { "id": "h-5e6f7a8b", "kind": "highlight", "page": 0, "x": 60, "y": 400, "w": 200, "h": 11.25,
      "z": 12, "color": "yellow", "hex": "#FFF066" }
  ],
  "selection": ["p0-x12-0"],
  "history": { "can_undo": true, "can_redo": false, "label": "edit.move" },
  "language": "zh-CN", "languages": ["zh-CN", "en-US"],
  "theme": "light", "show_guides": true, "show_inspector": true, "eight_handles": true,
  "keybindings": {}, "reference": { "left_mm": [10], "right_mm": [10, 50], … },
  "palette": { "text": [{"key": "blue", "hex": "#0078D4"}, …], "highlight": […] },
  "fonts": [{ "key": "msyh", "css": "Microsoft YaHei" }, …],
  "defaults": { "text_font": "msyh", "text_size_px": 14, "text_color": "blue",
                "text_width_mm": 40, "text_line_height": 1.15,
                "highlight_height_px": 15, "highlight_color": "yellow" },
  "undo_limit": 100,
  "log_level": "INFO", "log_cleanup": true, "log_retention_days": 30,
  "backup_retention_days": 30
}
```

- `rev` 在生成快照那一刻递增，前端只认更大的值，晚到的旧回包自动作废。
- 前端不维护业务数据，只保留纯视图状态（缩放、已加载页、手势中标志）。

### 7.2 方法表

| 类别 | 方法 |
|---|---|
| 读取 | `get_state` `get_strings` `poll_task` |
| 文档 | `browse_pdf` `open_path` `reload_document` |
| 渲染 | `load_page`（另：`render_page` 供资源服务内部调用） |
| 选择 | `select` |
| 编辑 | `commit_transform` `delete_objects` `reorder_objects` `undo` `redo` |
| 切分 | `split_object` `keep_cell` `punch_cell` `fill_cell` |
| 合并 | `merge_images` |
| 文本 | `create_text` `update_text`（清空即删除） |
| 荧光笔 | `create_highlight` `update_highlight` |
| 表格线 | `straighten_table` |
| 保存导出 | `save_document` `browse_save` `export_pages` |
| 剪贴板 / 外部 | `paste_image` `edit_external` `replace_image` |
| 其它 | `preprocess_pdf` `update_reference` `update_settings` `set_language` `reset_settings` |
| 拖拽 | `offer_drop`（后端 → 页面，不是页面调的） |
| 数据目录 | `set_data_dir` `reset_data_dir` `restart_app` |
| 关闭 | `answer_close` |

约定：**越界或非法参数不抛异常**，原样返回当前快照。网页拿到 Python traceback 是最难排查的一类问题。

### 7.3 线程与任务

pywebview 给每次 JS 调用单起一个线程，所以：

- 所有对文档状态的读写都在同一把 `RLock` 里；
- 长任务（打开、预处理）返回 `task_id`，前端轮询 `poll_task`（80ms 一次）；
- 任务表只留最近 20 条，避免无限增长；
- 线程池固定 2 个 worker，避免同时开多个大 PDF 把内存打满。

### 7.4 关闭握手

`window.events.closing` 在 **UI 线程**执行，在里面调 `evaluate_js` 会等同一个正在执行回调的消息循环 → 死锁。所以：

```
closing（UI 线程） → 有未保存修改就 request_close_prompt()（丢进线程池）
                   → return False（取消本次关闭）
线程池             → evaluate_js("window.host.askUnsaved()")
页面               → 用户选择 → answer_close("save"|"discard"|"cancel")
后端               → 确认后 window.destroy()
```

`window.host` 由 `main.js` 在启动时装上；名字不用 `window.app`，因为页面里有 `id="app"` 的元素，浏览器会用元素占住那个全局名。

### 7.5 资源服务

为什么不用 data URL 走 JS 桥：一张 150 DPI 的 A4 位图约 400KB，base64 之后膨胀成 550KB 的 JSON 字符串，一次缩放要重传十几页。走 HTTP 还能吃到浏览器的图片缓存与异步解码。

| 路由 | 内容 | 缓存 |
|---|---|---|
| `/a/<token>/static/<path>` | 页面、CSS、JS | `no-store` |
| `/a/<token>/page/<n>.png?dpi=&v=` | 页面位图 | 一年，immutable |
| `/a/<token>/img/<id>?w=` | 原图 / 缩略图 | 一年，immutable |

只绑 `127.0.0.1`，端口随机，路径里带一次性 token（`secrets.token_urlsafe`），随窗口一起退出。它不是业务服务端，没有任何写接口。

## 8. 前端结构

### 8.1 模块划分

零构建，原生 ES module，22 个文件各管一件事：

| 文件 | 职责 |
|---|---|
| `main.js` | 装配、动作分发表、`window.host` |
| `bridge.js` | 桥接封装：`call()`、`T()`、状态栏 `toast()` |
| `state.js` | 纯视图状态（缩放、DPI、主题、手势中） |
| `sync.js` | **唯一**的快照通道，合并短时间内的多次刷新 |
| `render.js` | 快照 → DOM，含属性栏、多选组框与语言替换；按 `kind` 分派到图片 / 文本框 / 荧光带 |
| `canvas.js` | 页面可见性、位图加载、缩放与滚动 |
| `interact.js` | 指针手势：选中、拖动（含吸附）、八手柄缩放、组缩放、框选、平移 |
| `split.js` | 分割模式：切线、格子高亮、执行 |
| `modes.js` | 左栏三种模式（选择 / 文本 / 荧光笔）与光标 |
| `text.js` | 文本框的渲染、contenteditable 编辑、浮动工具栏 |
| `floatbar.js` | 浮动工具栏挂到 body、按窗口定位并夹在窗口内 |
| `highlight.js` | 荧光带的渲染、绘制预览、调色条 |
| `guides.js` | 参考线绘制（每边多条）、对齐线位置与吸附计算、吸附时的绿色提示线 |
| `drop.js` | 拖文件进窗口：遮罩提示、挡住 WebView2 的默认导航 |
| `controls.js` | 通用表单控件（分段选择器），设置页与首次运行共用 |
| `settings.js` | 设置弹窗 |
| `modal.js` | 通用弹窗与确认框 |
| `markdown.js` | 使用说明的 Markdown 渲染 |
| `export.js` | 导出页弹窗 |
| `keymap.js` | 键位表、归一化、冲突检测 |
| `shortcuts.js` | 键位 → 动作分发 |
| `actions.js` | 会改后端状态的动作，点击与快捷键共用 |

### 8.2 渲染管线

```
call('get_state') → apply(snapshot)
  → rev 检查（旧回包丢弃）
  → 手势检查（手势中不落地，标记 stale）
  → 文档变了（generation 不同）→ 重建页面骨架
  → 对象签名变了 → 重建对象节点
  → 只更新选择 / 属性栏 / 工具栏状态
```

`sync.js` 是唯一的「拉状态 + 落地渲染」入口，其它模块只负责触发一次刷新。这样后端模型永远是唯一真相。

页面背景（`core/render.page_png`）画的是「原文档去掉可编辑图片」的样子。文本框与荧光带虽然是真正的页面内容，但它们由前端用 DOM 按模型再画一遍，所以渲染时用 `overlay.hidden` 临时把覆盖层从 `/Contents` 里摘掉，`finally` 再原样挂回。不这么做的话，保存过的文字会被烘焙进背景：移动文本框时原位留下一个擦不掉的残影，重开文件还会看到两份叠在一起。

### 8.3 缩放与 DPI

```
BASE_PX_PER_PT = 96/72
pxPerPt = zoom × BASE_PX_PER_PT
dpi = clamp(round(96 × zoom × devicePixelRatio / 24) × 24, 72, 300)
```

按档位取图：比例跨过一档才向后端要新位图，中间的连续缩放只改 CSS 尺寸。

页面加载是一个固定窗口：`WINDOW = [0, +1, -1, +2]`，以视口中心所在的页为基准，只拉这四页（第 30 页 → 30、31、29、32）。`IntersectionObserver` 的 `rootMargin` 为 0，只用来兜底「真正压在视口里的页」——低倍缩放时一屏可能露出三页，窗口外的也得加载，否则屏幕上是灰块。

请求按窗口顺序**串行**发出：后端 `load_page` 要拿同一把锁，并发只会在锁上排队；串行还能保证当前页第一个回来，不会被先发出的远页堵住。已经渲染过的页不卸载；跳页时距离超过一屏半就用 `scrollTo({behavior: "auto"})` 而不是平滑滚动——平滑滚动会一路经过中间页，每页都触发一次加载。

### 8.4 手势

| 手势 | 起点 | 结果 |
|---|---|---|
| 移动 | 按在图片上拖动 | 整组（多选时）改 `rect`，跨页则改 `page` |
| 单图缩放 | 图片的八个手柄 | 角等比、边单向；`Alt` 解锁比例 |
| 组缩放 | 大框的八个手柄 | 按同一 `sx/sy` 缩放整组，锚点是对面那条边 |
| 框选 | 空白处拖动 | 与选框相交（含部分重叠）的本页图片 |
| 平移 | `Space` + 拖动 / 中键 | 只改滚动位置，不碰模型 |
| 画荧光带 | 荧光笔模式下横向拖动 | 松手才建对象，拖动中只有一个预览块 |
| 建文本框 | 文本模式下单击空白 | 落点即左上角，随即进入编辑 |

文本框与荧光带的手柄规则：文本框只有左右两个（改宽度、文字不缩放），荧光带一个都没有。组缩放时两者只按 `sx/sy` 挪位置，宽高一律不动——拉大整组不等于把字也拉大。

- 拖动只改 `left/top`，不重排布局；松手一次性提交。
- 移动阈值 3px，最小尺寸 4pt；组缩放还要保证组里最小的那张不低于 4pt、整组不出页面。
- 缩放的锚点是手柄的**对边**。角手柄命名是 `tl/tr/bl/br`、边手柄是 `n/s/w/e`，判断方向必须两套都认（`l/r` 与 `w`、`t/b` 与 `n`），否则 `tl` 会被当成往右下长。
- 缩放结果先按锚点到页边的距离算出最大倍率再夹取（`clampScale`），不能留给后端：`clamp_rect_to_page` 只按边裁，长宽比会被裁坏。
- 八个手柄是纯 CSS 开关（`#app.eight-handles`），关掉时边手柄 `display:none`，不用重建 DOM。
- 手柄的填充色**两种主题下都是白的**（`--handle-fill: #ffffff`）：页面本身永远是白纸，深色模式只把画布背景调暗，手柄跟着变黑就会和页面糊在一起。描边用主题蓝，那是唯一的深色线索。
- 多选限同一页：组框要有共同坐标系；`api.select` 也会截断跨页的 id。
- 手势期间后端快照一律不落地（见 6.4），组框在非组手势期间临时隐藏。

保存期间另有一层锁：`state.view.busy` 为真时指针与快捷键都不响应，状态栏上挂一条不自动消失的「正在保存」提示（见 8.7）。后端在保存过程中已经把文档句柄放掉，此时任何编辑都会落空。

### 8.5 移动吸附与对齐线

对齐线（`app.json` 的 `align`）和参考线存法相同：四边各一组毫米值，位置从那条边往里算。区别在用途——参考线常驻显示，对齐线平时不画，只在移动元素时吸附，吸住了才画一条绿色提示线。

- 参与吸附的是元素（或整组）的**外接矩形**：左边、竖直中线、右边吸竖直对齐线，上边、水平中线、下边吸水平对齐线；取距离最近的一条，阈值 6 屏幕像素（换算成 pt 后比较，缩放后手感一致）。
- 吸附以**指针所在页**为准。跨页拖动时，吸的是要落下去的那一页的线。
- 吸附结果如果会把元素推出页面，这一轴就放弃吸附——宁可不对齐，也不能出页。
- 提示线是 `.snap-guides` 图层里的两个 2px 绿条（`--snap-line`），层级高于参考线，低于浮动工具栏；手势结束、取消、页面重建时一律清掉。

### 8.6 键位系统

两套作用域：`global` 与 `split`。分割模式下只查 `split` 表，全局快捷键暂停，所以两边可以绑同一个键。

- 组合键用 `event.code` 归一化（`KeyS` → `S`，`Digit1` → `1`），避开 Shift 改字符与键盘布局差异；
- 只按修饰键不触发任何动作；
- 同一作用域里重复的组合键由 `findConflicts` 检出，设置面板当场拦下；
- 方向键微调不参与自定义键位，避免与全局表互相干扰。

### 8.7 状态栏

底部居中的圆角黑条，界面上**唯一**的临时提示出口：操作结果、失败原因、进行中的保存都走这里。不再另造横幅——多一种提示条就多一套颜色、圆角和消失时机，用户看到的是「这个程序有好几种提示」。

结构是一个固定底边的 `flex-direction: column` 容器（`.toast-root`），条目按加入顺序从下往上堆：

- **新的一条**从下方 10px 处淡入并轻微放大（`toast-in` 0.2s）。
- **已有的几条**同时上移一格。位移用 FLIP 补：加新条之前记下每条的 `getBoundingClientRect().top`，加完再按差值先 `translateY(+delta)` 再归零，所以看到的是「挪了一格」而不是「跳了一格」。
- **最多三条**。满了还要来第四条时，最老的那条**一边往上飘一边渐隐**（`toast-out`），并且先被摘出文档流、换成绝对定位的「幽灵」再飘走——留在流里会让剩下的条目先被顶上去、再掉下来，看着像抖了一下。
- 成功 2400ms、失败 4200ms 自动消失；退场同样走幽灵，后面的条目平滑补位。
- `z-index: 200`：必须高于弹窗（50）与下拉（45），提示不能被正在做的事盖住。
- 文案结尾的句号由 `toast()` 统一去掉——状态栏是一句话，不是段落。

`toast(text, ok)` 返回一个句柄，`{ sticky: true }` 时不自动消失（保存中用它，`close()` 收尾），`{ busy: true }` 时在文字前加一个转圈的小环。

## 9. 线程模型

| 线程 | 归属 | 做什么 |
|---|---|---|
| pywebview UI 线程 | 窗口 | 消息循环；`closing` 回调 |
| js_api 线程 | 每次 JS 调用一个 | 执行 `EditorApi` 方法，全部在 `RLock` 内 |
| 线程池（2） | `ThreadPoolExecutor` | 打开文档、预处理、关闭询问 |
| 资源服务线程 | `ThreadingHTTPServer` | 响应页面位图、图片、静态文件 |

规则：**跨线程只传数据**。控件与窗口只在 UI 线程碰；`evaluate_js` 一律从工作线程发起。

## 10. 错误处理

| 场景 | 策略 |
|---|---|
| 配置损坏 | `ConfigError` → 记日志 → 弹窗给日志路径 → 退出 |
| PDF 打不开 | `PdfError` → 任务状态置 `error` → 前端 toast |
| 保存失败 | `SaveError` → 句柄接回去，编辑不丢，界面提示原因 |
| 单张图插入失败 | 记进 `SaveReport.warnings`，不中断保存 |
| 单个请求出错 | 资源服务返回 500，记日志，不拖垮服务 |
| 未捕获异常 | `sys.excepthook` / `threading.excepthook` 记录后弹窗 |

原则：**能降级的降级，不能降级的必须留下可读的原因。任何静默失败都算缺陷。**

异常对象里带的是**已经本地化的文案**（抛出那一刻用 `i18n.t` 取好），界面层 `str(exc)` 就能直接显示；同时保留 `key` 与 `params` 供测试断言。代价是切换语言后已抛出的异常文案不跟着变——单机工具可以接受。

## 11. 配置与本地化

### 配置

所有设置在一个文件 `<数据目录>/app.json` 里，参考线边距是它的 `reference` 子对象，移动吸附用的对齐线是 `align` 子对象。

- **原子写入**：临时文件 + `os.replace`，中途崩溃不会留下半个文件。
- **读的时候夹取**：数字越界夹回范围，非数字回退默认，`NaN` 视为非法，布尔接受 `1/true/yes/on`。
- **未知键原样保留**：跨版本共存不会丢用户手写的内容。
- **损坏就报错**：抛 `ConfigError` 并指出文件名，绝不静默重建——静默重建会把用户数据洗掉。
- **旧格式迁移**：早期版本把边距单独放在 `reference.json`（更早是 `reference_line.json`，单位厘米），读取时一次性并进 `app.json` 并删掉旧文件。

| 键 | 范围 |
|---|---|
| `language` | `locales/` 下已有的代码 |
| `theme` | `light` / `dark` |
| `undo_limit` | 10 – 500 |
| `render_dpi_cap` | 96 – 400（`RenderCache` 的渲染上限） |
| `preprocess_threshold` | 0 – 255 |
| `show_guides` / `show_inspector` / `eight_handles` | 布尔 |
| `keybindings` | `{作用域: {命令: 组合键}}` |
| `reference.*_mm` / `align.*_mm` | 0 – 300 |
| `backup_retention_days` | 1 – 3650 |

字段的完整含义与越界行为见 [configuration.md](configuration.md)。

### 本地化

- 文案在 `app/locales/{语言代码}.json`，**文件名就是语言代码**（`zh-CN`、`en-US`）。
- 启动时扫描目录，放进去什么语言就支持什么语言。
- `t("键", 占位符=值)` 查表；缺键回退默认语言，再缺返回键名本身，**绝不抛异常**。
- 语言在界面上的显示名来自语言包自己的 `language.name` 键（必须是文件第一个键，值用该语言自己的文字书写，如 `简体中文 (中国)` / `English (US)`），程序里没有硬编码的名称表。
- 静态文案在 HTML 上用 `data-i18n*` 标记，启动时统一替换；动态文案走 `T()`，键表由 `get_strings()` 一次性下发。

## 12. 测试策略

```
tests/
├─ conftest.py              夹具：临时配置、现场生成 PDF、真实 EditorApi + 资源服务
├─ test_paths.py            路径推导
├─ test_settings.py         夹取、迁移、原子写
├─ test_i18n.py             语言发现与键完整性
├─ test_units.py            pt/mm、页码范围
├─ test_geometry.py         夹取、角/边手柄缩放、切分矩阵
├─ test_document.py         打开、页信息、可编辑图片筛选
├─ test_render.py           涂白、渲染上限、缓存淘汰
├─ test_split.py            切分 / 保留 / 打孔 / 涂白
├─ test_textlayout.py       换行、行高、基线
├─ test_overlay.py          文本框与荧光笔的落盘、读回、回收
├─ test_tablelines.py       表格框线检测、拉直、交叉口
├─ test_undo.py             栈行为、宏、dirty
├─ test_save.py             文字保留、批注保留、长宽比、备份命名与清理、失败回滚
├─ test_editor_api.py       接口层：快照、越界、任务、保存后重定基线
├─ test_asset_server.py     路由、token、缓存头、路径穿越
├─ test_system.py           剪贴板、外部打开、预处理
└─ test_source_hygiene.py   静态守卫
```

约定：

- **不碰真实的 ProgramData / LOCALAPPDATA**：`conftest.py` 在导入 `app` 之前设置三个 `SIXCOIN_*` 环境变量，`temp_config` 夹具再把 `paths` 里的路径改到 `tmp_path`。
- **PDF 现场生成**：`pdf_factory` 造带文字层和若干张彩色块的文档，用完即弃。
- **界面后端跑真的**：`editor` 夹具起真实的 `EditorApi` + `AssetServer`，只是不建窗口，所以接口层的行为（含线程与任务）都被覆盖。
- **断言文案用中文**：`conftest.py` 把语言钉死，测试不受环境影响。
- 静态守卫用 AST 扫描，见第 1 节的表。

跑法：

```bash
uv run pytest
```

## 13. 不能破的约定

1. **坐标一律是 pt，左上原点，y 向下。** 转换点只有 `insert_image` 那一处。
2. **图片按内容寻址存在 `ImageStore` 里**（sha1 → bytes）。撤销只改 `image_id`，不复制像素。
3. **`ImageObject` 同时存 `rect` 与 `src_rect`（以及 `src_page`）。** 少任何一个，「移动一张图」就没法正确落盘。
4. **删除要留墓碑。** 对象可以走，位置必须留下，否则保存后原图复活。
5. **`core` 不导入界面库，也不反向依赖 `ui` / `system`。** 由 AST 测试守。
6. **cwd 只在 `bootstrap.ensure_cwd()` 里钉一次，不写 `print`。** 同样由测试守。
7. **前端只认快照。** 任何「前端自己算一份业务数据」的写法都会让两边的模型分叉。
8. **`closing` 回调里不碰网页。** 要弹框就从工作线程 `evaluate_js`。
9. **保存先写临时文件再替换。** 并且就地保存前必须先关句柄。
10. **新增颜色先加 token。** `static/css/tokens.css` 是唯一的颜色来源，深色模式只覆盖变量，不改布局。
11. **配置里的键必须有人读。** 写进 `DEFAULT_APP` 却没有任何模块消费，就是一条会误导人的假设置。
12. **临时提示只走状态栏。** 新加一种「底部横幅」「右上角气泡」等于再造一套提示语言；要表达进行中就用 `toast(..., { sticky: true, busy: true })`。
13. **覆盖层只能靠内容流首行的标记认亲。** `garbage=4` 会重编号对象，xref 存不住；撤旧时只删标记点名的那一个 XObject。
14. **子集化只在草稿文档里做。** 主文档调一次 `subset_fonts()` 就会把原文档的字体全部重写，等于改了不该改的东西。
15. **文字与荧光笔画进页面内容流，不画成批注。** 批注的外观流各家阅读器支持不一，而且会被 Edge 的批注界面当成「用户的批注」。
