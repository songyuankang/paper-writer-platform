# DOCX 目录缺失原因分析

> 生成时间：2026-08-11 ｜ 只分析，不修改代码
> 适用分支：`agent/template-management-ui`（当前工作区）

---

## 结论速览

**目录缺失的根因：主生成流程走的是「旧构建器默认模式」，该模式只把标题渲染成黑体加粗的普通段落——不插入 Word 目录域（TOC field）、不设置大纲级别（outlineLvl）、不用 Heading 样式。**

而项目里**唯一真正能插入 Word 自动目录域的渲染器（TemplateRenderer）**，只在「正文编辑器导出且用户显式选择了模板」时才会被调用。两条链路没有交汇，导致主流程导出的 `论文.docx` 完全没有目录。

---

## A. 当前导出流程（4 条链路）

### 1. 主生成流程（用户日常生成论文的路径）⭐

```
generate 接口 → paper_service.generate（app/services/paper_service.py:171）
  → formatter_service.format_paper(task_id, task_dir, req, spec, charts=…)
      ↑ 没有传 template_id / template_path（两个参数都是 None）
  → app/formatter/service.py format_paper 判定 template_id is None
  → docx_builder.build_docx(task_dir, spec, meta, template_path=None)
  → 引擎脚本 paper_writer_scripts/build_docx.py 的 build_default()（默认模式）
  → 输出 task_dir/论文.docx（无目录）
```

**下载**：历史记录/预览页下载的就是这个 `论文.docx`。

### 2. 正文编辑器导出（BodyEditorUniPaper）

```
draft.py POST /{task_id}/export（app/api/draft.py:167）
  → draft/service.py:565 format_paper(…, template_path=…, template_id=…)
  → 用户选了模板 → template_id 非空 → v2 render_with_template（TemplateRenderer）
      ✅ 有真实 TOC 域
  → 用户没选模板 → 同链路 1（无目录）
```

### 3. 格式处理页（Format / format_task）

```
format_task.py:118 → docx_builder.build_docx(…, template_path=旧版style.docx, toc_update=…)
  → 有旧模板（v1 上传的 style.docx）→ 引擎 build_with_template()（模板模式）
      ⚠️ 目录仅当「上传的 docx 本身含 TOC 域」时保留
  → 无模板 → 默认模式（无目录）
```

### 4. 历史/预览下载

直接返回任务目录下的 `论文.docx`——即链路 1 的产物。

---

## B. 目录缺失原因

### 根因 1：默认模式不生成任何目录

`paper_writer_scripts/build_docx.py::build_default()`（默认模式）里标题渲染：

```python
def add_heading(doc, text, level):          # build_docx.py:238
    conf = {1: (16, 12, 12), 2: (14, 6, 6), 3: (12, 6, 6)}…
    add_para(doc, text, cn="黑体", size=conf[0], bold=True, align=LEFT, …)
```

- 标题 = **黑体加粗普通段落**（16/14/12pt）
- ❌ 不插入 Word TOC 域（无 `w:fldSimple` / `w:instrText TOC`）
- ❌ 不设置 `w:outlineLvl`（Word 目录无法收集）
- ❌ 不用 Word Heading 1/2/3 内置样式

### 根因 2：`mark_toc_update` 是"标记更新"，不是"插入目录"

```python
# app/formatter/toc.py
def mark_toc_update(doc):
    settings… set w:updateFields = true   # 仅让 Word 打开时刷新域
```

`docx_builder.py:27` 和模板模式确实都调了 `mark_toc_update`，但**文档里没有 TOC 域可供刷新**——设置了个寂寞。全项目搜 `TOC \o` 域插入，只有 `renderer.py` 一处（见 C）。

### 根因 3：主流程永远不触发 v2 渲染器

`format_paper` 的 docstring 明示了分叉（`app/formatter/service.py:67-107`）：

```python
# template_id 非 None → TemplateRenderer 新链路（有目录）
if template_id is not None:
    render_service.render_with_template(template_id, …)   # ✅ TOC 域
# None → 旧构建器默认模式（无目录）
if not rendered:
    docx_builder.build_docx(task_dir, spec, meta, template_path=None)
```

而 `paper_service.py:171` 调用时**两个参数都没传** → 永远走旧链路。

---

## C. 已存在的相关能力（系统其实是齐的）

### 1. 论文 spec 有完整层级 ✅

`sections` 数组用 `type` 字段表达层级（生成器 `pipeline_spec_from_content`、`_sections_from_outline` 均产出）：

```json
{ "sections": [
  { "type": "h1", "text": "第一章 绪论" },
  { "type": "h2", "text": "1.1 研究背景" },
  { "type": "h3", "text": "1.1.1 国内外现状" },
  { "type": "p",  "text": "正文段落" }
]}
```

