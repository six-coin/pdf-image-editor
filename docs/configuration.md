# 配置与数据格式

程序只有一个配置文件 `config/app.json`，UTF-8 编码的 JSON。写入使用「临时文件 + `os.replace`」的原子替换，中途崩溃不会留下写了一半的文件。

首次启动时若文件不存在，会自动生成一份可用的默认内容。手改坏了不会静默重建，而是抛 `ConfigError`、弹窗指出文件名并退出——静默重建会把用户数据洗掉。

## 1. `app.json`

```json
{
    "language": "zh-CN",
    "theme": "light",
    "undo_limit": 100,
    "render_dpi_cap": 300,
    "preprocess_threshold": 235,
    "show_guides": true,
    "show_inspector": true,
    "eight_handles": true,
    "keybindings": {
        "global": { "save": "Ctrl+S" },
        "split": { "split_keep": "1" }
    },
    "reference": {
        "left_mm": 10.0,
        "top_mm": 10.0,
        "right_mm": 50.0,
        "bottom_mm": 10.0
    }
}
```

| 字段 | 类型 | 默认 | 取值与行为 |
|---|---|---|---|
| `language` | 字符串 | `"zh-CN"` | `app/locales` 下已有的语言代码；其他值回退 `zh-CN` |
| `theme` | 字符串 | `"light"` | `light` / `dark`；其他值回退 `light` |
| `undo_limit` | 整数 | `100` | 10–500，越界夹取；非数字回退 100 |
| `render_dpi_cap` | 整数 | `300` | 96–400，越界夹取；页面位图的渲染上限，调低省内存但放大后发虚 |
| `preprocess_threshold` | 整数 | `235` | 0–255，越界夹取；黑白化时亮于该值的像素压成纯白 |
| `show_guides` | 布尔 | `true` | 画布上的页边距参考线 |
| `show_inspector` | 布尔 | `true` | 右侧属性栏是否展开 |
| `eight_handles` | 布尔 | `true` | 选中图片时显示八个手柄（四角 + 四边中点）；关掉只留四角 |
| `keybindings` | 对象 | `{}` | 见 1.1 |
| `reference.left_mm` 等 | 数字 | `10 / 10 / 50 / 10` | 0–300，越界夹取；参考线四边边距（毫米） |

说明：

- 布尔字段除 `true` / `false` 外也接受 `1` / `0`、`"true"` / `"yes"` / `"on"`，手改文件时不必纠结写法。
- `NaN` 视为非法数字，回退默认值。
- **未知键原样保留**：跨版本共存时，旧版本写的字段不会在保存时被丢掉。
- `keybindings` 为空对象表示「全部用前端内置的默认键位」，用户改过才会写进来。

### 1.1 `keybindings`

两层结构：`{作用域: {命令: 组合键}}`。

| 作用域 | 包含 |
|---|---|
| `global` | 打开、保存、另存为、导出、撤销、重做、删除、全选（当前页）、粘贴、缩放、切分、置顶/置底、外部编辑、设置、属性栏开关 |
| `split` | 仅保留此格、提取此格、按格切分、撤销上一刀、退出分割 |

- 组合键形如 `Ctrl+Shift+S`、`E`、`Delete`，修饰键顺序固定 `Ctrl+Alt+Shift+Win`。
- 只接受非空字符串；其他类型（数字、`null`、纯空格）整条丢弃，回落到默认键位。
- 组合键由前端用 `event.code` 归一化，所以 `Ctrl+Shift+S` 与 `Ctrl+S` 不会因为 Shift 改变字符而混淆。
- 同一作用域里重复的组合键在设置面板当场拦下，不会写进文件。

## 2. 旧格式迁移

早期版本把参考线边距放在单独的文件里，读取时一次性并入 `app.json` 并删掉旧文件：

| 旧文件 | 旧键 | 换算 |
|---|---|---|
| `config/reference.json` | `left_mm` 等 | 原样 |
| `config/reference_line.json` | `left_cm` 等 | 厘米 × 10 → 毫米 |

删除失败不影响使用，下次启动会再试一次。`save_mode` 是早期版本的单选保存方式，读到后直接丢弃。

## 3. 校验时机

| 时机 | 检查内容 |
|---|---|
| 读取 | 顶层必须是对象；语言与主题必须在允许集合里；数字夹取范围；键位表过滤非法项 |
| 保存前 | 先归一化（夹取、过滤、补默认），再原子写入 |
| 启动 | `EditorApi()` 构造时读一次，损坏就在这里抛 `ConfigError` |

## 4. 语言包

`app/locales/{语言代码}.json` 是扁平的键值表，**文件名就是语言代码**：

```json
{
  "app.title": "PDF 图像编辑器",
  "page.indicator": "第 {current} 页 / 共 {total} 页"
}
```

- 键名点分小写，形如 `<域>.<对象>_<属性>`：`toolbar.save`、`save.warning_page`、`error.pdf_open`。
- `{name}` 形式的占位符由 `i18n.t("键", name=值)` 填充；占位符对不上时原样返回模板，不抛异常。
- 其他语言缺键时回退 `zh-CN`；再缺返回键名本身，界面不会崩，但会露出裸键——所以 `tests/test_i18n.py` 强制两份语言的键集合完全相等。
- 语言在设置里的显示名来自语言包自己的 `language.name` 键（文件第一个键，用该语言自己的文字书写，如 `简体中文 (中国)` / `English (US)`），程序里没有硬编码的名称表。
- 前端拿到的是**合并后的整张表**（默认语言打底 + 当前语言覆盖），因为前端没有回退逻辑。

新增一种语言的步骤见 [extending.md](extending.md)。

## 5. 日志

`logs/pdf_image_editor_*.log`，每次启动新建一个，文件名带启动时间。

- 单文件超过 5 MB 轮转，保留 14 天。
- 格式：`[级别] [YYYY-MM-DD HH:MM:SS] 消息`。
- `diagnose=False`：不把局部变量写进日志，避免把路径、密钥一类内容带出去。
- 标准库 `logging`（`http.server`、PyMuPDF 等）的输出被接到 loguru，`pythonw` 下不会丢。
- 未捕获异常由 `sys.excepthook` / `threading.excepthook` 记录后弹原生窗口，窗口里给出日志目录。

日志路径永远是绝对路径，由 `app/paths.py::LOG_DIR` 决定。

## 6. 运行期目录

| 目录 | 内容 | 是否进版本库 |
|---|---|---|
| `config/` | `app.json` | 否 |
| `logs/` | 每次启动一个日志文件 | 否 |
| `temp/` | 外部编辑的临时目录，启动时清理一天前的残留 | 否 |
| `pdfs/` | 打开对话框的默认目录，不存在会自动创建 | 否 |

删除以上任意目录后重启即可重新生成，不会影响程序本身。
