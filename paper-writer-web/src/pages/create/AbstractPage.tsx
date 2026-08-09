import {
  inputCls,
  useCreateWizard,
} from "./CreateWizardContext";

export default function AbstractPage() {
  const {
    abstract,
    setAbstract,
    setKeywords,
    keywordsText,
    setKeywordsText,
    abstractLoading,
    abstractError,
    error,
    submitting,
    loadAbstract,
    handleNext,
    goStep,
  } = useCreateWizard();

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-bold text-slate-800">
          请选择一个最优的论文摘要
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          可编辑或点击「新建一条」重新生成，定稿后论文将使用这份摘要
        </p>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <label className="text-sm font-medium text-slate-700">
            论文摘要
          </label>
          <button
            type="button"
            onClick={loadAbstract}
            disabled={abstractLoading}
            className="rounded-lg border border-neutral-300 bg-white px-3 py-1.5 text-xs font-medium text-neutral-700 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {abstractLoading ? "生成中…" : "✨ 新建一条"}
          </button>
        </div>
        <textarea
          value={abstract}
          onChange={(e) => setAbstract(e.target.value)}
          placeholder={
            abstractLoading
              ? "正在生成摘要…"
              : "请输入论文摘要（可自行填写或点击「新建一条」由 AI 生成）"
          }
          rows={10}
          className={`${inputCls} leading-relaxed ${abstractLoading ? "opacity-60" : ""}`}
        />
        <p className="mt-1 text-right text-xs text-slate-400">
          {abstract.length} 字
        </p>
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-slate-700">
          关键词（用逗号分隔）
        </label>
        <input
          value={keywordsText}
          onChange={(e) => {
            setKeywordsText(e.target.value);
            setKeywords(
              e.target.value
                .split(/[,，]/)
                .map((k) => k.trim())
                .filter(Boolean),
            );
          }}
          placeholder="例如：深度学习，图像识别，智能制造"
          className={inputCls}
        />
      </div>

      {abstractError && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
          摘要生成失败：{abstractError}
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between pt-2">
        <button
          type="button"
          onClick={() => goStep(1)}
          className="rounded-xl border border-neutral-300 px-4 py-2 text-sm text-neutral-600 transition hover:border-neutral-400"
        >
          ← 返回选题
        </button>
        <button
          type="button"
          onClick={handleNext}
          disabled={submitting || !abstract.trim()}
          className="rounded-xl bg-black px-8 py-2.5 text-sm font-semibold text-white transition hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? "提交中…" : "下一步"}
        </button>
      </div>
    </div>
  );
}
