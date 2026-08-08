# paper-writer-api

把 paper-writer Skill 封装成独立 API 服务的接口层，方便后续接入网页前端。

职责划分：

- **paper-writer（Skill）= 核心生成引擎**：内容排版、模板解析、图表、参考文献脚本
- **paper-writer-api（本项目）= 接口层**：任务队列、上传校验、进度状态、结果下载，通过模块导入方式调用引擎（不复制引擎代码）

> 第一阶段说明：当前正文内容由 `app/services/content_generator.py` 生成**示例占位内容**（明确标注“示例内容/示例文献”），用于打通整条 API 流水线。正式使用请在该文件中接入 LLM 内容生成，或由前端提供正文。

## 目录结构

```text
paper-writer-api/
├── app/
│   ├── main.py                 # FastAPI 入口（日志、任务管理器、路由）
│   ├── config.py               # 配置（环境变量覆盖）
│   ├── api/
│   │   └── generate.py         # POST /api/generate、GET /api/status、/api/download、/api/health
│   ├── services/
│   │   ├── paper_service.py    # 编排：模板解析→内容→图表→docx→检查→格式意见
│   │   ├── content_generator.py# 示例内容生成（预留 LLM 接入点）
│   │   └── task_manager.py     # 内存+磁盘元数据的任务队列
│   └── models/                 # Pydantic 请求/响应模型
├── uploads/                    # 用户上传的学校模板（运行时创建）
├── outputs/                    # 任务结果（运行时创建，每任务一个目录）
├── logs/                       # 运行日志（运行时创建）
├── requirements.txt
├── Dockerfile
└── README.md
```

## 安装

要求 Python 3.11+。

```bash
cd paper-writer-api
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

引擎脚本目录默认读取 `~/.codex/skills/paper-writer/scripts`（本机默认位置）；如果 paper-writer skill 在其他位置，设置环境变量：

```bash
set PAPER_WRITER_SCRIPTS_DIR=D:\path\to\paper-writer\scripts
```

## 启动

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

或：

```bash
python -m app.main
```

交互式接口文档：http://127.0.0.1:8000/docs

## API 使用示例

### 1. 提交生成任务

`paper_type` 支持：课程论文 / 毕业论文 / 期刊论文 / 实证研究 / 文献综述 / 开题报告。

```bash
curl -X POST http://127.0.0.1:8000/api/generate \
  -F "title=数字化转型对企业绩效的影响研究" \
  -F "major=工商管理" \
  -F "paper_type=课程论文" \
  -F "word_count=3000" \
  -F "chart_enabled=true" \
  -F "reference_style=gb7714" \
  -F "school_template=@school_template.docx"
```

### 1.0 参考资料上传（可选）

`POST /api/generate` 支持随表单上传多个参考资料文件（对应网页端"资料上传"）：

| 表单字段 | 类型 | 说明 |
| --- | --- | --- |
| `files` | file[] | 资料文件，最多 5 个、每个 ≤5MB；支持 txt/docx/xls/xlsx/jpg/jpeg/png |
| `material_kinds` | string | JSON 数组，与 files 一一对应：`["开题报告","仿写论文","其他资料"]` |

文件保存到 `outputs/<task_id>/materials/<kind>/`；txt/docx/xls/xlsx 会提取文本
（每文件 ≤6000 字、合计 ≤30000 字），以【参考资料】形式合并进
`special_requirements` 供 AI 摘要/正文/结论/参考文献生成参考；图片仅保存不解析。

```bash
curl -X POST http://127.0.0.1:8000/api/generate \
  -F "title=..." -F "major=..." -F "paper_type=开题报告" \
  -F "material_kinds=[\"开题报告\",\"其他资料\"]" \
  -F "files=@开题报告.docx" \
  -F "files=@实验数据.xlsx"
