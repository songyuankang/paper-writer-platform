import { useState, type FormEvent } from "react";
import {
  type ManualReferenceInput,
  type ManualReferenceType,
  type ReferenceItem,
} from "../../api/paper";
import { useCreateWizard } from "./CreateWizardContext";

const SOURCE_LABELS: Record<string, string> = {
  crossref: "CrossRef",
  openalex: "OpenAlex",
  semantic_scholar: "Semantic Scholar",
  arxiv: "arXiv",
  manual: "本地录入",
};

const SOURCE_FILTERS = [
  { value: "all", label: "全部" },
  { value: "manual", label: "手动添加" },
  { value: "openalex", label: "OpenAlex" },
  { value: "crossref", label: "CrossRef" },
  { value: "semantic_scholar", label: "Semantic Scholar" },
  { value: "arxiv", label: "arXiv" },
];

const REFERENCE_TYPES: { value: ManualReferenceType; label: string }[] = [
  { value: "journal", label: "期刊论文" },
  { value: "thesis", label: "学位论文" },
  { value: "conference", label: "会议论文" },
  { value: "book", label: "图书" },
  { value: "report", label: "报告" },
  { value: "web", label: "网络资源" },
  { value: "standard", label: "标准" },
];

const EMPTY_MANUAL_REFERENCE: ManualReferenceInput = {
  reference_type: "journal",
  authors: "",
  title: "",
  source: "",
  year: String(new Date().getFullYear()),
  volume: "",
  issue: "",
  pages: "",
  doi: "",
  url: "",
};

function manualFormFrom(reference?: ReferenceItem): ManualReferenceInput {
  return reference?.manual
    ? { ...reference.manual }
    : { ...EMPTY_MANUAL_REFERENCE };
}

