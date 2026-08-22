import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  addDraftOutlineSection,
  confirmDraftOutline,
  deleteDraftOutlineSection,
  fetchDraft,
  fetchTaskStatus,
  regenerateDraftOutline,
  updateDraftSection,
  type DraftSection,
  type PaperDraft,
} from "../../api/paper";
import { useCreateWizard } from "./CreateWizardContext";

const riskStyle: Record<string, string> = {
  high: "border-amber-200 bg-amber-50 text-amber-900",
  low: "border-emerald-200 bg-emerald-50 text-emerald-900",
};

export default function OutlineReviewPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { modelId } = useCreateWizard();
  const taskId = searchParams.get("task");
  const [draft, setDraft] = useState<PaperDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [waitingLong, setWaitingLong] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState<"regenerate" | "confirm" | null>(null);
  const [editing, setEditing] = useState<Record<string, { title: string; gist: string }>>({});
  const [newTitle, setNewTitle] = useState("");
  const [parentId, setParentId] = useState("");

  const refresh = useCallback(async () => {
    if (!taskId) return;
    setDraft(await fetchDraft(taskId));
    setEditing({});
  }, [taskId]);

  useEffect(() => {
    if (!taskId) {
      navigate("/create/topic", { replace: true });
      return;
    }
    let cancelled = false;
    let retry: number | undefined;
    const startedAt = Date.now();

    const scheduleRetry = () => {
      retry = window.setTimeout(() => void load(), 1000);
    };
    const load = async () => {
      try {
        const next = await fetchDraft(taskId);
        if (!cancelled) {
          setDraft(next);
          setError(null);
          setWaitingLong(false);
          setLoading(false);
        }
      } catch (draftError) {
        if (cancelled) return;
        try {
          const info = await fetchTaskStatus(taskId);
          if (cancelled) return;
          if (info.status === "queued" || info.status === "running") {
            if (Date.now() - startedAt >= 120_000) {
              setWaitingLong(true);
            }
            scheduleRetry();
            return;
          }
          setError(
            info.status === "failed"
              ? (info.error ?? "大纲草稿生成失败")
              : "草稿生成已结束但未找到草稿文件，请重新生成",
          );
        } catch {
          setError(
            draftError instanceof Error ? draftError.message : "无法读取大纲草稿",
          );
        }
        setLoading(false);
      }
    };
    setDraft(null);
    setError(null);
    setLoading(true);
    setWaitingLong(false);
    void load();
    return () => {
      cancelled = true;
      if (retry) window.clearTimeout(retry);
    };
  }, [navigate, taskId]);

  const meta = draft?.outline_meta;
  const roots = useMemo(() => (draft?.sections ?? []).filter((item) => item.level === 1), [draft]);

  async function saveSection(section: DraftSection) {
    if (!taskId) return;
    const value = editing[section.id];
    if (!value?.title.trim()) return;
    try {
      await updateDraftSection(taskId, section.id, { title: value.title.trim(), gist: value.gist.trim() });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存章节失败");
    }
  }

  async function addSection() {
    if (!taskId || !newTitle.trim()) return;
    try {
      await addDraftOutlineSection(taskId, { title: newTitle.trim(), parent_id: parentId || undefined });
      setNewTitle("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "新增章节失败");
    }
  }

  async function removeSection(section: DraftSection) {
    if (!taskId || !window.confirm(`确定删除「${section.number} ${section.title}」及其子章节吗？`)) return;
    try {
      await deleteDraftOutlineSection(taskId, section.id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除章节失败");
    }
  }

  async function regenerate() {
    if (!taskId) return;
    setWorking("regenerate");
    try {
      await regenerateDraftOutline(taskId, modelId || undefined);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "重新生成大纲失败");
    } finally {
      setWorking(null);
    }
  }

  async function confirm() {
    if (!taskId) return;
    setWorking("confirm");
    try {
      await confirmDraftOutline(taskId);
      navigate(`/create/body?task=${encodeURIComponent(taskId)}`, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "确认大纲失败");
    } finally {
      setWorking(null);
    }
  }

  if (loading && !draft) return <p className="py-12 text-center text-sm text-slate-500">{waitingLong ? "生成时间较长，仍在继续准备定制大纲…" : "正在准备定制大纲…"}</p>;
  if (!draft || !meta) return <div className="space-y-4 py-10 text-center"><p className="text-sm text-red-600">{error ?? "大纲草稿尚未就绪"}</p><button type="button" onClick={() => navigate("/create/references")} className="rounded-lg border border-neutral-300 px-4 py-2 text-sm">返回参考文献</button></div>;

  const sourceText = meta.source === "ai" ? "AI 定制大纲" : meta.fallback_kind === "topic" ? "题目化保底大纲" : "通用回退模板";
  return (
    <div className="space-y-5">
      <header>
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Outline review</p>
        <h2 className="mt-1 text-xl font-bold text-slate-900">确认论文大纲</h2>
        <p className="mt-1 text-sm leading-6 text-slate-500">正文生成前，请检查目录是否覆盖研究对象、方法和验证路径。</p>
      </header>
      <section className={`rounded-2xl border p-4 ${riskStyle[meta.template_risk] ?? riskStyle.high}`}>
        <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="text-sm font-semibold">{sourceText}</p><p className="mt-1 text-xs">研究范式：{meta.research_type} · 质量评分：{meta.score}/100 · 题目实体覆盖：{Math.round(meta.entity_coverage * 100)}%{meta.attempt_count ? ` · 生成尝试：${meta.attempt_count} 次` : ""}</p></div><span className="rounded-full border border-current/20 px-2.5 py-1 text-xs">风险：{meta.template_risk === "high" ? "需核对" : "较低"}</span></div>
        {meta.fallback_reason && <p className="mt-3 text-xs leading-5">回退原因：{meta.fallback_reason}</p>}
        {meta.score_breakdown && <p className="mt-3 text-xs leading-5">评分明细：结构 {meta.score_breakdown.structure} · 实体 {meta.score_breakdown.entity} · 范式 {meta.score_breakdown.research_type} · 方法 {meta.score_breakdown.method} · 验证 {meta.score_breakdown.experiment} · 逻辑 {meta.score_breakdown.logic}</p>}
        {meta.entity_matches && meta.entity_matches.length > 0 && <p className="mt-3 text-xs leading-5">实体命中：{meta.entity_matches.map((item) => `${item.entity}${item.matched_sections.length ? `（${item.matched_sections.join("、")}）` : "（未命中）"}`).join("；")}</p>}
        {meta.role_validation && <div className={`mt-3 rounded-lg border p-3 text-xs leading-5 ${meta.role_validation.valid ? "border-emerald-200 bg-emerald-50/70" : "border-red-200 bg-red-50/80"}`}><p className="font-semibold">章节职责校验：{meta.role_validation.valid ? "通过" : "需处理"} · 模板：{meta.role_validation.profile ?? meta.research_type}</p>{meta.role_repair_attempts ? <p className="mt-1">系统已自动尝试修复目录 {meta.role_repair_attempts} 次。</p> : null}{meta.role_validation.issues?.length ? <ul className="mt-1 list-disc space-y-1 pl-4">{meta.role_validation.issues.map((issue, index) => <li key={`${issue.code}-${index}`}>{issue.message}{issue.roles?.length ? `（涉及：${issue.roles.join("、")}）` : ""}</li>)}</ul> : null}{meta.role_repair_failed ? <p className="mt-2 font-medium">自动修复后仍不符合职责模板。请编辑或重新生成目录；如坚持使用当前结构，点击下方按钮即表示已明确确认该风险。</p> : null}</div>}
        {meta.issues.length > 0 && <ul className="mt-3 list-disc space-y-1 pl-5 text-xs leading-5">{meta.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>}
        <p className="mt-3 text-xs">建议覆盖：{meta.required_elements.join("、")}</p>
      </section>
      {error && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
      <section className="rounded-2xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-sm font-semibold text-slate-900">目录与写作主旨</h3><p className="mt-1 text-xs text-slate-500">可编辑标题和末级小节主旨；正文生成前也可新增或删除章节。</p></div><button type="button" onClick={() => void regenerate()} disabled={working !== null} className="rounded-lg border border-neutral-300 px-3 py-2 text-xs font-medium hover:border-black disabled:opacity-50">{working === "regenerate" ? "重新生成中…" : "重新生成定制大纲"}</button></div>
        <div className="mt-4 space-y-2">{draft.sections.map((section) => {
          const value = editing[section.id] ?? { title: section.title, gist: section.gist };
          const isEditing = Boolean(editing[section.id]);
          return <article key={section.id} className="rounded-xl border border-slate-200 bg-slate-50/60 p-3" style={{ marginLeft: `${Math.max(0, section.level - 1) * 18}px` }}>{isEditing ? <div className="space-y-2"><input value={value.title} onChange={(event) => setEditing((old) => ({ ...old, [section.id]: { ...value, title: event.target.value } }))} className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium outline-none focus:border-black" /><textarea value={value.gist} onChange={(event) => setEditing((old) => ({ ...old, [section.id]: { ...value, gist: event.target.value } }))} placeholder="写作主旨（末级小节建议填写）" className="min-h-20 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs leading-5 outline-none focus:border-black" /><div className="flex gap-2"><button type="button" onClick={() => void saveSection(section)} className="rounded-md bg-black px-3 py-1.5 text-xs font-medium text-white">保存</button><button type="button" onClick={() => setEditing((old) => { const next = { ...old }; delete next[section.id]; return next; })} className="rounded-md border border-slate-300 px-3 py-1.5 text-xs">取消</button></div></div> : <div className="flex items-start justify-between gap-3"><div><p className="text-sm font-medium text-slate-800">{section.number} {section.title}</p>{section.gist && <p className="mt-1 text-xs leading-5 text-slate-500">{section.gist}</p>}</div><div className="flex shrink-0 gap-2"><button type="button" onClick={() => setEditing((old) => ({ ...old, [section.id]: { title: section.title, gist: section.gist } }))} className="text-xs text-slate-600 hover:text-black">编辑</button><button type="button" onClick={() => void removeSection(section)} className="text-xs text-slate-400 hover:text-red-600">删除</button></div></div>}</article>;
        })}</div>
        <div className="mt-4 grid gap-2 rounded-xl border border-dashed border-slate-300 bg-white p-3 sm:grid-cols-[1fr_180px_auto]"><input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} placeholder="新增章节标题" className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-black" /><select value={parentId} onChange={(event) => setParentId(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm"><option value="">新增一级章节</option>{roots.map((root) => <option key={root.id} value={root.id}>作为「{root.title}」的小节</option>)}</select><button type="button" onClick={() => void addSection()} disabled={!newTitle.trim()} className="rounded-lg border border-neutral-300 px-3 py-2 text-sm font-medium hover:border-black disabled:opacity-50">新增</button></div>
      </section>
      <footer className="flex flex-col-reverse gap-3 border-t border-slate-100 pt-5 sm:flex-row sm:items-center sm:justify-between"><button type="button" onClick={() => navigate("/create/references")} className="rounded-xl border border-neutral-300 px-4 py-2.5 text-sm text-neutral-700">返回参考文献</button><button type="button" onClick={() => void confirm()} disabled={working !== null} className="rounded-xl bg-black px-6 py-2.5 text-sm font-semibold text-white transition hover:bg-neutral-700 disabled:opacity-50">{working === "confirm" ? "确认中…" : meta.role_repair_failed ? "我已核对职责风险并进入正文" : "确认大纲并进入正文"}</button></footer>
    </div>
  );
}
