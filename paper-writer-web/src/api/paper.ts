/** paper-writer-api 客户端：只负责调用后端接口，不包含任何生成逻辑。 */

import { normalizeApiBase } from "./apiUrl";

export interface GenerateParams {
  title: string;
  major: string;
  paper_type: string;
  word_count: number;
  reference_style: string;
  special_requirements?: string;
  school_template?: File | null;
  generation_mode?: "auto" | "outline";
  outline?: string;
  model_id?: string;
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
 * 统一规范化会移除环境变量中的空白和尾部斜杠。
 */
export { normalizeApiBase } from "./apiUrl";

export const API_BASE = normalizeApiBase(
  import.meta.env.VITE_API_URL as string | undefined,
);

/** 可选的部署认证令牌；留空时保持本机开发流程完全不变。 */
export const API_AUTH_TOKEN =
  (import.meta.env.VITE_PAPER_WRITER_AUTH_TOKEN as string | undefined) ?? "";

/** 为无法自定义请求头的 SSE 与浏览器下载请求附加认证参数。 */
export function withAuthQuery(url: string): string {
  if (!API_AUTH_TOKEN) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}auth_token=${encodeURIComponent(API_AUTH_TOKEN)}`;
}

async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  if (API_AUTH_TOKEN) headers.set("Authorization", `Bearer ${API_AUTH_TOKEN}`);
  return fetch(input, { ...init, headers });
}

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
  form.append("reference_style", params.reference_style);
  if (params.generation_mode) {
    form.append("generation_mode", params.generation_mode);
  }
  if (params.outline) {
    form.append("outline", params.outline);
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

  const res = await apiFetch(`${API_BASE}/api/generate`, {
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
  const res = await apiFetch(`${API_BASE}/api/templates`);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

/** 获取模板可读详情（页面/目录/编号/参考文献/样式摘要）。 */
export async function getTemplateDetail(
  templateId: string,
): Promise<TemplateDetail> {
  const res = await apiFetch(
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
  const res = await apiFetch(
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
  const res = await apiFetch(
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
  const res = await apiFetch(`${API_BASE}/api/outline/generate`, {
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
  const res = await apiFetch(`${API_BASE}/api/topics/suggest`, {
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
  const res = await apiFetch(`${API_BASE}/api/abstract/generate`, {
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
export type ManualReferenceType =
  | "journal"
  | "thesis"
  | "conference"
  | "book"
  | "report"
  | "web"
  | "standard";

export interface ManualReferenceInput {
  reference_type: ManualReferenceType;
  authors: string;
  title: string;
  source: string;
  year: string;
  volume?: string;
  issue?: string;
  pages?: string;
  doi?: string;
  url?: string;
}

export interface ReferenceItem {
  title: string;
  authors: string;
  source: string;
  year: string;
  type: string;
  doi: string;
  abstract: string;
  citation: string;
  url?: string;
  manual?: ManualReferenceInput;
  source_name?: "crossref" | "openalex" | "semantic_scholar" | "arxiv" | "manual";
}

/** 将手动录入字段格式化为可勾选的本地参考文献条目。 */
export async function formatManualReference(
  payload: ManualReferenceInput,
): Promise<{ reference: ReferenceItem }> {
  const res = await apiFetch(`${API_BASE}/api/references/manual`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

/** 搜索真实参考文献（创作向导第③步）。 */
export async function searchReferences(params: {
  title: string;
  major: string;
  keywords?: string[];
  query?: string;
  limit?: number;
}): Promise<{ references: ReferenceItem[]; query: string }> {
  const res = await apiFetch(`${API_BASE}/api/references/search`, {
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

export interface DraftChartSeries {
  name: string;
  values: number[];
  axis: "left" | "right";
}
export interface DraftChartSpec {
  schema_version: 1 | 2;
  kind: "bar" | "line" | "mixed" | "pie" | "scatter" | "area" | "boxplot" | "histogram" | "heatmap" | "combo";
  title: string;
  caption: string;
  categories?: string[];
  series?: DraftChartSeries[];
  pie?: Array<{ name: string; value: number }>;
  data?: { categories: string[]; series: DraftChartSeries[]; pie?: Array<{ name: string; value: number }> };
  binding?: { dataset_id?: string; dataset_version?: number; source_table_id?: string; data_fingerprint?: string };
  appearance?: { template?: string; theme?: string; legend?: boolean; value_labels?: boolean; grid?: boolean; palette?: string[]; font_size?: number; x_label?: string; y_label?: string };
}
export interface DraftChartAsset {
  id: string;
  png_path: string;
  svg_path: string;
  data_fingerprint?: string;
  generated_at: string;
}
export interface CrossReference { id:string; task_id:string; source_block_id:string; target_object_id:string; target_type:"figure"|"table"; display_label:string; resolved_label?:string|null; target_title?:string|null; status:"ready"|"broken"; created_at:string; updated_at:string; }
export interface DependencyLink { id:string; task_id:string; source_type:string; source_id:string; source_version?:number|null; target_type:string; target_id:string; relation:"derived_from"|"explains"|"renders"|"references"; created_at:string; }
export interface DependencyNode { id:string; type:string; title:string; status:"current"|"ready"|"stale"|"stale_source"|"broken"|"missing"; version?:number|null; fingerprint?:string|null; }
export interface ResearchImpact { source:DependencyNode; analyses:DependencyNode[]; results:DependencyNode[]; tables:DependencyNode[]; figures:DependencyNode[]; explanations:DependencyNode[]; findings:DependencyNode[]; references:DependencyNode[]; links:DependencyLink[]; }
export interface FindingEvidence { finding:DependencyNode; dataset:Record<string,unknown>; analysis:DependencyNode; result:DependencyNode; explanation:DependencyNode; tables:DependencyNode[]; figures:DependencyNode[]; cross_references:DependencyNode[]; }
export interface ReferenceCandidate { id:string; type:"figure"|"table"; title:string; number:number; display_label:string; status:string; source_id:string; }
export interface DraftContentPart { type:"text"|"cross_reference"; text?:string; reference_id?:string; }
export interface FullPaperPipelineState {
  version?: number;
  status?: "running" | "pause_requested" | "paused" | "completed" | "failed" | "resuming";
  stage?: string;
  message?: string;
  current_section_id?: string;
  completed_section_ids?: string[];
  research_section_ids?: string[];
  inserted_block_ids?: string[];
  progress?: number;
  error?: string;
  visualization_plan?: {
    section_id?: string;
    candidate_count?: number;
    candidate_kinds?: string[];
    candidate_titles?: string[];
  };
  visualization_insertions?: Array<{
    kind: "table" | "chart";
    block_id: string;
    label: string;
    title: string;
  }>;
  visualization_failures?: Array<{ candidate_id: string; reason: string }>;
}

export interface DraftResearchVisualization {
  candidate_id?: string;
  evidence_ids?: string[];
  dataset_id?: string;
  dataset_version?: number;
  source_snapshot?: Array<{ source_type?: string; source_id?: string; source_title?: string; source_updated_at?: string; verification_status?: string }>;
  derivation?: string;
}

export interface DraftParagraph {
  id: string;
  text: string;
  version?: number;
  type?: "paragraph" | "table" | "chart" | "insight" | "cross_reference" | "finding";
  content?: DraftContentPart[];
  insight?: DraftInsightBlock;
  title?: string;
  headers?: string[];
  rows?: string[][];
  caption?: string;
  chart?: DraftChartSpec;
  chart_spec?: DraftChartSpec;
  asset?: DraftChartAsset;
  source_ids?: string[];
  /** 后端领域服务持久化的正式编号；前端不得由位置推断。 */
  figure_number?: number;
  table_number?: number;
  source?: string;
  note?: string;
  stale_reason?: string | null;
  display_scale?: number;
  provenance?: "user_provided" | "model_generated" | "illustrative";
  status?: "ready" | "stale" | "generating" | "failed" | "broken";
  generation_origin?: string;
  auto_full_paper?: boolean;
  generated_by?: string;
  research_visualization?: DraftResearchVisualization;
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
  outline_meta?: {
    version: number;
    source: "ai" | "fallback";
    fallback_reason?: string | null;
    research_type: string;
    required_elements: string[];
    coverage: Record<string, boolean>;
    entity_coverage: number;
    template_risk: "high" | "low";
    score: number;
    issues: string[];
    recommendations: string[];
    confirmation_required: boolean;
    confirmed: boolean;
    confirmed_at?: string | null;
  };
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
  full_paper_pipeline?: FullPaperPipelineState;
}

async function draftFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json() as Promise<T>;
}

export const fetchDraft = (taskId: string): Promise<PaperDraft> =>
  draftFetch(`/api/draft/${taskId}`);

export const confirmDraftOutline = (taskId: string): Promise<{ outline_meta: NonNullable<PaperDraft["outline_meta"]> }> =>
  draftFetch(`/api/draft/${taskId}/outline/confirm`, { method: "POST" });

export const regenerateDraftOutline = (taskId: string, modelId?: string): Promise<{ sections: DraftSection[]; outline_meta: NonNullable<PaperDraft["outline_meta"]> }> =>
  draftFetch(`/api/draft/${taskId}/outline/regenerate`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model_id: modelId }),
  });

export const addDraftOutlineSection = (taskId: string, body: { title: string; gist?: string; parent_id?: string }): Promise<DraftSection> =>
  draftFetch(`/api/draft/${taskId}/outline/section`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });

export const deleteDraftOutlineSection = (taskId: string, sectionId: string): Promise<{ ok: boolean }> =>
  draftFetch(`/api/draft/${taskId}/outline/section/${sectionId}`, { method: "DELETE" });

export const fetchDraftStatus = (
  taskId: string,
): Promise<{ generating: boolean; progress: number; done: number; total: number; pipeline?: FullPaperPipelineState }> =>
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

export const addDraftTable = (
  taskId: string,
  sectionId: string,
  title = "数据表",
  headers: string[] = ["指标", "数值"],
  rows: string[][] = [["", ""]],
): Promise<DraftParagraph> =>
  draftFetch(`/api/draft/${taskId}/table`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ section_id: sectionId, title, headers, rows }),
  });

export const updateDraftBlock = (
  taskId: string, blockId: string,
    patch: { text?: string; title?: string; headers?: string[]; rows?: string[][] },
): Promise<DraftParagraph> =>
  draftFetch(`/api/draft/${taskId}/block/${blockId}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
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
): Promise<{ ok: boolean; pipeline?: FullPaperPipelineState }> =>
  draftFetch(`/api/draft/${taskId}/oneclick`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId }),
  });

