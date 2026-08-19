import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  analyzePaper,
  downloadUrl,
  exportPaper,
  fetchPreview,
  fetchVersions,
  restoreVersion,
  reviseChapter,
  reviseParagraph,
  type AnalysisResult,
  type PaperPreview,
  type VersionInfo,
} from "../api/paper";
import TemplateManagerModal from "../components/TemplateManagerModal";

type LayoutMode = "reading" | "paper";

interface ReviseModalState {
  kind: "chapter" | "paragraph";
  id: string;
  changeType: string;
  label: string;
  defaultInstruction: string;
}

const CHAPTER_OPS = [
  { key: "regenerate", label: "重新生成本章", default: "重新生成该章内容" },
  { key: "expand", label: "扩展本章", default: "扩展本章内容，补充更多论述与分析" },
  { key: "condense", label: "精简本章", default: "精简本章内容，删除冗余表述" },
  { key: "custom", label: "自定义修改", default: "" },
];

const PARAGRAPH_OPS = [
  { key: "polish", label: "AI润色", default: "润色该段落，提升表达流畅度" },
  { key: "expand", label: "扩写", default: "扩写该段落，补充细节与论据" },
  { key: "rewrite", label: "改写", default: "改写该段落，换一种表达方式" },
];

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return iso;
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

