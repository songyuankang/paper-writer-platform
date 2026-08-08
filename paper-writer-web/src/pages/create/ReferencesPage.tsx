import { useState } from "react";
import { useCreateWizard } from "./CreateWizardContext";

const SOURCE_LABELS: Record<string, string> = {
  crossref: "CrossRef",
  openalex: "OpenAlex",
  semantic_scholar: "Semantic Scholar",
  arxiv: "arXiv",
};

const SOURCE_FILTERS = [
  { value: "all", label: "全部" },
  { value: "openalex", label: "OpenAlex" },
  { value: "crossref", label: "CrossRef" },
  { value: "semantic_scholar", label: "Semantic Scholar" },
  { value: "arxiv", label: "arXiv" },
];

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
    toggleRef,
    handleNext,
    goStep,
  } = useCreateWizard();
  const [sourceFilter, setSourceFilter] = useState("all");
  const filteredRefs =
    sourceFilter === "all"
      ? refs
      : refs.filter((r) => (r.source_name ?? "crossref") === sourceFilter);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-bold text-slate-800">
          请选择适合的参考文献
        </h2>
        {keywords.length > 0 && (
          <p className="mt-1 text-sm text-slate-500">
            关键词：{keywords.join("，")} · 数据来自 OpenAlex / CrossRef /
            Semantic Scholar / arXiv
          </p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 p-1">
        {SOURCE_FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => setSourceFilter(f.value)}
            className={`rounded-md px-3 py-1.5 text-xs transition ${
              sourceFilter === f.value
                ? "bg-black font-semibold text-white"
                : "text-slate-600 hover:bg-white/60"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-400">
          {refLoading
            ? "正在搜索真实文献…"
            : filteredRefs.length > 0
              ? `显示 ${filteredRefs.length} 条，已选 ${selectedRefs.length} 条`
              : ""}
        </span>
        <button
          type="button"
          onClick={loadReferences}
          disabled={refLoading}
          className="rounded-lg border border-neutral-300 bg-white px-3 py-1.5 text-xs font-medium text-neutral-700 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {refLoading ? "搜索中…" : "🔄 重新搜索"}
        </button>
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
          暂无文献，点击「重新搜索」或稍后重试
        </div>
      ) : (
        <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
          {filteredRefs.map((r, i) => {
            const selected = selectedRefs.includes(r.citation);
            return (
              <div
                key={`${r.doi}-${i}`}
                onClick={() => toggleRef(r.citation)}
                className={`flex cursor-pointer gap-3 rounded-xl border px-4 py-3 transition ${
                  selected
                    ? "border-black bg-neutral-50"
                    : "border-neutral-200 bg-white hover:border-neutral-300"
                }`}
              >
                <input
                  type="checkbox"
                  checked={selected}
                  onChange={() => toggleRef(r.citation)}
                  className="mt-1 h-4 w-4 shrink-0 rounded border-neutral-300 text-black focus:ring-neutral-300"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-sm font-medium text-slate-800">
                      [{i + 1}] {r.title}
                    </span>
                    <span className="shrink-0 rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] font-medium text-neutral-700">
                      {SOURCE_LABELS[r.source_name ?? "crossref"]}
                    </span>
                  </div>
                  <div className="mt-0.5 text-xs text-slate-500">
                    {r.authors ? `作者：${r.authors} · ` : ""}
                    {[r.source, r.year, r.type].filter(Boolean).join(" | ")}
                  </div>
                  {r.abstract && (
                    <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-400">
                      摘要：{r.abstract}
                    </p>
                  )}
                  <p className="mt-1 text-xs text-slate-500">{r.citation}</p>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <p className="text-xs text-slate-400">
        勾选需要引用的文献（默认全选），未勾选将不会出现在论文参考文献中；也可在「在线预览」中再编辑。
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
    </div>
  );
}
