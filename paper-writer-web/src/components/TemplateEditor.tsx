import { useState } from "react";
import type {
  TemplateBlockInput,
  TemplateDetail,
  TemplatePageInput,
  TemplateReferenceStyle,
  TemplateStyleInput,
  TemplateWritePayload,
} from "../api/paper";
import StyleFieldEditor from "./StyleFieldEditor";

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

const REFERENCE_STYLES: {
  value: TemplateReferenceStyle;
  label: string;
}[] = [
  { value: "gb7714", label: "GB/T 7714" },
  { value: "apa", label: "APA" },
  { value: "mla", label: "MLA" },
  { value: "chicago", label: "Chicago" },
];

const STYLE_GROUPS: { key: string; label: string; roles: string[] }[] = [
  { key: "title_zh", label: "论文标题", roles: ["self"] },
  { key: "title_en", label: "英文标题", roles: ["self"] },
  { key: "heading1", label: "一级标题", roles: ["self"] },
  { key: "heading2", label: "二级标题", roles: ["self"] },
  { key: "heading3", label: "三级标题", roles: ["self"] },
  { key: "heading4", label: "四级标题", roles: ["self"] },
  { key: "body", label: "正文", roles: ["self"] },
  { key: "abstract", label: "摘要", roles: ["title", "content"] },
  { key: "keywords", label: "关键词", roles: ["label", "content"] },
  { key: "figure_caption", label: "图题注", roles: ["self"] },
  { key: "table_caption", label: "表题注", roles: ["self"] },
  { key: "references", label: "参考文献", roles: ["title", "item"] },
];