```

响应：

```json
{"task_id": "3f9c...", "status": "queued"}
```

### 1.1 按大纲生成（generation_mode=outline）

`POST /api/generate` 新增可选参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `generation_mode` | string | `auto` | `auto`=自动生成论文；`outline`=按用户大纲生成 |
| `outline` | string | 无 | 大纲模式必填，多行章节文本（如 `第一章 绪论`、`1.1 研究背景`） |
| `special_requirements` | string/null | 无 | 特殊要求（高级可选）：如“第三章增加实验分析”“增加案例分析”等；空字符串或 null 均允许，不填写走默认生成流程 |

兼容旧请求：不传 `generation_mode` 时默认 `auto`，行为与之前完全一致。

```bash
curl -X POST http://127.0.0.1:8000/api/generate \
  -F "title=数字化转型对企业绩效的影响研究" \
  -F "major=工商管理" \
  -F "paper_type=毕业论文" \
  -F "word_count=5000" \
  -F "generation_mode=outline" \
  -F "outline=第一章 绪论
1.1 研究背景
1.2 研究意义

第二章 相关理论
2.1 理论基础"
```

大纲模式下服务端会解析章节（`第X章`/`1.1`/`1.1.1`/`1、` 等格式），按章节生成正文并合并到 docx。

特殊要求说明：`special_requirements` 为非必填。填写后生成流程会在摘要与各章节内容中
体现该要求（如“特别考虑了特殊要求：xxx”）；未填写（null 或空字符串）时跳过处理，
使用默认生成流程，不会创建空任务。

### 1.2 生成大纲（POST /api/outline/generate）

根据标题、专业、论文类型、字数生成论文大纲（AI 生成大纲后由用户确认）：

```bash
curl -X POST http://127.0.0.1:8000/api/outline/generate \
  -H "Content-Type: application/json" \
  -d '{"title":"人工智能对教育公平的影响分析","major":"教育学","paper_type":"毕业论文","word_count":5000}'
```

响应：

```json
{
  "outline": "第一章 绪论\n1.1 研究背景\n1.2 研究意义\n\n第二章 文献综述与理论基础\n...",
  "chapters": [
    {"title": "第一章 绪论", "level": 1, "word_count": 938},
    {"title": "1.1 研究背景", "level": 2, "word_count": 0},
    {"title": "1.2 研究意义", "level": 2, "word_count": 0}
  ]
}
```

`outline` 为可直接回填到 `/api/generate` 的大纲文本；`chapters` 含章节层级与一级章节的预计字数分配。用户确认后以 `generation_mode=outline` + `outline` 提交即可生成论文。

### 1.3 图表配置（chart_config，升级版图表模块）

`POST /api/generate` 新增可选参数 `chart_config`（JSON 字符串）：

```json
{
  "enabled": true,
  "count": 5,
  "types": ["bar", "line", "pie"]
}
```

- `enabled`：是否生成图表
- `count`：生成数量（1–20），按 `figure_1.png` … `figure_N.png` 循环生成并自动插入论文（图号自动编号，如 图1-1、图1-2、图2-1，正文自动引用“如图1-1所示”）
- `types`：图表类型列表（可多选，空列表则按专业智能推荐）；支持 20 种类型：

  `bar` 柱状图、`horizontal_bar` 条形图、`radar` 雷达图、`stacked_bar` 分向条形图、
  `line` 折线图、`area` 面积图、`heatmap` 热力图、`stock` 股价图、
  `histogram` 直方图、`boxplot` 箱线图、`violin` 小提琴图、`scatter` 散点图、
  `pie` 饼图、`treemap` 树状图、`sunburst` 旭日图、`decomposition_tree` 分解树、
  `sankey` 桑基图、`funnel` 漏斗图、`flowchart` 流程图、`chord` 和弦图

兼容旧参数：不传 `chart_config` 时，仍按旧 `chart_enabled` 逻辑生成 1 张示例图表。

```bash
# 示例：折线图 + 柱状图，生成 3 张图
curl -X POST http://127.0.0.1:8000/api/generate \
  -F "title=图表示例论文" -F "major=工商管理" \
  -F "paper_type=课程论文" -F "word_count=3000" \
  -F "chart_config={\"enabled\":true,\"count\":3,\"types\":[\"line\",\"bar\"]}"
