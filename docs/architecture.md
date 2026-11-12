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
| 全项目不调用 `os.chdir` | 工作目录是进程级全局状态，被所有线程共享 | `test_no_chdir_anywhere` |
| 所有内部路径由 `__file__` 推导 | 从任何目录、任何快捷方式启动行为一致 | `app/paths.py` + 代码评审 |
| `core` 不导入界面库，也不反向依赖 `ui` / `system` | 核心逻辑要能被纯 pytest 覆盖 | `test_core_has_no_ui_imports`、`test_core_does_not_reach_up` |
| 全项目不用 `print` | `.pyw` 进程没有控制台，输出等于丢失 | `test_no_print_anywhere` |
| 入口文件 < 30 行 | 装配集中在一处 | `test_entry_is_thin` |
| 每个模块都要有 docstring | 说明它负责什么、不负责什么 | `test_every_module_has_a_docstring` |

这些不是风格偏好，是硬性的：工作目录是进程级全局状态，被所有线程共享；一旦切换，别的线程写相对路径就会落到别处，日志和配置会随机出现在目标文件夹里。

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
│  ├─ document.py             PDF 句柄、页信息、可编辑图片
│  ├─ render.py               页面光栅化 + LRU 缓存
│  ├─ split.py                切分与打孔（纯函数）
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

`pymupdf` 要求 **2.x**：1.x 有已知安全问题，且 2.x 把 `keep_proportion` 的行为统一到了所有图片格式（见 6.8）。2.1 会带入 `numpy` / `onnxruntime` 等依赖，本项目不使用它们，只是上游的硬依赖。

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
| `objects` | 所有 `ImageObject` |
| `selection` | 选中的 id 列表 |
| `removed` | 墓碑表：`{页号: [被删掉的原图位置]}` |

**墓碑表**是保存正确性的关键：对象删了，但它在 PDF 里还占着位置，不记下来就擦不掉，保存完它又回来了。

`upsert` 按 id 覆盖（幂等，重复调用结果相同），`replace_all` 整份替换，`renormalize(page)` 把某页的 z 重排成 10、11、12…，`drop` 同时清理选择集。

### 4.6 z 序

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
| `core.document` | 打开 / 关闭、页信息、抽取可编辑图片 | 不渲染、不保存 |
| `core.render` | 页面光栅化 + 涂白 + LRU 缓存 | 不决定显示在哪一页 |
| `core.split` | 四个纯函数：切分、保留、打孔、像素裁切 | 不碰撤销栈 |
| `core.undo` | 命令栈、宏、dirty 判定 | 不知道命令的业务含义 |
| `core.save` | redaction + 重插 + 原子落盘 + 校验 | 不决定保存到哪 |
| `system.asset_server` | 把位图、缩略图、静态文件喂给 WebView2 | 不是业务服务端 |
| `ui.web.api` | 每个用户意图一个方法，返回快照；加锁、起任务 | 不拼 HTML |
| `ui.web.static` | 渲染与交互，状态全部来自快照 | 不维护业务数据 |

## 6. 关键流程

### 6.1 启动装配

```
logging_setup.setup("pdf_image_editor")
  → EditorApi()                     读配置；配置损坏在这里就抛
  → AssetServer(api, store, WEB_DIR).start()
  → i18n.set_language(config["language"])
  → webview.create_window(..., js_api=api, background_color=主题底色)
  → window.events.closing += 关闭拦截
  → webview.start()
  → 退出时 server.stop() + api.shutdown()
```

窗口尺寸取屏幕的 85%，最小 960×640。`background_color` 必须和页面的 `--bg` 一致，否则深色模式下首帧会闪一下白。

### 6.2 打开文档

```
前端 open_path(path)
  → 有未保存修改且没 force：直接返回 {reason: "dirty"}
  → generation += 1，建 task，丢进线程池
后台线程 _open_worker
  → PdfDocument.open()，逐页读 pt 尺寸
  → 回到锁内：代次没变才替换 _doc / RenderCache / DocumentState / UndoStack
  → 清空已装载页集合
前端轮询 poll_task，ready 后刷新快照
```

代次号（`generation`）解决「连续打开两个文件，先发的后到」：晚到的结果直接丢弃并关闭自己的句柄。

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

格子一律用 `(row, col)` 显式指定，行列号是**去重之后**的真实网格坐标——不存在「第 4 格就是中心」这种硬编码索引。

像素级细节：