export const pauseDraftOneclick = (taskId: string): Promise<{ ok: boolean; pipeline: FullPaperPipelineState }> =>
  draftFetch(`/api/draft/${taskId}/oneclick/pause`, { method: "POST" });

export const resumeDraftOneclick = (
  taskId: string,
  modelId?: string,
): Promise<{ ok: boolean; pipeline?: FullPaperPipelineState }> =>
  draftFetch(`/api/draft/${taskId}/oneclick/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId }),
  });

export const regenerateFullDraftSection = (
  taskId: string,
  sectionId: string,
  modelId?: string,
): Promise<{ ok: boolean; pipeline?: FullPaperPipelineState }> =>
  draftFetch(`/api/draft/${taskId}/section/${sectionId}/full-regenerate`, {
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
  const res = await apiFetch(`${API_BASE}/api/status/${taskId}`);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

export function downloadUrl(taskId: string, file?: string): string {
  const base = withAuthQuery(`${API_BASE}/api/download/${taskId}`);
  return file
    ? `${base}${base.includes("?") ? "&" : "?"}file=${encodeURIComponent(file)}`
    : base;
}

/** 论文预览：解析 docx 后的结构化 JSON（标题/章节/段落/图片/表格/参考文献）。 */
export async function fetchPreview(taskId: string): Promise<PaperPreview> {
  const res = await apiFetch(`${API_BASE}/api/preview/${taskId}`);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

export async function fetchChapters(taskId: string): Promise<{
  chapters: { id: string; level: number; title: string }[];
}> {
  const res = await apiFetch(`${API_BASE}/api/chapters/${taskId}`);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

export async function fetchHistory(): Promise<HistoryRecord[]> {
  const res = await apiFetch(`${API_BASE}/api/history`);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

export async function fetchHistoryRecord(taskId: string): Promise<HistoryRecord> {
  const res = await apiFetch(`${API_BASE}/api/history/${taskId}`);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

export async function deleteHistoryRecord(taskId: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}/api/history/${taskId}`, {
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
  const res = await apiFetch(`${API_BASE}${path}`, {
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
  const res = await apiFetch(`${API_BASE}/api/revise/versions/${taskId}`);
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
  const res = await apiFetch(`${API_BASE}/api/models`);
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
  const res = await apiFetch(`${API_BASE}/api/models/${id}`, {
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
  const res = await apiFetch(`${API_BASE}/api/models/${id}`, { method: "DELETE" });
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
  const res = await apiFetch(`${API_BASE}/api/content/${taskId}`);
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
  const res = await apiFetch(`${API_BASE}/api/format/status/${formatId}`);
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}

export function formatDownloadUrl(formatId: string, file?: string): string {
  const base = withAuthQuery(`${API_BASE}/api/format/download/${formatId}`);
  return file
    ? `${base}${base.includes("?") ? "&" : "?"}file=${encodeURIComponent(file)}`
    : base;
}

export async function fetchFormatTemplates(): Promise<FormatTemplate[]> {
  const res = await apiFetch(`${API_BASE}/api/templates`);
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
  const res = await apiFetch(`${API_BASE}/api/format/templates`, {
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
  const res = await apiFetch(`${API_BASE}/api/polish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    throw await toError(res);
  }
  return res.json();
}



export type DraftChartKind = "bar" | "line" | "mixed" | "pie";
export interface DraftChartCreateParams {
  title_hint?: string;
  chart_kind?: DraftChartKind;
  display_scale?: number;
  illustrative?: boolean;
}
export interface DraftChartPatchParams {
  title?: string;
  caption?: string;
  display_scale?: number;
}
export async function addDraftChart(taskId: string, sectionId: string, params: DraftChartCreateParams): Promise<DraftParagraph> {
  const res = await apiFetch(API_BASE + "/api/draft/" + taskId + "/section/" + sectionId + "/chart", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params) });
  if (!res.ok) throw await toError(res);
  return res.json();
}
export async function regenerateDraftChart(taskId: string, blockId: string, params: Pick<DraftChartCreateParams, "chart_kind" | "illustrative"> = {}): Promise<DraftParagraph> {
  const res = await apiFetch(API_BASE + "/api/draft/" + taskId + "/chart/" + blockId + "/regenerate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params) });
  if (!res.ok) throw await toError(res);
  return res.json();
}
export async function updateDraftChart(taskId: string, blockId: string, params: DraftChartPatchParams): Promise<DraftParagraph> {
  const res = await apiFetch(API_BASE + "/api/draft/" + taskId + "/chart/" + blockId, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params) });
  if (!res.ok) throw await toError(res);
  return res.json();
}

/** 保存正文内 Chart Editor 的结构化 ChartSpec；ECharts option 永不写入后端。 */
export async function updateDraftChartSpec(taskId: string, blockId: string, chartSpec: DraftChartSpec): Promise<DraftParagraph> {
  const res = await apiFetch(API_BASE + "/api/draft/" + taskId + "/chart/" + blockId + "/spec", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ chart_spec: chartSpec }) });
  if (!res.ok) throw await toError(res);
  return res.json();
}
export async function fetchDraftChartAsset(taskId: string, blockId: string, format: "svg" | "png" = "svg"): Promise<Blob> {
  const res = await apiFetch(API_BASE + "/api/draft/" + taskId + "/chart/" + blockId + "/asset?format=" + format);
  if (!res.ok) throw await toError(res);
  return res.blob();
}


export type DraftInsightKind = "chart" | "three_line_table" | "comparison_table" | "problem_solution_table" | "method_table" | "framework_diagram";
export interface DraftEvidenceRef { section_id: string; paragraph_id?: string; table_id?: string; excerpt: string; field?: string; }
export interface DraftInsightBlock {
  kind: DraftInsightKind;
  title: string;
  caption: string;
  scope: "section" | "chapter" | "full_paper";
  source_status: "user_data" | "text_synthesis" | "outline_synthesis";
  evidence: DraftEvidenceRef[];
  table?: { style: "three_line"; headers: string[]; rows: string[][] };
  chart?: { kind: "bar" | "line" | "mixed" | "pie"; title: string; caption: string; categories: string[]; series: Array<{ name: string; values: number[]; axis: "left" | "right" }>; source_table_id: string };
  framework?: { nodes: Array<{ id: string; label: string; group: "input" | "process" | "output" | "constraint" }>; edges: Array<{ from: string; to: string; label?: string }> };
  version: number;
  generated_at: string;
}
export interface DraftInsightParams { scope?: "section" | "chapter" | "full_paper"; intent?: "auto" | "chart" | "comparison_table" | "problem_solution_table" | "method_table" | "framework_diagram"; placement?: "section_end" | "after_current"; }
export async function createDraftInsight(taskId: string, sectionId: string, params: DraftInsightParams = {}): Promise<DraftParagraph> {
  const response = await apiFetch(API_BASE + "/api/draft/" + taskId + "/section/" + sectionId + "/insight", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scope: "full_paper", intent: "auto", placement: "section_end", ...params }) });
  if (!response.ok) throw await toError(response);
  return response.json();
}
export async function regenerateDraftInsight(taskId: string, blockId: string, params: Pick<DraftInsightParams, "scope" | "intent"> = {}): Promise<DraftParagraph> {
  const response = await apiFetch(API_BASE + "/api/draft/" + taskId + "/insight/" + blockId + "/regenerate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scope: "full_paper", intent: "auto", ...params }) });
  if (!response.ok) throw await toError(response);
  return response.json();
}


// ===== Visualization Lab =====
export type LabChartKind = "bar" | "line" | "pie" | "scatter" | "area" | "boxplot" | "histogram" | "heatmap" | "combo";
export type LabAggregation = "none" | "count" | "sum" | "avg" | "median" | "min" | "max";
export type LabFilterOperator = "=" | "!=" | ">" | "<" | ">=" | "<=" | "in" | "between";
export interface LabField {
  name: string;
  kind: "number" | "string";
  position: number;
  missing_count: number;
  unique_count: number;
  statistics?: { min: number; max: number; avg: number; median: number };
}
export interface LabDataset {
  id: string;
  title: string;
  version: number;
  row_count: number;
  source_type?: "table_block" | "research_dataset";
  source_table_id?: string | null;
  fingerprint: string;
  schema: Array<{ name: string; kind: "number" | "string"; position: number }>;
}
export interface DatasetColumn {
  name: string;
  type: "numeric" | "categorical" | "boolean" | "datetime" | "text";
  nullable: boolean;
  unique_count: number;
  missing_count: number;
  stats?: { mean: number; median: number; min: number; max: number; std: number } | null;
  warnings: string[];
}
export interface DatasetQuality {
  sample_size: number;
  variable_count: number;
  duplicate_rows: number;
  columns: DatasetColumn[];
  warnings: string[];
}
export interface DatasetVersion {
  dataset_id: string;
  version: number;
  schema: DatasetColumn[];
  row_count: number;
  fingerprint: string;
  source: { filename: string; extension: "csv" | "xlsx"; encoding?: string; sheet?: string };
  rows_path: string;
  source_path: string;
  quality: DatasetQuality;
  created_at: string;
  dataset_name?: string;
  deduplicated?: boolean;
}
export interface DatasetSummary {
  id: string;
  name: string;
  description: string;
  source_type: "csv" | "xlsx";
  created_at: string;
  updated_at: string;
  latest_version: number;
  task_ids: string[];
  row_count: number;
  variable_count: number;
  latest_source: DatasetVersion["source"];
}
export interface DatasetPreview {
  dataset_id: string;
  version: number;
  schema: DatasetColumn[];
  quality: DatasetQuality;
  rows: Array<Record<string, string>>;
  row_count: number;
  limit: number;
  offset: number;
  has_more: boolean;
}
export interface DatasetImportSelection {
  status: "sheet_selection_required";
  import_token: string;
  filename: string;
  source_type: "xlsx";
  sheets: string[];
  requires_sheet_selection: true;
}
export interface DatasetImportComplete {
  status: "imported";
  dataset: DatasetVersion;
}
export interface LabBinding {
  source_type?: "table_block" | "research_dataset";
  dataset_id?: string;
  dataset_version?: number;
  source_table_id?: string;
  category_column?: string;
  measure_columns?: string[];
  series_column?: string | null;
  aggregation?: LabAggregation;
  filters?: Array<{ column: string; operator: LabFilterOperator; value: unknown }>;
  data_fingerprint?: string;
}
export interface LabAppearance {
  template?: "academic" | "cn_thesis" | "clean_report";
  legend?: boolean;
  value_labels?: boolean;
  grid?: boolean;
  x_label?: string;
  y_label?: string;
}
export interface LabChart {
  id: string;
  title: string;
  caption: string;
  status: "ready" | "stale" | "failed" | "generating";
  version: number;
  in_paper: boolean;
  figure_number?: string;
  kind: LabChartKind;
  chart_spec: {
    schema_version: 2;
    kind: LabChartKind;
    title: string;
    caption: string;
    binding: LabBinding;
    appearance: LabAppearance;
    data: { categories: string[]; series: DraftChartSeries[]; pie?: Array<{ name: string; value: number }>; row_count?: number };
  };
  asset?: DraftChartAsset;
  stale_reason?: string | null;
}
export interface LabState {
  datasets: LabDataset[];
  research_datasets: DatasetSummary[];
  charts: Array<Omit<LabChart, "chart_spec"> & { dataset_id?: string; source_table_id?: string }>;
  sections: Array<{ id: string; number: string; title: string }>;
  templates: Array<{ id: string; label: string }>;
}
export interface LabDatasetPreview {
  dataset: Pick<LabDataset, "id" | "title" | "version" | "row_count" | "source_table_id" | "fingerprint">;
  fields: LabField[];
  rows: Array<Record<string, string>>;
  offset: number;
  limit: number;
  has_more: boolean;
}

export async function getLabState(taskId: string): Promise<LabState> {
  const res = await apiFetch(`${API_BASE}/api/draft/${taskId}/lab/state`);
  if (!res.ok) throw await toError(res);
  return res.json();
}
export async function getLabDataset(taskId: string, datasetId: string, limit = 50, offset = 0, version?: number): Promise<LabDatasetPreview> {
  const versionQuery = version ? `&version=${encodeURIComponent(version)}` : "";
  const res = await apiFetch(`${API_BASE}/api/draft/${taskId}/lab/datasets/${encodeURIComponent(datasetId)}?limit=${limit}&offset=${offset}${versionQuery}`);
  if (!res.ok) throw await toError(res);
  return res.json();
}
export async function getLabChart(taskId: string, chartId: string): Promise<LabChart> {
  const res = await apiFetch(`${API_BASE}/api/draft/${taskId}/lab/charts/${encodeURIComponent(chartId)}`);
  if (!res.ok) throw await toError(res);
  return res.json();
}
export async function createLabChart(taskId: string, input: { source_type?: "table_block" | "research_dataset"; table_id?: string; dataset_id?: string; dataset_version?: number; title_hint?: string; chart_kind?: LabChartKind }): Promise<LabChart> {
  const res = await apiFetch(`${API_BASE}/api/draft/${taskId}/lab/charts`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
  if (!res.ok) throw await toError(res);
  return res.json();
}
export async function updateLabChart(taskId: string, chartId: string, input: { title?: string; caption?: string; kind?: LabChartKind; binding?: LabBinding; appearance?: LabAppearance }): Promise<LabChart> {
  const res = await apiFetch(`${API_BASE}/api/draft/${taskId}/lab/charts/${encodeURIComponent(chartId)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
  if (!res.ok) throw await toError(res);
  return res.json();
}
export async function recomputeLabChart(taskId: string, chartId: string, chart_kind?: LabChartKind): Promise<LabChart> {
  const res = await apiFetch(`${API_BASE}/api/draft/${taskId}/lab/charts/${encodeURIComponent(chartId)}/recompute`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ chart_kind }) });
  if (!res.ok) throw await toError(res);
  return res.json();
}
export async function insertLabChart(taskId: string, chartId: string, section_id: string): Promise<LabChart> {
  const res = await apiFetch(`${API_BASE}/api/draft/${taskId}/lab/charts/${encodeURIComponent(chartId)}/insert`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ section_id }) });
  if (!res.ok) throw await toError(res);
  return res.json();
}
export async function inspectDatasetUpload(file: File): Promise<DatasetImportSelection | DatasetImportComplete> {
  const form = new FormData();
  form.append("file", file);
  const res = await apiFetch(`${API_BASE}/api/datasets/import`, { method: "POST", body: form });
  if (!res.ok) throw await toError(res);
  return res.json();
}
export async function importDataset(input: { file?: File; import_token?: string; source_filename?: string; name?: string; description?: string; dataset_id?: string; sheet?: string; task_id?: string }): Promise<DatasetImportSelection | DatasetImportComplete> {
  const form = new FormData();
  if (input.file) form.append("file", input.file);
  if (input.import_token) form.append("import_token", input.import_token);
  if (input.source_filename) form.append("source_filename", input.source_filename);
  if (input.name) form.append("name", input.name);
  if (input.description) form.append("description", input.description);
  if (input.dataset_id) form.append("dataset_id", input.dataset_id);
  if (input.sheet) form.append("sheet", input.sheet);
  if (input.task_id) form.append("task_id", input.task_id);
  const res = await apiFetch(`${API_BASE}/api/datasets/import`, { method: "POST", body: form });
  if (!res.ok) throw await toError(res);
  return res.json();
}
export async function listDatasets(taskId?: string): Promise<DatasetSummary[]> {
  const res = await apiFetch(`${API_BASE}/api/datasets${taskId ? `?task_id=${encodeURIComponent(taskId)}` : ""}`);
  if (!res.ok) throw await toError(res);
  return ((await res.json()) as { datasets: DatasetSummary[] }).datasets;
}
export async function getDataset(datasetId: string): Promise<{ summary: DatasetSummary; versions: DatasetVersion[] } & Record<string, unknown>> {
  const res = await apiFetch(`${API_BASE}/api/datasets/${encodeURIComponent(datasetId)}`);
  if (!res.ok) throw await toError(res);
  return res.json();
}
export async function getDatasetVersions(datasetId: string): Promise<DatasetVersion[]> {
  const res = await apiFetch(`${API_BASE}/api/datasets/${encodeURIComponent(datasetId)}/versions`);
  if (!res.ok) throw await toError(res);
  return ((await res.json()) as { versions: DatasetVersion[] }).versions;
}
export async function getDatasetPreview(datasetId: string, version: number, limit = 50, offset = 0): Promise<DatasetPreview> {
  const res = await apiFetch(`${API_BASE}/api/datasets/${encodeURIComponent(datasetId)}/versions/${version}/preview?limit=${limit}&offset=${offset}`);
  if (!res.ok) throw await toError(res);
  return res.json();
}
export async function attachDataset(datasetId: string, taskId: string): Promise<DatasetSummary> {
  const form = new FormData();
  form.append("task_id", taskId);
  const res = await apiFetch(`${API_BASE}/api/datasets/${encodeURIComponent(datasetId)}/attach`, { method: "POST", body: form });
  if (!res.ok) throw await toError(res);
  return ((await res.json()) as { dataset: DatasetSummary }).dataset;
}

export type AnalysisType = "descriptive" | "pearson" | "spearman" | "independent_t" | "anova" | "regression";
export type AnalysisMethod = AnalysisType | "student_t" | "welch_t" | "ols";
export type AnalysisStatus = "ready" | "stale" | "running" | "failed";
export interface Analysis {
  id: string;
  task_id: string;
  dataset_id: string;
  dataset_version: number;
  dataset_version_id: string;
  type: AnalysisType;
  name: string;
  description: string;
  variables: Record<string, unknown>;
  parameters: Record<string, unknown>;
  status: AnalysisStatus;
  stale_reason?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
  last_result_id?: string | null;
}
export interface AnalysisResult {
  id: string;
  analysis_id: string;
  dataset_id: string;
  dataset_version: number;
  dataset_version_id: string;
  result: {
    method: AnalysisMethod;
    numeric?: Array<{ variable: string; count: number; missing: number; mean: number | null; median: number | null; std: number | null; min: number | null; max: number | null; q1: number | null; q3: number | null }>;
    categorical?: Array<{ variable: string; count: number; missing: number; unique: number; frequency: Array<{ category: string; frequency: number; percentage: number }> }>;
    x?: string; y?: string; n?: number; r?: number; rho?: number; p_value?: number; significant?: boolean;
    pairs?: Array<{ x: number; y: number }>;
    group_column?: string; value_column?: string;
    group_a?: string; group_b?: string; n_a?: number; n_b?: number; mean_a?: number; mean_b?: number; std_a?: number; std_b?: number;
    mean_difference?: number; t_statistic?: number; df?: number; effect_size?: number; effect_size_type?: "cohens_d"; effect_size_interpretation?: "negligible" | "small" | "medium" | "large";
    groups?: string[]; group_statistics?: Array<{ group: string; count: number; mean: number; std: number; values?: number[] }>;
    grand_mean?: number; ss_between?: number; ss_within?: number; df_between?: number; df_within?: number; ms_between?: number; ms_within?: number; f_statistic?: number; eta_squared?: number;
    tukey_hsd?: Array<{ group1: string; group2: string; mean_difference: number; p_adjusted: number; lower: number; upper: number; reject: boolean }>;
    assumptions?: Record<string, unknown>;
    analysis_type?: "independent_t" | "regression";
    dependent_variable?: string; predictors?: string[]; raw_sample_size?: number; excluded_rows?: number; exclusion_reason?: string | null;
    r_squared?: number; adjusted_r_squared?: number; f_p_value?: number; df_model?: number; df_resid?: number;
    intercept?: { coefficient: number; standard_error: number; t_statistic: number; p_value: number; ci_lower: number; ci_upper: number };
    coefficients?: Array<{ variable: string; coefficient: number; standard_error: number; standardized_coefficient: number; t_statistic: number; p_value: number; ci_lower: number; ci_upper: number; vif: number }>;
    vif?: Array<{ variable: string; vif: number; status: "ok" | "warning" | "high_multicollinearity" }>;
    points?: Array<{ actual: number; predicted: number; residual: number }>;
  };
  warnings: string[];
  data_fingerprint: string | null;
  status: "ready" | "failed";
  created_at: string;
}
export interface AnalysisCreateInput {
  task_id: string;
  dataset_id: string;
  dataset_version?: number;
  type: AnalysisType;
  name?: string;
  description?: string;
  variables: Record<string, unknown>;
  parameters?: Record<string, unknown>;
}
export async function createAnalysis(input: AnalysisCreateInput): Promise<Analysis> {
  const res = await apiFetch(`${API_BASE}/api/analyses`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
  if (!res.ok) throw await toError(res);
  return ((await res.json()) as { analysis: Analysis }).analysis;
}
export async function listAnalyses(taskId?: string, datasetId?: string): Promise<Analysis[]> {
  const query = new URLSearchParams();
  if (taskId) query.set("task_id", taskId);
  if (datasetId) query.set("dataset_id", datasetId);
  const res = await apiFetch(`${API_BASE}/api/analyses${query.size ? `?${query.toString()}` : ""}`);
  if (!res.ok) throw await toError(res);
  return ((await res.json()) as { analyses: Analysis[] }).analyses;
}
export async function getAnalysis(analysisId: string): Promise<Analysis> {
  const res = await apiFetch(`${API_BASE}/api/analyses/${encodeURIComponent(analysisId)}`);
  if (!res.ok) throw await toError(res);
  return ((await res.json()) as { analysis: Analysis }).analysis;
}
export async function runAnalysis(analysisId: string): Promise<{ analysis: Analysis; result: AnalysisResult }> {
  const res = await apiFetch(`${API_BASE}/api/analyses/${encodeURIComponent(analysisId)}/run`, { method: "POST" });
  if (!res.ok) throw await toError(res);
  return res.json();
}
export async function getAnalysisResult(analysisId: string, resultId?: string): Promise<AnalysisResult> {
  const res = await apiFetch(`${API_BASE}/api/analyses/${encodeURIComponent(analysisId)}/result${resultId ? `?result_id=${encodeURIComponent(resultId)}` : ""}`);
  if (!res.ok) throw await toError(res);
  return ((await res.json()) as { result: AnalysisResult }).result;
}
export async function insertAnalysisResult(analysisId: string, input: { section_id: string; result_id?: string; artifact: "table" | "chart" | "actual_predicted" | "residual" | "coefficient" }): Promise<{ block: unknown; analysis: Analysis; result: AnalysisResult }> {
  const res = await apiFetch(`${API_BASE}/api/analyses/${encodeURIComponent(analysisId)}/insert`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
  if (!res.ok) throw await toError(res);
  return res.json();
}

export async function adaptInsightChart(taskId: string, insightId: string): Promise<DraftParagraph> {
  const res = await apiFetch(`${API_BASE}/api/draft/${taskId}/insight/${encodeURIComponent(insightId)}/adapt-chart`, { method: "POST" });
  if (!res.ok) throw await toError(res);
  return res.json();
}

export interface ResearchAssistantRecommendation {
  research_goal: string;
  variable_roles: Array<{ variable: string; role: string }>;
  recommended_methods: Array<{ type: AnalysisType; confidence: string; reason: string; variables: string[] }>;
  recommended_charts: Array<{ type: string; reason: string }>;
  required_variables: string[];
  warnings: string[];
}

export interface ResearchAssistantResponse {
  recommendation: ResearchAssistantRecommendation;
  dataset: { dataset_id: string; dataset_version: number; fingerprint: string; row_count: number; schema: DatasetColumn[] };
  provider: "configured_model" | "rule_fallback";
}

export async function getResearchAssistantRecommendation(input: { research_question: string; hypothesis?: string; dataset_id: string; dataset_version: number; model_id?: string }): Promise<ResearchAssistantResponse> {
  const res = await apiFetch(`${API_BASE}/api/research-assistant/recommend`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
  if (!res.ok) throw await toError(res);
  return res.json();
}

export async function runResearchAssistantRecommendation(input: { task_id: string; dataset_id: string; dataset_version: number; method: AnalysisType; variables: Record<string, unknown>; parameters?: Record<string, unknown> }): Promise<{ analysis: Analysis; result: AnalysisResult }> {
  const res = await apiFetch(`${API_BASE}/api/research-assistant/run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
  if (!res.ok) throw await toError(res);
  return res.json();
}

export interface ResearchExplanation {
  id: string;
  analysis_id: string;
  analysis_result_id: string;
  dataset_id: string;
  dataset_version: number;
  dataset_version_id: string;
  data_fingerprint: string;
  model_id: string | null;
  provider: "configured_model" | "rule_based_fallback";
  analysis_summary: string;
  statistical_facts: Array<{ text: string; source: "analysis_result" }>;
  interpretation: string[];
  limitations: string[];
  cautions: string[];
  created_at: string;
}

export async function explainAnalysisResult(input: { analysis_id: string; analysis_result_id: string; model_id?: string }): Promise<ResearchExplanation> {
  const res = await apiFetch(`${API_BASE}/api/research-assistant/explain`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
  if (!res.ok) throw await toError(res);
  return res.json();
}

export interface ResearchFinding { id:string; task_id:string; analysis_id:string; analysis_result_id:string; explanation_id:string; dataset_id:string; dataset_version_id:string; data_fingerprint:string; title:string; paragraphs:string[]; table_references:Array<{id:string;label:string;title:string;number?:number|null;research_object_id?:string|null}>; figure_references:Array<{id:string;label:string;title:string;number?:number|null;research_object_id?:string|null}>; research_object_ids?:string[]; style:Record<string,string>; status:string; created_at:string; }
export interface ResearchObject { id:string; type:"dataset"|"analysis"|"table"|"figure"|"finding"|"literature"|"discussion"; task_id:string; title:string; source_id:string; number:number|null; number_label:string|null; status:string; created_at:string; updated_at:string; }
export interface RenumberResponse { task_id:string; numbering_mode:"global"|"chapter"; numbering_config:{mode:"global"|"chapter"}; figures:Array<{id:string;figure_number:number;title:string}>; tables:Array<{id:string;table_number:number;title:string}>; objects:ResearchObject[]; }
export async function createResearchFinding(input:{task_id:string;analysis_id:string;analysis_result_id:string;explanation_id:string;style:Record<string,string>}):Promise<ResearchFinding>{ const r=await apiFetch(`${API_BASE}/api/research-findings`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(input)}); if(!r.ok) throw await toError(r); return r.json(); }
export async function listResearchFindings(taskId:string):Promise<ResearchFinding[]>{const r=await apiFetch(`${API_BASE}/api/research-findings?task_id=${encodeURIComponent(taskId)}`);if(!r.ok) throw await toError(r);return (await r.json()).findings;}
export async function insertResearchFinding(id:string,section_id:string):Promise<{block:unknown}>{const r=await apiFetch(`${API_BASE}/api/research-findings/${id}/insert`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({section_id})});if(!r.ok) throw await toError(r);return r.json();}
export async function getTaskResearchObjects(taskId:string):Promise<{objects:ResearchObject[]}>{const r=await apiFetch(`${API_BASE}/api/tasks/${taskId}/research-objects`);if(!r.ok) throw await toError(r);return r.json();}
export async function renumberTaskReferences(taskId:string):Promise<RenumberResponse>{const r=await apiFetch(`${API_BASE}/api/tasks/${taskId}/renumber`,{method:"POST"});if(!r.ok) throw await toError(r);return r.json();}
export async function getReferenceCandidates(taskId:string):Promise<{objects:ReferenceCandidate[]}>{const r=await apiFetch(`${API_BASE}/api/tasks/${taskId}/research-objects/references`);if(!r.ok) throw await toError(r);return r.json();}
export async function getCrossReferences(taskId:string):Promise<{references:CrossReference[]}>{const r=await apiFetch(`${API_BASE}/api/tasks/${taskId}/references`);if(!r.ok) throw await toError(r);return r.json();}
export async function insertCrossReference(input:{task_id:string;section_id:string;target_object_id:string;prefix?:string;suffix?:string}):Promise<{reference:CrossReference;block:DraftParagraph}>{const r=await apiFetch(`${API_BASE}/api/tasks/${input.task_id}/references`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({section_id:input.section_id,target_object_id:input.target_object_id,prefix:input.prefix||"如",suffix:input.suffix||"所示"})});if(!r.ok) throw await toError(r);return r.json();}
export async function updateCrossReference(taskId:string,referenceId:string,target_object_id:string):Promise<{reference:CrossReference}>{const r=await apiFetch(`${API_BASE}/api/tasks/${taskId}/references/${referenceId}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({target_object_id})});if(!r.ok) throw await toError(r);return r.json();}
export async function deleteCrossReference(taskId:string,referenceId:string):Promise<{ok:true}>{const r=await apiFetch(`${API_BASE}/api/tasks/${taskId}/references/${referenceId}`,{method:"DELETE"});if(!r.ok) throw await toError(r);return r.json();}
export async function getDatasetImpact(taskId:string,datasetId:string,version:number):Promise<ResearchImpact>{const r=await apiFetch(`${API_BASE}/api/research/impact/dataset/${datasetId}/version/${version}?task_id=${encodeURIComponent(taskId)}`);if(!r.ok) throw await toError(r);return r.json();}
export async function getResearchResults(taskId:string,kind?:string):Promise<{items:DependencyNode[];links:DependencyLink[]}>{const suffix=kind?`&kind=${encodeURIComponent(kind)}`:"";const r=await apiFetch(`${API_BASE}/api/research/results?task_id=${encodeURIComponent(taskId)}${suffix}`);if(!r.ok) throw await toError(r);return r.json();}
export async function getFindingEvidence(findingId:string):Promise<FindingEvidence>{const r=await apiFetch(`${API_BASE}/api/research/findings/${findingId}/evidence`);if(!r.ok) throw await toError(r);return r.json();}
export type HypothesisDirection = "positive"|"negative"|"difference"|"association"|"unknown";
export type HypothesisDecision = "pending"|"supported"|"not_supported"|"insufficient_evidence"|"inconclusive";
export interface ResearchHypothesis { id:string; task_id:string; title:string; statement:string; direction:HypothesisDirection; status:HypothesisDecision; variable_bindings:Record<string,unknown>; analysis_ids:string[]; latest_evaluation_id?:string; evaluation_status?:string; created_at:string; updated_at:string; }
export interface HypothesisEvaluation { id:string; hypothesis_id:string; task_id:string; analysis_id:string; analysis_result_id:string; dataset_id:string; dataset_version:number; dataset_version_id:string; data_fingerprint:string; decision:Exclude<HypothesisDecision,"pending">; evidence:Record<string,unknown>; data_status:"current"|"stale_source"|"missing"; created_at:string; }
export interface DiscussionFramework { id:string; task_id:string; hypothesis_ids:string[]; finding_ids:string[]; evaluation_ids:string[]; literature_evidence_ids?:string[]; sections:Record<string,unknown>; provider:string; status:"current"|"stale_source"; created_at:string; }
export async function createResearchHypothesis(input:{task_id:string;title?:string;statement:string;direction?:HypothesisDirection;variable_bindings?:Record<string,unknown>;analysis_ids?:string[]}):Promise<ResearchHypothesis>{const r=await apiFetch(`${API_BASE}/api/research/hypotheses`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(input)});if(!r.ok) throw await toError(r);return r.json();}
export async function listResearchHypotheses(taskId:string):Promise<ResearchHypothesis[]>{const r=await apiFetch(`${API_BASE}/api/research/hypotheses?task_id=${encodeURIComponent(taskId)}`);if(!r.ok) throw await toError(r);return (await r.json()).hypotheses;}
export async function updateResearchHypothesis(id:string,changes:Partial<Pick<ResearchHypothesis,"title"|"statement"|"direction"|"variable_bindings"|"analysis_ids">>):Promise<ResearchHypothesis>{const r=await apiFetch(`${API_BASE}/api/research/hypotheses/${id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(changes)});if(!r.ok) throw await toError(r);return r.json();}
export async function evaluateResearchHypothesis(id:string,analysis_id:string,analysis_result_id:string):Promise<HypothesisEvaluation>{const r=await apiFetch(`${API_BASE}/api/research/hypotheses/${id}/evaluate`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({analysis_id,analysis_result_id})});if(!r.ok) throw await toError(r);return r.json();}
export async function getHypothesisEvaluations(id:string):Promise<HypothesisEvaluation[]>{const r=await apiFetch(`${API_BASE}/api/research/hypotheses/${id}/evaluations`);if(!r.ok) throw await toError(r);return (await r.json()).evaluations;}
export async function createDiscussionFramework(input:{task_id:string;hypothesis_ids:string[];finding_ids?:string[];evaluation_ids?:string[]}):Promise<DiscussionFramework>{const r=await apiFetch(`${API_BASE}/api/research/discussion/framework`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(input)});if(!r.ok) throw await toError(r);return r.json();}
export async function getDiscussionFramework(id:string):Promise<DiscussionFramework>{const r=await apiFetch(`${API_BASE}/api/research/discussion/framework/${id}`);if(!r.ok) throw await toError(r);return r.json();}
export async function listDiscussionFrameworks(taskId:string):Promise<DiscussionFramework[]>{const r=await apiFetch(`${API_BASE}/api/research/discussion/frameworks?task_id=${encodeURIComponent(taskId)}`);if(!r.ok) throw await toError(r);return (await r.json()).frameworks;}
export type DiscussionSectionType="main_findings"|"hypothesis_discussion"|"literature_comparison"|"possible_explanations"|"theoretical_implications"|"practical_implications"|"limitations";
export interface DiscussionParagraph { text:string; evidence_refs:string[]; kind:string; }
export interface DiscussionDraft { id:string; task_id:string; framework_id:string; hypothesis_ids:string[]; finding_ids:string[]; literature_evidence_ids:string[]; sections:Record<string,{type:DiscussionSectionType;paragraphs:DiscussionParagraph[]}>; style:Record<string,string>; status:"draft"|"ready"|"stale"|"failed"; provider:string; model_id?:string|null; source_snapshot:{dataset_version_ids:string[];analysis_result_ids:string[];explanation_ids:string[];literature_evidence_ids:string[];data_fingerprints:string[]}; fact_package:Record<string,unknown>; created_at:string; updated_at:string; inserted_block_ids?:string[]; }
export type DiscussionSelection={task_id:string;framework_id:string;hypothesis_ids?:string[];finding_ids?:string[];literature_evidence_ids?:string[];research_context?:string;practical_context?:string};
export async function getDiscussionFactPackage(input:DiscussionSelection):Promise<Record<string,unknown>>{const r=await apiFetch(`${API_BASE}/api/research/discussion/fact-package`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(input)});if(!r.ok) throw await toError(r);return r.json();}
export async function generateDiscussionDraft(input:DiscussionSelection & {section_type:DiscussionSectionType;style?:Record<string,string>;model_id?:string}):Promise<DiscussionDraft>{const r=await apiFetch(`${API_BASE}/api/research/discussion/drafts`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(input)});if(!r.ok) throw await toError(r);return r.json();}
export async function listDiscussionDrafts(taskId:string,frameworkId?:string):Promise<DiscussionDraft[]>{const suffix=frameworkId?`&framework_id=${encodeURIComponent(frameworkId)}`:"";const r=await apiFetch(`${API_BASE}/api/research/discussion/drafts?task_id=${encodeURIComponent(taskId)}${suffix}`);if(!r.ok) throw await toError(r);return (await r.json()).drafts;}
export async function getDiscussionDraft(id:string):Promise<DiscussionDraft>{const r=await apiFetch(`${API_BASE}/api/research/discussion/drafts/${id}`);if(!r.ok) throw await toError(r);return r.json();}
export async function getDiscussionDraftEvidence(id:string):Promise<Record<string,unknown>>{const r=await apiFetch(`${API_BASE}/api/research/discussion/drafts/${id}/evidence`);if(!r.ok) throw await toError(r);return r.json();}
export async function insertDiscussionDraft(id:string,section_id:string):Promise<{blocks:DraftParagraph[]}>{const r=await apiFetch(`${API_BASE}/api/research/discussion/drafts/${id}/insert`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({section_id})});if(!r.ok) throw await toError(r);return r.json();}
export async function getHypothesisEvaluationEvidence(id:string):Promise<Record<string,unknown>>{const r=await apiFetch(`${API_BASE}/api/research/hypothesis-evaluations/${id}/evidence`);if(!r.ok) throw await toError(r);return r.json();}
export interface Literature { id:string; task_id:string; title:string; authors:string[]; year?:number|null; journal:string; volume:string; issue:string; pages:string; doi:string; url:string; abstract:string; publisher:string; source:"crossref"|"openalex"|"pubmed"|"manual"; source_id:string; external_id:string; keywords:string[]; user_note:string; status:"active"|"deleted"; metadata_updated:boolean; created_at:string; updated_at:string; }
export interface LiteratureEvidence { id:string; literature_id:string; claim:string; evidence:string; source_location:"abstract"|"metadata"|"user_note"; confidence:string; created_at:string; }
export interface HypothesisLiterature { link:{id:string;hypothesis_id:string;literature_id:string;relation:"supporting"|"contradicting"|"contextual"|"related"}; literature:Literature|null; evidence:LiteratureEvidence[]; }
export interface LiteratureCitation { id:string; task_id:string; literature_id:string; style:string; display_label:string; resolved_label?:string; source_block_id:string; status:"ready"|"broken"; created_at:string; updated_at:string; }
export async function searchLiterature(input:{query?:string;title?:string;author?:string;year_from?:number;year_to?:number;doi?:string;sources?:string[];limit?:number}):Promise<{results:Omit<Literature,"id"|"task_id"|"status"|"metadata_updated"|"created_at"|"updated_at"|"user_note">[];cached:boolean;warning:string}>{const r=await apiFetch(`${API_BASE}/api/research/literature/search`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(input)});if(!r.ok) throw await toError(r);return r.json();}
export async function listLiterature(taskId:string):Promise<Literature[]>{const r=await apiFetch(`${API_BASE}/api/research/literature?task_id=${encodeURIComponent(taskId)}`);if(!r.ok) throw await toError(r);return (await r.json()).literature;}
export async function getLiterature(id:string):Promise<Literature & {evidence:LiteratureEvidence[];hypothesis_links:Array<Record<string,unknown>>;citations:LiteratureCitation[]}>{const r=await apiFetch(`${API_BASE}/api/research/literature/${id}`);if(!r.ok) throw await toError(r);return r.json();}
export async function saveLiterature(task_id:string,metadata:Record<string,unknown>):Promise<Literature>{const r=await apiFetch(`${API_BASE}/api/research/literature/save`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({task_id,metadata})});if(!r.ok) throw await toError(r);return r.json();}
export async function updateLiterature(id:string,changes:Partial<Literature>):Promise<Literature>{const r=await apiFetch(`${API_BASE}/api/research/literature/${id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(changes)});if(!r.ok) throw await toError(r);return r.json();}
export async function deleteLiterature(id:string):Promise<Literature>{const r=await apiFetch(`${API_BASE}/api/research/literature/${id}`,{method:"DELETE"});if(!r.ok) throw await toError(r);return r.json();}
export async function addLiteratureEvidence(id:string,input:{claim:string;evidence:string;source_location:"abstract"|"metadata"|"user_note";confidence?:string}):Promise<LiteratureEvidence>{const r=await apiFetch(`${API_BASE}/api/research/literature/${id}/evidence`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(input)});if(!r.ok) throw await toError(r);return r.json();}
export async function getLiteratureEvidence(id:string):Promise<LiteratureEvidence[]>{const r=await apiFetch(`${API_BASE}/api/research/literature/${id}/evidence`);if(!r.ok) throw await toError(r);return (await r.json()).evidence;}
export async function linkHypothesisLiterature(id:string,input:{task_id:string;literature_id:string;relation:"supporting"|"contradicting"|"contextual"|"related"}):Promise<Record<string,unknown>>{const r=await apiFetch(`${API_BASE}/api/research/hypotheses/${id}/literature`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(input)});if(!r.ok) throw await toError(r);return r.json();}
export async function getHypothesisLiterature(id:string,taskId:string):Promise<HypothesisLiterature[]>{const r=await apiFetch(`${API_BASE}/api/research/hypotheses/${id}/literature?task_id=${encodeURIComponent(taskId)}`);if(!r.ok) throw await toError(r);return (await r.json()).items;}
export async function createLiteratureCitation(input:{task_id:string;literature_id:string;style?:string;section_id?:string;prefix?:string;suffix?:string}):Promise<{citation:LiteratureCitation;block?:DraftParagraph}>{const r=await apiFetch(`${API_BASE}/api/research/literature/citations`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(input)});if(!r.ok) throw await toError(r);return r.json();}
export async function listLiteratureCitations(taskId:string):Promise<LiteratureCitation[]>{const r=await apiFetch(`${API_BASE}/api/research/literature/citations?task_id=${encodeURIComponent(taskId)}`);if(!r.ok) throw await toError(r);return (await r.json()).citations;}

export type WorkspaceStatus = "ready"|"stale"|"broken"|"failed"|"draft"|"pending"|"metadata_updated";
export interface WorkspaceItem { id:string; title?:string; name?:string; status?:WorkspaceStatus|string; updated_at?:string|null; number_label?:string|null; latest_version?:number|null; latest_result_id?:string|null; latest_evaluation_id?:string|null; row_count?:number|null; column_count?:number|null; type?:string; year?:number|null; sections?:string[]; }
export interface WorkspaceCollection { count:number; stale_count?:number; failed_count?:number; updated_at?:string|null; items:WorkspaceItem[]; latest_version?:number|null; citation_count?:number; broken_citations?:number; evaluation_count?:number; needs_refresh_count?:number; decisions?:Record<string,number>; }
export interface WorkspaceIssue { code:string; status:"stale"|"broken"|"failed"; count:number; message:string; href:string; }
export interface ResearchWorkflowTemplate { id:"survey"|"experiment"|"empirical"|"custom"; name:string; description:string; steps:string[]; }
export interface ResearchWorkspace { project:{task_id:string;title:string;paper_type:string;updated_at?:string|null;has_paper:boolean;sections:Array<{id:string;title:string;number:string}>}; datasets:WorkspaceCollection; analyses:WorkspaceCollection; charts:WorkspaceCollection; tables:WorkspaceCollection; hypotheses:WorkspaceCollection; findings:WorkspaceCollection; literature:WorkspaceCollection; discussion:WorkspaceCollection; issues:WorkspaceIssue[]; impact_summary:{stale_analyses:number;stale_figures:number;broken_citations:number;relationship_count:number;needs_attention:number;href:string}; templates:ResearchWorkflowTemplate[]; generated_at:string; }
export type WorkspaceInsertType="analysis_result"|"table"|"figure"|"finding"|"discussion_draft"|"hypothesis_evaluation";
export interface WorkspaceInsertInput { task_id:string;source_type:WorkspaceInsertType;source_id:string;section_id:string;analysis_id?:string;artifact?:"table"|"chart"|"actual_predicted"|"residual"|"coefficient"; }
export interface WorkspaceInsertPreview { requires_confirmation:boolean;preview:{source_type:WorkspaceInsertType;source_id:string;section_id:string;section_title:string;artifact:string;title:string;source_summary:string;will_insert:string;decision?:string}; }
export async function getResearchWorkspace(taskId:string):Promise<ResearchWorkspace>{const r=await apiFetch(`${API_BASE}/api/research/workspace/${encodeURIComponent(taskId)}`);if(!r.ok)throw await toError(r);return r.json();}
export async function getResearchWorkflowTemplates():Promise<ResearchWorkflowTemplate[]>{const r=await apiFetch(`${API_BASE}/api/research/workspace/templates`);if(!r.ok)throw await toError(r);return (await r.json()).templates;}
export async function previewWorkspaceInsert(input:WorkspaceInsertInput):Promise<WorkspaceInsertPreview>{const r=await apiFetch(`${API_BASE}/api/research/workspace/insert-preview`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(input)});if(!r.ok)throw await toError(r);return r.json();}
export async function confirmWorkspaceInsert(input:WorkspaceInsertInput):Promise<{preview:WorkspaceInsertPreview["preview"];inserted:unknown}>{const r=await apiFetch(`${API_BASE}/api/research/workspace/insert`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...input,confirmed:true})});if(!r.ok)throw await toError(r);return r.json();}