```

生成结果中 `charts/` 目录包含 `figure_1.png`…`figure_N.png` 与 `chart_data.json`
（每条记录 `{"type":"bar","title":"","data":[]}`，数据为示例数据）。

### 1.4 论文生成结果预览

生成完成后可直接在网页预览，无需下载 docx。服务端解析 论文.docx（标题/章节/段落/
表格/图片/参考文献）为 JSON，不直接返回 docx。

| 接口 | 说明 |
| --- | --- |
| `GET /api/preview/{task_id}` | 完整预览 JSON：`title`、`metadata`（字数/图表数/参考文献数/格式检查等）、`chapters[]`（标题/层级/HTML 内容/图片）、`references[]` |
| `GET /api/chapters/{task_id}` | 论文目录（章节 id/层级/标题），供左侧导航 |
| `GET /api/images/{task_id}` | 图表元数据（图号/标题/路径），供缩略图展示 |

图片实际字节可经 `GET /api/download/{task_id}?file=charts/figure_1.png` 获取。
任务未完成时返回 409，任务不存在返回 404。

### 1.5 论文生成记录（历史）

每次提交 `/api/generate` 会自动写入生成记录（SQLite，生产可迁移 PostgreSQL）。

| 接口 | 说明 |
| --- | --- |
| `GET /api/history` | 历史记录列表（按创建时间倒序） |
| `GET /api/history/{task_id}` | 单条详情：论文信息、生成参数（params）、状态、文件/预览地址 |
| `DELETE /api/history/{task_id}` | 删除记录 + 生成文件（outputs/）+ 上传模板（uploads/） |

记录状态：`pending`（已提交）→ `generating`（生成中）→ `completed` / `failed`。
`params` 保存完整生成参数，前端可用它“重新生成”同参数新任务。

数据库说明：

```text
paper-writer-api/data/history.db   # SQLite 开发库（.gitignore）
```

表 `generation_records`：id、task_id（唯一）、title、major、paper_type、word_count、
generation_mode、status、created_at、completed_at、file_path、preview_path、
error_message、params（JSON）。SQL 尽量保持标准，迁移 PostgreSQL 时替换连接层即可
（见 `app/db.py`）。

### 1.6 论文修改与版本管理

预览页可对章节/段落/全文进行修改，每次修改保存一个新版本（不覆盖原始 论文.docx）。

| 接口 | 说明 |
| --- | --- |
| `POST /api/revise/chapter` | 修改章节：`{task_id, chapter_id, change_type, instruction}`；change_type=regenerate/expand/condense/custom |
| `POST /api/revise/paragraph` | 修改段落：`{task_id, paragraph_id, change_type, instruction}`；change_type=polish/expand/rewrite/delete |
| `POST /api/revise/analyze` | 全文分析：返回问题列表与修改建议 |
| `GET /api/revise/versions/{task_id}` | 版本列表（版本号/操作类型/说明/时间） |
| `POST /api/revise/restore` | 恢复指定版本（保存为新版本，不覆盖当前文件） |

版本表 `revision_versions`：id、task_id、version_number（同任务内递增）、change_type、
description、created_at、content_snapshot（JSON 内容快照）。

修改后重新生成 `paper_vN.docx`（N 为版本号），原始 `论文.docx` 保持不变；
预览接口自动读取最新版本。删除历史记录时会同时清理该任务的修改版本。

> 当前修改内容为规则化示例实现（标注【修改示例】），正式版可替换为 LLM 生成。

### 1.7 DeepSeek 接入（论文内容生成模型）

调用链：**Frontend → FastAPI → DeepSeek API**（前端不直接调用 DeepSeek）。

配置（`.env`，参考 `.env.example`）：

```bash
DEEPSEEK_API_KEY=sk-xxxx
DEEPSEEK_MODEL=deepseek-chat        # 或 deepseek-reasoner
# DEEPSEEK_BASE_URL=https://api.deepseek.com
# DEEPSEEK_TIMEOUT=120
```

生成流程：用户参数 → 生成 Prompt（`prompts/` 目录，不写死在代码）→ 调用 DeepSeek →
返回章节内容 → 保存论文记录。未配置 `DEEPSEEK_API_KEY` 时自动回退到内置示例内容生成，
不影响原有流程。

Prompt 文件：

```text
prompts/
├── paper_system.txt        # 系统提示（学术写作规范）
├── abstract_generate.txt   # 摘要与关键词
├── chapter_generate.txt    # 单章正文
├── outline_generate.txt    # 论文大纲
└── revision.txt            # 章节/段落修改
```

流式/进度：任务状态接口新增 `message` 字段，生成过程中返回“正在生成摘要…”、
“正在生成第一章：xxx…”等阶段提示，前端进度条直接展示。

错误处理（`app/services/deepseek.py`）：

| 场景 | 处理 |
| --- | --- |
| 401 Key 无效 | 任务失败并提示“DeepSeek API Key 无效” |
| 402 余额不足 | 提示“DeepSeek 余额不足” |
| 429 限流 | 自动重试 1 次后提示“请求过于频繁” |
| 超时 / 5xx | 自动重试 1 次后提示对应错误 |
| 未配置 Key | 回退内置占位内容生成 |

### 1.8 分段生成（generation_strategy）

`POST /api/generate` 新增参数 `generation_strategy`：

| 值 | 说明 |
| --- | --- |
| `section`（默认） | 分段生成：规划 → 摘要 → 逐章 → 结论 → 参考文献 → 全文检查 → docx |
| `single` | 一次请求生成全文（测试用） |

分段生成流程与任务状态（`current_stage`）：

```text
planning（生成规划）→ generating_abstract（摘要/关键词）
→ generating_chapter（逐章独立请求，每章保存）
→ generating_conclusion（结论）→ generating_reference（参考文献）
→ checking（全文检查：逻辑/重复/字数/格式）→ completed
```

- 上下文管理：只把「大纲 + 前章摘要 + 当前章要求」发给模型，不重复发送全文；
  检查点文件 `outline.json` / `chapter_summary.json` / `content.json` 支持断点续传
  （某章失败后自动重试一次，从失败章节继续，不重复生成前面章节）
- 任务状态/进度：`GET /api/status/{task_id}` 新增 `current_stage / current_chapter / chapter_count`；
  数据库 `generation_records` 同步新增 `current_stage / progress / current_chapter / chapter_count` 字段
- 实时进度：`GET /api/generate/stream/{task_id}` 提供 SSE，向前端推送
  `progress / message / current_stage / current_chapter`（前端已接入 EventSource，异常自动回退轮询）
- Prompt 全部独立拆分于 `prompts/`：`outline_generate.txt`（规划 JSON）、`abstract_generate.txt`、
  `chapter_generate.txt`（含大纲/前章摘要/本章重点）、`conclusion_generate.txt`、
  `reference_generate.txt`、`paper_check.txt`、`full_paper_generate.txt`（single 模式）

### 1.9 AI 模型配置中心

支持任意 OpenAI 兼容接口（DeepSeek / OpenAI / Anthropic / Google / OpenRouter / Ollama / 自定义），
不写死任何厂商。API Key 使用 Fernet 加密存储，接口只返回掩码（`******abc123`），
仅创建时返回一次完整 Key。

| 接口 | 说明 |
| --- | --- |
| `GET /api/models` | 模型列表（Key 掩码） |
| `POST /api/models` | 新增模型（响应含一次完整 Key） |
| `PUT /api/models/{id}` | 编辑模型（api_key 留空保持不变） |
| `DELETE /api/models/{id}` | 删除模型 |
| `POST /api/models/test` | 测试连接（`{id}` 或临时 `base_url/api_key/model`） |
| `POST /api/models/default/{id}` | 设为默认模型 |

`POST /api/generate` 新增可选参数 `model_id`：不传使用默认启用模型，传了使用指定模型；
大纲、章节修改同样使用默认模型。未配置任何模型且无 `DEEPSEEK_*` 环境变量时回退占位内容。

加密：密钥取环境变量 `MODEL_CONFIG_ENCRYPTION_KEY`（Fernet key），未配置自动生成到
`data/secret.key`。

OpenAI 兼容接口配置示例：

```bash
# DeepSeek
name: DeepSeek V3 | base_url: https://api.deepseek.com/v1 | model: deepseek-chat
# OpenAI
name: GPT-5 | base_url: https://api.openai.com/v1 | model: gpt-5
# Ollama（本地）
name: 本地Ollama | base_url: http://localhost:11434/v1 | model: llama3.1:8b
# OpenRouter
name: OpenRouter | base_url: https://openrouter.ai/api/v1 | model: meta-llama/llama-3.1-8b-instruct
```

### 1.10 架构：内容生成与格式处理分离

```text
paper-writer-api/app/
├── generation/                  # 第一阶段：AI 分段式内容生成（只生成内容）
│   ├── planner.py               #   论文规划（章节/目标字数/写作重点）
│   ├── outline.py               #   大纲生成与解析
│   ├── chapter_generator.py     #   摘要 / generate_section / 结论 / 参考文献
│   ├── context_manager.py       #   outline.json / chapter_summary.json / generation_state.json
│   ├── quality_check.py         #   全文检查
│   └── service.py               #   编排：规划→大纲→摘要→逐章→结论→检查
├── formatter/                   # 第二阶段：格式处理（markdown/json → docx）
│   ├── docx_builder.py          #   docx 构建（字体/模板，逻辑不变）
│   ├── style.py                 #   模板解析
│   ├── toc.py                   #   目录更新标记
│   ├── reference.py             #   参考文献格式化/检查
│   └── service.py               #   paper_content → spec → docx + 交付物
└── output/                      # 任务产物目录（outputs/<task_id>/）
```

- 内容生成只输出 `paper_content/`：`outline.json`、`abstract.md`、`chapter1.md…`、
  `conclusion.md`、`references.json`、`chapter_summary.json`、`generation_state.json`，
  **不生成 docx**
- 每个部分独立调用模型：`generate_section(paper_info, chapter_info, previous_summary, requirements)`
- 上下文管理：每章只读「论文目标 + 当前章节要求 + 前面章节摘要」（`chapter_summary.json`），
  `generation_state.json` 支持失败恢复（断点续传）
- 生成任务状态：`planning → outline_generating → chapter_generating →
  summary_generating → conclusion_generating → checking → completed`
- 格式处理由 `formatter` 负责（字体、目录、页码、参考文献、学校模板），逻辑未改动

新增接口：

| 接口 | 说明 |
| --- | --- |
| `GET /api/content/{task_id}` | 第一阶段产物：论文内容清单（不含 docx） |
| `POST /api/format/create` | 第二阶段：创建格式任务 `{task_id, template_id?, settings}` |
| `POST /api/format/start/{format_id}` | 开始处理（后台线程，状态推进） |
| `GET /api/format/status/{format_id}` | 查询状态（waiting/processing/checking/completed/failed + progress） |
| `GET /api/format/download/{format_id}` | 下载 formatted/（paper.docx、paper.pdf（可选）、format_report.md） |
| `GET /api/format/templates` | 学校模板列表 |
| `POST /api/format/templates` | 上传 .docx 模板并自动解析（页边距/字体/标题样式/行距/页眉页脚/目录规则 → template_config.json） |
| `DELETE /api/format/templates/{id}` | 删除模板 |

学校模板存储于 `app/formatter/templates/<id>/`：

```text
formatter/templates/
├── default/            # 默认格式（template.json + rules.json）
├── school_a/           # 上传的学校模板
│   ├── style.docx           # 上传的 Word 模板
│   ├── template.json        # 名称/学校/专业/论文类型/更新时间
│   ├── rules.json           # 目录/页码/标题编号/参考文献/图表规则
│   └── template_config.json # 自动解析结果
└── school_b/
```

格式处理输出：`outputs/<task_id>/formatted/paper.docx`、`paper.pdf`（可选，需 LibreOffice）、
`format_report.md`（字体/目录/参考文献/图表 通过/失败 检查）。生成模块不再接收学校模板，
模板选择与排版全部在格式处理页完成。

### 2. 查询状态

```bash
curl http://127.0.0.1:8000/api/status/3f9c...
```

```json
{
  "task_id": "3f9c...",
  "status": "running",
  "progress": 60,
  "error": null,
  "files": [],
  "created_at": "...",
  "updated_at": "..."
}
```

### 3. 下载结果

打包下载全部产物（论文.docx、格式意见整理.md、TemplateReport.md、ReferenceCheck.md、references.json、figures/*.png）：

```bash
curl -OJ http://127.0.0.1:8000/api/download/3f9c...
```

下载单个文件：

```bash
curl -OJ "http://127.0.0.1:8000/api/download/3f9c...?file=论文.docx"
```

### 4. 健康检查

```bash
curl http://127.0.0.1:8000/api/health
```

### 5. 段落优化（POST /api/polish）

独立于论文任务的文本处理接口（对应网页端"段落优化"页），支持润色 / 扩写 / 缩写 / 修改 / 翻译。
使用「模型设置」中启用的模型（或环境变量配置的 DeepSeek），未配置模型时返回 400 提示。

```bash
curl -X POST http://127.0.0.1:8000/api/polish \
  -H "Content-Type: application/json" \
  -d '{"text":"本文研究了深度学习在医学影像中的应用。","operation":"polish","instruction":""}'
