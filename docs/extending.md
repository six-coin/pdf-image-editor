# 扩展指南

本文说明几类常见改动该动哪些文件，以及改完之后必须满足的约定。架构本身见 [architecture.md](architecture.md)。

## 1. 新增一个后端接口

前端要调一个后端还没有的能力时走这条路。以「把当前页导出成图片」为例。

### 1.1 接口方法

`app/ui/web/api.py` 的 `EditorApi` 里加方法，命名用动词开头的 snake_case：

```python
def export_page_image(self, index: int, path: str) -> dict[str, Any]:
    with self._lock:                      # 所有读写文档状态的方法都要加锁
        doc = self._doc
        if doc is None:
            return {"ok": False, "message": i18n.t("error.no_document")}
        ...
    return {"ok": True, "path": path}
```

约定：

| 约定 | 原因 |
|---|---|
| 越界或非法参数不抛异常，返回 `{"ok": False, "message": ...}` | 网页拿到 Python traceback 是最难排查的一类问题 |
| 改了文档状态就返回 `self._snapshot()` | 前端只认快照，不自己拼模型 |
| 只做轻操作；超过 100ms 的活丢 `self._executor` 并返回 `task_id` | js_api 线程阻塞会让界面卡住 |
| 面向用户的文案走 `i18n.t()` | 异常信息也一样 |
| 新方法默认不暴露给资源服务 | 资源服务只读位图与静态文件 |

### 1.2 前端调用

业务代码里不直接写 `window.pywebview.api.xxx`，一律走 `bridge.js` 的 `call()`：

```js
import { call, T, toast } from './bridge.js';

const result = await call('export_page_image', index, path);
if (!result) return;                       // 桥没就绪或调用抛错，call() 已经提示过
if (!result.ok) {
  toast(result.message || T('error.unexpected'), false);
  return;
}
```

- 会改后端状态的动作放进 `actions.js`，再在 `main.js` 的 `ACTIONS` 表里挂上 `data-act`。
- 只是读数据的调用可以直接在用到它的模块里 `call()`。
- 拿到快照后交给 `apply(snapshot)`（`render.js`），不要自己改 `state.data`。

### 1.3 文案

`app/locales/zh-CN.json` 与 `en-US.json` 都要加，键名按 `<域>.<对象>_<属性>`：

```json
"toolbar.export_image": "导出为图片",
"error.image_export_failed": "导出图片失败：{reason}"
```

### 1.4 检查清单

- [ ] 方法在 `EditorApi` 上，且对文档状态的读写都在 `self._lock` 里
- [ ] 非法参数返回 `ok: false` 而不是抛异常
- [ ] 改了状态的方法返回完整快照
- [ ] 前端通过 `call()` 调用，没有直连 `window.pywebview.api`
- [ ] 中英文案都加了，占位符一致
- [ ] `tests/test_editor_api.py` 补一条正常路径 + 一条非法参数

## 2. 新增一种语言

不需要改代码。`app/i18n.py` 启动时扫描 `app/locales/*.json`，文件名就是语言代码。

1. 复制 `app/locales/en-US.json`，重命名为目标代码，例如 `ja-JP.json`；
2. 逐条翻译值，**键名与 `{name}` 占位符保持不变**；
3. 在新语言文件的**第一行**写 `"language.name": "日本語"`——值用这门语言自己的文字，设置里的语言列表显示的就是它；
4. 重启程序，设置里会自动多出这一项。

约定：

- 键集合必须完全相等，`tests/test_i18n.py::test_every_locale_has_the_same_keys` 会拦。
- 占位符集合必须相等，`test_placeholders_match_the_default_language` 会拦。
- 缺键会回退 `zh-CN`，所以可以先把文件放进去再慢慢补翻译；但界面上不会出现裸键。
- 删掉某个 JSON 等于移除该语言，配置里的旧值会自动回落到 `zh-CN`。
- 手册要不要跟着加语言？不加。仓库只提供中英两份使用手册。

## 3. 新增一个设置项

以「页面背景色」为例。

### 3.1 定义与校验

`app/settings.py`：

```python
DEFAULT_APP = {
    ...
    "page_tint": "white",
}
```

在 `_normalize_app` 里夹取，写法参照已有的 `_choice` / `_integer` / `_boolean`：

```python
merged["page_tint"] = _choice(raw.get("page_tint"), DEFAULT_APP["page_tint"], ("white", "sepia"))
```

读取时一律夹取、不信任文件内容；未知键保留。

### 3.2 下发给前端

`app/ui/web/api.py::_snapshot` 里加字段：

```python
"page_tint": self._settings["page_tint"],
```

### 3.3 设置面板

`app/ui/web/static/js/settings.js::renderBody` 里加一个控件，写完立刻落盘：

```js
body.appendChild(
  field(
    'settings.page_tint',
    segmented(
      [
        { value: 'white', label: T('settings.tint_white') },
        { value: 'sepia', label: T('settings.tint_sepia') },
      ],
      data.page_tint,
      (value) => writeSettings({ page_tint: value })
    )
  )
);
```