- 页内矩形按比例换算成原图像素矩形，再逐行拷贝裁切（不依赖版本相关的裁剪 API）；
- 洞是直接挖在原图像素上的，不叠白色矩形——叠层在缩放时会被插值成半透明；
- 切分线是纯视图状态，按落笔顺序存在前端数组里，撤销就是弹最后一条。

### 6.7 撤销栈

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

### 6.8 保存

```
api.save_document(path?)
  → 只读文件提前拦下
  → doc.close()（Windows 上 os.replace 覆盖不了仍被打开的文件）
  → core.save.save(src, dst, state, store)
       → 逐页：摘 /Annots → add_redact_annot(src_rect) → apply_redactions
                → 挂回 /Annots → 按 z 插入当前图片
       → doc.save(临时文件, garbage=4, deflate=True)
       → 重新打开校验页数
       → 就地保存且目标已存在时留一份 .bak.pdf
       → os.replace(临时文件, 目标)
  → 成功：以新文件为基线；失败：把句柄接回去，编辑不丢
```

`apply_redactions` 的参数是刻意的：`images=REMOVE` 只摘图，`graphics=LINE_ART_NONE`、`text=TEXT_NONE` 保证文字与矢量不动。

`insert_image` 也必须显式写 `keep_proportion=False`。默认值 `True` 会按图片原始比例把图居中塞进目标矩形，中心与短边不变，看起来就是「用户调过的长宽比被还原了」。PyMuPDF 2.x 起这条对所有格式一致生效（1.x 只对 JPEG 生效，PNG 重新编码时会被忽略），所以样本里必须带上 JPEG 才能覆盖到。

单页失败不拖累其他页，只记一条警告，最后汇总成一份报告（见使用手册第 9 节）。

### 6.9 保存后的基线重建

保存完不能整份重建——那样界面会闪一下，撤销栈也会清空。所以先试「就地重定基线」：

1. 重新打开新文件，逐页抽出可编辑图片；
2. 和模型里该页的对象按 z 排序后**数量比对**；
3. 对得上：把每张图的 `src_xref` / `src_rect` / `image_id` 更新成新文件里的值，清空墓碑表，保留对象、撤销栈、DOM；
4. 对不上（切分粒度不同、有图被跳过）：退回完整重建，`generation += 1` 让前端重新加载页面。

墓碑表必须清空：被删的图已经在文件里彻底消失，留着的话下次保存会照着旧坐标去擦，可能擦掉刚放进去的新图。

### 6.10 导出页

读的是**磁盘上的文件**，不是内存模型，所以有未保存修改时直接拒绝。

页码解析在后端（`parse_page_range`），支持 `1-3,5,7-9`、中文逗号、空格。非法片段不静默丢弃，返回 `(错误码, 原始片段)` 由界面列出。

### 6.11 外部编辑

```
edit_external(id)   → 图片写到 temp/edit-<随机>/image.png → os.startfile 打开
用户在外部程序里改完、保存、关闭
前端弹确认框
replace_image(id, path) → 校验能解析成图片 → push ImageReplaced → 删临时目录
```

临时目录只允许删 `TEMP_DIR` 下自己建的那一层；启动时还会清理一天前的残留。

### 6.12 预处理

把页内每张图转灰度、把亮于阈值的像素压成纯白（扫描件去底灰），结果另存为新文件。

入口在顶栏的「预处理」：先弹说明框，里面两条路——「处理当前打开的文档」（要求没有未保存修改，因为处理的是磁盘版本）或「处理其他文档」（另选文件）；确认后再选目标文件。跑完会问要不要立刻打开结果，打开走的是和「打开」同一条路径，所以未保存修改照样会被拦下。

不用 numpy / Pillow（numpy 只是 PyMuPDF 2.x 的传递依赖，本项目不直接调用）：`bytes.translate` 是 C 实现，逐字节查表比逐像素循环快两个数量级；灰度转换交给 `pymupdf.Pixmap(csGRAY, pix)`。带 alpha 的图跳过——压成二值会把透明区域变成黑块。

落盘同样是「临时文件 + `os.replace`」，目标与源相同时直接拒绝：源文件正被自己打开着，写回去只会得到半个坏文件。任务在线程池里跑，通过 `progress` 回调更新任务进度。

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
  "objects": [{ "id": "p0-x12-0", "page": 0, "x": 100, "y": 100, "w": 200, "h": 150,
                "z": 10, "rotation": 0, "image": "sha1…", "thumb": "…", "src": "…" }],
  "selection": ["p0-x12-0"],
  "history": { "can_undo": true, "can_redo": false, "label": "edit.move" },
  "language": "zh-CN", "languages": ["zh-CN", "en-US"],
  "theme": "light", "show_guides": true, "show_inspector": true, "eight_handles": true,
  "keybindings": {}, "reference": { "left_mm": 10, … }, "undo_limit": 100
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
| 切分 | `split_object` `keep_cell` `punch_cell` |
| 保存导出 | `save_document` `browse_save` `export_pages` |
| 剪贴板 / 外部 | `paste_image` `edit_external` `replace_image` |
| 其它 | `preprocess_pdf` `update_reference` `update_settings` `set_language` `reset_settings` |
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

