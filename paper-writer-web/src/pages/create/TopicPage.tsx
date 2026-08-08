import { Link } from "react-router-dom";
import {
  DISCIPLINES,
  MATERIAL_KIND_OPTIONS,
  PAPER_TYPES,
  inputCls,
  useCreateWizard,
} from "./CreateWizardContext";

export default function TopicPage() {
  const {
    paperType,
    setPaperType,
    discipline,
    setDiscipline,
    major,
    setMajor,
    topic,
    setTopic,
    wordCount,
    setWordCount,
    language,
    setLanguage,
    specialRequirements,
    setSpecialRequirements,
    materialsOn,
    setMaterialsOn,
    materialFiles,
    setMaterialFiles,
    materialKinds,
    setMaterialKinds,
    uploadError,
    setUploadError,
    templates,
    templateId,
    setTemplateId,
    templateDetail,
    models,
    modelId,
    setModelId,
    error,
    submitting,
    typeDef,
    majorsOf,
    recommendTopic,
    addMaterialFiles,
    removeMaterialFile,
    formatSize,
    handleNext,
  } = useCreateWizard();

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2">
        {PAPER_TYPES.map((t) => (
          <button
            type="button"
            key={t.value}
            onClick={() => setPaperType(t.value)}
            className={`rounded-xl border p-4 text-left transition ${
              paperType === t.value
                ? "border-black bg-white ring-2 ring-neutral-200"
                : "border-neutral-200 bg-white hover:border-black"
            }`}
          >
            <div className="text-sm font-bold text-slate-800">{t.label}</div>
            <div className="mt-0.5 text-[11px] uppercase tracking-wide text-slate-400">
              {t.en}
            </div>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-500">
              {t.desc}
            </p>
          </button>
        ))}
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-slate-700">
          论文模板
        </label>
        <div className="grid gap-2 sm:grid-cols-3">
          {templates.map((t) => (
            <button
              type="button"
              key={t.id}
              onClick={() => setTemplateId(t.id)}
              className={`rounded-xl border p-3 text-left transition ${
                templateId === t.id
                  ? "border-black bg-white ring-2 ring-neutral-200"
                  : "border-neutral-200 bg-white hover:border-black"
              }`}
            >
              <div className="flex items-center gap-1.5">
                <span
                  className={`h-3 w-3 shrink-0 rounded-full border ${
                    templateId === t.id
                      ? "border-black bg-black"
                      : "border-neutral-300"
                  }`}
                />
                <span className="truncate text-sm font-semibold text-slate-800">
                  {t.name}
                </span>
                {t.is_default && (
                  <span className="shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                    默认
                  </span>
                )}
              </div>
              <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-500">
                {t.description}
              </p>
            </button>
          ))}
        </div>
        {templateDetail && (
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
            <span>纸张：{templateDetail.page.size}</span>
            <span>目录：{templateDetail.toc.enabled ? "支持" : "不支持"}</span>
            <span>
              标题编号：
              {templateDetail.numbering.enabled ? "支持" : "不支持"}
            </span>
            <span>
              参考文献：{templateDetail.reference_style.toUpperCase()}
            </span>
          </div>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1.5 block text-sm font-medium text-slate-700">
            学科门类
          </label>
          <select
            value={discipline}
            onChange={(e) => {
              const d = e.target.value;
              setDiscipline(d);
              const m =
                DISCIPLINES.find((x) => x.name === d)?.majors[0] ?? "";
              setMajor(m);
            }}
            className={inputCls}
          >
            {DISCIPLINES.map((d) => (
              <option key={d.name} value={d.name}>
                {d.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1.5 block text-sm font-medium text-slate-700">
            专业类
          </label>
          <select
            value={major}
            onChange={(e) => setMajor(e.target.value)}
            className={inputCls}
          >
            {majorsOf.map((m) => (
              <option key={m} value={m}>
                {discipline}-{m}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-slate-700">
          输入选题
        </label>
        <textarea
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="请输入已确定的论文选题，例如：基于深度学习的图像识别在智能制造中的应用研究"
          rows={3}
          className={inputCls}
        />
        <button
          type="button"
          onClick={recommendTopic}
          className="mt-2 rounded-lg border border-neutral-300 bg-white px-3 py-1.5 text-xs font-medium text-neutral-700 transition hover:bg-neutral-100"
        >
          ✨ 推荐选题
        </button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1.5 block text-sm font-medium text-slate-700">
            全文字数
          </label>
          <div className="flex flex-wrap items-center gap-2">
            {typeDef.words.map((w) => (
              <button
                type="button"
                key={w}
                onClick={() => setWordCount(w)}
                className={`rounded-lg border px-3 py-1.5 text-sm transition ${
                  wordCount === w
                    ? "border-black bg-black font-semibold text-white"
                    : "border-neutral-300 text-neutral-600 hover:border-black"
                }`}
              >
                {w.toLocaleString()}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="mb-1.5 block text-sm font-medium text-slate-700">
            正文语种
          </label>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className={inputCls}
          >
            <option value="中文">中文</option>
            <option value="英文">英文</option>
          </select>
        </div>
      </div>
      <p className="text-xs text-slate-400">
        以上字数为推荐大纲的参考字数，实际生成受章节数、上传的资料与具体要求影响，由
        AI 大模型生成，非平台精准控制。
      </p>

      <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
        <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
          <input
            type="checkbox"
            checked={materialsOn}
            onChange={(e) => {
              setMaterialsOn(e.target.checked);
              setUploadError(null);
              if (!e.target.checked) {
                setMaterialFiles([]);
                setMaterialKinds([]);
              }
            }}
            className="h-4 w-4 rounded border-neutral-300 text-black focus:ring-neutral-300"
          />
          资料上传 / 其他要求（可选）
        </label>

        {materialsOn && (
          <div className="mt-3 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              {materialFiles.map((f, i) => (
                <div
                  key={`${f.name}-${i}`}
                  className="flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs"
                >
                  <span className="max-w-[120px] truncate font-medium text-slate-700">
                    {f.name}
                  </span>
                  <span className="text-slate-400">{formatSize(f.size)}</span>
                  <select
                    value={materialKinds[i]}
                    onChange={(e) =>
                      setMaterialKinds((prev) =>
                        prev.map((k, idx) =>
                          idx === i ? e.target.value : k,
                        ),
                      )
                    }
                    className="rounded-md border border-slate-200 bg-white px-1 py-0.5 text-xs text-slate-600 outline-none"
                  >
                    {MATERIAL_KIND_OPTIONS.map((k) => (
                      <option key={k} value={k}>
                        {k}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => removeMaterialFile(i)}
                    className="text-slate-400 transition hover:text-red-500"
                    title="移除"
                  >
                    ✕
                  </button>
                </div>
              ))}
              {materialFiles.length < 5 && (
                <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-dashed border-neutral-300 bg-white px-3 py-1.5 text-xs font-medium text-neutral-700 transition hover:bg-neutral-100">
                  <span>+</span>
                  <span>
                    上传资料（{materialFiles.length}/5）
                  </span>
                  <input
                    type="file"
                    multiple
                    accept=".txt,.docx,.xls,.xlsx,.jpg,.jpeg,.png"
                    className="hidden"
                    onChange={(e) => {
                      addMaterialFiles(e.target.files);
                      e.target.value = "";
                    }}
                  />
                </label>
              )}
            </div>
            <p className="text-[11px] leading-relaxed text-slate-400">
              支持 txt、docx、xls、xlsx、jpg、jpeg、png（如各类文档资料、
              理工科图纸、SPSS 分析结果等）；最多 5 个文件、每个 ≤5MB。文档会提取文本供
              AI 参考；图片仅保存、无法解析，数据和图片请在下方要求中另行说明。
            </p>

            {uploadError && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                {uploadError}
              </div>
            )}

            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">
                写作倾向 / 对大纲目录的要求
              </label>
              <textarea
                value={specialRequirements}
                onChange={(e) => setSpecialRequirements(e.target.value)}
                placeholder="可输入论文写作倾向要求、对目录大纲的要求等，例：\n“目录大纲按以下结构生成：\n1. 绪论\n1.1 研究背景与意义 …”"
                rows={3}
                className={`${inputCls} bg-white text-xs`}
              />
            </div>
          </div>
        )}
      </div>

      {models.length > 0 && (
        <div>
          <label className="mb-1.5 block text-sm font-medium text-slate-700">
            AI 模型
          </label>
          <select
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
            className={inputCls}
          >
            <option value="">默认模型</option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}（{m.model}）
              </option>
            ))}
          </select>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between pt-1">
        <Link
          to="/"
          className="rounded-xl border border-neutral-300 px-4 py-2 text-sm text-neutral-600 transition hover:border-neutral-400"
        >
          ← 返回首页
        </Link>
        <button
          type="button"
          onClick={handleNext}
          disabled={submitting}
          className="rounded-xl bg-black px-8 py-2.5 text-sm font-semibold text-white transition hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? "提交中…" : "下一步"}
        </button>
      </div>
    </div>
  );
}
