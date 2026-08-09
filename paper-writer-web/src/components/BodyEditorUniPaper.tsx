import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  addDraftParagraph,
  deleteDraftParagraph,
  startDraftOneclick,
  downloadUrl,
  exportDraft,
  fetchDraft,
  generateDraftAck,
  generateDraftEnAbstract,
  generateDraftSection,
  moveDraftParagraph,
  listTemplates,
  getTemplateDetail,
  updateDraftParagraph,
  updateDraftSection,
  type PaperDraft,
  type DraftSection,
  type ModelConfig,
  type TemplateSummary,
  type TemplateDetail,
} from "../api/paper";

/* ============ AI UniPaper 极简黑白样式常量 ============ */
const BTN_BLACK =
  "rounded-md bg-black px-4 py-2 text-sm text-white transition hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-40";
const BTN_GHOST =
  "rounded-md border border-neutral-200 px-3 py-1.5 text-sm text-neutral-700 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-40";
const BTN_TINY =
  "shrink-0 rounded border border-neutral-300 bg-white px-2 py-0.5 text-[11px] text-neutral-600 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-40";
const INPUT_FLAT =
  "w-full bg-transparent outline-none placeholder:text-neutral-400";

/* 正文段落样式（对齐 AI UniPaper /example：14px、行高 1.6、首行缩进 30px、圆角 6px、内边距 4px 11px、白底、hover 浅灰、focus 黑边） */
const paraCls =
  "w-full rounded-md border-2 border-transparent bg-white px-[11px] py-1 text-sm leading-[1.6] text-neutral-900 outline-none placeholder:text-neutral-400 [text-indent:30px] transition hover:bg-black/[0.05] focus:border-black/60 focus:bg-white";

/** 已生成字数（段落 + 摘要 + 致谢）。 */
function wordCount(draft: PaperDraft): number {
  let n = 0;
  for (const s of draft.sections) {
    for (const p of s.paragraphs) n += (p.text || "").length;
  }
  n += (draft.abstract?.zh || "").length;
  n += (draft.acknowledgement || "").length;
  return n;
}

/** 把数组关键词渲染为逗号分隔文本。 */
function kwText(list: string[] | undefined): string {
  return (list || []).join("，");
}

