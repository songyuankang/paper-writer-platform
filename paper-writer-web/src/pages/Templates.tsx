import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  createTemplate,
  deleteTemplateRecord,
  duplicateTemplate,
  getTemplateDetail,
  listTemplates,
  setDefaultTemplate,
  updateTemplate,
  uploadFormatTemplate,
  type TemplateDetail,
  type TemplateSummary,
  type TemplateWritePayload,
} from "../api/paper";
import TemplateEditor from "../components/TemplateEditor";

type FilterValue = "all" | "builtin" | "school" | "mine";

const FILTERS: { value: FilterValue; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "builtin", label: "内置" },
  { value: "school", label: "学校" },
  { value: "mine", label: "我的" },
];

const SOURCE_LABELS: Record<TemplateSummary["source"], string> = {
  builtin: "内置",
  school: "学校",
  mine: "我的",
};

function formatDate(iso: string): string {
  if (!iso) {
    return "";
  }
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return iso;
  }
  return d.toLocaleDateString("zh-CN");
}

interface EditorState {
  mode: "new" | "edit";
  template: TemplateDetail | null;
  baseId: string | null;
}

export default function Templates() {
  const [items, setItems] = useState<TemplateSummary[]>([]);
  const [defaultId, setDefaultId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TemplateDetail | null>(null);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterValue>("all");
  const [query, setQuery] = useState("");
  const uploadRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await listTemplates();
      setItems(data.items);
      setDefaultId(data.default_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载模板列表失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function openDetail(id: string) {
    setError(null);
    try {
      setDetail(await getTemplateDetail(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载模板详情失败");
    }
  }

  async function startCreate() {
    const baseId = defaultId ?? items[0]?.id ?? null;
    if (!baseId) {
      setError("没有可用基础模板");
      return;
    }
    setError(null);
    try {
      const base = await getTemplateDetail(baseId);
      setEditor({
        mode: "new",
        baseId,
        template: {
          ...base,
          name: "",
          description: "",
          paper_type: base.category ?? "",
        },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载基础模板失败");
    }
  }

  async function startEdit(id: string) {
    setError(null);
    try {
      setEditor({
        mode: "edit",
        baseId: null,
        template: await getTemplateDetail(id),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载模板失败");
    }
  }

  async function saveTemplate(payload: TemplateWritePayload) {
    if (!editor) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (editor.mode === "new") {
        await createTemplate(payload);
      } else if (editor.template) {
        await updateTemplate(editor.template.id, payload);
      }
      setEditor(null);
      setDetail(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存模板失败");
    } finally {
      setSaving(false);
    }
  }

  async function duplicate(item: TemplateSummary) {
    setError(null);
    const name = window.prompt("副本名称", `${item.name}（副本）`);
    if (name === null) {
      return;
    }
    try {
      await duplicateTemplate(item.id, name.trim() || undefined);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "复制模板失败");
    }
  }

  async function remove(item: TemplateSummary) {
    if (!window.confirm(`确定删除模板「${item.name}」吗？`)) {
      return;
    }
    setError(null);
    try {
      await deleteTemplateRecord(item.id);
      if (detail?.id === item.id) {
        setDetail(null);
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除模板失败");
    }
  }

  async function setDefault(item: TemplateSummary) {
    setError(null);
    try {
      await setDefaultTemplate(item.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "设置默认模板失败");
    }
  }

  async function handleUpload(file: File | undefined) {
    if (!file) return;
    if (!/\.docx$/i.test(file.name)) {
      setError("仅支持 .docx 模板文件");
      return;
    }
    const defaultName = file.name.replace(/\.docx$/i, "");
    setUploading(true);
    setError(null);
    setSuccess(null);
    try {
      const uploaded = await uploadFormatTemplate(
        { name: defaultName, school_name: "", major: "", paper_type: "" },
        file,
      );
      await load();
      setSuccess(`模板“${uploaded.name}”上传并分析成功，已加入模板管理。`);
      await openDetail(uploaded.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传模板失败");
    } finally {
      setUploading(false);
    }
  }

  const visible = items.filter((item) => {
    const matchedFilter = filter === "all" || item.source === filter;
    const kw = query.trim().toLowerCase();
    const matchedQuery =
      !kw ||
      item.name.toLowerCase().includes(kw) ||
      item.description.toLowerCase().includes(kw) ||
      item.school_name.toLowerCase().includes(kw) ||
      item.category.toLowerCase().includes(kw);
    return matchedFilter && matchedQuery;
  });

  return (
    <div className="min-h-screen bg-white">
      <header className="sticky top-0 z-20 border-b border-neutral-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-4">
            <Link to="/" className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-black text-sm font-bold text-white">
                论
              </span>
              <span className="text-lg font-bold text-slate-800">
                论文生成助手
              </span>
            </Link>
            <span className="hidden rounded-full bg-neutral-100 px-3 py-1 text-xs font-medium text-neutral-700 sm:inline">
              模板管理
            </span>
          </div>
          <nav className="flex items-center gap-2 text-sm">
            <Link
              to="/create"
              className="rounded-lg px-3 py-1.5 text-slate-600 transition hover:bg-slate-100"
            >
              开始创作
            </Link>
            <Link
              to="/history"
              className="rounded-lg px-3 py-1.5 text-slate-600 transition hover:bg-slate-100"
            >
              历史记录
            </Link>
            <Link
              to="/settings/models"
              className="rounded-lg px-3 py-1.5 text-slate-600 transition hover:bg-slate-100"
            >
              模型设置
            </Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">模板管理</h1>
            <p className="mt-1 text-sm text-slate-500">
              共 {items.length} 个模板
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => uploadRef.current?.click()}
              disabled={uploading}
              className="rounded-lg border border-neutral-300 bg-white px-5 py-2.5 text-sm font-semibold text-slate-700 transition hover:bg-neutral-50 disabled:opacity-50"
            >
              {uploading ? "正在分析…" : "↑ 上传 DOCX 模板"}
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
            <button
              type="button"
              onClick={startCreate}
              className="rounded-lg bg-black px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-neutral-700"
            >
              + 新建模板
            </button>
          </div>
        </div>

        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white p-1">
            {FILTERS.map((f) => (
              <button
                key={f.value}
                type="button"
                onClick={() => setFilter(f.value)}
                className={`rounded-md px-3 py-1.5 text-sm transition ${
                  filter === f.value
                    ? "bg-black text-white"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索模板名称 / 学校 / 分类"
            className="w-full max-w-xs rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm text-neutral-900 outline-none transition focus:border-black focus:ring-2 focus:ring-neutral-200"
          />
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
            {error}
          </div>
        )}
        {success && (
          <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm text-emerald-700">
            {success}
          </div>
        )}

        {loading ? (
          <div className="py-16 text-center text-sm text-slate-400">
            加载中…
          </div>
        ) : visible.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white py-16 text-center text-sm text-slate-400">
            暂无模板
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
            {visible.map((item) => {
              const isDefault = item.id === defaultId;
              return (
                <div
                  key={item.id}
                  className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-4 py-3 last:border-b-0"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-bold text-slate-800">
                        {item.name}
                      </span>
                      <span
                        className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${
                          item.source === "mine"
                            ? "bg-neutral-100 text-neutral-700"
                            : "bg-slate-100 text-slate-500"
                        }`}
                      >
                        {SOURCE_LABELS[item.source]}
                      </span>
                      {isDefault && (
                        <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-700">
                          默认
                        </span>
                      )}
                      {item.has_cover && (
                        <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[11px] font-medium text-emerald-600">
                          封面母版
                        </span>
                      )}
                    </div>
                    <div className="mt-1 truncate text-xs text-slate-500">
                      {[item.category, item.school_name, item.major]
                        .filter(Boolean)
                        .join(" · ") || item.description}
                    </div>
                    <div className="mt-0.5 text-[11px] text-slate-400">
                      {item.description} · 更新于 {formatDate(item.updated_at)}
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2 text-xs">
                    <button
                      type="button"
                      onClick={() => openDetail(item.id)}
                      className="rounded-md border border-neutral-300 px-2.5 py-1.5 text-neutral-600 transition hover:border-neutral-400 hover:text-black"
                    >
                      查看
                    </button>
                    <button
                      type="button"
                      onClick={() => duplicate(item)}
                      className="rounded-md border border-neutral-300 px-2.5 py-1.5 text-neutral-600 transition hover:border-neutral-400 hover:text-black"
                    >
                      复制
                    </button>
                    {!isDefault && (
                      <button
                        type="button"
                        onClick={() => setDefault(item)}
                        className="rounded-md border border-slate-300 px-2.5 py-1.5 text-slate-600 transition hover:border-amber-300 hover:text-amber-700"
                      >
                        设为默认
                      </button>
                    )}
                    {item.editable && (
                      <>
                        <button
                          type="button"
                          onClick={() => startEdit(item.id)}
                          className="rounded-md border border-neutral-200 bg-neutral-100 px-2.5 py-1.5 text-neutral-700 transition hover:bg-neutral-200"
                        >
                          编辑
                        </button>
                        <button
                          type="button"
                          onClick={() => remove(item)}
                          className="rounded-md border border-red-200 bg-red-50 px-2.5 py-1.5 text-red-600 transition hover:bg-red-100"
                        >
                          删除
                        </button>
                      </>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {detail && !editor && (
          <section className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <div>
                <h2 className="text-lg font-bold text-slate-900">
                  {detail.name}
                </h2>
                <p className="mt-1 text-xs text-slate-500">
                  {SOURCE_LABELS[detail.source]} · 分类 {detail.category} ·{" "}
                  论文类型 {detail.paper_type || "未设置"} · 专业{" "}
                  {detail.major || "未设置"}
                </p>
              </div>
              <div className="flex items-center gap-2 text-xs">
                {detail.editable && (
                  <button
                    type="button"
                    onClick={() => startEdit(detail.id)}
                    className="rounded-md border border-neutral-200 bg-neutral-100 px-3 py-1.5 text-neutral-700 transition hover:bg-neutral-200"
                  >
                    编辑
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setDetail(null)}
                  className="rounded-md border border-neutral-300 px-3 py-1.5 text-neutral-600 transition hover:border-neutral-400"
                >
                  关闭
                </button>
              </div>
            </div>
            <div className="grid gap-x-6 gap-y-2 px-5 py-4 text-sm text-slate-600 sm:grid-cols-2 lg:grid-cols-4">
              <div>纸张：{detail.page.size}</div>
              <div>方向：{detail.page.orientation === "portrait" ? "纵向" : "横向"}</div>
              <div>目录：{detail.toc.enabled ? "启用" : "关闭"}</div>
              <div>编号：{detail.numbering.enabled ? "启用" : "关闭"}</div>
              <div>参考文献：{detail.reference_style.toUpperCase()}</div>
              <div>区块：{detail.blocks.length} 个</div>
              <div>版本：v{detail.version}</div>
              <div>更新：{formatDate(detail.updated_at)}</div>
            </div>
          </section>
        )}

        {editor && (
          <section className="mt-6 rounded-xl border border-slate-200 bg-white px-5 py-6">
            <TemplateEditor
              initial={editor.template}
              baseId={editor.baseId}
              isNew={editor.mode === "new"}
              saving={saving}
              onCancel={() => setEditor(null)}
              onSave={saveTemplate}
            />
          </section>
        )}
      </main>
    </div>
  );
}
