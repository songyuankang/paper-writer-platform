import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteTemplateRecord,
  duplicateTemplate,
  getTemplateDetail,
  listTemplates,
  setDefaultTemplate,
  updateTemplate,
  type TemplateDetail,
  type TemplatePageInput,
  type TemplateReferenceStyle,
  type TemplateStyleInput,
  type TemplateSummary,
  type TemplateWritePayload,
} from "../api/paper";
import StyleFieldEditor from "./StyleFieldEditor";

/**
 * 弹窗式「格式排版模板」管理（复用现有 v2 模板系统与 API）。
 *
 * 布局：
 * - 左侧：模板列表（基础模板 / 我的模板 / 学校模板 分组）
 * - 右侧：模板详情分区编辑（页面设置/页眉/页脚/论文标题/摘要/关键词/
 *   Abstract/目录/一~三级标题/正文/参考文献）
 *
 * 关闭：右上角 X 或点击遮罩。
 * 内置/学校模板只读（保存禁用），可「复制为我的模板」后编辑；
 * 我的模板编辑后通过 PUT /api/templates/{id} 保存。
 */

export type TemplateSectionKey =
  | "page"
  | "header"
  | "footer"
  | "title_zh"
  | "abstract"
  | "keywords"
  | "abstract_en"
  | "toc"
  | "heading1"
  | "heading2"
  | "heading3"
  | "body"
  | "references";

const SECTIONS: { key: TemplateSectionKey; label: string }[] = [
  { key: "page", label: "页面设置" },
  { key: "header", label: "页眉" },
  { key: "footer", label: "页脚" },
  { key: "title_zh", label: "论文标题" },
  { key: "abstract", label: "摘要" },
  { key: "keywords", label: "关键词" },
  { key: "abstract_en", label: "Abstract" },
  { key: "toc", label: "目录" },
  { key: "heading1", label: "一级标题" },
  { key: "heading2", label: "二级标题" },
  { key: "heading3", label: "三级标题" },
  { key: "body", label: "正文" },
  { key: "references", label: "参考文献" },
];

/** 区块 key → 可编辑样式角色。 */
const BLOCK_ROLES: Record<string, string[]> = {
  title_zh: ["self"],
  abstract: ["title", "content"],
  keywords: ["label", "content"],
  abstract_en: ["title", "content"],
  heading1: ["self"],
  heading2: ["self"],
  heading3: ["self"],
  body: ["self"],
  toc: ["title", "h1", "h2", "h3"],
  references: ["title", "item"],
};

const ROLE_LABELS: Record<string, string> = {
  self: "正文样式",
  title: "标题样式",
  content: "内容样式",
  label: "标签样式",
  item: "条目样式",
  h1: "一级条目",
  h2: "二级条目",
  h3: "三级条目",
};

const PAGE_SIZES = [
  "A3",
  "A4",
  "A5",
  "B4",
  "B5",
  "Letter",
  "Legal",
  "Tabloid",
];

const REFERENCE_STYLES: { value: string; label: string }[] = [
  { value: "gb7714", label: "GB/T 7714" },
  { value: "apa", label: "APA" },
  { value: "mla", label: "MLA" },
  { value: "chicago", label: "Chicago" },
];

const SOURCE_LABELS: Record<string, string> = {
  builtin: "内置",
  school: "学校",
  mine: "我的",
};

const inputCls =
  "w-full rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-sm text-slate-800 outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100";
const labelCls = "mb-1 block text-xs font-medium text-slate-600";

function defaultStyle(): TemplateStyleInput {
  return {
    font_family: { east_asia: "宋体", latin: "Times New Roman" },
    font_size_pt: 12,
    bold: false,
    italic: false,
    underline: false,
    alignment: "justify",
    line_spacing: { mode: "multiple", value: 1.5 },
    space_before_pt: 0,
    space_after_pt: 0,
    first_line_indent: { unit: "chars", value: 2 },
    keep_with_next: false,
    page_break_before: false,
  };
}

/** localStorage 键：导出时记住上次选择的模板（仅选择模式生效）。 */
const LAST_EXPORT_TEMPLATE_KEY = "paper-writer-last-export-template";

interface TemplateManagerModalProps {
  open: boolean;
  onClose: () => void;
  /** 选择模式：隐藏编辑操作，底部显示「使用该模板」按钮（用于导出前选模板）。 */
  selectMode?: boolean;
  /** 选择模式：点击「使用该模板」时回调 (templateId, templateName)。 */
  onSelectTemplate?: (templateId: string, templateName: string) => void;
}