零构建，原生 ES module，15 个文件各管一件事：

| 文件 | 职责 |
|---|---|
| `main.js` | 装配、动作分发表、`window.host` |
| `bridge.js` | 桥接封装：`call()`、`T()`、`toast()` |
| `state.js` | 纯视图状态（缩放、DPI、主题、手势中） |
| `sync.js` | **唯一**的快照通道，合并短时间内的多次刷新 |
| `render.js` | 快照 → DOM，含属性栏、多选组框与语言替换 |
| `canvas.js` | 页面可见性、位图加载、缩放与滚动 |
| `interact.js` | 指针手势：选中、拖动、八手柄缩放、组缩放、框选、平移 |
| `split.js` | 分割模式：切线、格子高亮、执行 |
| `guides.js` | 参考线绘制 |
| `settings.js` | 设置弹窗 |
| `modal.js` | 通用弹窗与确认框 |
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

- 拖动只改 `left/top`，不重排布局；松手一次性提交。
- 移动阈值 3px，最小尺寸 4pt；组缩放还要保证组里最小的那张不低于 4pt、整组不出页面。
- 缩放的锚点是手柄的**对边**。角手柄命名是 `tl/tr/bl/br`、边手柄是 `n/s/w/e`，判断方向必须两套都认（`l/r` 与 `w`、`t/b` 与 `n`），否则 `tl` 会被当成往右下长。
- 缩放结果先按锚点到页边的距离算出最大倍率再夹取（`clampScale`），不能留给后端：`clamp_rect_to_page` 只按边裁，长宽比会被裁坏。
- 八个手柄是纯 CSS 开关（`#app.eight-handles`），关掉时边手柄 `display:none`，不用重建 DOM。
- 多选限同一页：组框要有共同坐标系；`api.select` 也会截断跨页的 id。
- 手势期间后端快照一律不落地（见 6.4），组框在非组手势期间临时隐藏。

保存期间另有一层锁：`state.view.busy` 为真时指针与快捷键都不响应，底部显示「正在保存」横幅。后端在保存过程中已经把文档句柄放掉，此时任何编辑都会落空。

### 8.5 键位系统

两套作用域：`global` 与 `split`。分割模式下只查 `split` 表，全局快捷键暂停，所以两边可以绑同一个键。

- 组合键用 `event.code` 归一化（`KeyS` → `S`，`Digit1` → `1`），避开 Shift 改字符与键盘布局差异；
- 只按修饰键不触发任何动作；
- 同一作用域里重复的组合键由 `findConflicts` 检出，设置面板当场拦下；
- 方向键微调不参与自定义键位，避免与全局表互相干扰。

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

所有设置在一个文件 `config/app.json` 里，参考线边距是它的 `reference` 子对象。

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
| `reference.*_mm` | 0 – 300 |

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
├─ test_split.py            切分 / 保留 / 打孔
├─ test_undo.py             栈行为、宏、dirty
├─ test_save.py             文字保留、批注保留、长宽比、备份、失败回滚
├─ test_editor_api.py       接口层：快照、越界、任务、保存后重定基线
├─ test_asset_server.py     路由、token、缓存头、路径穿越
├─ test_system.py           剪贴板、外部打开、预处理
└─ test_source_hygiene.py   静态守卫
```

约定：

- **不碰真实的 `config/` 与 `logs/`**：`temp_config` 夹具用 `monkeypatch` 把 `paths` 里的路径改到 `tmp_path`。
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
6. **不调用 `os.chdir`，不写 `print`。** 同样由测试守。
7. **前端只认快照。** 任何「前端自己算一份业务数据」的写法都会让两边的模型分叉。
8. **`closing` 回调里不碰网页。** 要弹框就从工作线程 `evaluate_js`。
9. **保存先写临时文件再替换。** 并且就地保存前必须先关句柄。
10. **新增颜色先加 token。** `static/css/tokens.css` 是唯一的颜色来源，深色模式只覆盖变量，不改布局。
11. **配置里的键必须有人读。** 写进 `DEFAULT_APP` 却没有任何模块消费，就是一条会误导人的假设置。