export type EvidenceVerificationStatus =
  | "verified"
  | "pending"
  | "conflict"
  | "broken";

export interface ResearchSearchPlan {
  id: string;
  task_id: string;
  topic: string;
  chapter: string;
  research_question: string;
  queries: string[];
  providers: string[];
  provider: "configured_model" | "rule_fallback";
  status: string;
  created_at: string;
  updated_at: string;
  search_results?: Literature[];
  saved_literature_count?: number;
}

export interface ResearchEvidence {
  id: string;
  task_id: string;
  subject: string;
  metric: string;
  value: number;
  unit: string;
  canonical_value?: number;
  canonical_unit?: string;
  source_type: string;
  source_id: string;
  source_title: string;
  source_location: string;
  source_quote: string;
  year?: number | null;
  device_model?: string;
  test_condition?: string;
  verification_status: EvidenceVerificationStatus;
  verification_issues?: string[];
  created_at: string;
  updated_at: string;
}

export interface ResearchVisualizationCandidate {
  id: string;
  task_id: string;
  kind: "table" | "chart" | "dataset_chart";
  table_type?: string;
  chart_kind?: string;
  title: string;
  reason: string;
  status: "ready" | "pending" | "stale" | "broken" | "inserted";
  requires_confirmation: boolean;
  evidence_ids?: string[];
  source_snapshot?: Array<{
    source_type: string;
    source_id: string;
    source_title: string;
    verification_status: string;
  }>;
  table_spec?: {
    title: string;
    headers: string[];
    rows: Array<Array<string | number>>;
  };
  chart?: {
    chart_id: string;
    dataset_id: string;
    dataset_version: number;
    asset?: { png_path?: string; svg_path?: string };
  };
  dataset_id?: string;
  dataset_version?: number;
  inserted_block_ids?: string[];
}