export default function PreviewPage() {
  const { taskId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const [preview, setPreview] = useState<PaperPreview | null>(null);
  const [versions, setVersions] = useState<VersionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<LayoutMode>("reading");
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [analysisOpen, setAnalysisOpen] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [revising, setRevising] = useState(false);
  const [templateModalOpen, setTemplateModalOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  /** 导出：选择模板 → 后端按模板渲染 → 下载 docx。 */
  async function handleExport(templateId: string) {
    setTemplateModalOpen(false);
    setExporting(true);
    try {
      await exportPaper(taskId, templateId);
      window.location.href = downloadUrl(taskId, "论文.docx");
    } catch (err) {
      alert(err instanceof Error ? err.message : "导出失败");
    } finally {
      setExporting(false);
    }
  }
  const [restoringId, setRestoringId] = useState<number | null>(null);
  const [modal, setModal] = useState<ReviseModalState | null>(null);
  const [instruction, setInstruction] = useState("");
  const contentRef = useRef<HTMLDivElement>(null);

  const loadPreview = useCallback(async () => {
    const data = await fetchPreview(taskId);
    setPreview(data);
  }, [taskId]);

  const loadVersions = useCallback(async () => {
    try {
      setVersions(await fetchVersions(taskId));
    } catch {
      setVersions([]);
    }
  }, [taskId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([loadPreview(), loadVersions()])
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "加载论文预览失败");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [loadPreview, loadVersions]);

  // ?print=1 时自动打开浏览器打印（可另存为 PDF）
  useEffect(() => {
    if (searchParams.get("print") === "1" && preview) {
      const timer = window.setTimeout(() => window.print(), 400);
      return () => window.clearTimeout(timer);
    }
    return;
  }, [searchParams, preview]);

  function openModal(kind: "chapter" | "paragraph", id: string,
                     changeType: string, label: string,
                     defaultInstruction: string) {
    setModal({ kind, id, changeType, label, defaultInstruction });
    setInstruction(defaultInstruction);
  }

  async function runRevise() {
    if (!modal) {
      return;
    }
    if (!instruction.trim()) {
      window.alert("请填写修改要求");
      return;
    }
    setRevising(true);
    try {
      const res =
        modal.kind === "chapter"
          ? await reviseChapter({
              task_id: taskId,
              chapter_id: modal.id,
              instruction: instruction.trim(),
              change_type: modal.changeType,
            })
          : await reviseParagraph({
              task_id: taskId,
              paragraph_id: modal.id,
              instruction: instruction.trim(),
              change_type: modal.changeType,
            });
      window.alert(`已保存为版本 ${res.version}：${res.description}`);
      setModal(null);
      await Promise.all([loadPreview(), loadVersions()]);
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "修改失败");
    } finally {
      setRevising(false);
    }
  }

  async function handleDeleteParagraph(paragraphId: string) {
    if (!window.confirm("确定删除该段落吗？（会保存为新版本）")) {
      return;
    }
    setRevising(true);
    try {
      const res = await reviseParagraph({
        task_id: taskId,
        paragraph_id: paragraphId,
        instruction: "删除该段落",
        change_type: "delete",
      });
      window.alert(`已删除并保存为版本 ${res.version}`);
      await Promise.all([loadPreview(), loadVersions()]);
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "删除失败");
    } finally {
      setRevising(false);
    }
  }

  async function handleAnalyze() {
    setAnalyzing(true);
    setAnalysisOpen(true);
    try {
      setAnalysis(await analyzePaper(taskId));
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "分析失败");
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleRestore(versionNumber: number) {
    if (!window.confirm(`确定恢复到版本 ${versionNumber} 吗？（会保存为新版本）`)) {
      return;
    }
    setRestoringId(versionNumber);
    try {
      const res = await restoreVersion(taskId, versionNumber);
      window.alert(`已恢复并保存为版本 ${res.version}`);
      await Promise.all([loadPreview(), loadVersions()]);
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "恢复失败");
    } finally {
      setRestoringId(null);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <p className="text-slate-500">正在加载论文预览…</p>
      </div>
    );
  }

  if (error || !preview) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
        <div className="w-full max-w-md rounded-2xl border border-red-200 bg-white p-6">
          <h1 className="mb-2 text-lg font-semibold text-red-600">预览加载失败</h1>
          <p className="mb-4 text-sm text-slate-600">{error ?? "未找到预览数据"}</p>
          <Link
            to="/"
            className="rounded-lg bg-black px-4 py-2 text-sm font-medium text-white"
          >
            返回生成页
          </Link>
        </div>
      </div>
    );
  }

  const m = preview.metadata;

  return (
    <div className="min-h-screen bg-slate-100">
      {/* 顶部工具栏 */}
      <header className="no-print sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-2 px-4 py-2.5">
          <div className="flex items-center gap-2">
            <Link to="/" className="text-sm text-slate-500 hover:text-black">
              ← 返回
            </Link>
            <Link
              to="/history"
              className="text-sm text-slate-500 hover:text-black"
            >
              历史记录
            </Link>
          </div>
          <h1 className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-700">
            {preview.title}
          </h1>
          <div className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 p-0.5">
            {(
              [
                { value: "reading", label: "普通阅读" },
                { value: "paper", label: "论文排版" },
              ] as { value: LayoutMode; label: string }[]
            ).map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setMode(opt.value)}
                className={`rounded-md px-2.5 py-1 text-xs transition ${
                  mode === opt.value
                    ? "bg-black text-white"
                    : "text-slate-500 hover:text-black"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={handleAnalyze}
            disabled={analyzing}
            className="rounded-lg border border-neutral-300 bg-white px-3 py-1.5 text-xs font-medium text-neutral-600 hover:border-neutral-400 disabled:opacity-40"
          >
            {analyzing ? "分析中…" : "分析问题"}
          </button>
          <button
            type="button"
            onClick={handleAnalyze}
            disabled={analyzing}
            className="rounded-lg border border-neutral-300 bg-white px-3 py-1.5 text-xs font-medium text-neutral-600 hover:border-neutral-400 disabled:opacity-40"
          >
            生成修改建议
          </button>
          <button
            type="button"
            onClick={() => setTemplateModalOpen(true)}
            disabled={exporting}
            className="rounded-lg bg-black px-3 py-1.5 text-xs font-medium text-white hover:bg-neutral-700 disabled:opacity-40"
          >
            {exporting ? "导出中…" : "下载 docx"}
          </button>
          <button
            type="button"
            onClick={() => window.print()}
            className="rounded-lg border border-neutral-300 bg-white px-3 py-1.5 text-xs font-medium text-neutral-600 hover:border-neutral-400"
          >
            打印 / 导出 PDF
          </button>
        </div>
      </header>

      {/* 检查报告 */}
      <section className="no-print mx-auto mt-4 grid max-w-6xl grid-cols-2 gap-2 px-4 sm:grid-cols-4">
        {[
          { label: "字数", value: `${m.word_count} 字`, sub: `目标 ${m.target_word_count} 字` },
          { label: "参考文献", value: `${m.reference_count} 条`, sub: m.reference_style.toUpperCase() },
          { label: "格式检查", value: m.format_check, sub: "" },
        ].map((item) => (
          <div
            key={item.label}
            className="rounded-xl border border-slate-200 bg-white px-4 py-3"
          >
            <p className="text-xs text-slate-400">{item.label}</p>
            <p
              className={`text-lg font-semibold ${
                item.label === "格式检查" && m.format_check !== "通过"
                  ? "text-amber-600"
                  : "text-slate-800"
              }`}
            >
              {item.value}
            </p>
            {item.sub && <p className="text-xs text-slate-400">{item.sub}</p>}
          </div>
        ))}
        <div className="col-span-2 rounded-xl border border-slate-200 bg-white px-4 py-3 sm:col-span-4">
          <p className="text-xs text-slate-400">特殊要求</p>
          <p className="text-sm text-slate-700">
            {m.special_requirements ? m.special_requirements : "无"}
          </p>
        </div>
      </section>

      {/* 全文分析结果 */}
      {analysisOpen && analysis && (
        <section className="no-print mx-auto mt-3 max-w-6xl px-4">
          <div className="rounded-2xl border border-neutral-200 bg-white p-4">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-700">
                全文分析（约 {analysis.word_count} 字 / 目标 {analysis.target_word_count} 字）
              </h2>
              <button
                type="button"
                onClick={() => setAnalysisOpen(false)}
                className="text-xs text-slate-400 hover:text-slate-600"
              >
                收起
              </button>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <p className="mb-1 text-xs font-medium text-red-500">问题列表</p>
                <ul className="list-disc space-y-1 pl-4 text-sm text-slate-600">
                  {analysis.problems.map((p, i) => (
                    <li key={`p-${i}`}>{p}</li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="mb-1 text-xs font-medium text-neutral-500">修改建议</p>
                <ul className="list-disc space-y-1 pl-4 text-sm text-slate-600">
                  {analysis.suggestions.map((s, i) => (
                    <li key={`s-${i}`}>{s}</li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* 修改记录（版本） */}
      <section className="no-print mx-auto mt-3 max-w-6xl px-4">
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <h2 className="mb-2 text-sm font-semibold text-slate-700">修改记录</h2>
          {versions.length === 0 ? (
            <p className="text-sm text-slate-400">暂无版本记录</p>
          ) : (
            <ol className="space-y-1.5">
              {versions.map((v) => (
                <li
                  key={v.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-1.5 text-sm"
                >
                  <span className="text-slate-600">
                    <span className="font-medium text-slate-800">
                      版本 {v.version_number}
                    </span>
                    ：{v.description ?? v.change_type}
                    <span className="ml-2 text-xs text-slate-400">
                      {formatTime(v.created_at)}
                    </span>
                  </span>
                  {v.version_number !== versions[versions.length - 1].version_number && (
                    <button
                      type="button"
                      disabled={restoringId !== null}
                      onClick={() => handleRestore(v.version_number)}
                      className="rounded-lg border border-neutral-200 px-2 py-0.5 text-xs text-neutral-700 hover:bg-neutral-100 disabled:opacity-40"
                    >
                      {restoringId === v.version_number ? "恢复中…" : "恢复此版本"}
                    </button>
                  )}
                </li>
              ))}
            </ol>
          )}
        </div>
      </section>

      {/* 主体：目录 + 内容 */}
      <main className="mx-auto flex items-start max-w-6xl gap-4 px-4 py-4">
        <aside className="no-print sticky top-16 hidden max-h-[calc(100vh-5rem)] w-56 shrink-0 self-start overflow-y-auto rounded-xl border border-slate-200 bg-white p-3 lg:block">
          <p className="mb-2 text-xs font-medium text-slate-400">论文目录</p>
          <nav className="space-y-0.5">
            {preview.chapters.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() =>
                  document
                    .getElementById(`chapter-${item.id}`)
                    ?.scrollIntoView({ behavior: "smooth", block: "start" })
                }
                className={`block w-full truncate rounded-lg px-2 py-1.5 text-left text-sm transition hover:bg-neutral-100 hover:text-black ${
                  item.level === 0 ? "font-medium text-slate-700" : "text-slate-500"
                }`}
              >
                {item.title}
              </button>
            ))}
          </nav>
        </aside>

        <div
          ref={contentRef}
          className={`min-w-0 flex-1 ${
            mode === "paper"
              ? "paper-page mx-auto w-full max-w-3xl rounded-lg shadow-lg"
              : "mx-auto max-w-3xl"
          }`}
        >
          <article
            className={
              mode === "paper"
                ? "px-8 py-10 text-[16px] leading-8 text-slate-900"
                : "rounded-xl border border-slate-200 bg-white px-6 py-8 text-[15px] leading-7 text-slate-700 sm:px-8"
            }
          >
            <h1 className="mb-6 text-center text-2xl font-bold text-slate-900">
              {preview.title}
            </h1>

            {preview.chapters.map((chapter) => (
              <section
                key={chapter.id}
                id={`chapter-${chapter.id}`}
                data-chapter-id={chapter.id}
                className="mb-5 scroll-mt-16"
              >
                <h2
                  className={`mb-3 font-semibold text-slate-900 ${
                    chapter.level === 0
                      ? "text-center text-lg"
                      : "border-b border-slate-200 pb-1 text-xl"
                  }`}
                >
                  {chapter.title}
                </h2>

                {chapter.number && (
                  <div className="no-print mb-3 flex flex-wrap gap-1.5">
                    {CHAPTER_OPS.map((op) => (
                      <button
                        key={op.key}
                        type="button"
                        disabled={revising}
                        onClick={() =>
                          openModal(
                            "chapter",
                            chapter.number!,
                            op.key,
                            op.label,
                            op.default,
                          )
                        }
                        className="rounded-lg border border-neutral-200 bg-neutral-50 px-2 py-1 text-xs text-neutral-600 hover:border-neutral-300 hover:text-black disabled:opacity-40"
                      >
                        {op.label}
                      </button>
                    ))}
                  </div>
                )}

                <div className="space-y-3">
                  {chapter.blocks.map((block) => {
                    if (block.type === "h2") {
                      return (
                        <h2 key={block.id} className="text-lg font-semibold text-slate-900">
                          {block.text}
                        </h2>
                      );
                    }
                    if (block.type === "h3") {
                      return (
                        <h3 key={block.id} className="text-base font-medium text-slate-900">
                          {block.text}
                        </h3>
                      );
                    }
                    if (block.type === "table") {
                      return (
                        <div
                          key={block.id}
                          className="overflow-x-auto text-sm [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-slate-300 [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-slate-300 [&_th]:px-2 [&_th]:py-1"
                          dangerouslySetInnerHTML={{ __html: block.html ?? "" }}
                        />
                      );
                    }
                    return (
                      <div key={block.id} className="group relative text-justify">
                        <p className="py-0.5">{block.text}</p>
                        {chapter.number && block.id && (
                          <div className="absolute right-0 top-0 hidden items-center gap-0.5 rounded-lg border border-slate-200 bg-white p-0.5 shadow group-hover:flex">
                            {PARAGRAPH_OPS.map((op) => (
                              <button
                                key={op.key}
                                type="button"
                                disabled={revising}
                                onClick={() =>
                                  openModal(
                                    "paragraph",
                                    block.id!,
                                    op.key,
                                    op.label,
                                    op.default,
                                  )
                                }
                                className="rounded px-1.5 py-0.5 text-xs text-slate-500 hover:bg-neutral-100 hover:text-black disabled:opacity-40"
                              >
                                {op.label}
                              </button>
                            ))}
                            <button
                              type="button"
                              disabled={revising}
                              onClick={() => handleDeleteParagraph(block.id!)}
                              className="rounded px-1.5 py-0.5 text-xs text-slate-400 hover:bg-red-50 hover:text-red-500 disabled:opacity-40"
                            >
                              删除
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </section>
            ))}

            {/* 参考文献 */}
            <section id="chapter-references" className="mt-8 scroll-mt-16">
              <h2 className="border-b border-slate-200 pb-1 text-xl font-semibold text-slate-900">
                参考文献
              </h2>
              <ol className="mt-3 list-decimal space-y-1.5 pl-6 text-sm leading-6">
                {preview.references.map((ref, i) => (
                  <li key={`${ref}-${i}`} className="text-justify">
                    {ref}
                  </li>
                ))}
              </ol>
            </section>
          </article>
        </div>
      </main>

      {/* 修改弹窗 */}
      {modal && (
        <div
          className="no-print fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={() => setModal(null)}
        >
          <div
            className="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="mb-1 text-base font-semibold text-slate-800">
              {modal.label}
            </h3>
            <p className="mb-3 text-xs text-slate-400">
              修改将保存为新版本（不会覆盖原文件）
            </p>
            <textarea
              autoFocus
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              rows={4}
              maxLength={1000}
              placeholder="填写具体修改要求…"
              className="w-full resize-y rounded-xl border border-neutral-300 px-3 py-2.5 text-sm outline-none focus:border-black focus:ring-2 focus:ring-neutral-200"
            />
            <div className="mt-3 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setModal(null)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-600"
              >
                取消
              </button>
              <button
                type="button"
                disabled={revising}
                onClick={runRevise}
                className="rounded-lg bg-black px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700 disabled:opacity-40"
              >
                {revising ? "保存中…" : "确认修改"}
              </button>
            </div>
          </div>
        </div>
      )}


      <TemplateManagerModal
        open={templateModalOpen}
        onClose={() => setTemplateModalOpen(false)}
        selectMode
        onSelectTemplate={(id) => void handleExport(id)}
      />
    </div>
  );
}
