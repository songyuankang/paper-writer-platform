import { useCallback, useEffect, useRef, useState } from "react";
import EditorModalShell from "./EditorModalShell";
import EditableDraftBlock from "./EditableDraftBlock";
import OneClickConfirmModal from "./OneClickConfirmModal";
import HistoryPage from "../pages/History";
import SettingsModels from "../pages/SettingsModels";
import {
  addDraftParagraph,
  updateDraftBlock,
  addDraftTable,
  addDraftChart,
  createDraftInsight,
  regenerateDraftChart,
  updateDraftChart,
  deleteDraftParagraph,
  startDraftOneclick,
  pauseDraftOneclick,
  resumeDraftOneclick,
  regenerateFullDraftSection,
  downloadUrl,
  exportDraft,
  fetchDraft,
  generateDraftAck,
  generateDraftEnAbstract,
  generateDraftSection,
  moveDraftParagraph,
  getReferenceCandidates,
  insertCrossReference,
  renumberTaskReferences,
  updateDraftParagraph,
  updateDraftSection,
  type PaperDraft,
  type DraftSection,
  type ModelConfig,
  type ReferenceCandidate,
} from "../api/paper";
import TemplateManagerModal from "./TemplateManagerModal";

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

/** 正文有效字数：仅统计叶子小节的非空白字符，与后端验收口径一致。 */
function wordCount(draft: PaperDraft): number {
  const parents = new Set(
    draft.sections
      .filter((section) => draft.sections.some((other) => other.id.startsWith(`${section.id}-`)))
      .map((section) => section.id),
  );
  return draft.sections
    .filter((section) => !parents.has(section.id))
    .reduce(
      (total, section) =>
        total + section.paragraphs.reduce(
          (sum, paragraph) => sum + (paragraph.text || "").replace(/\s+/g, "").length,
          0,
        ),
      0,
    );
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
  const [pipelineActionBusy, setPipelineActionBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportedFiles, setExportedFiles] = useState<string[] | null>(null);
  const [templatePickerOpen, setTemplatePickerOpen] = useState(false);
  const [templateManagerOpen, setTemplateManagerOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [modelSettingsOpen, setModelSettingsOpen] = useState(false);
  const [oneclickConfirmOpen, setOneclickConfirmOpen] = useState(false);
  const [revisionOpen, setRevisionOpen] = useState(false);
  const [formatOpen, setFormatOpen] = useState(false);
  const [previewTaskId, setPreviewTaskId] = useState<string | null>(null);
  const [referencePicker, setReferencePicker] = useState<{ sectionId: string; type: "figure" | "table" } | null>(null);
  const [referenceCandidates, setReferenceCandidates] = useState<ReferenceCandidate[]>([]);
  const [referenceBusy, setReferenceBusy] = useState(false);
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

  async function handlePauseOneclick() {
    setError(null);
    setPipelineActionBusy(true);
    try {
      await pauseDraftOneclick(taskId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "暂停失败");
    } finally {
      setPipelineActionBusy(false);
    }
  }

  async function handleResumeOneclick() {
    setError(null);
    setPipelineActionBusy(true);
    try {
      await resumeDraftOneclick(taskId, activeModel || undefined);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "继续生成失败");
    } finally {
      setPipelineActionBusy(false);
    }
  }

  async function handleFullSectionRegenerate(section: DraftSection) {
    setError(null);
    setGenSection(section.id);
    try {
      await regenerateFullDraftSection(taskId, section.id, activeModel || undefined);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "当前章节重新生成失败");
    } finally {
      setGenSection(null);
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

  function openTemplatePicker() {
    setTemplatePickerOpen(true);
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

  async function addTableBlock(sectionId: string) {
    try { await addDraftTable(taskId, sectionId); await refresh(); } catch (err) { setError(err instanceof Error ? err.message : "新增表格失败"); }
  }

  async function createChart(sectionId: string) {
    setError(null);
    try {
      await addDraftChart(taskId, sectionId, { chart_kind: "bar" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "新增图表失败，请先检查本节数据表");
    }
  }

  async function createInsight(sectionId: string) {
    setError(null);
    try {
      await createDraftInsight(taskId, sectionId, {
        scope: "full_paper",
        intent: "auto",
        placement: "section_end",
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "总结生成失败");
    }
  }

  async function patchChart(blockId: string, patch: { title?: string; caption?: string; display_scale?: number }) {
    setError(null);
    try {
      await updateDraftChart(taskId, blockId, patch);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "修改图表失败");
    }
  }

  async function regenerateChart(blockId: string) {
    setError(null);
    try {
      await regenerateDraftChart(taskId, blockId, { illustrative: true });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "重新生成图表失败");
    }
  }

  async function patchContentBlock(blockId: string, patch: { text?: string; title?: string; headers?: string[]; rows?: string[][] }) {
    try { await updateDraftBlock(taskId, blockId, patch); await refresh(); } catch (err) { setError(err instanceof Error ? err.message : "修改内容块失败"); }
  }

  async function addPara(sectionId: string) {
    try {
      await addDraftParagraph(taskId, sectionId);
      await refresh();
    } catch {
      /* 忽略 */
    }
  }

  async function openReferencePicker(sectionId = "", type: "figure" | "table" = "figure") {
    setError(null);
    setReferenceBusy(true);
    try {
      const response = await getReferenceCandidates(taskId);
      setReferenceCandidates(response.objects);
      setReferencePicker({ sectionId, type });
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法加载可引用对象");
    } finally { setReferenceBusy(false); }
  }

  async function insertReference(targetObjectId: string) {
    if (!referencePicker?.sectionId) {
      setError("请先选择要插入引用的正文小节");
      return;
    }
    setReferenceBusy(true);
    try {
      await insertCrossReference({ task_id: taskId, section_id: referencePicker.sectionId, target_object_id: targetObjectId });
      setReferencePicker(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "插入引用失败");
    } finally { setReferenceBusy(false); }
  }

  async function renumberReferences() {
    setError(null);
    try {
      await renumberTaskReferences(taskId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "重新编号失败");
    }
  }

  async function delPara(pid: string) {
    try {
      await deleteDraftParagraph(taskId, pid);
      await renumberReferences();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除内容块失败");
    }
  }

  async function movePara(pid: string, direction: "up" | "down") {
    try {
      await moveDraftParagraph(taskId, pid, direction);
      await renumberReferences();
    } catch (err) {
      setError(err instanceof Error ? err.message : "移动内容块失败");
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

  const totalWords = draft.word_stats?.actual ?? wordCount(draft);
  const target = draft.word_stats?.target ?? draft.meta?.word_count ?? 0;
  const minimum = draft.word_stats?.minimum ?? Math.round(target * 0.95);
  const shortfall = draft.word_stats?.shortfall ?? Math.max(0, target - totalWords);
  const wordStatus = draft.word_status ?? (totalWords >= minimum ? "completed" : "shortfall");
  const pct = target > 0 ? Math.min(100, Math.round((totalWords / target) * 100)) : 0;
  const sections = draft.sections;
  const roots = sections.filter((s) => s.level === 1);
  const pipeline = draft.full_paper_pipeline;
  const pipelinePaused = pipeline?.status === "paused";
  const pipelineRunning = draft.generating || pipeline?.status === "running" || pipeline?.status === "pause_requested";

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
          <span className="text-xs text-neutral-400">正文有效字数</span>
          {!draft.generating && target > 0 && wordStatus === "shortfall" && (
            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
              仍差 {shortfall} 字
            </span>
          )}
          {!draft.generating && target > 0 && wordStatus === "completed" && (
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
              已达标（最低 {minimum} 字）
            </span>
          )}
        </div>
        {pipelineRunning && (
          <span className="flex max-w-[320px] items-center gap-2 truncate text-xs text-neutral-600" title={pipeline?.message}>
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-neutral-300 border-t-black" />
            {pipeline?.message || (wordStatus === "supplementing" ? `字数补写中（第 ${draft.supplement_rounds || 1} 轮）` : `正在生成正文 ${draft.done}/${draft.total}`)}
          </span>
        )}
        {pipelinePaused && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700">已暂停：{pipeline?.message || "可继续生成"}</span>}
        {(pipelineRunning || pipeline?.status === "completed") && (pipeline?.visualization_plan || (pipeline?.visualization_insertions?.length ?? 0) > 0) && (
          <span className="hidden max-w-[360px] items-center gap-1 truncate text-[11px] text-emerald-700 lg:flex" title={pipeline?.visualization_insertions?.map((item) => `${item.label} ${item.title}`).join("；") || pipeline?.visualization_plan?.candidate_titles?.join("；")}>
            {pipeline?.visualization_insertions?.length
              ? <>已插入 {pipeline.visualization_insertions.map((item) => item.label).join("、")}</>
              : <>已找到 {pipeline?.visualization_plan?.candidate_count ?? 0} 个可插入研究表图</>}
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
        <nav className="hidden items-center gap-3 text-sm text-neutral-600 sm:flex" aria-label="编辑器工具">
          <a href={`/lab/${taskId}`} className="font-medium text-blue-700 hover:text-blue-900">Visualization Lab</a>
          <button type="button" onClick={() => void openReferencePicker()} className="hover:text-black">引用</button>
          <button type="button" onClick={() => setTemplateManagerOpen(true)} className="hover:text-black">模板管理</button>
          <button type="button" onClick={() => setHistoryOpen(true)} className="hover:text-black">历史记录</button>
          <button type="button" onClick={() => setModelSettingsOpen(true)} className="hover:text-black">模型设置</button>
        </nav>
        <button
          type="button"
          onClick={() => void renumberReferences()}
          disabled={draft.generating}
          className={BTN_GHOST}
        >
          重新编号
        </button>
        {pipelineRunning && (
          <button type="button" onClick={() => void handlePauseOneclick()} disabled={pipelineActionBusy} className={BTN_GHOST}>
            {pipelineActionBusy ? "处理中…" : "暂停生成"}
          </button>
        )}
        {pipelinePaused && (
          <button type="button" onClick={() => void handleResumeOneclick()} disabled={pipelineActionBusy} className={BTN_BLACK}>
            {pipelineActionBusy ? "处理中…" : "继续生成"}
          </button>
        )}
        <button
          type="button"
          onClick={() => setOneclickConfirmOpen(true)}
          disabled={pipelineRunning || oneclickStarting || pipelinePaused}
          className={BTN_BLACK}
        >
          {oneclickStarting ? "启动中…" : pipelineRunning ? "全文生成中…" : pipelinePaused ? "已暂停" : "一键全文"}
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

      {!draft.generating && target > 0 && wordStatus === "shortfall" && (
        <div className="flex flex-wrap items-center gap-2 border-b border-amber-200 bg-amber-50 px-6 py-2 text-sm text-amber-800">
          <span className="font-semibold">正文尚未达标</span>
          <span>当前 {totalWords}/{target} 字，仍差 {shortfall} 字；系统已完成最多两轮定向补写。可补充或编辑正文后再次执行一键全文。</span>
        </div>
      )}
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
          <button type="button" onClick={() => setRevisionOpen(true)} className="underline underline-offset-2 hover:text-neutral-600">
            在线预览 / 修订
          </button>
          <button type="button" onClick={() => setFormatOpen(true)} className="underline underline-offset-2 hover:text-neutral-600">
            格式处理
          </button>
          <button
            type="button"
            onClick={() => setExportedFiles(null)}
            className="ml-auto text-neutral-400 hover:text-black"
          >
            ✕
          </button>
        </div>
      )}

      <TemplateManagerModal
        open={templateManagerOpen}
        onClose={() => setTemplateManagerOpen(false)}
      />
      <EditorModalShell
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        title="历史记录"
        description="查看、筛选、导出或重新生成任务，不离开当前编辑页。"
      >
        <HistoryPage
          embedded
          onOpenPreview={(historyTaskId) => {
            setHistoryOpen(false);
            setPreviewTaskId(historyTaskId);
            setRevisionOpen(true);
          }}
        />
      </EditorModalShell>
      <EditorModalShell
        open={modelSettingsOpen}
        onClose={() => setModelSettingsOpen(false)}
        title="模型设置"
        description="管理当前写作可用的模型配置，不离开编辑页。"
        className="max-w-[1120px]"
      >
        <SettingsModels embedded />
      </EditorModalShell>
      <EditorModalShell
        open={revisionOpen}
        onClose={() => { setRevisionOpen(false); setPreviewTaskId(null); }}
        title="在线预览 / 修订"
        description="预览和修订在当前编辑页的弹窗中进行，不改变浏览器地址。"
        className="max-w-[1200px]"
      >
        <iframe
          title="论文预览与修订"
          src={`/preview/${previewTaskId || taskId}`}
          className="h-[72vh] w-full rounded-lg border border-slate-200 bg-white"
        />
      </EditorModalShell>
      <EditorModalShell
        open={formatOpen}
        onClose={() => setFormatOpen(false)}
        title="格式处理"
        description="格式处理在当前编辑页的弹窗中完成，不改变浏览器地址。"
        className="max-w-[1200px]"
      >
        <iframe
          title="论文格式处理"
          src={`/format/${taskId}`}
          className="h-[72vh] w-full rounded-lg border border-slate-200 bg-white"
        />
      </EditorModalShell>
      <OneClickConfirmModal
        open={oneclickConfirmOpen}
        onClose={() => setOneclickConfirmOpen(false)}
        onConfirm={() => {
          setOneclickConfirmOpen(false);
          void handleOneclick();
        }}
        modelName={models?.find((model) => model.id === activeModel)?.name}
        currentWords={totalWords}
        targetWords={target}
        sectionCount={draft.sections.filter((section) => section.level === 1).length}
        busy={oneclickStarting || draft.generating}
      />

      <TemplateManagerModal
        open={templatePickerOpen}
        onClose={() => setTemplatePickerOpen(false)}
        selectMode
        onSelectTemplate={(templateId) => {
          setTemplatePickerOpen(false);
          void handleExport(templateId);
        }}
      />
      <EditorModalShell
        open={Boolean(referencePicker)}
        onClose={() => setReferencePicker(null)}
        title="插入交叉引用"
        description="引用标签由目标 ResearchObject 的当前正式编号动态确定；重编号后正文和 DOCX 会同步更新。"
      >
        {referencePicker && <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs text-neutral-600">插入到正文小节
              <select value={referencePicker.sectionId} onChange={(event) => setReferencePicker({ ...referencePicker, sectionId: event.target.value })} className="mt-1 w-full rounded border border-neutral-300 bg-white px-2 py-2 text-sm text-neutral-900">
                <option value="">请选择小节</option>
                {sections.map((section) => <option key={section.id} value={section.id}>{section.number} {section.title}</option>)}
              </select>
            </label>
            <div className="text-xs text-neutral-600">引用类型
              <div className="mt-1 flex gap-2"><button type="button" onClick={() => setReferencePicker({ ...referencePicker, type: "figure" })} className={referencePicker.type === "figure" ? BTN_BLACK : BTN_GHOST}>引用图</button><button type="button" onClick={() => setReferencePicker({ ...referencePicker, type: "table" })} className={referencePicker.type === "table" ? BTN_BLACK : BTN_GHOST}>引用表</button></div>
            </div>
          </div>
          <div className="space-y-2 rounded border border-neutral-200 p-3">
            {(referenceCandidates.filter((item) => item.type === referencePicker.type)).map((item) => <button type="button" key={item.id} disabled={referenceBusy} onClick={() => void insertReference(item.id)} className="flex w-full items-center justify-between rounded border border-neutral-200 px-3 py-2 text-left text-sm transition hover:border-black disabled:opacity-40"><span className="font-medium">{item.display_label}</span><span className="ml-3 flex-1 truncate text-neutral-700">{item.title}</span><span className="text-xs text-neutral-400">插入</span></button>)}
            {!referenceBusy && referenceCandidates.filter((item) => item.type === referencePicker.type).length === 0 && <p className="text-sm text-neutral-500">当前论文没有可引用的{referencePicker.type === "figure" ? "图" : "表"}。</p>}
            {referenceBusy && <p className="text-sm text-neutral-500">正在加载对象…</p>}
          </div>
        </div>}
      </EditorModalShell>

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
                {/* 章节点：可编辑标题（显示 number + title） */}
                <div
                  className="flex h-[70px] cursor-pointer items-center rounded-md px-4 hover:bg-black/[0.05]"
                  onClick={() => scrollTo(`sec-${root.id}`)}
                >
                  <span className="w-7 shrink-0 text-right text-[11px] text-neutral-400">
                    {root.number}
                  </span>
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
                  <h2 className="text-xl font-bold">
                    {root.number} {root.title}
                  </h2>
                  {children.map((child) => {
                    const grandchildren = sections.filter(
                      (s) => s.level === 3 && s.id.startsWith(child.id + "-"),
                    );
                    if (grandchildren.length === 0) {
                      return (
                        <LeafSection
                          key={child.id}
                          taskId={taskId}
                          section={child}
                          genSection={genSection}
                          onPatch={(patch) => void patchSection(child.id, patch)}
                          onGenerate={() => void handleGenerateSection(child)}
                          onRegenerateFull={() => void handleFullSectionRegenerate(child)}
                          onAdd={() => void addPara(child.id)}
                          onAddTable={() => void addTableBlock(child.id)}
          onCreateChart={() => void createChart(child.id)}
                                    onCreateInsight={() => void createInsight(child.id)}
                          onReference={(type) => void openReferencePicker(child.id, type)}
                          onRefresh={async () => { await refresh(); }}

          onChartUpdate={(id, patch) => void patchChart(id, patch)}
          onRegenerateChart={(id) => void regenerateChart(id)}
                          onPatchBlock={(id, patch) => void patchContentBlock(id, patch)}
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
                            taskId={taskId}
                            section={g}
                            genSection={genSection}
                            onPatch={(patch) => void patchSection(g.id, patch)}
                            onGenerate={() => void handleGenerateSection(g)}
                            onRegenerateFull={() => void handleFullSectionRegenerate(g)}
                            onAdd={() => void addPara(g.id)}
                          onAddTable={() => void addTableBlock(g.id)}
                            onCreateChart={() => void createChart(g.id)}
                            onCreateInsight={() => void createInsight(g.id)}
                            onReference={(type) => void openReferencePicker(g.id, type)}
                            onRefresh={async () => { await refresh(); }}
                            onChartUpdate={(id, patch) => void patchChart(id, patch)}
                            onRegenerateChart={(id) => void regenerateChart(id)}
                          onPatchBlock={(id, patch) => void patchContentBlock(id, patch)}
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
  taskId,
  section,
  genSection,
  onPatch,
  onGenerate,
  onRegenerateFull,
  onAdd,
  onAddTable,
  onCreateChart,
  onCreateInsight,
  onReference,
  onRefresh,
  onChartUpdate,
  onRegenerateChart,
  onPatchPara,
  onPatchBlock,
  onDel,
  onMove,
}: {
  taskId: string;
  section: DraftSection;
  genSection: string | null;
  onPatch: (patch: { title?: string; gist?: string }) => void;
  onGenerate: () => void;
  onRegenerateFull: () => void;
  onAdd: () => void;
  onAddTable: () => void;
  onCreateChart: () => void;
  onCreateInsight: () => void;
  onReference: (type: "figure" | "table") => void;
  onRefresh: () => Promise<void> | void;
  onChartUpdate: (id: string, patch: { title?: string; caption?: string; display_scale?: number }) => void;
  onRegenerateChart: (id: string) => void;
  onPatchPara: (pid: string, text: string) => void;
  onPatchBlock: (id: string, patch: { text?: string; title?: string; headers?: string[]; rows?: string[][] }) => void;
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
          <EditableDraftBlock
            key={p.id}
            taskId={taskId}
            block={p}
            index={i}
            onText={(text) => onPatchPara(p.id, text)}
            onUpdate={(patch) => onPatchBlock(p.id, patch)}
            onRefresh={onRefresh}
            onChartUpdate={(patch) => onChartUpdate(p.id, patch)}
            onRegenerateChart={() => onRegenerateChart(p.id)}
            onDelete={() => onDel(p.id)}
            onMove={(direction) => onMove(p.id, direction)}
            canMoveUp={i > 0}
            canMoveDown={i < section.paragraphs.length - 1}
          />
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
        <button type="button" onClick={onRegenerateFull} disabled={genSection === section.id} className={BTN_GHOST}>
          重新生成本节
        </button>
        <button type="button" onClick={onAdd} className={BTN_GHOST}>
          + 新增段落
        </button>
        <button type="button" onClick={onAddTable} className={BTN_GHOST}>+ 新增表格</button>
        <button type="button" onClick={onCreateChart} className={BTN_GHOST}>+ 从表格生成图表</button>
        <button type="button" onClick={() => onReference("figure")} className={BTN_GHOST}>引用图</button>
        <button type="button" onClick={() => onReference("table")} className={BTN_GHOST}>引用表</button>
        <button type="button" onClick={onCreateInsight} className={BTN_GHOST}>+ 总结生成</button>
      </div>
    </div>
  );
}
