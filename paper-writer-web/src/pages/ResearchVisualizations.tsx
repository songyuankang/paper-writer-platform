import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  API_BASE,
  Literature,
  ResearchEvidence,
  ResearchSearchPlan,
  ResearchVisualizationCandidate,
  createResearchVisualizationPlan,
  extractResearchEvidence,
  getResearchVisualizationPlan,
  insertResearchVisualizationCandidate,
  listResearchEvidence,
  listResearchVisualizationCandidates,
  previewResearchVisualizationCandidate,
  recommendResearchVisualizations,
  saveResearchVisualizationSources,
  searchResearchVisualizationSources,
  verifyResearchEvidence,
} from "../api/paper";

const statusLabel: Record<string, string> = {
  verified: "已核验",
  pending: "待核验",
  conflict: "存在冲突",
  broken: "来源不存在",
  stale: "来源已变化",
  ready: "可加入论文",
  inserted: "已加入论文",
};

const statusClass: Record<string, string> = {
  verified: "bg-emerald-50 text-emerald-700 border-emerald-200",
  ready: "bg-emerald-50 text-emerald-700 border-emerald-200",
  inserted: "bg-slate-100 text-slate-600 border-slate-200",
  pending: "bg-amber-50 text-amber-700 border-amber-200",
  conflict: "bg-amber-50 text-amber-700 border-amber-200",
  stale: "bg-amber-50 text-amber-700 border-amber-200",
  broken: "bg-red-50 text-red-700 border-red-200",
};