export async function createResearchVisualizationPlan(payload: {
  task_id: string;
  topic: string;
  chapter?: string;
  research_question?: string;
  model_id?: string;
}): Promise<{ plan: ResearchSearchPlan }> {
  return postJson("/api/research/visualizations/plan", payload);
}

export async function getResearchVisualizationPlan(taskId: string): Promise<{ plan: ResearchSearchPlan }> {
  const res = await apiFetch(`${API_BASE}/api/research/visualizations/${encodeURIComponent(taskId)}/plan`);
  if (!res.ok) throw await toError(res);
  return res.json();
}

export async function searchResearchVisualizationSources(payload: {
  task_id: string;
  limit?: number;
}): Promise<{ plan: ResearchSearchPlan; results: Literature[]; saved_literature: Literature[] }> {
  return postJson("/api/research/visualizations/search", payload);
}

export async function saveResearchVisualizationSources(payload: {
  task_id: string;
  sources: Array<Record<string, unknown>>;
}): Promise<{ literature: Literature[] }> {
  return postJson("/api/research/visualizations/sources", payload);
}

export async function listResearchEvidence(taskId: string): Promise<{ evidence: ResearchEvidence[] }> {
  const res = await apiFetch(`${API_BASE}/api/research/visualizations/${encodeURIComponent(taskId)}/evidence`);
  if (!res.ok) throw await toError(res);
  return res.json();
}