const ROLE_LABELS: Record<string, string> = {
  self: "正文样式",
  title: "标题样式",
  content: "内容样式",
  label: "标签样式",
  item: "条目样式",
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

interface TemplateEditorProps {
  initial: TemplateDetail | null;
  baseId: string | null;
  isNew: boolean;
  saving: boolean;
  onCancel: () => void;
  onSave: (payload: TemplateWritePayload) => Promise<void>;
}

export default function TemplateEditor({
  initial,
  baseId,
  isNew,
  saving,
  onCancel,
  onSave,
}: TemplateEditorProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [category, setCategory] = useState(initial?.category ?? "");
  const [paperType, setPaperType] = useState(initial?.paper_type ?? "");
  const [schoolName, setSchoolName] = useState(initial?.school_name ?? "");
  const [major, setMajor] = useState(initial?.major ?? "");
  const [page, setPage] = useState<TemplatePageInput>(
    initial?.page ?? {
      size: "A4",
      orientation: "portrait",
      margins: { top_mm: 25, bottom_mm: 25, left_mm: 30, right_mm: 25 },
      header_distance_mm: 15,
      footer_distance_mm: 17.5,
    },
  );
  const [numbering, setNumbering] = useState({
    enabled: initial?.numbering.enabled ?? true,
    h1: initial?.numbering.h1 ?? "第{chinese}章",
    h2: initial?.numbering.h2 ?? "{h1}.{n}",
    h3: initial?.numbering.h3 ?? "{h1}.{h2}.{n}",
    h4: initial?.numbering.h4 ?? "{h1}.{h2}.{h3}.{n}",
  });
  const [toc, setToc] = useState({
    enabled: initial?.toc.enabled ?? true,
    include_page_numbers: initial?.toc.include_page_numbers ?? true,
  });
  const [referenceStyle, setReferenceStyle] =
    useState<TemplateReferenceStyle>(initial?.reference_style ?? "gb7714");
  const header = initial?.header ?? null;
  const footer = initial?.footer ?? null;
  const [blocks, setBlocks] = useState<TemplateBlockInput[]>(
    initial?.blocks ?? [],
  );
  const [error, setError] = useState<string | null>(null);

  function updateBlockStyle(
    blockKey: string,
    role: string,
    style: TemplateStyleInput,
  ) {
    setBlocks((prev) =>
      prev.map((b) =>
        b.key === blockKey
          ? { ...b, styles: { ...b.styles, [role]: style } }
          : b,
      ),
    );
  }

  function handleSave() {
    if (!name.trim()) {
      setError("模板名称不能为空");
      return;
    }
    setError(null);
    void onSave({
      base_template_id: isNew ? baseId : null,
      name: name.trim(),
      description,
      category,
      paper_type: paperType,
      school_name: schoolName,
      major,
      page,
      header,
      footer,
      numbering,
      toc,
      reference_style: referenceStyle,
      blocks,
    });
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-slate-800">
            {isNew ? "新建模板" : "编辑模板"}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-600 transition hover:border-indigo-300"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saving ? "保存中…" : "保存模板"}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          {error}
        </div>
      )}

      <section>
        <h3 className="mb-3 text-base font-bold text-slate-800">基本信息</h3>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <label className={labelCls}>模板名称</label>
            <input
              className={inputCls}
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={100}
            />
          </div>
          <div>
            <label className={labelCls}>分类</label>
            <input
              className={inputCls}
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              maxLength={100}
            />
          </div>
          <div>
            <label className={labelCls}>论文类型</label>
            <input
              className={inputCls}
              value={paperType}
              onChange={(e) => setPaperType(e.target.value)}
              maxLength={100}
            />
          </div>
          <div>
            <label className={labelCls}>学校名称</label>
            <input
              className={inputCls}
              value={schoolName}
              onChange={(e) => setSchoolName(e.target.value)}
              maxLength={100}
            />
          </div>
          <div>
            <label className={labelCls}>专业</label>
            <input
              className={inputCls}
              value={major}
              onChange={(e) => setMajor(e.target.value)}
              maxLength={100}
            />
          </div>
          <div className="sm:col-span-2 lg:col-span-1">
            <label className={labelCls}>描述</label>
            <input
              className={inputCls}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={2000}
            />
          </div>
        </div>
      </section>

      <section>
        <h3 className="mb-3 text-base font-bold text-slate-800">页面设置</h3>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <label className={labelCls}>纸张大小</label>
            <select
              className={inputCls}
              value={page.size}
              onChange={(e) =>
                setPage({
                  ...page,
                  size: e.target.value as TemplatePageInput["size"],
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
                setPage({
                  ...page,
                  orientation: e.target
                    .value as TemplatePageInput["orientation"],
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
                value={page.margins[key]}
                onChange={(e) =>
                  setPage({
                    ...page,
                    margins: {
                      ...page.margins,
                      [key]: Number(e.target.value),
                    },
                  })
                }
              />
            </div>
          ))}
          <div>
            <label className={labelCls}>页眉距离（mm）</label>
            <input
              type="number"
              min={0}
              max={50}
              step={0.5}
              className={inputCls}
              value={page.header_distance_mm ?? 0}
              onChange={(e) =>
                setPage({
                  ...page,
                  header_distance_mm: Number(e.target.value),
                })
              }
            />
          </div>
          <div>
            <label className={labelCls}>页脚距离（mm）</label>
            <input
              type="number"
              min={0}
              max={50}
              step={0.5}
              className={inputCls}
              value={page.footer_distance_mm ?? 0}
              onChange={(e) =>
                setPage({
                  ...page,
                  footer_distance_mm: Number(e.target.value),
                })
              }
            />
          </div>
        </div>
      </section>

      <section>
        <h3 className="mb-3 text-base font-bold text-slate-800">标题编号</h3>
        <label className="mb-3 flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={numbering.enabled}
            onChange={(e) =>
              setNumbering((prev) => ({ ...prev, enabled: e.target.checked }))
            }
            className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
          />
          启用自动标题编号
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          {(
            [
              ["h1", "一级标题模式"],
              ["h2", "二级标题模式"],
              ["h3", "三级标题模式"],
              ["h4", "四级标题模式"],
            ] as const
          ).map(([key, label]) => (
            <div key={key}>
              <label className={labelCls}>{label}</label>
              <input
                className={inputCls}
                value={numbering[key]}
                onChange={(e) =>
                  setNumbering((prev) => ({
                    ...prev,
                    [key]: e.target.value,
                  }))
                }
                placeholder="{n}、{chinese}、{h1}.{n} 等"
                maxLength={200}
              />
            </div>
          ))}
        </div>
      </section>

      <section>
        <h3 className="mb-3 text-base font-bold text-slate-800">目录</h3>
        <div className="space-y-2">
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={toc.enabled}
              onChange={(e) =>
                setToc((prev) => ({ ...prev, enabled: e.target.checked }))
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
                setToc((prev) => ({
                  ...prev,
                  include_page_numbers: e.target.checked,
                }))
              }
              className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
            />
            目录显示页码
          </label>
        </div>
      </section>

      <section>
        <h3 className="mb-3 text-base font-bold text-slate-800">参考文献</h3>
        <select
          className={`${inputCls} max-w-sm`}
          value={referenceStyle}
          onChange={(e) =>
            setReferenceStyle(e.target.value as TemplateReferenceStyle)
          }
        >
          {REFERENCE_STYLES.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </section>

      <section>
        <h3 className="mb-3 text-base font-bold text-slate-800">样式</h3>
        <div className="space-y-2">
          {STYLE_GROUPS.map((group) => {
            const block = blocks.find((b) => b.key === group.key);
            if (!block) {
              return null;
            }
            return (
              <div key={group.key}>
                {group.roles.map((role) => (
                  <StyleFieldEditor
                    key={role}
                    title={`${group.label} · ${ROLE_LABELS[role] ?? role}`}
                    value={block.styles[role] ?? defaultStyle()}
                    onChange={(style) =>
                      updateBlockStyle(group.key, role, style)
                    }
                  />
                ))}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
