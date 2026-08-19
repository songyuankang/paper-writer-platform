import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  adaptInsightChart,
  createLabChart,
  exportDraft,
  fetchDraftChartAsset,
  getLabChart,
  getLabDataset,
  getLabState,
  getDatasetVersions,
  insertLabChart,
  type LabAppearance,
  type LabBinding,
  type LabChart,
  type LabChartKind,
  type LabDatasetPreview,
  type LabFilterOperator,
  type LabState,
  type DatasetVersion,
  recomputeLabChart,
  updateLabChart,
} from "../api/paper";

const CHART_TYPES: Array<{ id: LabChartKind; label: string }> = [
  { id: "bar", label: "柱状图" }, { id: "line", label: "折线图" }, { id: "pie", label: "饼图" },
  { id: "scatter", label: "散点图" }, { id: "area", label: "面积图" }, { id: "boxplot", label: "箱线图" },
  { id: "histogram", label: "直方图" }, { id: "heatmap", label: "热力图" }, { id: "combo", label: "组合图" },
];
const AGGREGATIONS = ["none", "count", "sum", "avg", "median", "min", "max"] as const;
const FILTER_OPERATORS: LabFilterOperator[] = ["=", "!=", ">", "<", ">=", "<=", "in", "between"];

type FilterDraft = { column: string; operator: LabFilterOperator; value: string };