function Badge({ status }: { status: string }) {
  return <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${statusClass[status] || "bg-slate-100 text-slate-600 border-slate-200"}`}>{statusLabel[status] || status}</span>;
}

function candidateAssetUrl(taskId: string, candidate: ResearchVisualizationCandidate): string | null {
  if (candidate.kind !== "chart" || !candidate.chart?.chart_id || !taskId) return null;
  return `${API_BASE}/api/draft/${encodeURIComponent(taskId)}/chart/${encodeURIComponent(candidate.chart.chart_id)}/asset?format=svg`;
}

export default function ResearchVisualizations() {
  const route = useParams<{ taskId?: string }>();
  const navigate = useNavigate();
  const [taskId, setTaskId] = useState(route.taskId || "");
  const [topic, setTopic] = useState("");
  const [chapter, setChapter] = useState("");
  const [question, setQuestion] = useState("");
  const [plan, setPlan] = useState<ResearchSearchPlan | null>(null);
  const [results, setResults] = useState<Literature[]>([]);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [savedSources, setSavedSources] = useState<Literature[]>([]);
  const [evidence, setEvidence] = useState<ResearchEvidence[]>([]);
  const [candidates, setCandidates] = useState<ResearchVisualizationCandidate[]>([]);
  const [activeCandidate, setActiveCandidate] = useState<ResearchVisualizationCandidate | null>(null);
  const [sectionId, setSectionId] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const verifiedEvidence = useMemo(() => evidence.filter((item) => item.verification_status === "verified"), [evidence]);

  const refresh = async (id = taskId) => {
    if (!id.trim()) return;
    const [planResult, evidenceResult, candidateResult] = await Promise.all([
      getResearchVisualizationPlan(id).catch(() => null),
      listResearchEvidence(id).catch(() => ({ evidence: [] })),
      listResearchVisualizationCandidates(id).catch(() => ({ candidates: [] })),
    ]);
    if (planResult) {
      setPlan(planResult.plan);
      setTopic(planResult.plan.topic);
      setChapter(planResult.plan.chapter || "");
      setQuestion(planResult.plan.research_question || "");
      setResults(planResult.plan.search_results || []);
    }
    setEvidence(evidenceResult.evidence);
    setCandidates(candidateResult.candidates);
  };

  useEffect(() => { void refresh(route.taskId || ""); }, [route.taskId]);

  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError(""); setNotice("");
    try { await action(); }
    catch (err) { setError(err instanceof Error ? err.message : "操作未完成，请稍后重试。"); }
    finally { setBusy(false); }
  };

  const createPlan = () => run(async () => {
    if (!taskId.trim() || !topic.trim()) throw new Error("请填写论文任务 ID 和研究主题。");
    const response = await createResearchVisualizationPlan({ task_id: taskId.trim(), topic: topic.trim(), chapter: chapter.trim(), research_question: question.trim() });
    setPlan(response.plan); setResults([]); setSavedSources([]); setEvidence([]); setCandidates([]);
    setNotice("已生成检索计划。下一步请检索公开资料并选择要保存的来源。");
  });

  const search = () => run(async () => {
    if (!plan) throw new Error("请先生成检索计划。");
    const response = await searchResearchVisualizationSources({ task_id: taskId, limit: 8 });
    setPlan(response.plan); setResults(response.results); setSavedSources(response.saved_literature); setSelectedSources([]);
    setNotice(`已获得 ${response.results.length} 条公开学术资料候选。检索结果不会自动写入论文。`);
  });

  const saveSelected = () => run(async () => {
    const selected = results.filter((item) => selectedSources.includes(item.external_id || item.doi || item.title));
    if (!selected.length) throw new Error("请至少选择一条来源。");
    const response = await saveResearchVisualizationSources({ task_id: taskId, sources: selected as unknown as Array<Record<string, unknown>> });
    setSavedSources(response.literature);
    setNotice("已保存选中的文献来源。现在可以从可访问摘要或用户记录中提取候选证据。");
  });

  const extract = () => run(async () => {
    if (!savedSources.length) throw new Error("请先保存至少一条来源。");
    const response = await extractResearchEvidence({ task_id: taskId, literature_ids: savedSources.map((item) => item.id) });
    setEvidence(response.evidence);
    setNotice(`已提取并核验 ${response.evidence.length} 条候选数值。待核验、冲突或来源缺失的数据不会进入候选图表。`);
  });

  const verify = () => run(async () => {
    const response = await verifyResearchEvidence({ task_id: taskId, evidence_ids: evidence.map((item) => item.id) });
    setEvidence(response.evidence);
    setNotice("已重新核验来源、原文摘录、数值和单位。");
  });

  const recommend = () => run(async () => {
    if (!verifiedEvidence.length && savedSources.length < 2) throw new Error("请先取得至少两条已核验证据，或保存至少两篇文献以生成文献综述表。");
    const response = await recommendResearchVisualizations({ task_id: taskId, section: chapter, evidence_ids: verifiedEvidence.map((item) => item.id) });
    const usable = response.candidates.filter((item): item is ResearchVisualizationCandidate => "id" in item);
    setCandidates(usable);
    setNotice(usable.length ? "已生成候选内容。请在右侧预览来源后明确确认加入论文。" : "尚无可安全生成的候选内容。");
  });

  const preview = async (candidate: ResearchVisualizationCandidate) => {
    await run(async () => {
      const response = await previewResearchVisualizationCandidate(candidate.id);
      setActiveCandidate(response.candidate);
    });
  };

  const insert = () => run(async () => {
    if (!activeCandidate) throw new Error("请先预览候选内容。");
    if (!sectionId.trim()) throw new Error("请输入论文目标章节 ID；系统不会自动选择正文位置。");
    await insertResearchVisualizationCandidate(activeCandidate.id, { section_id: sectionId.trim(), confirmed: true });
    setNotice("已按你的确认加入论文，并已创建图表/表格编号、来源引用和血缘关系。");
    setActiveCandidate(null);
    await refresh(taskId);
  });

  return <main className="min-h-screen bg-slate-50 text-slate-900">
    <header className="border-b bg-white px-6 py-4 shadow-sm">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
        <div><p className="text-xs font-semibold uppercase tracking-widest text-blue-700">Research Workspace</p><h1 className="mt-1 text-2xl font-semibold">AI 智能研究可视化</h1><p className="mt-1 text-sm text-slate-500">仅将可定位、可核验的来源证据转化为候选图表或研究型表格；加入论文前必须由你确认。</p></div>
        <div className="flex gap-2"><button className="rounded-md border px-3 py-2 text-sm hover:bg-slate-50" onClick={() => taskId && navigate(`/research/${taskId}`)}>返回工作台</button><button className="rounded-md bg-slate-900 px-3 py-2 text-sm text-white hover:bg-slate-700" disabled={busy} onClick={() => void refresh()}>刷新状态</button></div>
      </div>
    </header>
    <div className="mx-auto max-w-7xl px-6 py-5">
      {error && <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
      {notice && <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">{notice}</div>}
      <div className="grid gap-5 xl:grid-cols-[1fr_1.25fr_1fr]">
        <section className="space-y-4 rounded-xl border bg-white p-4 shadow-sm">
          <div><h2 className="font-semibold">研究主题与检索范围</h2><p className="mt-1 text-xs text-slate-500">AI 只制定检索词；来源与数值仍由服务端规则核验。</p></div>
          <label className="block text-sm font-medium">论文任务 ID<input value={taskId} onChange={(event) => setTaskId(event.target.value)} placeholder="论文任务 ID" className="mt-1 w-full rounded-md border px-3 py-2 text-sm" /></label>
          <label className="block text-sm font-medium">研究主题<input value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="例如：红外阵列传感器与毫米波雷达、可穿戴设备技术比较" className="mt-1 w-full rounded-md border px-3 py-2 text-sm" /></label>
          <label className="block text-sm font-medium">当前章节<input value={chapter} onChange={(event) => setChapter(event.target.value)} placeholder="例如：第二章 原理与技术比较" className="mt-1 w-full rounded-md border px-3 py-2 text-sm" /></label>
          <label className="block text-sm font-medium">研究问题<textarea value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} placeholder="希望比较哪些技术或指标？" className="mt-1 w-full rounded-md border px-3 py-2 text-sm" /></label>
          <button disabled={busy} onClick={() => void createPlan()} className="w-full rounded-md bg-blue-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">1. 制定检索计划</button>
          {plan && <div className="rounded-lg bg-slate-50 p-3 text-sm"><p className="font-medium">检索计划</p><ul className="mt-2 list-disc space-y-1 pl-4 text-slate-600">{plan.queries.map((item) => <li key={item}>{item}</li>)}</ul><button disabled={busy} onClick={() => void search()} className="mt-3 w-full rounded-md border border-blue-200 bg-white px-3 py-2 text-sm text-blue-700">2. 搜索公开资料</button></div>}
          <div className="border-t pt-4"><h3 className="text-sm font-semibold">数据集可视化</h3><p className="mt-1 text-xs text-slate-500">已有 Dataset 的字段绑定和统计图仍在 Visualization Lab 中完成。</p><button className="mt-2 w-full rounded-md border px-3 py-2 text-sm hover:bg-slate-50" onClick={() => taskId && navigate(`/lab/${taskId}`)}>打开 Visualization Lab</button></div>
        </section>

        <section className="space-y-4 rounded-xl border bg-white p-4 shadow-sm">
          <div><h2 className="font-semibold">AI 检索过程、来源与证据</h2><p className="mt-1 text-xs text-slate-500">搜索结果不会自动保存，更不会自动成为论文证据。</p></div>
          <div className="max-h-72 space-y-2 overflow-auto pr-1">
            {results.length === 0 && <p className="rounded-md border border-dashed p-4 text-sm text-slate-500">尚未检索公开来源。</p>}
            {results.map((item) => { const key = item.external_id || item.doi || item.title; return <label key={key} className="block cursor-pointer rounded-lg border p-3 hover:bg-slate-50"><div className="flex items-start gap-2"><input type="checkbox" checked={selectedSources.includes(key)} onChange={(event) => setSelectedSources((current) => event.target.checked ? [...current, key] : current.filter((value) => value !== key))} /><span><span className="font-medium">{item.title}</span><span className="mt-1 block text-xs text-slate-500">{item.year || "年份未知"} · {item.journal || item.source} · {item.doi || item.url || "公开元数据"}</span><span className="mt-1 line-clamp-2 block text-xs text-slate-600">{item.abstract || "未提供公开摘要；仅可作为文献综述来源。"}</span></span></div></label>; })}
          </div>
          {results.length > 0 && <button disabled={busy} onClick={() => void saveSelected()} className="w-full rounded-md border border-blue-200 px-3 py-2 text-sm text-blue-700">3. 保存选中的来源</button>}
          <div className="border-t pt-4"><div className="flex items-center justify-between"><h3 className="text-sm font-semibold">可核验证据</h3><button disabled={busy || !savedSources.length} onClick={() => void extract()} className="text-sm text-blue-700">从已保存来源提取</button></div><div className="mt-2 max-h-72 space-y-2 overflow-auto pr-1">{evidence.length === 0 && <p className="text-sm text-slate-500">尚无数值证据。只有原文摘录同时包含数值和单位时，才会被标为已核验。</p>}{evidence.map((item) => <article key={item.id} className="rounded-lg border p-3"><div className="flex items-center justify-between gap-2"><span className="font-medium">{item.subject} · {item.metric}</span><Badge status={item.verification_status} /></div><p className="mt-1 text-sm">{item.value} {item.unit}</p><p className="mt-1 text-xs text-slate-500">来源：{item.source_title} · {item.source_location}</p><blockquote className="mt-2 border-l-2 border-slate-200 pl-2 text-xs text-slate-600">{item.source_quote}</blockquote>{item.verification_issues?.map((issue) => <p key={issue} className="mt-1 text-xs text-amber-700">{issue}</p>)}</article>)}</div>{evidence.length > 0 && <button disabled={busy} onClick={() => void verify()} className="mt-3 w-full rounded-md border px-3 py-2 text-sm hover:bg-slate-50">重新核验来源</button>}</div>
        </section>

        <section className="space-y-4 rounded-xl border bg-white p-4 shadow-sm">
          <div><h2 className="font-semibold">推荐图表与研究型表格</h2><p className="mt-1 text-xs text-slate-500">候选仅供预览。系统不会自动插入正文，也不会在存在冲突时自行选择来源。</p></div>
          <button disabled={busy || (!verifiedEvidence.length && savedSources.length < 2)} onClick={() => void recommend()} className="w-full rounded-md bg-emerald-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">4. 生成候选内容</button>
          <div className="max-h-[38rem] space-y-3 overflow-auto pr-1">{candidates.length === 0 && <p className="rounded-md border border-dashed p-4 text-sm text-slate-500">候选将在来源与证据核验完成后显示。</p>}{candidates.map((candidate) => <article key={candidate.id} className="rounded-lg border p-3"><div className="flex items-start justify-between gap-2"><div><p className="font-medium">{candidate.title}</p><p className="mt-1 text-xs text-slate-500">{candidate.kind === "chart" ? "统计图" : candidate.kind === "table" ? "研究型表格" : "Dataset 图表建议"}</p></div><Badge status={candidate.status} /></div><p className="mt-2 text-sm text-slate-600">{candidate.reason}</p><p className="mt-2 text-xs text-slate-500">已关联 {candidate.evidence_ids?.length || candidate.source_snapshot?.length || 0} 条来源/证据。</p><div className="mt-3 flex gap-2"><button onClick={() => void preview(candidate)} className="rounded border px-2 py-1 text-xs hover:bg-slate-50">预览与查看来源</button>{candidate.kind === "dataset_chart" && <button onClick={() => taskId && navigate(`/lab/${taskId}`)} className="rounded border px-2 py-1 text-xs hover:bg-slate-50">在 Lab 完成绑定</button>}</div></article>)}</div>
        </section>
      </div>
    </div>
    {activeCandidate && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4"><div className="max-h-[90vh] w-full max-w-3xl overflow-auto rounded-xl bg-white p-6 shadow-2xl"><div className="flex items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-widest text-blue-700">预览</p><h2 className="mt-1 text-xl font-semibold">{activeCandidate.title}</h2><p className="mt-1 text-sm text-slate-600">{activeCandidate.reason}</p></div><button onClick={() => setActiveCandidate(null)} className="text-slate-500">关闭</button></div><div className="mt-5 rounded-lg border bg-slate-50 p-4">{activeCandidate.kind === "table" && activeCandidate.table_spec ? <div className="overflow-auto"><table className="min-w-full text-sm"><thead><tr>{activeCandidate.table_spec.headers.map((header) => <th key={header} className="border-b px-3 py-2 text-left">{header}</th>)}</tr></thead><tbody>{activeCandidate.table_spec.rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex} className="border-b px-3 py-2">{cell}</td>)}</tr>)}</tbody></table></div> : candidateAssetUrl(taskId, activeCandidate) ? <img src={candidateAssetUrl(taskId, activeCandidate) || ""} className="mx-auto max-h-96 max-w-full bg-white" alt={activeCandidate.title} /> : <p className="text-sm text-slate-600">此候选需要在 Visualization Lab 选择字段绑定后才会生成正式图表资产。</p>}</div><section className="mt-5"><h3 className="font-medium">来源与核验状态</h3><div className="mt-2 space-y-2">{(activeCandidate.source_snapshot || []).map((source, index) => <div key={`${source.source_title}-${index}`} className="rounded border p-2 text-sm"><div className="flex justify-between gap-2"><span>{source.source_title || "用户提供来源"}</span><Badge status={source.verification_status} /></div><p className="mt-1 text-xs text-slate-500">{source.source_type} {source.source_id ? "· 已关联 Literature/Dataset" : "· 已保留来源摘录"}</p></div>)}</div></section><section className="mt-5 border-t pt-4"><p className="text-sm font-medium">确认加入论文</p><p className="mt-1 text-xs text-slate-500">系统不会自动选择正文位置。请输入目标章节 ID，确认后才会创建 FigureBlock 或 TableBlock、编号、引用和血缘关系。</p><input value={sectionId} onChange={(event) => setSectionId(event.target.value)} placeholder="目标章节 ID，例如 2-1" className="mt-3 w-full rounded-md border px-3 py-2 text-sm" /><button disabled={busy || activeCandidate.status !== "ready" || activeCandidate.kind === "dataset_chart"} onClick={() => void insert()} className="mt-3 w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">确认加入论文</button>{activeCandidate.status !== "ready" && <p className="mt-2 text-xs text-amber-700">该候选当前不是可插入状态，请先处理来源变化、冲突或核验问题。</p>}</section></div></div>}
  </main>;
}
