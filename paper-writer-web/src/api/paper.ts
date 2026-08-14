/** paper-writer-api 客户端：只负责调用后端接口，不包含任何生成逻辑。 */

export interface GenerateParams {
  title: string;
  major: string;
  paper_type: string;
  word_count: number;
  chart_enabled: boolean;
  reference_style: string;
  special_requirements?: string;
  school_template?: File | null;
  generation_mode?: "auto" | "outline";
  outline?: string;
  model_id?: string;
  chart_config?: { enabled: boolean; count: number; types: string[] } | null;
  /** 参考资料文件（开题报告/仿写论文/其他资料），最多 5 个、每个 ≤5MB */
  files?: File[];
  /** 与 files 一一对应的资料类型 */
  materialKinds?: string[];
  /** 用户自定义摘要（创作向导第②步定稿后覆盖自动生成） */
  abstract?: string;
  /** 用户自定义关键词 */
  keywords?: string[];
  /** 用户选择的真实参考文献引文（GB/T 7714，覆盖自动生成） */
  references?: string[];
  /** 草稿模式：只构建大纲草稿（逐段生成编辑器用） */
  draft_mode?: boolean;
}

export interface OutlineChapter {
  title: string;
  level: number;
  word_count: number;
}

export interface OutlineResult {
  outline: string;
  chapters: OutlineChapter[];
}

export interface PreviewImage {
  path: string;
  number: string;
  title: string;
}

export interface PreviewChapter {
  id: string;
  level: number;
  number?: string;
  title: string;
  content: string;
  blocks: {
    id?: string;
    type: "h2" | "h3" | "p" | "table" | "figure";
    text?: string;
    html?: string;
    path?: string;
    number?: string;
    title?: string;
  }[];
  images: PreviewImage[];
}

export interface PaperPreview {
  title: string;
  metadata: {
    word_count: number;
    target_word_count: number;
    chart_count: number;
    reference_count: number;
    format_check: string;
    major: string;
    paper_type: string;
    generation_mode: string;
    reference_style: string;
    template: boolean;
    special_requirements?: string | null;
  };
  chapters: PreviewChapter[];
  references: string[];
}

export interface HistoryRecord {
  id: string;
  task_id: string;
  title: string;
  major: string;
  paper_type: string;
  word_count: number;
  generation_mode: string;
  status: "pending" | "generating" | "completed" | "failed";
  created_at: string;
  completed_at?: string | null;
  file_path?: string | null;
  preview_path?: string | null;
  error_message?: string | null;
  params?: Record<string, unknown> | null;
}

export type TaskStatus = "queued" | "running" | "completed" | "failed";

export interface TaskInfo {
  task_id: string;
  status: TaskStatus;
  progress: number;
  message?: string | null;
  current_stage?: string | null;
  current_chapter?: string | null;
  chapter_count?: number | null;
  error: string | null;
  files: string[];
  created_at?: string;
  updated_at?: string;
}

/**
 * 后端地址来自 .env 的 VITE_API_URL。
 * 留空时使用相对路径 /api，开发模式由 Vite 代理转发到 paper-writer-api。
 */
export const API_BASE = (
  (import.meta.env.VITE_API_URL as string | undefined) ?? ""
).replace(/\/+$/, "");

async function toError(res: Response): Promise<Error> {
  let message = `请求失败（HTTP ${res.status}）`;
  try {
    const data = await res.json();
    if (typeof data.detail === "string") {
      message = data.detail;
    } else if (Array.isArray(data.detail)) {
      message = data.detail
        .map((d: { msg?: string }) => d.msg ?? "")
        .filter(Boolean)
        .join("；");
    }
  } catch {
    // 响应不是 JSON，保留默认信息
  }
  return new Error(message);
}