function message(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function AssetPreview({ taskId, chart }: { taskId: string; chart: LabChart | null }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const assetId = chart?.asset?.id;
  useEffect(() => {
    let alive = true;
    let objectUrl: string | null = null;
    setUrl(null); setFailed(false);
    if (!chart || !assetId) return () => undefined;
    void fetchDraftChartAsset(taskId, chart.id, "svg").then((blob) => {
      objectUrl = URL.createObjectURL(blob);
      if (alive) setUrl(objectUrl);
    }).catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [taskId, chart?.id, chart?.version, assetId]);
  if (!chart) return <div className="flex h-full min-h-[440px] items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 text-sm text-slate-500">从左侧选择数据表并新建图表，或选择已有图表。</div>;
  if (url && !failed) return <div className="flex h-full min-h-[440px] items-center justify-center rounded-xl border bg-white p-4 shadow-sm"><img src={url} alt={chart.title} className="max-h-[70vh] w-full object-contain" /></div>;
  return <div className="flex h-full min-h-[440px] items-center justify-center rounded-xl border bg-slate-50 text-sm text-slate-500">{failed ? "图表资产无法加载，请重新计算。" : "正在加载统一图表资产…"}</div>;
}

export default function VisualizationLab() {
  const { taskId = "" } = useParams();
  const [state, setState] = useState<LabState | null>(null);
  const [preview, setPreview] = useState<LabDatasetPreview | null>(null);
  const [sourceType, setSourceType] = useState<"table_block" | "research_dataset">("table_block");
  const [datasetId, setDatasetId] = useState("");
  const [datasetVersion, setDatasetVersion] = useState<number | undefined>(undefined);
  const [researchVersions, setResearchVersions] = useState<DatasetVersion[]>([]);
  const [chart, setChart] = useState<LabChart | null>(null);
  const [binding, setBinding] = useState<LabBinding>({ aggregation: "none", filters: [] });
  const [appearance, setAppearance] = useState<LabAppearance>({ template: "academic", legend: true, grid: true });
  const [filters, setFilters] = useState<FilterDraft[]>([]);
  const [insertSectionId, setInsertSectionId] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedDataset = useMemo(() => sourceType === "research_dataset"
    ? state?.research_datasets.find((item) => item.id === datasetId) || null
    : state?.datasets.find((item) => item.id === datasetId) || null, [state, datasetId, sourceType]);
  const fields = preview?.fields || [];
  const categoryFields = fields.filter((field) => field.kind === "string");
  const measureFields = fields.filter((field) => field.kind === "number");

  async function refresh(selectChartId?: string) {
    const next = await getLabState(taskId);
    setState(next);
    const currentExists = sourceType === "research_dataset"
      ? next.research_datasets.some((item) => item.id === datasetId)
      : next.datasets.some((item) => item.id === datasetId);
    if (!currentExists) {
      if (next.datasets.length) { setSourceType("table_block"); setDatasetId(next.datasets[0].id); setDatasetVersion(undefined); }
      else if (next.research_datasets.length) { setSourceType("research_dataset"); setDatasetId(next.research_datasets[0].id); setDatasetVersion(next.research_datasets[0].latest_version); }
      else { setDatasetId(""); setDatasetVersion(undefined); }
    }
    setInsertSectionId((current) => current || next.sections[0]?.id || "");
    const chartId = selectChartId || chart?.id;
    if (chartId) {
      const selected = await getLabChart(taskId, chartId);
      setChart(selected); syncConfig(selected);
    }
  }
  function syncConfig(next: LabChart) {
    const nextBinding = next.chart_spec.binding || {};
    setBinding(nextBinding);
    if (nextBinding.source_type === "research_dataset" && nextBinding.dataset_id) {
      setSourceType("research_dataset"); setDatasetId(nextBinding.dataset_id); setDatasetVersion(nextBinding.dataset_version);
    } else if (nextBinding.source_table_id) {
      setSourceType("table_block"); setDatasetId(nextBinding.dataset_id || ""); setDatasetVersion(undefined);
    }
    setAppearance(next.chart_spec.appearance || {});
    setFilters((next.chart_spec.binding?.filters || []).map((item) => ({ column: item.column, operator: item.operator, value: Array.isArray(item.value) ? item.value.join(",") : String(item.value ?? "") })));
  }
  useEffect(() => { if (taskId) void refresh().catch((err) => setError(message(err, "无法加载 Visualization Lab"))); }, [taskId]);
  useEffect(() => {
    if (sourceType !== "research_dataset" || !datasetId) { setResearchVersions([]); return; }
    void getDatasetVersions(datasetId).then((versions) => {
      setResearchVersions(versions);
      setDatasetVersion((current) => current && versions.some((item) => item.version === current) ? current : versions[versions.length - 1]?.version);
    }).catch((err) => setError(message(err, "无法加载数据集版本")));
  }, [datasetId, sourceType]);
  useEffect(() => {
    if (datasetId) void getLabDataset(taskId, datasetId, 50, 0, sourceType === "research_dataset" ? datasetVersion : undefined).then(setPreview).catch((err) => setError(message(err, "无法加载数据集预览")));
  }, [taskId, datasetId, datasetVersion, sourceType]);

  async function chooseChart(chartId: string) {
    try { const next = await getLabChart(taskId, chartId); setChart(next); syncConfig(next); setNotice(""); } catch (err) { setError(message(err, "无法读取图表配置")); }
  }
  async function createChart() {
    if (!selectedDataset) return;
    setBusy(true); setError("");
    try {
      const next = await createLabChart(taskId, sourceType === "research_dataset"
        ? { source_type: "research_dataset", dataset_id: datasetId, dataset_version: datasetVersion, chart_kind: "bar" }
        : { source_type: "table_block", table_id: state?.datasets.find((item) => item.id === datasetId)?.source_table_id || undefined, chart_kind: "bar" });
      setChart(next); syncConfig(next); setNotice("已在图表库中创建。请在右侧配置字段后保存，再插入论文。");
      await refresh(next.id);
    } catch (err) { setError(message(err, "创建图表失败")); } finally { setBusy(false); }
  }
  function patchBinding(patch: Partial<LabBinding>) { setBinding((current) => ({ ...current, ...patch })); }
  function toggleMeasure(name: string) {
    const current = binding.measure_columns || [];
    patchBinding({ measure_columns: current.includes(name) ? current.filter((item) => item !== name) : [...current, name] });
  }
  function requestFilters(): LabBinding["filters"] {
    return filters.filter((item) => item.column && item.value.trim()).map((item) => ({
      column: item.column, operator: item.operator,
      value: item.operator === "in" ? item.value.split(",").map((part) => part.trim()).filter(Boolean) : item.operator === "between" ? item.value.split(",").map((part) => part.trim()).slice(0, 2) : item.value.trim(),
    }));
  }
  async function saveConfiguration() {
    if (!chart) return;
    setBusy(true); setError("");
    try {
      const next = await updateLabChart(taskId, chart.id, { kind: chart.chart_spec.kind, binding: { ...binding, source_type: sourceType, dataset_id: datasetId, dataset_version: sourceType === "research_dataset" ? datasetVersion : binding.dataset_version, filters: requestFilters() }, appearance, title: chart.title, caption: chart.caption });
      setChart(next); syncConfig(next); setNotice("配置已保存，ChartSpec 与 ChartAsset 已在服务端更新。");
      await refresh(next.id);
    } catch (err) { setError(message(err, "保存配置失败")); } finally { setBusy(false); }
  }
  async function recalculate() {
    if (!chart) return;
    setBusy(true); setError("");
    try { const next = await recomputeLabChart(taskId, chart.id, chart.chart_spec.kind); setChart(next); syncConfig(next); setNotice("已从当前 DatasetVersion 重新计算并生成新资产。"); await refresh(next.id); } catch (err) { setError(message(err, "重新计算失败")); } finally { setBusy(false); }
  }
  async function insertPaper() {
    if (!chart || !insertSectionId) return;
    setBusy(true); setError("");
    try { const next = await insertLabChart(taskId, chart.id, insertSectionId); setChart(next); setNotice("图表已插入论文正文；DOCX 导出会按正文顺序重新编号。"); await refresh(next.id); } catch (err) { setError(message(err, "插入论文失败")); } finally { setBusy(false); }
  }
  async function exportPaper() {
    setBusy(true); setError("");
    try { const result = await exportDraft(taskId); setNotice(`DOCX 已生成：${result.files[0] || "论文.docx"}`); } catch (err) { setError(message(err, "导出 DOCX 失败")); } finally { setBusy(false); }
  }
  async function adaptInsight() {
    const insightId = window.prompt("输入需要迁移的 Insight 图表块 ID：");
    if (!insightId) return;
    setBusy(true); setError("");
    try { await adaptInsightChart(taskId, insightId); setNotice("Insight 已生成 ChartSpec v2 与统一 ChartAsset。"); await refresh(); } catch (err) { setError(message(err, "Insight 适配失败")); } finally { setBusy(false); }
  }

  return <div className="min-h-screen bg-slate-100 text-slate-900">
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white px-5 py-3 shadow-sm">
      <div className="mx-auto flex max-w-[1800px] flex-wrap items-center gap-3"><Link to={`/create/body?task_id=${taskId}`} className="text-sm text-slate-500 hover:text-slate-900">← 返回论文编辑</Link><div className="h-5 border-l border-slate-200" /><h1 className="mr-auto text-lg font-semibold">Visualization Lab</h1><span className="text-xs text-slate-500">任务 {taskId.slice(0, 8)}</span>
        <button onClick={() => void saveConfiguration()} disabled={!chart || busy} className="rounded bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-40">保存</button>
        <button onClick={() => void recalculate()} disabled={!chart || busy} className="rounded border border-slate-300 bg-white px-3 py-2 text-sm disabled:opacity-40">重新计算</button>
        <button onClick={() => void insertPaper()} disabled={!chart || !insertSectionId || busy} className="rounded border border-blue-300 bg-blue-50 px-3 py-2 text-sm text-blue-800 disabled:opacity-40">插入论文</button>
        <button onClick={() => void exportPaper()} disabled={busy} className="rounded border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 disabled:opacity-40">导出</button>
      </div>
    </header>
    <main className="mx-auto grid max-w-[1800px] grid-cols-1 gap-4 p-4 xl:grid-cols-[320px_minmax(480px,1fr)_360px]">
      <aside className="space-y-4 xl:sticky xl:top-[76px] xl:max-h-[calc(100vh-92px)] xl:overflow-auto">
        <section className="rounded-xl border bg-white p-4 shadow-sm"><div className="mb-3 flex items-center justify-between"><h2 className="font-semibold">数据集与字段</h2><button onClick={() => void createChart()} disabled={!selectedDataset || busy} className="rounded bg-blue-600 px-2.5 py-1.5 text-xs font-medium text-white disabled:opacity-40">+ 新建图表</button></div>
          <label className="mb-2 block text-xs font-medium text-slate-600">数据来源<select value={sourceType} onChange={(event) => { const nextType = event.target.value as "table_block" | "research_dataset"; setSourceType(nextType); const next = nextType === "research_dataset" ? state?.research_datasets[0] : state?.datasets[0]; setDatasetId(next?.id || ""); setDatasetVersion(nextType === "research_dataset" ? state?.research_datasets[0]?.latest_version : undefined); setPreview(null); }} className="mt-1 w-full rounded border border-slate-300 bg-white p-2 text-sm"><option value="table_block">论文表格</option><option value="research_dataset">研究数据集</option></select></label>
          {sourceType === "table_block" ? <select value={datasetId} onChange={(event) => { setDatasetId(event.target.value); setDatasetVersion(undefined); }} className="mb-3 w-full rounded border border-slate-300 bg-white p-2 text-sm">{(state?.datasets || []).map((item) => <option key={item.id} value={item.id}>{item.title} · {item.row_count} 行 · v{item.version}</option>)}</select> : <><select value={datasetId} onChange={(event) => { setDatasetId(event.target.value); setDatasetVersion(undefined); }} className="mb-2 w-full rounded border border-slate-300 bg-white p-2 text-sm"><option value="">选择研究数据集</option>{(state?.research_datasets || []).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.row_count} 行 · v{item.latest_version}</option>)}</select><select value={datasetVersion || ""} onChange={(event) => setDatasetVersion(Number(event.target.value) || undefined)} disabled={!datasetId} className="mb-3 w-full rounded border border-slate-300 bg-white p-2 text-sm disabled:bg-slate-100"><option value="">选择版本</option>{researchVersions.map((item) => <option key={item.version} value={item.version}>版本 v{item.version} · {item.row_count} 行 · {new Date(item.created_at).toLocaleDateString()}</option>)}</select></>}
          <div className="space-y-2">{fields.map((field) => <div key={field.name} className="rounded border border-slate-100 bg-slate-50 p-2"><div className="flex items-center justify-between text-sm font-medium"><span>{field.name}</span><span className={`rounded px-1.5 py-0.5 text-[10px] ${field.kind === "number" ? "bg-blue-100 text-blue-700" : "bg-violet-100 text-violet-700"}`}>{field.kind === "number" ? "数值" : "类别"}</span></div><p className="mt-1 text-xs text-slate-500">缺失 {field.missing_count} · 唯一 {field.unique_count}</p>{field.statistics && <p className="mt-1 text-xs text-slate-500">均值 {field.statistics.avg.toFixed(2)} · 中位数 {field.statistics.median.toFixed(2)}</p>}</div>)}</div>
        </section>
        <section className="rounded-xl border bg-white p-4 shadow-sm"><h2 className="mb-3 font-semibold">数据预览</h2><div className="max-h-72 overflow-auto rounded border"><table className="min-w-full text-xs"><thead className="sticky top-0 bg-slate-100"><tr>{fields.map((field) => <th className="whitespace-nowrap border-b px-2 py-2 text-left" key={field.name}>{field.name}</th>)}</tr></thead><tbody>{(preview?.rows || []).map((row, index) => <tr key={index}>{fields.map((field) => <td key={field.name} className="max-w-40 truncate border-b px-2 py-1.5">{row[field.name]}</td>)}</tr>)}</tbody></table></div>{preview?.has_more && <p className="mt-2 text-xs text-slate-500">仅展示前 {preview.limit} 行；大数据集按页加载。</p>}</section>
        <section className="rounded-xl border bg-white p-4 shadow-sm"><div className="flex items-center justify-between"><h2 className="font-semibold">图表库</h2><button className="text-xs text-slate-500 hover:text-slate-900" onClick={() => void adaptInsight()} disabled={busy}>适配 Insight</button></div><div className="mt-2 space-y-1">{(state?.charts || []).map((item) => <button key={item.id} onClick={() => void chooseChart(item.id)} className={`w-full rounded border px-2 py-2 text-left text-sm ${chart?.id === item.id ? "border-blue-400 bg-blue-50" : "border-slate-200 hover:bg-slate-50"}`}><div className="flex justify-between gap-2"><span className="truncate font-medium">{item.title}</span><span className="shrink-0 text-xs text-slate-500">{item.kind}</span></div><p className="mt-1 text-xs text-slate-500">{item.in_paper ? "已插入论文" : "仅在图表库"} · {item.status}</p></button>)}</div></section>
      </aside>
      <section className="min-w-0 space-y-3"><div className="flex items-center justify-between rounded-xl border bg-white px-4 py-3 shadow-sm"><div><p className="font-semibold">{chart?.title || "实时图表"}</p><p className="text-xs text-slate-500">由后端 ChartRenderer 生成的 SVG/PNG ChartAsset</p></div>{chart?.status === "stale" && <span className="rounded bg-amber-100 px-2 py-1 text-xs text-amber-800">数据已变更，请重新计算</span>}</div><AssetPreview taskId={taskId} chart={chart} />{chart && <div className="rounded-xl border bg-white p-4 text-sm text-slate-600"><span className="font-medium text-slate-800">当前数据绑定：</span>{chart.chart_spec.binding.dataset_id} · v{chart.chart_spec.binding.dataset_version} · {chart.chart_spec.data.row_count ?? ""} 行参与计算</div>}</section>
      <aside className="space-y-4 xl:sticky xl:top-[76px] xl:max-h-[calc(100vh-92px)] xl:overflow-auto"><section className="rounded-xl border bg-white p-4 shadow-sm"><h2 className="mb-4 font-semibold">配置</h2>{chart ? <div className="space-y-4">
        <label className="block text-sm font-medium">图表类型<select value={chart.chart_spec.kind} onChange={(event) => setChart((current) => current ? { ...current, chart_spec: { ...current.chart_spec, kind: event.target.value as LabChartKind } } : current)} className="mt-1 w-full rounded border border-slate-300 p-2 text-sm">{CHART_TYPES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        <label className="block text-sm font-medium">X 轴 / 类别列<select value={binding.category_column || ""} onChange={(event) => patchBinding({ category_column: event.target.value })} className="mt-1 w-full rounded border border-slate-300 p-2 text-sm">{fields.map((field) => <option key={field.name} value={field.name}>{field.name}</option>)}</select></label>
        <div><p className="text-sm font-medium">Y 轴 / 度量列</p><div className="mt-1 space-y-1 rounded border border-slate-200 p-2">{measureFields.map((field) => <label key={field.name} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={(binding.measure_columns || []).includes(field.name)} onChange={() => toggleMeasure(field.name)} />{field.name}</label>)}</div></div>
        <label className="block text-sm font-medium">Series / 分组列<select value={binding.series_column || ""} onChange={(event) => patchBinding({ series_column: event.target.value || null })} className="mt-1 w-full rounded border border-slate-300 p-2 text-sm"><option value="">不分组</option>{categoryFields.filter((field) => field.name !== binding.category_column).map((field) => <option key={field.name} value={field.name}>{field.name}</option>)}</select></label>
        <label className="block text-sm font-medium">聚合<select value={binding.aggregation || "none"} onChange={(event) => patchBinding({ aggregation: event.target.value as LabBinding["aggregation"] })} className="mt-1 w-full rounded border border-slate-300 p-2 text-sm">{AGGREGATIONS.map((item) => <option key={item} value={item}>{({ none: "不聚合", count: "计数", sum: "求和", avg: "平均值", median: "中位数", min: "最小值", max: "最大值" } as Record<string, string>)[item]}</option>)}</select></label>
        <div><div className="mb-1 flex items-center justify-between"><p className="text-sm font-medium">筛选条件</p><button type="button" onClick={() => setFilters((current) => [...current, { column: fields[0]?.name || "", operator: "=", value: "" }])} className="text-xs text-blue-700">+ 添加</button></div>{filters.map((filter, index) => <div className="mb-2 grid grid-cols-[1fr_76px_1fr_24px] gap-1" key={index}><select value={filter.column} onChange={(event) => setFilters((current) => current.map((item, i) => i === index ? { ...item, column: event.target.value } : item))} className="min-w-0 rounded border p-1 text-xs">{fields.map((field) => <option key={field.name} value={field.name}>{field.name}</option>)}</select><select value={filter.operator} onChange={(event) => setFilters((current) => current.map((item, i) => i === index ? { ...item, operator: event.target.value as LabFilterOperator } : item))} className="rounded border p-1 text-xs">{FILTER_OPERATORS.map((op) => <option key={op} value={op}>{op}</option>)}</select><input value={filter.value} onChange={(event) => setFilters((current) => current.map((item, i) => i === index ? { ...item, value: event.target.value } : item))} placeholder={filter.operator === "between" ? "10,20" : filter.operator === "in" ? "A,B" : "值"} className="min-w-0 rounded border p-1 text-xs" /><button onClick={() => setFilters((current) => current.filter((_, i) => i !== index))} className="text-slate-400 hover:text-red-600">×</button></div>)}</div>
        <label className="block text-sm font-medium">论文图表模板<select value={appearance.template || "academic"} onChange={(event) => setAppearance((current) => ({ ...current, template: event.target.value as LabAppearance["template"] }))} className="mt-1 w-full rounded border border-slate-300 p-2 text-sm">{(state?.templates || []).map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={appearance.legend !== false} onChange={(event) => setAppearance((current) => ({ ...current, legend: event.target.checked }))} />显示图例</label><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={appearance.grid !== false} onChange={(event) => setAppearance((current) => ({ ...current, grid: event.target.checked }))} />显示网格</label><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={appearance.value_labels === true} onChange={(event) => setAppearance((current) => ({ ...current, value_labels: event.target.checked }))} />显示数值标签</label>
        <label className="block text-sm font-medium">插入位置<select value={insertSectionId} onChange={(event) => setInsertSectionId(event.target.value)} className="mt-1 w-full rounded border border-slate-300 p-2 text-sm">{(state?.sections || []).map((section) => <option key={section.id} value={section.id}>{section.number} {section.title}</option>)}</select></label>
      </div> : <p className="text-sm text-slate-500">选择或新建图表后即可编辑 ChartSpec 的绑定和视觉配置。</p>}</section>{(notice || error) && <div className={`rounded-xl border p-3 text-sm ${error ? "border-red-200 bg-red-50 text-red-700" : "border-emerald-200 bg-emerald-50 text-emerald-700"}`}>{error || notice}</div>}</aside>
    </main>
  </div>;
}