export async function extractResearchEvidence(payload: {
  task_id: string;
  literature_ids?: string[];
}): Promise<{ evidence: ResearchEvidence[] }> {
  return postJson("/api/research/visualizations/extract", payload);
}

export async function addManualResearchEvidence(payload: {
  task_id: string;
  subject: string;
  metric: string;
  value: number;
  unit: string;
  source_title: string;
  source_location: string;
  source_quote: string;
  source_type?: string;
  source_id?: string;
  year?: number;
  device_model?: string;
  test_condition?: string;
}): Promise<{ evidence: ResearchEvidence }> {
  return postJson("/api/research/visualizations/evidence/manual", payload);
}

export async function verifyResearchEvidence(payload: {
  task_id: string;
  evidence_ids?: string[];
}): Promise<{ evidence: ResearchEvidence[] }> {
  return postJson("/api/research/visualizations/verify", payload);
}

export async function recommendResearchVisualizations(payload: {
  task_id: string;
  section?: string;
  evidence_ids?: string[];
  dataset_id?: string;
  dataset_version?: number;
}): Promise<{ candidates: ResearchVisualizationCandidate[] }> {
  return postJson("/api/research/visualizations/recommend", payload);
}

export async function listResearchVisualizationCandidates(taskId: string): Promise<{ candidates: ResearchVisualizationCandidate[] }> {
  const res = await apiFetch(`${API_BASE}/api/research/visualizations/${encodeURIComponent(taskId)}/candidates`);
  if (!res.ok) throw await toError(res);
  return res.json();
}

export async function previewResearchVisualizationCandidate(candidateId: string): Promise<{
  requires_confirmation: boolean;
  candidate: ResearchVisualizationCandidate;
}> {
  const res = await apiFetch(`${API_BASE}/api/research/visualizations/candidate/${encodeURIComponent(candidateId)}/preview`);
  if (!res.ok) throw await toError(res);
  return res.json();
}

export async function insertResearchVisualizationCandidate(candidateId: string, payload: {
  section_id: string;
  confirmed: boolean;
}): Promise<Record<string, unknown>> {
  return postJson(`/api/research/visualizations/candidate/${encodeURIComponent(candidateId)}/insert`, payload);
}
