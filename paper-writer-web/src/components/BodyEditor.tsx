import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  addDraftParagraph,
  deleteDraftParagraph,
  downloadUrl,
  exportDraft,
  fetchDraft,
  fetchDraftStatus,
  generateDraftAck,
  generateDraftEnAbstract,
  generateDraftSection,
  moveDraftParagraph,
  startDraftOneclick,
  updateDraftParagraph,
  updateDraftSection,
  type PaperDraft,
  type DraftSection,
} from "../api/paper";

const inputCls =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100";

/** 判断小节是否为叶子节点（无子节）。 */
function isLeaf(draft: PaperDraft, id: string): boolean {
  return !draft.sections.some(
    (s) => s.id !== id && s.id.startsWith(id + "-"),
  );
}

function wordCount(draft: PaperDraft): number {
  let n = 0;
  for (const s of draft.sections) {
    for (const p of s.paragraphs) n += (p.text || "").length;
  }
  n += (draft.abstract?.zh || "").length;
  n += (draft.acknowledgement || "").length;
  return n;
}

export default function BodyEditor({
  taskId,
  modelId,
}: {
  taskId: string;
  modelId?: string;
}) {
  const [draft, setDraft] = useState<PaperDraft | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [genSection, setGenSection] = useState<string | null>(null);
  const [oneclickStarting, setOneclickStarting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportedFiles, setExportedFiles] = useState<string[] | null>(null);
  const pollRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const d = await fetchDraft(taskId);
      setDraft(d);
      if (!selectedId && d.sections.length > 0) {
        setSelectedId(d.sections[0].id);
      }
      return d;
    } catch {
      return null;
    }
  }, [taskId, selectedId]);

  useEffect(() => {
    let cancelled = false;
    let retries = 0;
    const load = async () => {
      const d = await refresh();
      if (!d && !cancelled && retries < 30) {
        retries += 1;
        window.setTimeout(load, 2000); // 大纲草稿尚未建好，稍后重试
      }
    };
    void load();
    return () => {
      cancelled = true;
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  // 一键全文进行中：轮询刷新
  useEffect(() => {
    if (!draft?.generating) {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    pollRef.current = window.setInterval(async () => {
      try {
        const st = await fetchDraftStatus(taskId);
        if (!st.generating) {
          if (pollRef.current !== null) {
            window.clearInterval(pollRef.current);
            pollRef.current = null;
          }
          await refresh();
        } else {
          await refresh();
        }
      } catch {
        /* 忽略轮询错误 */
      }
    }, 2500);
    return () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft?.generating, taskId]);

  async function handleGenerateSection(section: DraftSection) {
    if (!section.gist.trim()) {
      setError(`小节「${section.title}」没有段落主旨，请先在右侧填写主旨`);
      return;
    }
    setError(null);
    setGenSection(section.id);
    try {
      await generateDraftSection(taskId, section.id, modelId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成失败");
    } finally {
      setGenSection(null);
    }
  }

  async function handleOneclick() {
    setError(null);
    setOneclickStarting(true);
    try {
      await startDraftOneclick(taskId, modelId);
      const d = await refresh();
      if (d) {
        const firstWithText = d.sections.find((s) =>
          (s.paragraphs || []).some((p) => p.text.trim()),
        );
        if (firstWithText) {
          setSelectedId(firstWithText.id);
        }
        if (
          !d.generating &&
          !d.sections.some((s) =>
            (s.paragraphs || []).some((p) => p.text.trim()),
          )
        ) {
          setError("一键全文没有生成内容，请检查 AI 模型配置");
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "启动失败");
    } finally {
      setOneclickStarting(false);
    }
  }

  async function handleExport() {
    setError(null);
    setExporting(true);
    try {
      const res = await exportDraft(taskId);
      setExportedFiles(res.files);
    } catch (err) {
      setError(err instanceof Error ? err.message : "导出失败");
    } finally {
      setExporting(false);
    }
  }

  async function patchSection(
    sectionId: string,
    patch: { title?: string; gist?: string },
  ) {
    setDraft((prev) =>
      prev
        ? {
            ...prev,
            sections: prev.sections.map((s) =>
              s.id === sectionId ? { ...s, ...patch } : s,
            ),
          }
        : prev,
    );
    try {
      await updateDraftSection(taskId, sectionId, patch);
    } catch {
      /* 忽略 */
    }
  }

  async function patchParagraph(pid: string, text: string) {
    setDraft((prev) =>
      prev
        ? {
            ...prev,
            sections: prev.sections.map((s) => ({
              ...s,
              paragraphs: s.paragraphs.map((p) =>
                p.id === pid ? { ...p, text } : p,
              ),
            })),
          }
        : prev,
    );
    try {
      await updateDraftParagraph(taskId, pid, text);
    } catch {
      /* 忽略 */
    }
  }

  async function addPara(sectionId: string) {
    try {
      await addDraftParagraph(taskId, sectionId);
      await refresh();
    } catch {
      /* 忽略 */
    }
  }

  async function delPara(pid: string) {
    try {
      await deleteDraftParagraph(taskId, pid);
      await refresh();
    } catch {
      /* 忽略 */
    }
  }

  async function movePara(pid: string, direction: "up" | "down") {
    try {
      await moveDraftParagraph(taskId, pid, direction);
      await refresh();
    } catch {
      /* 忽略 */
    }
  }

  if (!draft) {
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-center">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-indigo-200 border-t-indigo-600" />
        <p className="text-sm text-slate-500">正在生成大纲草稿…</p>
      </div>
    );
  }

  const selected = draft.sections.find((s) => s.id === selectedId) ?? null;
  const totalWords = wordCount(draft);

  return (
    <div className="space-y-4">
      {/* 工具栏 */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <div className="flex items-center gap-3">
          <h2 className="text-base font-bold text-slate-800">论文正文编辑器</h2>
          <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs text-indigo-600">
            全文约 {totalWords} 字
          </span>
          {draft.generating && (
            <span className="flex items-center gap-2 text-xs text-indigo-600">
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-indigo-300 border-t-indigo-600" />
              一键生成中 {draft.done}/{draft.total}（{draft.progress}%）
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleOneclick}
            disabled={draft.generating || oneclickStarting}
            className="rounded-lg bg-gradient-to-r from-indigo-500 to-violet-600 px-4 py-2 text-sm font-semibold text-white transition hover:from-indigo-600 hover:to-violet-700 disabled:opacity-50"
          >
            {oneclickStarting
              ? "启动中…"
              : draft.generating
                ? "生成中…"
                : "⚡ 一键全文"}
          </button>
          <button
            type="button"
            onClick={handleExport}
            disabled={exporting}
            className="rounded-lg border border-green-300 bg-green-50 px-4 py-2 text-sm font-semibold text-green-700 transition hover:bg-green-100 disabled:opacity-50"
          >
            {exporting ? "导出中…" : "📄 导出全文"}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {exportedFiles && (
        <div className="rounded-2xl border border-green-200 bg-green-50 p-5">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-lg">🎉</span>
            <h3 className="font-semibold text-green-800">导出完成</h3>
          </div>
          <div className="flex flex-wrap gap-2">
            <a
              href={downloadUrl(taskId, "论文.docx")}
              className="rounded-lg border border-green-300 bg-white px-4 py-2 text-sm font-medium text-green-700 hover:bg-green-100"
            >
              ⬇️ 下载论文.docx
            </a>
            <Link
              to={`/preview/${taskId}`}
              className="rounded-lg border border-indigo-300 bg-white px-4 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-100"
            >
              📖 在线预览 / 修订
            </Link>
            <Link
              to={`/format/${taskId}`}
              className="rounded-lg border border-violet-300 bg-white px-4 py-2 text-sm font-medium text-violet-700 hover:bg-violet-100"
            >
              🎨 格式处理
            </Link>
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        {/* 左栏：大纲树 */}
        <aside className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="text-sm font-bold text-slate-700">目录</span>
          </div>
          <div className="max-h-[560px] space-y-0.5 overflow-y-auto pr-1">
            {draft.sections.map((s) => (
              <div
                key={s.id}
                style={{ paddingLeft: `${(s.level - 1) * 14 + 4}px` }}
              >
                <div
                  className={`flex cursor-pointer items-center justify-between gap-1 rounded-lg px-2 py-1.5 text-sm transition ${
                    selectedId === s.id
                      ? "bg-indigo-50 text-indigo-700"
                      : "text-slate-600 hover:bg-slate-50"
                  }`}
                  onClick={() => setSelectedId(s.id)}
                >
                  <span className="truncate">
                    {s.number} {s.title}
                    {s.paragraphs.length > 0 && (
                      <span className="ml-1 text-[10px] text-indigo-400">
                        ({s.paragraphs.length})
                      </span>
                    )}
                  </span>
                  {isLeaf(draft, s.id) && (
                    <button
                      type="button"
                      title="生成段落"
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleGenerateSection(s);
                      }}
                      disabled={genSection === s.id}
                      className="shrink-0 rounded-md border border-indigo-200 bg-indigo-50 px-1.5 py-0.5 text-[10px] text-indigo-600 hover:bg-indigo-100 disabled:opacity-50"
                    >
                      {genSection === s.id ? "…" : "生成段落"}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </aside>

        {/* 右栏：编辑区 */}
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          {!selected ? (
            <div className="py-16 text-center text-sm text-slate-400">
              从左侧选择一个章节小节开始编辑
            </div>
          ) : (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-500">
                    {selected.number} · 标题
                  </label>
                  <input
                    value={selected.title}
                    onChange={(e) =>
                      void patchSection(selected.id, { title: e.target.value })
                    }
                    className={inputCls}
                  />
                </div>
                {isLeaf(draft, selected.id) && (
                  <div>
                    <label className="mb-1 block text-xs font-medium text-slate-500">
                      段落主旨（生成段落的指令，可编辑）
                    </label>
                    <input
                      value={selected.gist}
                      onChange={(e) =>
                        void patchSection(selected.id, { gist: e.target.value })
                      }
                      placeholder="填写这一段要写什么…"
                      className={inputCls}
                    />
                  </div>
                )}
              </div>

              {/* 段落列表 */}
              <div className="space-y-3">
                {selected.paragraphs.length === 0 && (
                  <p className="rounded-lg border border-dashed border-slate-300 py-8 text-center text-sm text-slate-400">
                    还没有段落，点击「生成段落」或「新增段落」
                  </p>
                )}
                {selected.paragraphs.map((p, i) => (
                  <div
                    key={p.id}
                    className="group rounded-xl border border-slate-200 bg-slate-50/60 p-3"
                  >
                    <textarea
                      value={p.text}
                      onChange={(e) => void patchParagraph(p.id, e.target.value)}
                      rows={5}
                      className={`${inputCls} bg-white leading-relaxed`}
                    />
                    <div className="mt-1.5 flex items-center justify-between">
                      <span className="text-xs text-slate-400">段落 {i + 1}</span>
                      <div className="flex items-center gap-1 text-xs">
                        <button
                          type="button"
                          onClick={() => void movePara(p.id, "up")}
                          disabled={i === 0}
                          className="rounded-md border border-slate-200 px-2 py-1 text-slate-500 hover:bg-slate-100 disabled:opacity-40"
                        >
                          ↑
                        </button>
                        <button
                          type="button"
                          onClick={() => void movePara(p.id, "down")}
                          disabled={i === selected.paragraphs.length - 1}
                          className="rounded-md border border-slate-200 px-2 py-1 text-slate-500 hover:bg-slate-100 disabled:opacity-40"
                        >
                          ↓
                        </button>
                        <button
                          type="button"
                          onClick={() => void delPara(p.id)}
                          className="rounded-md border border-red-200 px-2 py-1 text-red-500 hover:bg-red-50"
                        >
                          删除
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              {/* 操作按钮 */}
              <div className="flex items-center gap-2 pt-1">
                {isLeaf(draft, selected.id) && (
                  <button
                    type="button"
                    onClick={() => void handleGenerateSection(selected)}
                    disabled={genSection === selected.id || draft.generating}
                    className="rounded-lg bg-gradient-to-r from-indigo-500 to-violet-600 px-4 py-2 text-sm font-semibold text-white transition hover:from-indigo-600 hover:to-violet-700 disabled:opacity-50"
                  >
                    {genSection === selected.id ? "生成中…" : "✨ 生成段落"}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => void addPara(selected.id)}
                  className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-600 transition hover:border-indigo-300"
                >
                  + 新增段落
                </button>
              </div>
            </div>
          )}

          {/* 前置/后置区块：摘要、致谢、参考文献 */}
          <div className="mt-6 space-y-4 border-t border-slate-100 pt-4">
            <div>
              <div className="mb-1 flex items-center justify-between">
                <label className="text-sm font-bold text-slate-700">摘要</label>
                <button
                  type="button"
                  onClick={() => void generateDraftEnAbstract(taskId, modelId)}
                  className="rounded-md border border-indigo-200 bg-indigo-50 px-2 py-1 text-xs text-indigo-600 hover:bg-indigo-100"
                >
                  生成英文摘要
                </button>
              </div>
              <textarea
                value={draft.abstract?.zh || ""}
                onChange={(e) =>
                  setDraft((prev) =>
                    prev
                      ? { ...prev, abstract: { ...prev.abstract, zh: e.target.value } }
                      : prev,
                  )
                }
                rows={4}
                className={`${inputCls} leading-relaxed`}
              />
              {draft.abstract?.en && (
                <textarea
                  value={draft.abstract.en}
                  onChange={(e) =>
                    setDraft((prev) =>
                      prev
                        ? { ...prev, abstract: { ...prev.abstract, en: e.target.value } }
                        : prev,
                    )
                  }
                  rows={3}
                  className={`${inputCls} mt-2 leading-relaxed`}
                  placeholder="英文摘要"
                />
              )}
            </div>

            <div>
              <div className="mb-1 flex items-center justify-between">
                <label className="text-sm font-bold text-slate-700">致谢</label>
                <button
                  type="button"
                  onClick={async () => {
                    await generateDraftAck(taskId, modelId);
                    await refresh();
                  }}
                  className="rounded-md border border-indigo-200 bg-indigo-50 px-2 py-1 text-xs text-indigo-600 hover:bg-indigo-100"
                >
                  生成致谢
                </button>
              </div>
              <textarea
                value={draft.acknowledgement || ""}
                onChange={(e) =>
                  setDraft((prev) =>
                    prev ? { ...prev, acknowledgement: e.target.value } : prev,
                  )
                }
                rows={3}
                className={`${inputCls} leading-relaxed`}
                placeholder="致谢（可点击生成或手动填写）"
              />
            </div>

            <div>
              <label className="mb-1 block text-sm font-bold text-slate-700">
                参考文献（{draft.references.length} 条）
              </label>
              <div className="max-h-40 space-y-1 overflow-y-auto text-xs leading-relaxed text-slate-600">
                {draft.references.map((r, i) => (
                  <div key={i} className="rounded bg-slate-50 px-3 py-1.5">
                    <span className="mr-1 font-semibold text-indigo-600">[{i + 1}]</span>
                    {r}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