export async function generatePaper(
  params: GenerateParams,
): Promise<{ task_id: string }> {
  const form = new FormData();
  form.append("title", params.title);
  form.append("major", params.major);
  form.append("paper_type", params.paper_type);
  form.append("word_count", String(params.word_count));
  form.append("chart_enabled", String(params.chart_enabled));
  form.append("reference_style", params.reference_style);
  if (params.generation_mode) {
    form.append("generation_mode", params.generation_mode);
  }
  if (params.outline) {
    form.append("outline", params.outline);
  }
  if (params.chart_config) {
    form.append("chart_config", JSON.stringify(params.chart_config));
  }
  if (params.special_requirements != null) {
    form.append("special_requirements", params.special_requirements);
  }
  if (params.model_id) {
    form.append("model_id", params.model_id);
  }
  if (params.school_template) {
    form.append("school_template", params.school_template);
  }
  if (params.files && params.files.length > 0) {
    for (const f of params.files) {
      form.append("files", f);
    }
    form.append(
      "material_kinds",
      JSON.stringify(params.materialKinds ?? []),
    );
  }
  if (params.abstract) {
    form.append("abstract", params.abstract);
    form.append("keywords", JSON.stringify(params.keywords ?? []));
  }
  if (params.references && params.references.length > 0) {
    form.append("references", JSON.stringify(params.references));
  }
  if (params.draft_mode) {
    form.append("draft_mode", "true");
  }

  const res = await fetch(`${API_BASE}/api/generate`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

// ===== 排版模板 =====

export type TemplateSource = "builtin" | "school" | "mine";
export type TemplatePageSize =
  | "A3" | "A4" | "A5" | "B4" | "B5" | "Letter" | "Legal" | "Tabloid";
export type TemplateOrientation = "portrait" | "landscape";
export type TemplateAlignment = "left" | "center" | "right" | "justify";
export type TemplateLineSpacingMode = "multiple" | "exact" | "at_least";
export type TemplateIndentUnit = "chars" | "pt";
export type TemplateReferenceStyle = "gb7714" | "apa" | "mla" | "chicago";

export interface TemplateSummary {
  id: string;
  name: string;
  description: string;
  category: string;
  paper_type: string;
  source: TemplateSource;
  type: string;
  school_name: string;
  major: string;
  version: number;
  created_at: string;
  updated_at: string;
  is_default: boolean;
  is_favorite: boolean;
  has_cover: boolean;
  legacy: boolean;
  editable: boolean;
}

export interface TemplateBlockSummary {
  key: string;
  kind: string;
  label: string;
  enabled: boolean;
  level?: number | null;
}

export interface TemplateStyleSummary {
  font: string;
  latin_font: string;
  font_size_pt: number;
  bold: boolean;
  alignment: string;
  line_spacing: number;
  first_line_indent: { unit: string; value: number };
}

export interface TemplateFontFamilyInput {
  east_asia: string;
  latin: string;
}

export interface TemplateLineSpacingInput {
  mode: TemplateLineSpacingMode;
  value: number;
}

export interface TemplateFirstLineIndentInput {
  unit: TemplateIndentUnit;
  value: number;
}

export interface TemplateStyleInput {
  font_family: TemplateFontFamilyInput;
  font_size_pt: number;
  bold: boolean;
  italic: boolean;
  underline: boolean;
  alignment: TemplateAlignment;
  line_spacing: TemplateLineSpacingInput;
  space_before_pt: number;
  space_after_pt: number;
  first_line_indent: TemplateFirstLineIndentInput;
  keep_with_next: boolean;
  page_break_before: boolean;
}

export interface TemplateBlockInput {
  key: string;
  kind: string;
  label: string;
  enabled: boolean;
  level?: number | null;
  styles: Record<string, TemplateStyleInput>;
  settings: Record<string, unknown>;
}

export interface TemplateHeaderFooterInput {
  content: string;
  style?: TemplateStyleInput | null;
}

export interface TemplatePageInput {
  size: TemplatePageSize;
  orientation: TemplateOrientation;
  margins: {
    top_mm: number;
    bottom_mm: number;
    left_mm: number;
    right_mm: number;
  };
  header_distance_mm?: number | null;
  footer_distance_mm?: number | null;
}

export interface TemplateNumberingInput {
  enabled: boolean;
  h1?: string;
  h2?: string;
  h3?: string;
  h4?: string;
}

export interface TemplateTocInput {
  enabled: boolean;
  include_page_numbers: boolean;
}

export interface TemplateWritePayload {
  base_template_id?: string | null;
  name: string;
  description: string;
  category: string;
  paper_type: string;
  school_name: string;
  major: string;
  page?: TemplatePageInput | null;
  header?: TemplateHeaderFooterInput | null;
  footer?: TemplateHeaderFooterInput | null;
  numbering?: TemplateNumberingInput | null;
  toc?: TemplateTocInput | null;
  reference_style?: TemplateReferenceStyle | null;
  blocks?: TemplateBlockInput[] | null;
}

export interface TemplateDetail extends TemplateSummary {
  page: TemplatePageInput;
  numbering: TemplateNumberingInput;
  toc: { enabled: boolean; include_page_numbers: boolean };
  reference_style: TemplateReferenceStyle;
  header: TemplateHeaderFooterInput;
  footer: TemplateHeaderFooterInput;
  blocks: TemplateBlockInput[];
  styles: {
    title?: TemplateStyleSummary | null;
    heading1?: TemplateStyleSummary | null;
    body?: TemplateStyleSummary | null;
    references?: TemplateStyleSummary | null;
  };
}

/** 获取可用排版模板列表（含默认模板标记）。 */
export async function listTemplates(): Promise<{
  items: TemplateSummary[];
  default_id: string | null;
}> {
  const res = await fetch(`${API_BASE}/api/templates`);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

/** 获取模板可读详情（页面/目录/编号/参考文献/样式摘要）。 */
export async function getTemplateDetail(
  templateId: string,
): Promise<TemplateDetail> {
  const res = await fetch(
    `${API_BASE}/api/templates/${encodeURIComponent(templateId)}`,
  );
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

/** 创建我的模板（结构化 DTO，后端组装并校验）。 */
export function createTemplate(
  payload: TemplateWritePayload,
): Promise<TemplateDetail> {
  return postJson("/api/templates", payload);
}

/** 更新我的模板。 */
export async function updateTemplate(
  templateId: string,
  payload: TemplateWritePayload,
): Promise<TemplateDetail> {
  const res = await fetch(
    `${API_BASE}/api/templates/${encodeURIComponent(templateId)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

/** 复制任意可用模板为我的模板。 */
export function duplicateTemplate(
  templateId: string,
  name?: string,
): Promise<TemplateDetail> {
  return postJson(
    `/api/templates/${encodeURIComponent(templateId)}/duplicate`,
    { name },
  );
}

/** 删除我的模板。 */
export async function deleteTemplateRecord(templateId: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/templates/${encodeURIComponent(templateId)}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    throw await toError(res);
  }
}

/** 设置默认模板（全局唯一）。 */
export function setDefaultTemplate(
  templateId: string,
): Promise<{ default_id: string }> {
  return postJson(
    `/api/templates/${encodeURIComponent(templateId)}/set-default`,
    {},
  );
}

/** AI 生成论文大纲（标题/专业/论文类型/字数 -> 章节结构 + 预计字数分配）。 */
export async function generateOutline(params: {
  title: string;
  major: string;
  paper_type: string;
  word_count: number;
  model_id?: string;
}): Promise<OutlineResult> {
  const body: Record<string, unknown> = { ...params };
  if (!params.model_id) {
    delete body.model_id;
  }
  const res = await fetch(`${API_BASE}/api/outline/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

export async function generateTopicSuggestions(params: {
  discipline?: string;
  major: string;
  paper_type: string;
  model_id?: string;
  prompt?: string;
}): Promise<{ topics: string[] }> {
  const res = await fetch(`${API_BASE}/api/topics/suggest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw await toError(res);
  return (await res.json()) as { topics: string[] };
}

/** 独立生成论文摘要与关键词（创作向导第②步，"新建一条"按钮）。 */
export async function generateAbstract(params: {
  title: string;
  major: string;
  paper_type: string;
  special_requirements?: string;
  model_id?: string;
}): Promise<{ abstract: string; keywords: string[] }> {
  const res = await fetch(`${API_BASE}/api/abstract/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

/** 真实参考文献条目（CrossRef 学术库）。 */
export interface ReferenceItem {
  title: string;
  authors: string;
  source: string;
  year: string;
  type: string;
  doi: string;
  abstract: string;
  citation: string;
  source_name?: "crossref" | "openalex" | "semantic_scholar" | "arxiv";
}

/** 搜索真实参考文献（创作向导第③步）。 */
export async function searchReferences(params: {
  title: string;
  major: string;
  keywords?: string[];
  query?: string;
  limit?: number;
}): Promise<{ references: ReferenceItem[]; query: string }> {
  const res = await fetch(`${API_BASE}/api/references/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

// ===== 论文草稿（逐段生成编辑器）=====

export interface DraftParagraph {
  id: string;
  text: string;
}

export interface DraftSection {
  id: string;
  number: string;
  title: string;
  level: number;
  gist: string;
  paragraphs: DraftParagraph[];
  target_chars?: number;
  min_chars?: number;
}

export interface PaperDraft {
  title: string;
  meta: {
    major: string;
    paper_type: string;
    word_count: number;
    special_requirements?: string | null;
    keywords: string[];
    reference_style: string;
  };
  abstract: { zh: string; en: string };
  keywords: { zh: string[]; en: string[] };
  acknowledgement: string;
  references: string[];
  sections: DraftSection[];
  generating: boolean;
  progress: number;
  done: number;
  total: number;
  word_status?: "generating" | "supplementing" | "completed" | "shortfall";
  supplement_rounds?: number;
  word_stats?: {
    target: number;
    minimum: number;
    actual: number;
    shortfall: number;
  };
}

async function draftFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json() as Promise<T>;
}

export const fetchDraft = (taskId: string): Promise<PaperDraft> =>
  draftFetch(`/api/draft/${taskId}`);

export const fetchDraftStatus = (
  taskId: string,
): Promise<{ generating: boolean; progress: number; done: number; total: number }> =>
  draftFetch(`/api/draft/${taskId}/status`);

export const generateDraftSection = (
  taskId: string,
  sectionId: string,
  modelId?: string,
): Promise<DraftParagraph> =>
  draftFetch(`/api/draft/${taskId}/section/${sectionId}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId }),
  });

export const updateDraftSection = (
  taskId: string,
  sectionId: string,
  patch: { title?: string; gist?: string },
): Promise<{ ok: boolean }> =>
  draftFetch(`/api/draft/${taskId}/section/${sectionId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });

export const addDraftParagraph = (
  taskId: string,
  sectionId: string,
  text = "",
): Promise<DraftParagraph> =>
  draftFetch(`/api/draft/${taskId}/paragraph`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ section_id: sectionId, text }),
  });

export const updateDraftParagraph = (
  taskId: string,
  pid: string,
  text: string,
): Promise<{ ok: boolean }> =>
  draftFetch(`/api/draft/${taskId}/paragraph/${pid}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });

export const deleteDraftParagraph = (
  taskId: string,
  pid: string,
): Promise<{ ok: boolean }> =>
  draftFetch(`/api/draft/${taskId}/paragraph/${pid}`, { method: "DELETE" });

export const moveDraftParagraph = (
  taskId: string,
  pid: string,
  direction: "up" | "down",
): Promise<{ ok: boolean }> =>
  draftFetch(`/api/draft/${taskId}/paragraph/${pid}/move`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ direction }),
  });

export const startDraftOneclick = (
  taskId: string,
  modelId?: string,
): Promise<{ ok: boolean }> =>
  draftFetch(`/api/draft/${taskId}/oneclick`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId }),
  });