设置面板没有「保存」和「取消」，每个控件都必须自己 `writeSettings`。

### 3.4 生效

消费这个字段的地方在 `render.js` 或 `app.css` 里。颜色走 CSS 变量，并在 `[data-theme="dark"]` 里给一份深色值。

### 3.5 检查清单

- [ ] `DEFAULT_APP` 有默认值，`_normalize_app` 有夹取
- [ ] `_snapshot` 下发了这个字段
- [ ] 设置面板有控件，且改完立刻 `writeSettings`
- [ ] 深浅两套主题都好看
- [ ] `docs/configuration.md` 的字段表补了一行
- [ ] `tests/test_settings.py` 补一条默认值 + 一条越界

## 4. 新增一个快捷键命令

1. `app/ui/web/static/js/keymap.js`：在 `GLOBAL_DEFS` 或 `SPLIT_DEFS` 里加一行 `[命令名, 默认组合键, 文案键]`；
2. `app/ui/web/static/js/shortcuts.js`：在 `GLOBAL_RUNNERS` 或 `SPLIT_RUNNERS` 里挂上实现；
3. 两个语言文件加文案键（通常复用按钮已有的键，不必新造）；
4. 需要按钮上显示按键提示的，`render.js` 的 `ACTIONS` / `SPLIT_ACTIONS` 表会自动带出来。

约定：同一作用域内组合键不能重复，设置面板会当场拦下；方向键微调不参与键位表。

## 5. 新增一种保存期警告

保存时某张图出了问题不该中断整次保存，而是进 `SaveReport.warnings`。

1. `app/core/save.py`：在对应分支追加

   ```python
   report.warnings.append({"page": index, "code": "color_space_lost", "detail": obj.id})
   ```

2. `app/ui/web/static/js/actions.js`：`WARNING_KEYS` 加一条映射

   ```js
   color_space_lost: 'save.warning_color_space',
   ```

3. 两个语言文件加 `save.warning_color_space`，需要细节时用 `{detail}` 占位符；
4. `docs/readme/zh-CN.md` 与 `en-US.md` 第 9 节的提示表各补一行。

`page` 为 `null` 表示整份文档级别的警告，界面上不会显示页码徽标。

## 6. 修改界面

前端是三个静态文件加一组 ES module，没有构建步骤，改完刷新窗口即可看到效果。

| 文件 | 内容 |
|---|---|
| `index.html` | 结构与静态文案（`data-i18n*` 标记） |
| `css/tokens.css` | 颜色、圆角、缓动；深色只在 `[data-theme="dark"]` 里覆盖变量 |
| `css/base.css` | 重置、字体、通用组件（按钮、输入框、弹窗、开关） |
| `css/app.css` | 应用壳、顶栏、画布、属性栏、分割条 |
| `js/*.js` | 每个文件一件事，见 architecture.md 第 8 节 |

约定：

- 不维护业务数据。状态只来自快照，前端只保留缩放、已加载页、手势中这类纯视图状态。
- 新增静态文案用 `data-i18n` / `data-i18n-title` / `data-i18n-placeholder` / `data-i18n-aria`，不要写死中文。
- **弹窗的标题与按钮**要能被切语言刷新：`openModal` 传 `titleKey`，动作传 `action.i18n`。它们会被标上 `data-i18n`，由 `applyStrings()` 统一替换；只传翻译好的 `label` 而不给键，按钮会永远停在打开时的语言。
- **用 `T()` 现算的文案**（属性栏按钮、页码浮标、分割条提示、页面角标）由 `render.js::refreshTexts()` 负责重建。新增同类文案时把它加进这个函数，否则切一次语言就落后一拍，切两次看起来就是「和当前语言相反」。
- 新增颜色先加 token，再在深色主题里给值，否则深色下会看不清。
- 所有后端调用走 `call()`；所有快照落地走 `apply()`。
- 手势期间（`state.view.gesture`）不要触发重绘，否则正在拖的节点会被换掉。

## 7. 代码约定

| 约定 | 说明 |
|---|---|
| 注释与 docstring 用中文 | 包括标点；变量名、函数名保持英文 |
| 注释只写「现在为什么这样」 | 不写「从 X 改成 Y」，版本历史归 git |
| 不调用 `os.chdir` | 需要工作目录就传参数 |
| 内部路径从 `app/paths.py` 取 | 不要在模块里自己拼 `Path("config")` |
| 面向用户的文本走 `i18n.t()` | 异常信息也一样 |
| 捕获异常要有具体理由 | 说明为什么这里能吞、吞掉之后用户看到什么 |
| `core` 不导入界面库，也不反向依赖 `ui` / `system` | 由 `tests/test_source_hygiene.py` 守 |

提交前跑：

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

三项全绿才提交。改了界面再手工冒烟一遍，自动化测试覆盖不到视觉。