function kwList(text: string): string[] {
  return text
    .split(/[，,、;；]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function BodyEditorUniPaper({
  taskId,
  modelId,
  models,
  onModelChange,
  typeLabel,
  onBack,
}: {
  taskId: string;
  modelId?: string;
  models?: ModelConfig[];
  onModelChange?: (id: string) => void;
  typeLabel?: string;
  onBack?: () => void;
}) {
  const [draft, setDraft] = useState<PaperDraft | null>(null);
  const [selModel, setSelModel] = useState<string>(modelId || "");
  const [genSection, setGenSection] = useState<string | null>(null);
  const [oneclickStarting, setOneclickStarting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportedFiles, setExportedFiles] = useState<string[] | null>(null);
  const [templatePickerOpen, setTemplatePickerOpen] = useState(false);
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [templateCategory, setTemplateCategory] = useState<"all" | "builtin" | "mine" | "school">("all");
  const [selectedTemplateDetail, setSelectedTemplateDetail] = useState<TemplateDetail | null>(null);
  const pollRef = useRef<number | null>(null);

  // 当前生效模型：本地选择优先，其次外部传入，最后默认模型
  const activeModel =
    selModel ||
    modelId ||
    models?.find((m) => m.is_default)?.id ||
    "";

  const refresh = useCallback(async () => {
    try {
      const d = await fetchDraft(taskId);
      setDraft(d);
      return d;
    } catch {
      return null;
    }
  }, [taskId]);

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
        // 生成中必须刷新完整 draft，而不只是刷新进度数字；否则后端已经
        // 写入的段落不会出现在当前页面。
        const latest = await refresh();
        if (latest && !latest.generating) {
          if (pollRef.current !== null) window.clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch {
        /* 忽略轮询错误 */
      }
    }, 1000);
    return () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft?.generating, taskId]);

  function handleModelChange(id: string) {
    setSelModel(id);
    onModelChange?.(id);
  }

  async function handleGenerateSection(section: DraftSection) {
    if (!section.gist.trim()) {
      setError(`小节「${section.title}」没有段落主旨，请先填写主旨`);
      return;
    }
    setError(null);
    setGenSection(section.id);
    try {
      await generateDraftSection(taskId, section.id, activeModel || undefined);
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
      await startDraftOneclick(taskId, activeModel || undefined);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "启动失败");
    } finally {
      setOneclickStarting(false);
    }
  }

  async function handleExport(templateId?: string) {
    setError(null);
    setExporting(true);
    try {
      const res = await exportDraft(taskId, templateId);
      setExportedFiles(res.files);
    } catch (err) {
      setError(err instanceof Error ? err.message : "导出失败");
    } finally {
      setExporting(false);
    }
  }

  async function openTemplatePicker() {
    setTemplatePickerOpen(true);
    setTemplatesLoading(true);
    try {
      const result = await listTemplates();
      setTemplates(result.items);
      setTemplateCategory("all");
      const initialId = result.default_id ?? result.items[0]?.id ?? "";
      setSelectedTemplateId(initialId);
      setSelectedTemplateDetail(initialId ? await getTemplateDetail(initialId) : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载模板失败");
    } finally {
      setTemplatesLoading(false);
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

  /** 点击目录节点 → 右栏滚动定位。 */
  function scrollTo(id: string) {
    document
      .getElementById(id)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  if (!draft) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-white text-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-neutral-300 border-t-black" />
        <p className="text-sm text-neutral-500">正在生成大纲草稿…</p>
      </div>
    );
  }

  const totalWords = wordCount(draft);
  const target = draft.meta?.word_count || 0;
  const pct = target > 0 ? Math.min(100, Math.round((totalWords / target) * 100)) : 0;
  const sections = draft.sections;
  const roots = sections.filter((s) => s.level === 1);

  return (
    <div className="flex min-h-screen flex-col bg-white text-neutral-900">
      {/* ============ 顶栏（AI UniPaper 风格） ============ */}
      <header className="flex h-20 shrink-0 items-center gap-3 border-b border-neutral-200 bg-white px-12">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-1 text-sm text-neutral-600 hover:text-black"
        >
          ← 返回
        </button>
        {typeLabel && (
          <span className="rounded-full border border-neutral-300 px-3 py-0.5 text-xs text-neutral-700">
            {typeLabel}
          </span>
        )}
        {/* 字数进度条 */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-neutral-500 tabular-nums">
            {totalWords}/{target}
          </span>
          <div className="h-1.5 w-28 overflow-hidden rounded-full bg-neutral-200">
            <div
              className="h-full bg-black transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-xs text-neutral-400">字</span>
        </div>
        {draft.generating && (
          <span className="flex items-center gap-2 text-xs text-neutral-500">
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-neutral-300 border-t-black" />
            生成中 {draft.done}/{draft.total}
          </span>
        )}
        <div className="flex-1" />
        {/* 模型切换（黑胶囊） */}
        {models && models.length > 0 && (
          <select
            value={activeModel}
            onChange={(e) => handleModelChange(e.target.value)}
            className="cursor-pointer rounded-full bg-black px-3 py-1 text-xs text-white outline-none"
          >
            {models
              .filter((m) => m.enabled)
              .map((m) => (
                <option key={m.id} value={m.id} className="bg-white text-black">
                  {m.name}
                </option>
              ))}
          </select>
        )}
        <nav className="hidden items-center gap-3 text-sm text-neutral-600 sm:flex">
          <Link to="/templates" className="hover:text-black">模板管理</Link>
          <Link to="/history" className="hover:text-black">历史记录</Link>
          <Link to="/settings/models" className="hover:text-black">模型设置</Link>
        </nav>
        <button
          type="button"
          onClick={handleOneclick}
          disabled={draft.generating || oneclickStarting}
          className={BTN_BLACK}
        >
          {oneclickStarting ? "启动中…" : draft.generating ? "生成中…" : "一键全文"}
        </button>
        <button
          type="button"
          onClick={() => void openTemplatePicker()}
          disabled={exporting}
          className={BTN_GHOST}
        >
          {exporting ? "导出中…" : "导出"}
        </button>
      </header>

      {error && (
        <div className="border-b border-red-200 bg-red-50 px-6 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {exportedFiles && (
        <div className="flex flex-wrap items-center gap-3 border-b border-neutral-200 bg-neutral-50 px-6 py-3 text-sm">
          <span className="font-semibold">导出完成</span>
          <a
            href={downloadUrl(taskId, "论文.docx")}
            className="text-black underline underline-offset-2 hover:text-neutral-600"
          >
            下载论文.docx
          </a>
          <Link to={`/preview/${taskId}`} className="underline underline-offset-2 hover:text-neutral-600">
            在线预览 / 修订
          </Link>
          <Link to={`/format/${taskId}`} className="underline underline-offset-2 hover:text-neutral-600">
            格式处理
          </Link>
          <button
            type="button"
            onClick={() => setExportedFiles(null)}
            className="ml-auto text-neutral-400 hover:text-black"
          >
            ✕
          </button>
        </div>
      )}

      {templatePickerOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4 py-6">
          <div className="max-h-[88vh] w-full max-w-4xl overflow-hidden rounded-2xl bg-[#f8faff] shadow-[0_8px_40px_rgba(0,0,0,.18)]">
            <div className="flex items-center justify-between border-b border-neutral-200 px-6 py-5"><h2 className="text-xl font-semibold">选择排版格式</h2><button type="button" onClick={() => setTemplatePickerOpen(false)} className="rounded-full px-2 text-2xl text-neutral-400 hover:bg-white hover:text-black">×</button></div>
            <div className="grid max-h-[58vh] grid-cols-[205px_1fr] overflow-y-auto">
              <aside className="border-r border-neutral-200 bg-[#eef1f6] p-3">
                <div className="mb-2 px-3 text-xs font-semibold text-neutral-500">模板名称</div>
                <div className="space-y-1">{templates.filter((template) => templateCategory === "all" || template.source === templateCategory).map((template) => <button key={template.id} type="button" onClick={() => { setSelectedTemplateId(template.id); void getTemplateDetail(template.id).then(setSelectedTemplateDetail).catch(() => setSelectedTemplateDetail(null)); }} className={`block w-full rounded-md px-3 py-2 text-left text-sm transition ${selectedTemplateId === template.id ? "bg-black text-white" : "text-neutral-700 hover:bg-white"}`}>{template.name}</button>)}</div>
                <Link to="/templates" className="mt-5 block px-3 text-xs text-neutral-500 underline underline-offset-2 hover:text-black">模板管理</Link>
              </aside>
              <div className="min-w-0 bg-[#f8faff] p-5">
                {templatesLoading || !selectedTemplateDetail ? <div className="py-12 text-center text-sm text-neutral-500">{templatesLoading ? "正在加载模板…" : "请选择左侧模板"}</div> : <div className="space-y-3 text-sm">
                  <div className="rounded-lg bg-white px-4 py-3"><div className="font-semibold">{selectedTemplateDetail.name}</div><div className="mt-1 text-xs text-neutral-500">{selectedTemplateDetail.description || "通用论文排版模板"}</div></div>
                  <div className="rounded-lg border border-neutral-200 bg-white"><div className="border-b border-neutral-200 bg-[#eef1f6] px-4 py-3 font-semibold">页面设置（{selectedTemplateDetail.page.size}）</div><div className="grid grid-cols-2 gap-3 px-4 py-4 text-neutral-600">{[["上边距", selectedTemplateDetail.page.margins.top_mm], ["下边距", selectedTemplateDetail.page.margins.bottom_mm], ["左边距", selectedTemplateDetail.page.margins.left_mm], ["右边距", selectedTemplateDetail.page.margins.right_mm]].map(([label, value]) => <div key={String(label)} className="flex justify-between rounded bg-[#f5f6f8] px-3 py-2"><span>{label}</span><span>{value} mm</span></div>)}</div></div>
                  <div className="rounded-lg border border-neutral-200 bg-white"><div className="border-b border-neutral-200 bg-[#eef1f6] px-4 py-3 font-semibold">页眉 / 页脚</div><div className="space-y-2 px-4 py-4 text-neutral-600"><div><span className="mr-3 text-neutral-400">页眉</span>{selectedTemplateDetail.header.content || "未设置"}</div><div><span className="mr-3 text-neutral-400">页脚</span>{selectedTemplateDetail.footer.content || "未设置"}</div></div></div>
                  <div className="rounded-lg border border-neutral-200 bg-white"><div className="border-b border-neutral-200 bg-[#eef1f6] px-4 py-3 font-semibold">论文结构与参考文献</div><div className="grid grid-cols-2 gap-3 px-4 py-4 text-neutral-600"><div>目录：{selectedTemplateDetail.toc.enabled ? "启用" : "关闭"}</div><div>页码：{selectedTemplateDetail.toc.include_page_numbers ? "显示" : "隐藏"}</div><div>编号：{selectedTemplateDetail.numbering.enabled ? "启用" : "关闭"}</div><div>参考文献：{selectedTemplateDetail.reference_style}</div></div></div>
                </div>}
              </div>
            </div>
            <div className="flex justify-end gap-3 border-t border-neutral-200 px-6 py-4"><button type="button" onClick={() => setTemplatePickerOpen(false)} className={BTN_GHOST}>取消</button><button type="button" disabled={templatesLoading || !selectedTemplateId} onClick={() => { setTemplatePickerOpen(false); void handleExport(selectedTemplateId); }} className={BTN_BLACK}>使用该模板</button></div>
          </div>
        </div>
      )}

      {/* ============ 主体：左目录树 + 右正文流 ============ */}
      <div className="flex flex-1 overflow-hidden">
        {/* ---------- 左栏：目录树 ---------- */}
        <aside className="w-[492px] shrink-0 overflow-y-auto border-r border-neutral-200 bg-white">
          {/* 工具行 */}
          <div className="sticky top-0 z-10 flex items-center justify-between border-b border-neutral-200 bg-white px-4 py-2.5">
            <span className="text-sm font-bold">目录</span>
            <div className="flex items-center gap-3 text-xs text-neutral-500">
              <button
                type="button"
                className="hover:text-black"
                onClick={() => setError("大纲由创建向导生成，暂不支持在此重新生成")}
              >
                重新生成
              </button>
              <button
                type="button"
                className="hover:text-black"
                onClick={() => setError("标记说明功能未启用")}
              >
                标记说明
              </button>
              <button
                type="button"
                className="hover:text-black"
                onClick={() => setError("自动标记功能未启用")}
              >
                自动标记
              </button>
            </div>
          </div>

          {/* 摘要 / 关键词 / Abstract / Keywords 节点 */}
          <TreeNode
            label="摘要"
            value={(draft.abstract?.zh || "").slice(0, 30)}
            actionLabel="重新生成"
            onAction={() => setError("摘要由创作向导生成，可在向导第②步重新生成")}
            onJump={() => scrollTo("sec-abstract")}
          />
          <TreeNode
            label="关键词"
            value={kwText(draft.keywords?.zh).slice(0, 30)}
            actionLabel="重新生成"
            onAction={() => setError("关键词由创作向导生成，可在向导第②步重新生成")}
            onJump={() => scrollTo("sec-keywords")}
          />
          <TreeNode
            label="Abstract"
            value={(draft.abstract?.en || "").slice(0, 30)}
            actionLabel="生成段落"
            onAction={async () => {
              setError(null);
              await generateDraftEnAbstract(taskId, activeModel || undefined);
              await refresh();
            }}
            onJump={() => scrollTo("sec-abstract-en")}
          />
          <TreeNode
            label="Keywords"
            value={kwText(draft.keywords?.en).slice(0, 30)}
            actionLabel="生成段落"
            onAction={async () => {
              setError(null);
              await generateDraftEnAbstract(taskId, activeModel || undefined);
              await refresh();
            }}
            onJump={() => scrollTo("sec-keywords-en")}
          />

          {/* 章节树 */}
          {roots.map((root) => {
            const children = sections.filter(
              (s) => s.level === 2 && s.id.startsWith(root.id + "-"),
            );
            return (
              <div key={root.id} className="border-b border-neutral-100">
                {/* 章节点：可编辑标题 */}
                <div
                  className="flex h-[70px] cursor-pointer items-center rounded-md px-4 hover:bg-black/[0.05]"
                  onClick={() => scrollTo(`sec-${root.id}`)}
                >
                  <input
                    value={root.title}
                    onChange={(e) =>
                      void patchSection(root.id, { title: e.target.value })
                    }
                    onClick={(e) => e.stopPropagation()}
                    className={`${INPUT_FLAT} text-[14px] font-semibold`}
                  />
                </div>
                {children.map((child) => {
                  const grandchildren = sections.filter(
                    (s) => s.level === 3 && s.id.startsWith(child.id + "-"),
                  );
                  return (
                    <div key={child.id} className="pl-4">
                      <SectionTreeItem
                        section={child}
                        isLeaf={grandchildren.length === 0}
                        genSection={genSection}
                        onJump={() => scrollTo(`sec-${child.id}`)}
                        onPatch={(patch) => void patchSection(child.id, patch)}
                        onGenerate={() => void handleGenerateSection(child)}
                      />
                      {grandchildren.map((g) => (
                        <SectionTreeItem
                          key={g.id}
                          section={g}
                          isLeaf
                          genSection={genSection}
                          onJump={() => scrollTo(`sec-${g.id}`)}
                          onPatch={(patch) => void patchSection(g.id, patch)}
                          onGenerate={() => void handleGenerateSection(g)}
                        />
                      ))}
                    </div>
                  );
                })}
              </div>
            );
          })}

          {/* 致谢 / 参考文献 */}
          <TreeNode
            label="致谢"
            value={(draft.acknowledgement || "").slice(0, 30)}
            actionLabel="生成致谢"
            onAction={async () => {
              setError(null);
              await generateDraftAck(taskId, activeModel || undefined);
              await refresh();
            }}
            onJump={() => scrollTo("sec-ack")}
          />
          <TreeNode
            label="参考文献"
            value={`参考文献 ${draft.references.length} 条`}
            onJump={() => scrollTo("sec-refs")}
          />
        </aside>

        {/* ---------- 右栏：整篇正文流 ---------- */}
        <div className="flex-1 overflow-y-auto bg-white">
          <div className="ml-[116px] max-w-[892px] px-8 py-8">
            {/* 论文标题 */}
            <h1 className="mb-4 border-b border-neutral-200 pb-4 text-center text-xl font-semibold">
              {draft.title || draft.meta?.paper_type || "论文"}
            </h1>

            {/* 摘要 */}
            <Block id="sec-abstract" title="摘要">
              <AutoGrowTextarea
                value={draft.abstract?.zh || ""}
                onChange={(e) =>
                  setDraft((prev) =>
                    prev
                      ? { ...prev, abstract: { ...prev.abstract, zh: e.target.value } }
                      : prev,
                  )
                }
                placeholder="请输入摘要…"
                className={paraCls}
              />
            </Block>

            {/* 关键词 */}
            <Block id="sec-keywords" title="关键词">
              <AutoGrowTextarea
                value={kwText(draft.keywords?.zh)}
                onChange={(e) =>
                  setDraft((prev) =>
                    prev
                      ? {
                          ...prev,
                          keywords: {
                            ...prev.keywords,
                            zh: kwList(e.target.value),
                          },
                        }
                      : prev,
                  )
                }
                className={paraCls}
              />
            </Block>

            {/* Abstract */}
            <Block
              id="sec-abstract-en"
              title="Abstract"
              actionLabel="生成英文摘要"
              onAction={async () => {
                setError(null);
                await generateDraftEnAbstract(taskId, activeModel || undefined);
                await refresh();
              }}
            >
              <AutoGrowTextarea
                value={draft.abstract?.en || ""}
                onChange={(e) =>
                  setDraft((prev) =>
                    prev
                      ? { ...prev, abstract: { ...prev.abstract, en: e.target.value } }
                      : prev,
                  )
                }
                placeholder="English abstract…"
                className={paraCls}
              />
            </Block>

            {/* Keywords */}
            <Block id="sec-keywords-en" title="Keywords">
              <AutoGrowTextarea
                value={kwText(draft.keywords?.en)}
                onChange={(e) =>
                  setDraft((prev) =>
                    prev
                      ? {
                          ...prev,
                          keywords: {
                            ...prev.keywords,
                            en: kwList(e.target.value),
                          },
                        }
                      : prev,
                  )
                }
                className={paraCls}
              />
            </Block>

            {/* 章节正文 */}
            {roots.map((root) => {
              const children = sections.filter(
                (s) => s.level === 2 && s.id.startsWith(root.id + "-"),
              );
              return (
                <section key={root.id} id={`sec-${root.id}`} className="mt-6">
                  <h2 className="text-xl font-bold">{root.title}</h2>
                  {children.map((child) => {
                    const grandchildren = sections.filter(
                      (s) => s.level === 3 && s.id.startsWith(child.id + "-"),
                    );
                    if (grandchildren.length === 0) {
                      return (
                        <LeafSection
                          key={child.id}
                          section={child}
                          genSection={genSection}
                          onPatch={(patch) => void patchSection(child.id, patch)}
                          onGenerate={() => void handleGenerateSection(child)}
                          onAdd={() => void addPara(child.id)}
                          onPatchPara={patchParagraph}
                          onDel={delPara}
                          onMove={movePara}
                        />
                      );
                    }
                    return (
                      <div key={child.id}>
                        <h3 className="mt-4 text-lg font-semibold">
                          {child.number} {child.title}
                        </h3>
                        {grandchildren.map((g) => (
                          <LeafSection
                            key={g.id}
                            section={g}
                            genSection={genSection}
                            onPatch={(patch) => void patchSection(g.id, patch)}
                            onGenerate={() => void handleGenerateSection(g)}
                            onAdd={() => void addPara(g.id)}
                            onPatchPara={patchParagraph}
                            onDel={delPara}
                            onMove={movePara}
                          />
                        ))}
                      </div>
                    );
                  })}
                </section>
              );
            })}

            {/* 致谢 */}
            <Block
              id="sec-ack"
              title="致谢"
              actionLabel="生成致谢"
              onAction={async () => {
                setError(null);
                await generateDraftAck(taskId, activeModel || undefined);
                await refresh();
              }}
            >
              <AutoGrowTextarea
                value={draft.acknowledgement || ""}
                onChange={(e) =>
                  setDraft((prev) =>
                    prev ? { ...prev, acknowledgement: e.target.value } : prev,
                  )
                }
                placeholder="致谢（可点击生成或手动填写）"
                className={paraCls}
              />
            </Block>

            {/* 参考文献 */}
            <Block id="sec-refs" title={`参考文献（${draft.references.length} 条）`}>
              <ol className="list-decimal space-y-1.5 pl-6 text-sm leading-relaxed text-neutral-700">
                {draft.references.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ol>
            </Block>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ============ 子组件 ============ */

/** 高度自适应 textarea：内容全部摊开显示，不内部滚动（对齐 example 的 paragraph-textarea）。 */
function AutoGrowTextarea({
  value,
  onChange,
  placeholder,
  className,
  minRows = 3,
}: {
  value: string;
  onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  placeholder?: string;
  className?: string;
  minRows?: number;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const grow = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${el.scrollHeight}px`;
    el.style.overflowY = "hidden";
  }, []);
  useEffect(() => {
    grow();
  }, [value, grow]);
  return (
    <textarea
      ref={ref}
      value={value}
      onChange={(e) => {
        onChange(e);
        requestAnimationFrame(grow);
      }}
      placeholder={placeholder}
      rows={minRows}
      className={`${className || ""} resize-none overflow-hidden`}
    />
  );
}

/** 目录树通用节点（摘要/关键词/Abstract/Keywords/致谢/参考文献）。 */
function TreeNode({
  label,
  value,
  actionLabel,
  onAction,
  onJump,
}: {
  label: string;
  value: string;
  actionLabel?: string;
  onAction?: () => void;
  onJump?: () => void;
}) {
  return (
    <div
      className="flex h-[70px] cursor-pointer items-center gap-2 rounded-md px-4 hover:bg-black/[0.05]"
      onClick={onJump}
    >
      <input
        readOnly
        value={value}
        placeholder={`${label}…`}
        className={`${INPUT_FLAT} flex-1 text-[12px] text-neutral-500`}
      />
      {actionLabel && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onAction?.();
          }}
          className={BTN_TINY}
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}

/** 目录树章节小节节点。 */
function SectionTreeItem({
  section,
  isLeaf,
  genSection,
  onJump,
  onPatch,
  onGenerate,
}: {
  section: DraftSection;
  isLeaf: boolean;
  genSection: string | null;
  onJump: () => void;
  onPatch: (patch: { title?: string; gist?: string }) => void;
  onGenerate: () => void;
}) {
  return (
    <div
      className="flex h-[70px] cursor-pointer flex-col justify-center rounded-md px-4 hover:bg-black/[0.05]"
      onClick={onJump}
    >
      <div className="flex items-center gap-1.5">
        <span className="w-7 shrink-0 text-right text-[11px] text-neutral-400">
          {section.number}
        </span>
        <input
          value={section.title}
          onChange={(e) => onPatch({ title: e.target.value })}
          onClick={(e) => e.stopPropagation()}
          className={`${INPUT_FLAT} flex-1 text-[13px]`}
        />
        {isLeaf && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onGenerate();
            }}
            disabled={genSection === section.id}
            className={BTN_TINY}
          >
            {genSection === section.id ? "…" : "生成段落"}
          </button>
        )}
      </div>
        {isLeaf && (
          <input
            value={section.gist}
            onChange={(e) => onPatch({ gist: e.target.value })}
            placeholder="暂无段落主旨"
            onClick={(e) => e.stopPropagation()}
            className={`${INPUT_FLAT} pl-[34px] text-[11px] text-neutral-400`}
          />
        )}
    </div>
  );
}

/** 右栏通用区块（标题 + 可选操作按钮 + 内容）。 */
function Block({
  id,
  title,
  actionLabel,
  onAction,
  children,
}: {
  id: string;
  title: string;
  actionLabel?: string;
  onAction?: () => void;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="mb-6">
      <div className="mb-2 flex items-center justify-between border-b border-neutral-100 pb-1">
        <h4 className="text-[15px] font-semibold">{title}</h4>
        {actionLabel && (
          <button type="button" onClick={onAction} className={BTN_TINY}>
            {actionLabel}
          </button>
        )}
      </div>
      {children}
    </section>
  );
}

/** 右栏叶子小节（标题 + 主旨 + 段落列表 + 操作）。 */
function LeafSection({
  section,
  genSection,
  onPatch,
  onGenerate,
  onAdd,
  onPatchPara,
  onDel,
  onMove,
}: {
  section: DraftSection;
  genSection: string | null;
  onPatch: (patch: { title?: string; gist?: string }) => void;
  onGenerate: () => void;
  onAdd: () => void;
  onPatchPara: (pid: string, text: string) => void;
  onDel: (pid: string) => void;
  onMove: (pid: string, dir: "up" | "down") => void;
}) {
  return (
    <div id={`sec-${section.id}`} className="mt-4 scroll-mt-4">
      <div className="flex items-baseline gap-2">
        <span className="text-sm font-semibold">{section.number}</span>
        <input
          value={section.title}
          onChange={(e) => onPatch({ title: e.target.value })}
          className={`${INPUT_FLAT} flex-1 text-[16px] font-semibold`}
        />
      </div>
      <p className="mb-2 mt-0.5 text-xs text-neutral-400">
        {section.gist || "暂无段落主旨"}
      </p>
      {section.paragraphs.length === 0 && (
        <p className="rounded-md border border-dashed border-neutral-300 py-6 text-center text-sm text-neutral-400">
          暂无段落，点击「生成段落」或「新增段落」
        </p>
      )}
      <div className="space-y-4">
        {section.paragraphs.map((p, i) => (
          <div key={p.id} className="group">
            <AutoGrowTextarea
              value={p.text}
              onChange={(e) => onPatchPara(p.id, e.target.value)}
              className={paraCls}
            />
            <div className="mt-1.5 flex items-center justify-between">
              <span className="text-xs text-neutral-400">段落 {i + 1}</span>
              <div className="flex items-center gap-1 text-xs">
                <button
                  type="button"
                  onClick={() => onMove(p.id, "up")}
                  disabled={i === 0}
                  className="rounded border border-neutral-200 px-2 py-0.5 text-neutral-500 hover:bg-neutral-100 disabled:opacity-40"
                >
                  ↑
                </button>
                <button
                  type="button"
                  onClick={() => onMove(p.id, "down")}
                  disabled={i === section.paragraphs.length - 1}
                  className="rounded border border-neutral-200 px-2 py-0.5 text-neutral-500 hover:bg-neutral-100 disabled:opacity-40"
                >
                  ↓
                </button>
                <button
                  type="button"
                  onClick={() => onDel(p.id)}
                  className="rounded border border-red-200 px-2 py-0.5 text-red-500 hover:bg-red-50"
                >
                  删除
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={onGenerate}
          disabled={genSection === section.id}
          className={BTN_BLACK}
        >
          {genSection === section.id ? "生成中…" : "生成段落"}
        </button>
        <button type="button" onClick={onAdd} className={BTN_GHOST}>
          + 新增段落
        </button>
      </div>
    </div>
  );
}