export default function ReferencesPage() {
  const {
    keywords,
    refs,
    selectedRefs,
    refLoading,
    refError,
    error,
    submitting,
    loadReferences,
    saveManualReference,
    deleteManualReference,
    toggleRef,
    handleNext,
    goStep,
  } = useCreateWizard();
  const [sourceFilter, setSourceFilter] = useState("all");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editingReference, setEditingReference] = useState<ReferenceItem | null>(null);
  const [manualForm, setManualForm] = useState<ManualReferenceInput>(
    EMPTY_MANUAL_REFERENCE,
  );
  const [manualSaving, setManualSaving] = useState(false);
  const [manualError, setManualError] = useState<string | null>(null);

  const filteredRefs =
    sourceFilter === "all"
      ? refs
      : refs.filter((r) => (r.source_name ?? "crossref") === sourceFilter);

  function openManualDrawer(reference?: ReferenceItem) {
    setEditingReference(reference ?? null);
    setManualForm(manualFormFrom(reference));
    setManualError(null);
    setDrawerOpen(true);
  }

  function closeManualDrawer() {
    setDrawerOpen(false);
    setEditingReference(null);
    setManualError(null);
  }

  function updateManualField<K extends keyof ManualReferenceInput>(
    key: K,
    value: ManualReferenceInput[K],
  ) {
    setManualForm((previous) => ({ ...previous, [key]: value }));
  }

  async function submitManualReference(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!manualForm.authors.trim() || !manualForm.title.trim() || !manualForm.source.trim()) {
      setManualError("请至少填写作者、题名和期刊/来源");
      return;
    }
    if (!/^\d{4}$/.test(manualForm.year.trim())) {
      setManualError("年份须为 4 位数字，例如 2024");
      return;
    }
    setManualSaving(true);
    setManualError(null);
    try {
      await saveManualReference(
        {
          ...manualForm,
          authors: manualForm.authors.trim(),
          title: manualForm.title.trim(),
          source: manualForm.source.trim(),
          year: manualForm.year.trim(),
          volume: manualForm.volume?.trim() ?? "",
          issue: manualForm.issue?.trim() ?? "",
          pages: manualForm.pages?.trim() ?? "",
          doi: manualForm.doi?.trim() ?? "",
          url: manualForm.url?.trim() ?? "",
        },
        editingReference?.citation,
      );
      closeManualDrawer();
    } catch (requestError) {
      setManualError(
        requestError instanceof Error ? requestError.message : "手动添加文献失败",
      );
    } finally {
      setManualSaving(false);
    }
  }

  function removeManualReference(reference: ReferenceItem) {
    if (!window.confirm(`确定删除手动添加的文献《${reference.title}》吗？`)) return;
    deleteManualReference(reference.citation);
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-bold text-slate-800">请选择适合的参考文献</h2>
        {keywords.length > 0 && (
          <p className="mt-1 text-sm text-slate-500">
            关键词：{keywords.join("，")} · 数据来自 OpenAlex / CrossRef /
            Semantic Scholar / arXiv
          </p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 p-1">
        {SOURCE_FILTERS.map((filter) => (
          <button
            key={filter.value}
            type="button"
            onClick={() => setSourceFilter(filter.value)}
            className={`rounded-md px-3 py-1.5 text-xs transition ${
              sourceFilter === filter.value
                ? "bg-black font-semibold text-white"
                : "text-slate-600 hover:bg-white/60"
            }`}
          >
            {filter.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-slate-400">
          {refLoading
            ? "正在搜索真实文献…"
            : filteredRefs.length > 0
              ? `显示 ${filteredRefs.length} 条，已选 ${selectedRefs.length} 条`
              : "可搜索真实文献，或手动添加本地文献"}
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={loadReferences}
            disabled={refLoading}
            className="rounded-lg border border-neutral-300 bg-white px-3 py-1.5 text-xs font-medium text-neutral-700 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {refLoading ? "搜索中…" : "🔄 重新搜索"}
          </button>
          <button
            type="button"
            onClick={() => openManualDrawer()}
            disabled={refLoading}
            className="rounded-lg border border-black bg-white px-3 py-1.5 text-xs font-semibold text-black transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60"
          >
            + 手动添加文献
          </button>
        </div>
      </div>

      {refError && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
          {refError}
        </div>
      )}

      {refLoading ? (
        <div className="flex flex-col items-center gap-3 py-10 text-center">
          <div className="h-10 w-10 animate-spin rounded-full border-4 border-neutral-200 border-t-black" />
          <p className="text-sm text-slate-500">正在搜索真实参考文献…</p>
        </div>
      ) : filteredRefs.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 py-10 text-center text-sm text-slate-400">
          暂无文献，点击「重新搜索」或「手动添加文献」
        </div>
      ) : (
        <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
          {filteredRefs.map((reference, index) => {
            const selected = selectedRefs.includes(reference.citation);
            const manual = reference.source_name === "manual";
            return (
              <div
                key={`${reference.doi || reference.citation}-${index}`}
                onClick={() => toggleRef(reference.citation)}
                className={`flex cursor-pointer gap-3 rounded-xl border px-4 py-3 transition ${
                  selected
                    ? "border-black bg-neutral-50"
                    : "border-neutral-200 bg-white hover:border-neutral-300"
                }`}
              >
                <input
                  type="checkbox"
                  checked={selected}
                  onClick={(event) => event.stopPropagation()}
                  onChange={() => toggleRef(reference.citation)}
                  className="mt-1 h-4 w-4 shrink-0 rounded border-neutral-300 text-black focus:ring-neutral-300"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-sm font-medium text-slate-800">
                      [{index + 1}] {reference.title}
                    </span>
                    <div className="flex shrink-0 items-center gap-1">
                      {manual && (
                        <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700">
                          手动添加
                        </span>
                      )}
                      <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] font-medium text-neutral-700">
                        {SOURCE_LABELS[reference.source_name ?? "crossref"] ?? "文献"}
                      </span>
                    </div>
                  </div>
                  <div className="mt-0.5 text-xs text-slate-500">
                    {reference.authors ? `作者：${reference.authors} · ` : ""}
                    {[reference.source, reference.year, reference.type].filter(Boolean).join(" | ")}
                  </div>
                  {reference.abstract && (
                    <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-400">
                      摘要：{reference.abstract}
                    </p>
                  )}
                  <p className="mt-1 text-xs text-slate-500">{reference.citation}</p>
                  {manual && (
                    <div className="mt-2 flex gap-3 text-xs">
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          openManualDrawer(reference);
                        }}
                        className="font-medium text-neutral-700 underline underline-offset-2 hover:text-black"
                      >
                        编辑
                      </button>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          removeManualReference(reference);
                        }}
                        className="font-medium text-red-600 underline underline-offset-2 hover:text-red-700"
                      >
                        删除
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <p className="text-xs text-slate-400">
        勾选需要引用的文献（默认全选），未勾选将不会出现在论文参考文献中；手动添加的文献可在本页编辑或删除。
      </p>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between pt-2">
        <button
          type="button"
          onClick={() => goStep(2)}
          className="rounded-xl border border-neutral-300 px-4 py-2 text-sm text-neutral-600 transition hover:border-neutral-400"
        >
          ← 返回摘要
        </button>
        <button
          type="button"
          onClick={handleNext}
          disabled={submitting || selectedRefs.length === 0}
          className="rounded-xl bg-black px-8 py-2.5 text-sm font-semibold text-white transition hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? "提交中…" : "下一步"}
        </button>
      </div>

      {drawerOpen && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/20" role="dialog" aria-modal="true" aria-label="手动添加文献">
          <aside className="flex h-full w-full max-w-xl flex-col bg-white shadow-2xl">
            <div className="flex items-start justify-between border-b border-neutral-200 px-6 py-5">
              <div>
                <h3 className="text-lg font-bold text-neutral-900">
                  {editingReference ? "编辑手动文献" : "手动添加文献"}
                </h3>
                <p className="mt-1 text-xs text-neutral-500">
                  保存后将进入当前候选列表并自动勾选参与后续写作。
                </p>
              </div>
              <button
                type="button"
                onClick={closeManualDrawer}
                disabled={manualSaving}
                aria-label="关闭"
                className="rounded p-1 text-xl leading-none text-neutral-400 hover:bg-neutral-100 hover:text-black disabled:opacity-50"
              >
                ×
              </button>
            </div>

            <form onSubmit={submitManualReference} className="flex min-h-0 flex-1 flex-col">
              <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-5">
                <label className="block text-sm font-medium text-neutral-800">
                  文献类型
                  <select
                    value={manualForm.reference_type}
                    onChange={(event) => updateManualField("reference_type", event.target.value as ManualReferenceType)}
                    className="mt-1.5 w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm outline-none focus:border-black focus:ring-2 focus:ring-neutral-200"
                  >
                    {REFERENCE_TYPES.map((type) => (
                      <option key={type.value} value={type.value}>{type.label}</option>
                    ))}
                  </select>
                </label>
                <Field label="作者" required value={manualForm.authors} onChange={(value) => updateManualField("authors", value)} placeholder="例如：张敏；李华" />
                <Field label="题名" required value={manualForm.title} onChange={(value) => updateManualField("title", value)} placeholder="请输入文献题名" />
                <Field label="期刊 / 来源" required value={manualForm.source} onChange={(value) => updateManualField("source", value)} placeholder="例如：学前教育研究" />
                <div className="grid grid-cols-2 gap-3">
                  <Field label="年份" required value={manualForm.year} onChange={(value) => updateManualField("year", value)} placeholder="2024" inputMode="numeric" />
                  <Field label="卷(期)" value={manualForm.volume ?? ""} onChange={(value) => updateManualField("volume", value)} placeholder="例如：12" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="期号" value={manualForm.issue ?? ""} onChange={(value) => updateManualField("issue", value)} placeholder="例如：3" />
                  <Field label="页码" value={manualForm.pages ?? ""} onChange={(value) => updateManualField("pages", value)} placeholder="例如：45-56" />
                </div>
                <Field label="DOI（可选）" value={manualForm.doi ?? ""} onChange={(value) => updateManualField("doi", value)} placeholder="例如：10.1234/example.2024.003" />
                <Field label="URL（可选）" value={manualForm.url ?? ""} onChange={(value) => updateManualField("url", value)} placeholder="https://…" type="url" />
                <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
                  <p className="text-xs font-semibold text-neutral-700">GB/T 7714 格式预览</p>
                  <p className="mt-1 text-xs leading-relaxed text-neutral-500">
                    保存后由服务端统一格式化，并作为可勾选参考文献进入论文生成。
                  </p>
                </div>
                {manualError && (
                  <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                    {manualError}
                  </div>
                )}
              </div>
              <div className="flex justify-end gap-3 border-t border-neutral-200 px-6 py-4">
                <button type="button" onClick={closeManualDrawer} disabled={manualSaving} className="rounded-lg border border-neutral-300 px-4 py-2 text-sm text-neutral-700 hover:bg-neutral-50 disabled:opacity-50">
                  取消
                </button>
                <button type="submit" disabled={manualSaving} className="rounded-lg bg-black px-4 py-2 text-sm font-semibold text-white hover:bg-neutral-700 disabled:opacity-50">
                  {manualSaving ? "保存中…" : editingReference ? "保存修改" : "添加并勾选"}
                </button>
              </div>
            </form>
          </aside>
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  required = false,
  type = "text",
  inputMode,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  required?: boolean;
  type?: string;
  inputMode?: "numeric";
}) {
  return (
    <label className="block text-sm font-medium text-neutral-800">
      {label}{required && <span className="ml-1 text-red-600">*</span>}
      <input
        type={type}
        value={value}
        required={required}
        inputMode={inputMode}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="mt-1.5 w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm outline-none placeholder:text-neutral-400 focus:border-black focus:ring-2 focus:ring-neutral-200"
      />
    </label>
  );
}