export const generateDraftAck = (
  taskId: string,
  modelId?: string,
): Promise<{ text: string }> =>
  draftFetch(`/api/draft/${taskId}/acknowledgement`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId }),
  });

export const generateDraftEnAbstract = (
  taskId: string,
  modelId?: string,
): Promise<{ text: string }> =>
  draftFetch(`/api/draft/${taskId}/abstract/en`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId }),
  });

export const exportDraft = (
  taskId: string,
  templateId?: string,
): Promise<{ ok: boolean; files: string[] }> =>
  draftFetch(`/api/draft/${taskId}/export${templateId ? `?template_id=${encodeURIComponent(templateId)}` : ""}`, { method: "POST" });

/** 按选定排版模板导出论文 docx（未传 template_id 时后端使用默认基础模板）。 */
export const exportPaper = (
  taskId: string,
  templateId?: string,
): Promise<{ ok: boolean; files: string[] }> =>
  postJson(
    `/api/export/${taskId}${templateId ? `?template_id=${encodeURIComponent(templateId)}` : ""}`,
    {},
  );

export async function fetchTaskStatus(taskId: string): Promise<TaskInfo> {
  const res = await fetch(`${API_BASE}/api/status/${taskId}`);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

export function downloadUrl(taskId: string, file?: string): string {
  const base = `${API_BASE}/api/download/${taskId}`;
  return file ? `${base}?file=${encodeURIComponent(file)}` : base;
}

/** 论文预览：解析 docx 后的结构化 JSON（标题/章节/段落/图片/表格/参考文献）。 */
export async function fetchPreview(taskId: string): Promise<PaperPreview> {
  const res = await fetch(`${API_BASE}/api/preview/${taskId}`);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

export async function fetchChapters(taskId: string): Promise<{
  chapters: { id: string; level: number; title: string }[];
}> {
  const res = await fetch(`${API_BASE}/api/chapters/${taskId}`);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

export async function fetchImages(taskId: string): Promise<{
  images: PreviewImage[];
  count: number;
}> {
  const res = await fetch(`${API_BASE}/api/images/${taskId}`);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

export async function fetchHistory(): Promise<HistoryRecord[]> {
  const res = await fetch(`${API_BASE}/api/history`);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

export async function fetchHistoryRecord(taskId: string): Promise<HistoryRecord> {
  const res = await fetch(`${API_BASE}/api/history/${taskId}`);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

export async function deleteHistoryRecord(taskId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/history/${taskId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw await toError(res);
  }
}

export interface ReviseResult {
  task_id: string;
  version: number;
  change_type: string;
  description: string;
  docx_file: string;
  preview_url: string;
}

export interface AnalysisResult {
  problems: string[];
  suggestions: string[];
  word_count: number;
  target_word_count: number;
  chapter_words: [string, number][];
}

export interface VersionInfo {
  id: string;
  task_id: string;
  version_number: number;
  change_type: string;
  description: string | null;
  created_at: string;
}

async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

export function reviseChapter(params: {
  task_id: string;
  chapter_id: string;
  instruction: string;
  change_type: string;
  model_id?: string;
}): Promise<ReviseResult> {
  return postJson("/api/revise/chapter", params);
}

export function reviseParagraph(params: {
  task_id: string;
  paragraph_id: string;
  instruction: string;
  change_type: string;
  model_id?: string;
}): Promise<ReviseResult> {
  return postJson("/api/revise/paragraph", params);
}

export function analyzePaper(taskId: string): Promise<AnalysisResult> {
  return postJson("/api/revise/analyze", { task_id: taskId });
}

export function restoreVersion(
  taskId: string,
  versionNumber: number,
): Promise<ReviseResult> {
  return postJson("/api/revise/restore", {
    task_id: taskId,
    version_number: versionNumber,
  });
}

export async function fetchVersions(taskId: string): Promise<VersionInfo[]> {
  const res = await fetch(`${API_BASE}/api/revise/versions/${taskId}`);
  if (!res.ok) {
    throw await toError(res);
  }
  const data = (await res.json()) as { versions: VersionInfo[] };
  return data.versions;
}

export interface ModelConfig {
  id: string;
  name: string;
  provider: string;
  base_url: string;
  api_key_masked?: string;
  api_key?: string;
  has_api_key?: boolean;
  model: string;
  is_default: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ModelConfigInput {
  name: string;
  provider: string;
  base_url: string;
  api_key?: string;
  model: string;
  is_default?: boolean;
  enabled?: boolean;
}

export async function fetchModels(): Promise<ModelConfig[]> {
  const res = await fetch(`${API_BASE}/api/models`);
  if (!res.ok) {
    throw await toError(res);
  }
  const data = (await res.json()) as { models: ModelConfig[] };
  return data.models;
}

export function createModel(input: ModelConfigInput): Promise<ModelConfig> {
  return postJson("/api/models", input);
}

export async function updateModel(
  id: string,
  input: ModelConfigInput,
): Promise<ModelConfig> {
  const res = await fetch(`${API_BASE}/api/models/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

export async function deleteModel(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/models/${id}`, { method: "DELETE" });
  if (!res.ok) {
    throw await toError(res);
  }
}

export function testModel(
  payload: { id: string } | ModelConfigInput,
): Promise<{ ok: boolean; message: string }> {
  return postJson("/api/models/test", payload);
}

export function setDefaultModel(id: string): Promise<{ default: string }> {
  return postJson(`/api/models/default/${id}`, {});
}

export interface PaperContentManifest {
  outline: { chapters: { title: string }[] };
  abstract: string;
  keywords: string[];
  chapters: { title: string; text: string }[];
  conclusion: string;
  references: string[];
}

export async function fetchPaperContent(
  taskId: string,
): Promise<PaperContentManifest> {
  const res = await fetch(`${API_BASE}/api/content/${taskId}`);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

export function formatPaper(taskId: string): Promise<{
  ok: boolean;
  message: string;
  files: string[];
}> {
  return postJson(`/api/format/${taskId}`, {});
}

export interface FormatTaskInfo {
  id: string;
  task_id: string;
  template_id: string | null;
  status: "waiting" | "processing" | "checking" | "completed" | "failed";
  progress: number;
  message: string | null;
  settings: Record<string, unknown>;
  files: string[];
  created_at: string;
  completed_at: string | null;
}

export interface FormatTemplate {
  id: string;
  name: string;
  school_name: string;
  major: string;
  paper_type: string;
  created_at: string;
  updated_at: string;
  config?: Record<string, unknown>;
  rules?: Record<string, unknown>;
}

export function createFormatTask(params: {
  task_id: string;
  template_id?: string | null;
  settings: object;
}): Promise<{ format_id: string; status: string }> {
  return postJson("/api/format/create", params);
}

export function startFormatTask(formatId: string): Promise<{ ok: boolean }> {
  return postJson(`/api/format/start/${formatId}`, {});
}

export async function fetchFormatStatus(formatId: string): Promise<FormatTaskInfo> {
  const res = await fetch(`${API_BASE}/api/format/status/${formatId}`);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

export function formatDownloadUrl(formatId: string, file?: string): string {
  const base = `${API_BASE}/api/format/download/${formatId}`;
  return file ? `${base}?file=${encodeURIComponent(file)}` : base;
}

export async function fetchFormatTemplates(): Promise<FormatTemplate[]> {
  const res = await fetch(`${API_BASE}/api/templates`);
  if (!res.ok) {
    throw await toError(res);
  }
  const data = (await res.json()) as { items: FormatTemplate[] };
  return data.items;
}

export async function uploadFormatTemplate(
  meta: { name: string; school_name: string; major: string; paper_type: string },
  file: File,
): Promise<FormatTemplate> {
  const form = new FormData();
  form.append("name", meta.name);
  form.append("school_name", meta.school_name);
  form.append("major", meta.major);
  form.append("paper_type", meta.paper_type);
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/format/templates`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

/** 段落优化操作类型（对应 aiunipaper 段落优化）。 */
export type PolishOperation =
  | "polish"
  | "expand"
  | "condense"
  | "rewrite"
  | "translate";

export const POLISH_OPERATIONS: {
  value: PolishOperation;
  label: string;
  desc: string;
}[] = [
  { value: "polish", label: "润色", desc: "优化语言、逻辑与表达" },
  { value: "expand", label: "扩写", desc: "补充论据与细节，充实内容" },
  { value: "condense", label: "缩写", desc: "简化概括，突出重点" },
  { value: "rewrite", label: "修改", desc: "按你的要求针对性修改" },
  { value: "translate", label: "翻译", desc: "翻译为指定语言" },
];

/** 对粘贴文本进行润色/扩写/缩写/修改/翻译（独立于论文任务）。 */
export async function polishText(params: {
  text: string;
  operation: PolishOperation;
  instruction?: string;
  model_id?: string;
}): Promise<{ text: string; operation: PolishOperation }> {
  const res = await fetch(`${API_BASE}/api/polish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}