（层级在 `type` 字段，不是独立 `level` 字段；标题文字已带编号。）

### 2. v2 TemplateRenderer 具备完整 TOC 能力 ✅

`app/formatter/template/renderer.py`：

| 能力 | 实现 |
|---|---|
| 真实 Word 目录域 | `_render_toc()` 插入 `w:instrText ' TOC \o "1-3" \h \z \u '`（renderer.py:504） |
| 标题大纲级别 | `_set_outline_level()` 写 `w:outlineLvl 0/1/2`（heading 渲染时传入 level） |
| 打开自动更新 | `_mark_toc_update()` 设 `w:updateFields=true` |
| 模板标题样式落地 | `_render_heading()` → `_resolve_block("headingN")` → `_apply_style()` 应用模板 headingN block 的字体/字号/间距 |

### 3. 模板 JSON 已含全部所需字段 ✅

内置模板（`templates/basic/*.json`）：
- `blocks.toc`（kind=toc，settings.include_page_numbers + title/h1/h2/h3 样式）
- `blocks.heading1/2/3/4`（kind=heading，level 1-4，styles.self）
- `numbering`（h1..h4 编号模式，可选）

### 4. 旧引擎模板模式部分能力 ✅

`build_with_template()`：标题尝试应用 docx 内置 Heading 样式（`p.style = doc.styles["Heading {level}"]`，build_docx.py:292）、`find_anchors()` 保留模板原有 TOC 域——**但仅当上传的模板 docx 自带目录时才有效**。

### 5. 格式处理页有 TOC 检测 ✅

`format_task.py:179-180` 会检测文档是否含 TOC 域（用于格式报告），但只检测不生成。

---

## D. 修改方案建议（只给方案，不执行）

| 方案 | 做法 | 效果 | 代价/风险 |
|---|---|---|---|
| **1. 主流程默认走 v2 渲染器（推荐）** | `paper_service.py:171` 给 `format_paper` 传默认模板 id（如 `basic-course-paper`，或模板系统 `default_id`），让所有生成任务默认走 `render_with_template` | 主流程 docx 带真实 TOC 域 + 模板化样式 | 低：`format_paper` 已有「新链路失败自动回退旧构建器」的兜底（service.py:101-106）；行为变化是"更好看"，可先对比产出 |
| **2. 旧构建器默认模式补 TOC 域** | 在 `build_docx.py::build_default` 首个标题前插入 `TOC \o "1-3" \h \z \u` 域；`add_heading` 里补 `set_outline_level(p, level-1)`（或改用 Heading 样式） | 不改调用方，最小改动补目录 | 中：引擎脚本要动两处；默认样式链仍是硬编码 |
| **3. 默认模式标题改 Word Heading 样式** | `setup_document` 定义内置 Heading 1/2/3 样式并应用 | 目录 + 导航窗格 + 大纲视图都正常 | 中：需要处理样式定义；`\o` 切换依赖 outline level，仍需配 `\o` TOC 域 |
| **4. 格式处理页统一走 v2 链路** | `format_task.py:118` 改用 `render_service.render_with_template`（把 v1 `template_path` 映射为 v2 `template_id`） | 格式处理也带目录 | 中：涉及 v1→v2 模板映射 |

**共性说明**：`mark_toc_update`（`w:updateFields`）已全链路生效，Word 打开文档时会自动弹出"更新域"并生成目录；上述任一方案落地后，**用户打开 docx 即见目录**（无需手动操作）。若要"打开前就显示静态目录文字"，需额外在导出时预渲染目录（复杂度高，不建议，Word 域方案是标准做法）。

---

## 附：关键文件定位

| 环节 | 文件 |
|---|---|
| 主流程调用 | `app/services/paper_service.py:171` |
| 新旧链路分叉 | `app/formatter/service.py:67-107`（`format_paper`） |
| 旧构建器入口 | `app/formatter/docx_builder.py:13`（`build_docx`） |
| 默认模式（无目录） | `paper_writer_scripts/build_docx.py:238`（`add_heading`）、`:242`（`build_default`） |
| 模板模式（依赖上传 docx） | `paper_writer_scripts/build_docx.py:287`（`add_heading_tmpl`）、`:440`（`build_with_template`） |
| v2 渲染器（唯一插 TOC 域） | `app/formatter/template/renderer.py:502`（`_render_toc`） |
| 仅标记更新 | `app/formatter/toc.py:6`（`mark_toc_update`） |
| 格式处理页 | `app/formatter/format_task.py:118`、`:179`（TOC 检测） |
| 正文编辑器导出 | `app/api/draft.py:167`、`app/draft/service.py:565` |