export default function TemplateManagerModal({
  open,
  onClose,
  selectMode = false,
  onSelectTemplate,
}: TemplateManagerModalProps) {
  const [items, setItems] = useState<TemplateSummary[]>([]);
  const [defaultId, setDefaultId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<TemplateDetail | null>(null);
  const [section, setSection] = useState<TemplateSectionKey>("page");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  const load = useCallback(async (autoSelect = false) => {
    setLoading(true);
    setError(null);
    try {
      const data = await listTemplates();
      setItems(data.items);
      setDefaultId(data.default_id);
      // 首次打开：优先选中上次导出用过的模板（仍有效时），否则默认模板（或第一项）
      if (autoSelect) {
        const remembered = selectMode
          ? localStorage.getItem(LAST_EXPORT_TEMPLATE_KEY)
          : null;
        const rememberedValid =
          remembered !== null && data.items.some((i) => i.id === remembered);
        const target =
          (rememberedValid && remembered) ||
          data.default_id ||
          data.items[0]?.id ||
          null;
        if (target) {
          setSelectedId(target);
          setDraft(await getTemplateDetail(target));
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载模板列表失败");
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (open) {
      setDraft(null);
      setSection("page");
      setError(null);
      setSuccess(null);
      void load(true);
    }
  }, [open, load]);

  async function openDetail(id: string) {
    setSelectedId(id);
    setSection("page");
    setDetailLoading(true);
    setError(null);
    try {
      setDraft(await getTemplateDetail(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载模板详情失败");
      setDraft(null);
    } finally {
      setDetailLoading(false);
    }
  }

  // ---------------- 编辑操作 ----------------

  function patchDraft(patch: Partial<TemplateDetail>) {
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
  }

  function updateBlockStyle(
    blockKey: string,
    role: string,
    style: TemplateStyleInput,
  ) {
    setDraft((prev) => {
      if (!prev) {
        return prev;
      }
      return {
        ...prev,
        blocks: prev.blocks.map((b) =>
          b.key === blockKey
            ? { ...b, styles: { ...b.styles, [role]: style } }
            : b,
        ),
      };
    });
  }

  function blockStyle(blockKey: string, role: string): TemplateStyleInput | null {
    const block = draft?.blocks.find((b) => b.key === blockKey);
    return block?.styles?.[role] ?? null;
  }

  function sectionNavLabel(key: TemplateSectionKey): string {
    if (key === "page" && draft) {
      return `页面设置(${draft.page?.size ?? "A4"})`;
    }
    return SECTIONS.find((s) => s.key === key)?.label ?? key;
  }

  // ---------------- 保存 / 复制 / 默认 / 删除 ----------------

  function buildPayload(): TemplateWritePayload {
    return {
      base_template_id: null,
      name: draft?.name ?? "",
      description: draft?.description ?? "",
      category: draft?.category ?? "",
      paper_type: draft?.paper_type ?? "",
      school_name: draft?.school_name ?? "",
      major: draft?.major ?? "",
      page: draft?.page ?? null,
      header: draft?.header ?? null,
      footer: draft?.footer ?? null,
      numbering: draft?.numbering ?? null,
      toc: draft?.toc ?? null,
      reference_style: draft?.reference_style ?? "gb7714",
      blocks: draft?.blocks ?? null,
    };
  }

  async function handleSave() {
    if (!draft || !draft.editable) {
      return;
    }
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      await updateTemplate(draft.id, buildPayload());
      setSuccess("模板已保存");
      const next = await getTemplateDetail(draft.id);
      setDraft(next);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存模板失败");
    } finally {
      setSaving(false);
    }
  }

  async function handleDuplicate() {
    if (!draft) {
      return;
    }
    const name = window.prompt("副本名称", `${draft.name}（副本）`);
    if (name === null) {
      return;
    }
    setError(null);
    setSuccess(null);
    try {
      const copied = await duplicateTemplate(draft.id, name.trim() || undefined);
      setSuccess("已复制为我的模板");
      await load();
      await openDetail(copied.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "复制模板失败");
    }
  }

  async function handleSetDefault() {
    if (!draft) {
      return;
    }
    setError(null);
    setSuccess(null);
    try {
      await setDefaultTemplate(draft.id);
      setSuccess("已设为默认模板");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "设置默认模板失败");
    }
  }

  async function handleDelete() {
    if (!draft || !draft.editable) {
      return;
    }
    if (!window.confirm(`确定删除模板「${draft.name}」吗？`)) {
      return;
    }
    setError(null);
    setSuccess(null);
    try {
      await deleteTemplateRecord(draft.id);
      setDraft(null);
      setSelectedId(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除模板失败");
    }
  }

  async function handleUpload(file: File | undefined) {
    if (!file) {
      return;
    }
    if (!/\.docx$/i.test(file.name)) {
      setError("仅支持 .docx 模板文件");
      return;
    }
    setUploading(true);
    setError(null);
    setSuccess(null);
    try {
      const { uploadFormatTemplate } = await import("../api/paper");
      const uploaded = await uploadFormatTemplate(
        {
          name: file.name.replace(/\.docx$/i, ""),
          school_name: "",
          major: "",
          paper_type: "",
        },
        file,
      );
      setSuccess(`模板“${uploaded.name}”上传并分析成功`);
      await load();
      await openDetail(uploaded.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传模板失败");
    } finally {
      setUploading(false);
    }
  }

  // ---------------- 分组 ----------------

  const builtinItems = items.filter((i) => i.source === "builtin");
  const mineItems = items.filter((i) => i.source === "mine");
  const schoolItems = items.filter((i) => i.source === "school");
  const selectedItem = items.find((i) => i.id === selectedId) ?? null;

  /** 选择模式：记住本次选择 → 通知父级并关闭弹窗（父级负责导出）。 */
  function handleUseTemplate() {
    if (!selectedItem || !onSelectTemplate) {
      return;
    }
    if (selectMode) {
      localStorage.setItem(LAST_EXPORT_TEMPLATE_KEY, selectedItem.id);
    }
    onSelectTemplate(selectedItem.id, selectedItem.name);
    onClose();
  }

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="flex h-[700px] w-[820px] max-w-[95vw] flex-col overflow-hidden rounded-2xl bg-white shadow-[0_20px_60px_rgba(0,0,0,.25)]">
        {/* 头部 */}
        <div className="flex shrink-0 items-center justify-between border-b border-slate-200 px-6 py-4">
          <div>
            <h2 className="text-lg font-bold text-slate-900">
              格式排版模板
            </h2>
            <p className="mt-0.5 text-xs text-slate-400">
              选择或编辑论文排版模板，保存后用于论文导出排版
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="rounded-full px-2 text-2xl leading-none text-slate-400 transition hover:bg-slate-100 hover:text-slate-800"
          >
            ×
          </button>
        </div>

        {/* 提示条 */}
        {error && (
          <div className="shrink-0 border-b border-red-100 bg-red-50 px-6 py-2 text-xs text-red-700">
            {error}
          </div>
        )}
        {success && (
          <div className="shrink-0 border-b border-emerald-100 bg-emerald-50 px-6 py-2 text-xs text-emerald-700">
            {success}
          </div>
        )}

        <div className="flex min-h-0 flex-1">
          {/* 左侧：模板列表 */}
          <aside className="flex w-[240px] shrink-0 flex-col border-r border-slate-200 bg-slate-50">
            <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
              <span className="text-sm font-bold text-slate-700">模板列表</span>
              <button
                type="button"
                onClick={() => uploadRef.current?.click()}
                disabled={uploading}
                className="rounded-md bg-black px-2.5 py-1 text-xs font-medium text-white transition hover:bg-neutral-700 disabled:opacity-50"
              >
                {uploading ? "分析中…" : "上传 DOCX"}
              </button>
              <input
                ref={uploadRef}
                type="file"
                accept=".docx"
                className="hidden"
                onChange={(e) => {
                  void handleUpload(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto py-2">
              {loading ? (
                <div className="px-4 py-8 text-center text-xs text-slate-400">
                  加载中…
                </div>
              ) : (
                <>
                  <GroupHeader label="基础模板" />
                  {builtinItems.length === 0 && <EmptyGroup />}
                  {builtinItems.map((item) => (
                    <TemplateRow
                      key={item.id}
                      item={item}
                      active={item.id === selectedId}
                      isDefault={item.id === defaultId}
                      onClick={() => void openDetail(item.id)}
                    />
                  ))}
                  <GroupHeader label="我的模板" />
                  {mineItems.length === 0 && <EmptyGroup />}
                  {mineItems.map((item) => (
                    <TemplateRow
                      key={item.id}
                      item={item}
                      active={item.id === selectedId}
                      isDefault={item.id === defaultId}
                      onClick={() => void openDetail(item.id)}
                    />
                  ))}
                  <GroupHeader label="学校模板" />
                  {schoolItems.length === 0 && <EmptyGroup />}
                  {schoolItems.map((item) => (
                    <TemplateRow
                      key={item.id}
                      item={item}
                      active={item.id === selectedId}
                      isDefault={item.id === defaultId}
                      onClick={() => void openDetail(item.id)}
                    />
                  ))}
                </>
              )}
            </div>
          </aside>

          {/* 右侧：模板详情 + 分区编辑 */}
          <main className="flex min-h-0 min-w-0 flex-1 flex-col">
            {detailLoading ? (
              <div className="flex flex-1 items-center justify-center text-sm text-slate-400">
                加载模板配置…
              </div>
            ) : !draft ? (
              <div className="flex flex-1 items-center justify-center px-6 text-center text-sm text-slate-400">
                {loading ? "加载中…" : "从左侧选择一个模板查看 / 编辑配置"}
              </div>
            ) : (
              <>
                {/* 模板信息 + 操作 */}
                <div className="shrink-0 border-b border-slate-100 px-5 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-bold text-slate-900">
                      {draft.name}
                    </span>
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-500">
                      {SOURCE_LABELS[draft.source] ?? draft.source}
                    </span>
                    {draft.id === defaultId && (
                      <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-700">
                        默认
                      </span>
                    )}
                    {draft.category && (
                      <span className="rounded bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-400">
                        {draft.category}
                      </span>
                    )}
                  </div>
                  {!selectMode && (
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                    <button
                      type="button"
                      onClick={() => void handleDuplicate()}
                      className="rounded-md border border-neutral-300 px-2.5 py-1 text-neutral-600 transition hover:border-neutral-400 hover:text-black"
                    >
                      复制
                    </button>
                    {draft.id !== defaultId && (
                      <button
                        type="button"
                        onClick={() => void handleSetDefault()}
                        className="rounded-md border border-slate-300 px-2.5 py-1 text-slate-600 transition hover:border-amber-300 hover:text-amber-700"
                      >
                        设为默认
                      </button>
                    )}
                    {draft.editable && (
                      <>
                        <button
                          type="button"
                          onClick={() => void handleDelete()}
                          className="rounded-md border border-red-200 bg-red-50 px-2.5 py-1 text-red-600 transition hover:bg-red-100"
                        >
                          删除
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleSave()}
                          disabled={saving}
                          className="rounded-md bg-indigo-600 px-3 py-1 font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {saving ? "保存中…" : "保存"}
                        </button>
                      </>
                    )}
                    {!draft.editable && (
                      <span className="text-[11px] text-amber-600">
                        内置 / 学校模板只读，可先「复制」为我的模板再编辑
                      </span>
                    )}
                    </div>
                  )}
                </div>

                {/* 分区导航 + 内容 */}
                <div className="flex min-h-0 flex-1">
                  <nav className="w-[150px] shrink-0 overflow-y-auto border-r border-slate-100 bg-slate-50/60 py-2">
                    {SECTIONS.map((s) => (
                      <button
                        key={s.key}
                        type="button"
                        onClick={() => setSection(s.key)}
                        className={`block w-full px-4 py-1.5 text-left text-xs transition ${
                          section === s.key
                            ? "border-r-2 border-indigo-600 bg-white font-semibold text-indigo-700"
                            : "text-slate-600 hover:bg-white hover:text-slate-800"
                        }`}
                      >
                        {sectionNavLabel(s.key)}
                      </button>
                    ))}
                  </nav>
                  <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
                    <SectionContent
                      draft={draft}
                      section={section}
                      blockStyle={blockStyle}
                      updateBlockStyle={updateBlockStyle}
                      patchDraft={patchDraft}
                    />
                  </div>
                </div>
              </>
            )}
          </main>
        </div>

        {/* 选择模式：底部操作栏 */}
        {selectMode && (
          <div className="flex shrink-0 items-center justify-between border-t border-slate-200 bg-white px-6 py-3">
            <div className="min-w-0 text-xs text-slate-500">
              {selectedItem ? (
                <>
                  已选择：
                  <span className="font-medium text-slate-800">
                    {selectedItem.name}
                  </span>
                </>
              ) : (
                "请选择排版模板（不选则使用默认基础模板）"
              )}
            </div>
            <button
              type="button"
              disabled={!selectedItem}
              onClick={handleUseTemplate}
              className="rounded-lg bg-black px-5 py-2 text-sm font-semibold text-white transition hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              使用该模板
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function GroupHeader({ label }: { label: string }) {
  return (
    <div className="px-4 pb-1 pt-3 text-[11px] font-bold uppercase tracking-wide text-slate-400">
      {label}
    </div>
  );
}

function EmptyGroup() {
  return <div className="px-4 py-1 text-[11px] text-slate-300">暂无</div>;
}

function TemplateRow({
  item,
  active,
  isDefault,
  onClick,
}: {
  item: TemplateSummary;
  active: boolean;
  isDefault: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`block w-full px-4 py-2 text-left transition ${
        active ? "bg-white shadow-sm" : "hover:bg-white/70"
      }`}
    >
      <div className="flex items-center gap-1.5">
        <span
          className={`min-w-0 flex-1 truncate text-[13px] font-medium ${
            active ? "text-indigo-700" : "text-slate-700"
          }`}
        >
          {item.name}
        </span>
        {isDefault && (
          <span className="shrink-0 rounded bg-amber-100 px-1 text-[10px] font-medium text-amber-700">
            默认
          </span>
        )}
      </div>
      {item.school_name && (
        <div className="mt-0.5 truncate text-[11px] text-slate-400">
          {item.school_name}
        </div>
      )}
    </button>
  );
}

interface SectionContentProps {
  draft: TemplateDetail;
  section: TemplateSectionKey;
  blockStyle: (blockKey: string, role: string) => TemplateStyleInput | null;
  updateBlockStyle: (
    blockKey: string,
    role: string,
    style: TemplateStyleInput,
  ) => void;
  patchDraft: (patch: Partial<TemplateDetail>) => void;
}

function SectionContent({
  draft,
  section,
  blockStyle,
  updateBlockStyle,
  patchDraft,
}: SectionContentProps) {
  switch (section) {
    case "page":
      return <PageEditor draft={draft} patchDraft={patchDraft} />;
    case "header":
      return (
        <HeaderFooterEditor
          label="页眉"
          value={draft.header}
          onChange={(next) => patchDraft({ header: next })}
        />
      );
    case "footer":
      return (
        <HeaderFooterEditor
          label="页脚"
          value={draft.footer}
          onChange={(next) => patchDraft({ footer: next })}
        />
      );
    case "toc":
      return <TocEditor draft={draft} patchDraft={patchDraft} updateBlockStyle={updateBlockStyle} />;
    case "references":
      return <ReferencesEditor draft={draft} patchDraft={patchDraft} updateBlockStyle={updateBlockStyle} />;
    default: {
      const roles = BLOCK_ROLES[section] ?? ["self"];
      const block = draft.blocks.find((b) => b.key === section);
      if (!block) {
        return (
          <div className="rounded-lg border border-dashed border-slate-200 px-4 py-8 text-center text-xs text-slate-400">
            该模板未包含此区块（{SECTIONS.find((s) => s.key === section)?.label}）
          </div>
        );
      }
      return (
        <div className="space-y-4">
          {roles.map((role) => (
            <StyleFieldEditor
              key={role}
              title={`${block.label} · ${ROLE_LABELS[role] ?? role}`}
              value={blockStyle(section, role) ?? defaultStyle()}
              onChange={(style) => updateBlockStyle(section, role, style)}
            />
          ))}
        </div>
      );
    }
  }
}

function PageEditor({
  draft,
  patchDraft,
}: {
  draft: TemplateDetail;
  patchDraft: (patch: Partial<TemplateDetail>) => void;
}) {
  const page = draft.page ?? {
    size: "A4",
    orientation: "portrait",
    margins: { top_mm: 25, bottom_mm: 25, left_mm: 30, right_mm: 25 },
  };
  return (
    <div className="space-y-4">
      <h3 className="text-sm font-bold text-slate-800">页面设置</h3>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className={labelCls}>纸张大小</label>
          <select
            className={inputCls}
            value={page.size}
            onChange={(e) =>
              patchDraft({
                page: {
                  ...page,
                  size: e.target.value as TemplatePageInput["size"],
                },
              })
            }
          >
            {PAGE_SIZES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls}>方向</label>
          <select
            className={inputCls}
            value={page.orientation}
            onChange={(e) =>
              patchDraft({
                page: {
                  ...page,
                  orientation: e.target
                    .value as TemplatePageInput["orientation"],
                },
              })
            }
          >
            <option value="portrait">纵向</option>
            <option value="landscape">横向</option>
          </select>
        </div>
        {(
          [
            ["top_mm", "上边距"],
            ["bottom_mm", "下边距"],
            ["left_mm", "左边距"],
            ["right_mm", "右边距"],
          ] as const
        ).map(([key, label]) => (
          <div key={key}>
            <label className={labelCls}>{label}（mm）</label>
            <input
              type="number"
              min={0}
              max={100}
              step={0.5}
              className={inputCls}
              value={page.margins?.[key] ?? 0}
              onChange={(e) =>
                patchDraft({
                  page: {
                    ...page,
                    margins: {
                      top_mm: page.margins?.top_mm ?? 25,
                      bottom_mm: page.margins?.bottom_mm ?? 25,
                      left_mm: page.margins?.left_mm ?? 30,
                      right_mm: page.margins?.right_mm ?? 25,
                      [key]: Number(e.target.value),
                    },
                  },
                })
              }
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function HeaderFooterEditor({
  label,
  value,
  onChange,
}: {
  label: string;
  value: { content: string; style?: TemplateStyleInput | null } | null;
  onChange: (next: { content: string; style?: TemplateStyleInput | null }) => void;
}) {
  return (
    <div className="space-y-4">
      <h3 className="text-sm font-bold text-slate-800">{label}</h3>
      <div>
        <label className={labelCls}>
          {label}内容（支持 {"{page}"} 页码占位）
        </label>
        <input
          className={inputCls}
          value={value?.content ?? ""}
          onChange={(e) => onChange({ content: e.target.value, style: value?.style })}
          maxLength={200}
          placeholder={label === "页脚" ? "{page}" : "如：××大学毕业论文"}
        />
      </div>
      <StyleFieldEditor
        title={`${label}样式`}
        value={value?.style ?? defaultStyle()}
        onChange={(style) => onChange({ content: value?.content ?? "", style })}
      />
    </div>
  );
}

function TocEditor({
  draft,
  patchDraft,
  updateBlockStyle,
}: {
  draft: TemplateDetail;
  patchDraft: (patch: Partial<TemplateDetail>) => void;
  updateBlockStyle: (
    blockKey: string,
    role: string,
    style: TemplateStyleInput,
  ) => void;
}) {
  const toc = draft.toc ?? { enabled: true, include_page_numbers: true };
  return (
    <div className="space-y-4">
      <h3 className="text-sm font-bold text-slate-800">目录</h3>
      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={toc.enabled}
            onChange={(e) =>
              patchDraft({ toc: { ...toc, enabled: e.target.checked } })
            }
            className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
          />
          启用目录
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={toc.include_page_numbers}
            onChange={(e) =>
              patchDraft({
                toc: { ...toc, include_page_numbers: e.target.checked },
              })
            }
            className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
          />
          目录显示页码
        </label>
      </div>
      {(["title", "h1", "h2", "h3"] as const).map((role) => (
        <StyleFieldEditor
          key={role}
          title={`目录 · ${ROLE_LABELS[role] ?? role}`}
          value={
            draft.blocks.find((b) => b.key === "toc")?.styles?.[role] ??
            defaultStyle()
          }
          onChange={(style) => updateBlockStyle("toc", role, style)}
        />
      ))}
    </div>
  );
}

function ReferencesEditor({
  draft,
  patchDraft,
  updateBlockStyle,
}: {
  draft: TemplateDetail;
  patchDraft: (patch: Partial<TemplateDetail>) => void;
  updateBlockStyle: (
    blockKey: string,
    role: string,
    style: TemplateStyleInput,
  ) => void;
}) {
  return (
    <div className="space-y-4">
      <h3 className="text-sm font-bold text-slate-800">参考文献</h3>
      <div>
        <label className={labelCls}>引用格式</label>
        <select
          className={`${inputCls} max-w-xs`}
          value={draft.reference_style ?? "gb7714"}
          onChange={(e) =>
            patchDraft({
              reference_style: e.target.value as TemplateReferenceStyle,
            })
          }
        >
          {REFERENCE_STYLES.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </div>
      {(["title", "item"] as const).map((role) => (
        <StyleFieldEditor
          key={role}
          title={`参考文献 · ${ROLE_LABELS[role] ?? role}`}
          value={
            draft.blocks.find((b) => b.key === "references")?.styles?.[role] ??
            defaultStyle()
          }
          onChange={(style) => updateBlockStyle("references", role, style)}
        />
      ))}
    </div>
  );
}