```

参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `text` | string | 待处理文本（必填，≤20000 字） |
| `operation` | string | `polish` 润色 / `expand` 扩写 / `condense` 缩写 / `rewrite` 修改 / `translate` 翻译 |
| `instruction` | string | 补充要求（`rewrite` 填修改要求；`translate` 填目标语言） |
| `model_id` | string/null | 指定使用的模型（留空用默认启用模型） |

响应：`{"text": "处理后的文本", "operation": "polish"}`

## 配置项（环境变量，前缀 PAPER_WRITER_）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PAPER_WRITER_HOST` / `PORT` | 0.0.0.0 / 8000 | 监听地址/端口 |
| `PAPER_WRITER_MAX_UPLOAD_MB` | 20 | 模板上传大小上限 |
| `PAPER_WRITER_TASK_WORKERS` | 2 | 并发任务数 |
| `PAPER_WRITER_TASK_EXPIRY_HOURS` | 24 | 任务元数据保留时间（预留） |
| `PAPER_WRITER_SCRIPTS_DIR` | `~/.codex/skills/paper-writer/scripts` | paper-writer 引擎脚本目录 |
| `PAPER_WRITER_UPLOAD_DIR` / `OUTPUT_DIR` / `LOG_DIR` | uploads/ outputs/ logs/ | 运行时目录 |

## 安全与校验

- 模板文件类型检查：仅允许 `.docx`，并校验 ZIP 魔数与 `word/document.xml`
- 上传大小限制：默认 20 MB（`PAPER_WRITER_MAX_UPLOAD_MB`）
- 上传文件以 task_id 命名存储，下载接口校验路径防止目录穿越
- 日志：`logs/app.log`（5MB 轮转 × 3）

## Docker 运行

```bash
cd paper-writer-api
docker build -t paper-writer-api .
docker run -d -p 8000:8000 \
  -v C:\Users\s1423\.codex\skills\paper-writer\scripts:/app/paper_writer_scripts:ro \
  -v paper-uploads:/app/uploads \
  -v paper-outputs:/app/outputs \
  -v paper-logs:/app/logs \
  paper-writer-api
```

引擎脚本目录通过只读卷挂载进容器（`/app/paper_writer_scripts`），容器内不复制生成代码。

## 后续接入网页前端

1. 前端表单以 `multipart/form-data` 提交 `POST /api/generate`（字段与 curl 示例一致，模板为可选文件）
2. 轮询 `GET /api/status/{task_id}` 渲染进度条
3. 完成后前端展示 `GET /api/download/{task_id}?file=...` 的下载链接（可直接放在 `<a>` 中），或下载 ZIP
4. 接入真实论文内容：替换 `app/services/content_generator.py` 的 `build_spec()` 为 LLM 生成（可同步生成摘要、正文、参考文献），其余流水线无需改动
