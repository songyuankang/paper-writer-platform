import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  createAnalysis,
  getAnalysisResult,
  getDatasetVersions,
  getLabState,
  insertAnalysisResult,
  listAnalyses,
  listDatasets,
  runAnalysis,
  type Analysis,
  type AnalysisResult,
  type AnalysisType,
  type DatasetSummary,
  type DatasetVersion,
  type LabState,
} from "../api/paper";

function message(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}
function number(value?: number | null) { return value == null ? "—" : value.toFixed(4); }
function GroupResult({ result }: { result: AnalysisResult }) {
  const value = result.result;
  if (value.method === "ols") return <div className="space-y-2 rounded bg-slate-50 p-3 text-sm"><p><b>普通线性回归（OLS）</b></p><p>N={value.n} / 原始样本={value.raw_sample_size} / 排除={value.excluded_rows || 0}</p><p>R²={number(value.r_squared)}，Adjusted R²={number(value.adjusted_r_squared)}</p><p>F={number(value.f_statistic)}，p={number(value.f_p_value)}，df=({value.df_model}, {value.df_resid})</p><p>系数：{value.coefficients?.length || 0} 个；VIF 提示：{value.vif?.filter((item) => item.status !== "ok").length || 0} 项</p><div className="max-h-48 overflow-auto rounded border bg-white"><table className="min-w-full text-xs"><thead><tr><th className="p-1 text-left">变量</th><th className="p-1">B</th><th className="p-1">p</th><th className="p-1">VIF</th></tr></thead><tbody>{(value.coefficients || []).map((item) => <tr key={item.variable} className="border-t"><td className="p-1">{item.variable}</td><td className="p-1 text-center">{number(item.coefficient)}</td><td className="p-1 text-center">{number(item.p_value)}</td><td className="p-1 text-center">{number(item.vif)}</td></tr>)}</tbody></table></div></div>;
  if (value.method === "student_t" || value.method === "welch_t") return <div className="space-y-2 rounded bg-slate-50 p-3 text-sm"><p><b>{value.method === "welch_t" ? "Welch t" : "Student t"}</b></p><p>组别：{value.group_a} (n={value.n_a}) / {value.group_b} (n={value.n_b})</p><p>均值：{number(value.mean_a)} / {number(value.mean_b)}</p><p>t={number(value.t_statistic)}，df={number(value.df)}，p={number(value.p_value)}</p><p>Cohen's d={number(value.effect_size)}（{value.effect_size_interpretation}）</p></div>;
  if (value.method === "anova") return <div className="space-y-2 rounded bg-slate-50 p-3 text-sm"><p><b>单因素 ANOVA</b></p><p>F={number(value.f_statistic)}，df=({value.df_between}, {value.df_within})，p={number(value.p_value)}</p><p>eta squared={number(value.eta_squared)}</p><p>组数：{value.groups?.length || 0}；Tukey HSD：{value.tukey_hsd?.length ? `${value.tukey_hsd.length} 组比较` : "未生成"}</p></div>;
  return <div className="space-y-2 rounded bg-slate-50 p-3 text-sm"><p><b>{value.method === "pearson" ? "Pearson r" : "Spearman rho"}</b>：{number(value.method === "pearson" ? value.r : value.rho)}</p><p>N：{value.n}</p><p>P-value：{number(value.p_value)}</p><p>显著性（p &lt; .05）：{value.significant ? "是" : "否"}</p></div>;
}

export default function ResearchAnalysis() {
  const [params] = useSearchParams();
  const [taskId, setTaskId] = useState(params.get("task_id") || "");
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [versions, setVersions] = useState<DatasetVersion[]>([]);
  const [version, setVersion] = useState<number | undefined>(undefined);
  const [type, setType] = useState<AnalysisType>("descriptive");
  const [columns, setColumns] = useState<string[]>([]);
  const [x, setX] = useState("");
  const [y, setY] = useState("");
  const [groupColumn, setGroupColumn] = useState("");
  const [valueColumn, setValueColumn] = useState("");
  const [dependentVariable, setDependentVariable] = useState("");
  const [predictors, setPredictors] = useState<string[]>([]);
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [lab, setLab] = useState<LabState | null>(null);
  const [sectionId, setSectionId] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const activeVersion = useMemo(() => versions.find((item) => item.version === version) || versions[versions.length - 1], [versions, version]);
  const schema = activeVersion?.schema || [];
  const numeric = schema.filter((item) => item.type === "numeric").map((item) => item.name);
  const categorical = schema.filter((item) => item.type !== "numeric").map((item) => item.name);

  async function refresh() {
    if (!taskId) { setDatasets([]); setAnalyses([]); setLab(null); return; }
    const [nextDatasets, nextAnalyses, nextLab] = await Promise.all([listDatasets(taskId), listAnalyses(taskId), getLabState(taskId)]);
    setDatasets(nextDatasets); setAnalyses(nextAnalyses); setLab(nextLab);
    setSectionId((current) => current || nextLab.sections[0]?.id || "");
    setDatasetId((current) => current && nextDatasets.some((item) => item.id === current) ? current : nextDatasets[0]?.id || "");
  }
  useEffect(() => { void refresh().catch((err) => setError(message(err, "请输入有效的论文任务 ID 后加载分析数据。"))); }, [taskId]);
  useEffect(() => {
    if (!datasetId) { setVersions([]); return; }
    void getDatasetVersions(datasetId).then((items) => { setVersions(items); setVersion((current) => current && items.some((item) => item.version === current) ? current : items[items.length - 1]?.version); }).catch((err) => setError(message(err, "无法读取 DatasetVersion")));
  }, [datasetId]);
  useEffect(() => { if (type === "descriptive") setColumns((current) => current.filter((item) => schema.some((field) => field.name === item))); }, [schema, type]);

  function toggleColumn(name: string) { setColumns((current) => current.includes(name) ? current.filter((item) => item !== name) : [...current, name]); }
  function togglePredictor(name: string) { setPredictors((current) => current.includes(name) ? current.filter((item) => item !== name) : [...current, name]); }
  async function runNewAnalysis() {
    if (!taskId || !datasetId || !version) return;
    setBusy(true); setError("");
    try {
      const variables = type === "descriptive" ? { columns: columns.length ? columns : schema.map((item) => item.name) } : type === "independent_t" || type === "anova" ? { group_column: groupColumn, value_column: valueColumn } : type === "regression" ? { dependent_variable: dependentVariable, predictors } : { x, y };
      if ((type === "pearson" || type === "spearman") && (!x || !y)) throw new Error("请选择 X 与 Y 两个数值变量。");
      if ((type === "independent_t" || type === "anova") && (!groupColumn || !valueColumn)) throw new Error("请选择分组变量与数值变量。");
      if (type === "regression" && (!dependentVariable || !predictors.length || predictors.includes(dependentVariable))) throw new Error("请选择一个数值因变量和至少一个不同的数值自变量。");
      const created = await createAnalysis({ task_id: taskId, dataset_id: datasetId, dataset_version: version, type, variables });
      const response = await runAnalysis(created.id);
      setAnalysis(response.analysis); setResult(response.result);
      setNotice(response.result.status === "ready" ? "分析已由后端真实 DatasetVersion 运行完成。" : "分析失败，已保存结构化 warning。" );
      await refresh();
    } catch (err) { setError(message(err, "运行分析失败")); } finally { setBusy(false); }
  }
  async function chooseAnalysis(item: Analysis) {
    setAnalysis(item); setResult(null); setError("");
    try { if (item.last_result_id) setResult(await getAnalysisResult(item.id)); } catch (err) { setError(message(err, "无法读取分析结果")); }
  }
  async function rerun() {
    if (!analysis) return;
    setBusy(true); setError("");
    try { const response = await runAnalysis(analysis.id); setAnalysis(response.analysis); setResult(response.result); setNotice("已重新运行，并保留旧 AnalysisResult。" ); await refresh(); } catch (err) { setError(message(err, "重新运行失败")); } finally { setBusy(false); }
  }
  async function insert(artifact: "table" | "chart" | "actual_predicted" | "residual" | "coefficient") {
    if (!analysis || !result || !sectionId) return;
    setBusy(true); setError("");
    try { await insertAnalysisResult(analysis.id, { section_id: sectionId, result_id: result.id, artifact }); setNotice(artifact === "table" ? "统计结果已插入为真实论文表格。" : "相关散点图已按统一 ChartSpec/ChartAsset 链路插入论文。" ); } catch (err) { setError(message(err, "插入论文失败")); } finally { setBusy(false); }
  }

  return <div className="min-h-screen bg-slate-100 text-slate-900"><header className="border-b border-slate-200 bg-white px-5 py-3 shadow-sm"><div className="mx-auto flex max-w-[1800px] flex-wrap items-center gap-3"><Link to={`/research/data${taskId ? `?task_id=${encodeURIComponent(taskId)}` : ""}`} className="text-sm text-slate-500 hover:text-slate-900">← 研究数据中心</Link><div className="h-5 border-l border-slate-200" /><h1 className="mr-auto text-lg font-semibold">研究分析</h1><input value={taskId} onChange={(event) => setTaskId(event.target.value.trim())} placeholder="32 位论文任务 ID" className="w-64 rounded border border-slate-300 p-2 text-sm" /></div></header>
    <main className="mx-auto grid max-w-[1800px] grid-cols-1 gap-4 p-4 xl:grid-cols-[300px_minmax(500px,1fr)_420px]"><aside className="space-y-4"><section className="rounded-xl border bg-white p-4 shadow-sm"><h2 className="mb-3 font-semibold">数据集</h2><select value={datasetId} onChange={(event) => setDatasetId(event.target.value)} className="mb-2 w-full rounded border border-slate-300 p-2 text-sm"><option value="">选择数据集</option>{datasets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.row_count} 行</option>)}</select><select value={version || ""} onChange={(event) => setVersion(Number(event.target.value) || undefined)} disabled={!datasetId} className="w-full rounded border border-slate-300 p-2 text-sm disabled:bg-slate-100"><option value="">选择版本</option>{versions.map((item) => <option key={item.version} value={item.version}>Dataset v{item.version} · {item.row_count} 行</option>)}</select><div className="mt-4 space-y-2">{schema.map((field) => <div key={field.name} className="rounded border border-slate-100 bg-slate-50 p-2"><div className="flex justify-between text-sm font-medium"><span>{field.name}</span><span className="text-xs text-slate-500">{field.type}</span></div><p className="mt-1 text-xs text-slate-500">缺失 {field.missing_count} · 唯一 {field.unique_count}</p></div>)}</div></section><section className="rounded-xl border bg-white p-4 shadow-sm"><h2 className="mb-2 font-semibold">历史分析</h2><div className="space-y-2">{analyses.map((item) => <button key={item.id} onClick={() => void chooseAnalysis(item)} className={`w-full rounded border p-2 text-left text-sm ${analysis?.id === item.id ? "border-blue-400 bg-blue-50" : "border-slate-200"}`}><p className="truncate font-medium">{item.name}</p><p className="mt-1 text-xs text-slate-500">{item.type} · v{item.dataset_version} · {item.status}</p></button>) || <p className="text-sm text-slate-500">尚无分析。</p>}</div></section></aside>
      <section className="rounded-xl border bg-white p-5 shadow-sm"><h2 className="mb-4 text-lg font-semibold">分析配置</h2><label className="block text-sm font-medium">分析类型<select value={type} onChange={(event) => setType(event.target.value as AnalysisType)} className="mt-1 w-full rounded border border-slate-300 p-2"><option value="descriptive">描述统计</option><option value="pearson">Pearson 相关</option><option value="spearman">Spearman 相关</option><option value="independent_t">独立样本 t 检验</option><option value="anova">单因素 ANOVA</option><option value="regression">线性回归（OLS）</option></select></label>{type === "descriptive" ? <div className="mt-5"><p className="mb-2 text-sm font-medium">变量（不选择时分析全部变量）</p><div className="grid grid-cols-1 gap-2 sm:grid-cols-2">{schema.map((field) => <label key={field.name} className="flex items-center gap-2 rounded border p-2 text-sm"><input type="checkbox" checked={columns.includes(field.name)} onChange={() => toggleColumn(field.name)} />{field.name}<span className="ml-auto text-xs text-slate-400">{field.type}</span></label>)}</div></div> : type === "regression" ? <div className="mt-5"><label className="block text-sm font-medium">因变量<select value={dependentVariable} onChange={(event) => { setDependentVariable(event.target.value); setPredictors((items) => items.filter((item) => item !== event.target.value)); }} className="mt-1 w-full rounded border border-slate-300 p-2"><option value="">选择数值因变量</option>{numeric.map((name) => <option key={name} value={name}>{name}</option>)}</select></label><p className="mb-2 mt-4 text-sm font-medium">自变量（仅支持数值字段）</p><div className="grid grid-cols-1 gap-2 sm:grid-cols-2">{numeric.filter((name) => name !== dependentVariable).map((name) => <label key={name} className="flex items-center gap-2 rounded border p-2 text-sm"><input type="checkbox" checked={predictors.includes(name)} onChange={() => togglePredictor(name)} />{name}</label>)}</div><p className="mt-3 text-sm text-slate-500">OLS 会显示 R²、系数、95% CI、VIF、有效样本量和缺失排除信息；分类自变量第一版不支持。</p></div> : type === "pearson" || type === "spearman" ? <div className="mt-5 grid gap-4 sm:grid-cols-2"><label className="block text-sm font-medium">X<select value={x} onChange={(event) => setX(event.target.value)} className="mt-1 w-full rounded border border-slate-300 p-2"><option value="">选择数值变量</option>{numeric.map((name) => <option key={name} value={name}>{name}</option>)}</select></label><label className="block text-sm font-medium">Y<select value={y} onChange={(event) => setY(event.target.value)} className="mt-1 w-full rounded border border-slate-300 p-2"><option value="">选择数值变量</option>{numeric.filter((name) => name !== x).map((name) => <option key={name} value={name}>{name}</option>)}</select></label><p className="sm:col-span-2 text-sm text-slate-500">计算采用成对有效观测，缺失值、非数值、无穷值与常数列会产生可见 warning 或失败结果。</p></div> : type === "independent_t" || type === "anova" ? <div className="mt-5 grid gap-4 sm:grid-cols-2"><label className="block text-sm font-medium">分组变量<select value={groupColumn} onChange={(event) => setGroupColumn(event.target.value)} className="mt-1 w-full rounded border border-slate-300 p-2"><option value="">选择分类变量</option>{categorical.map((name) => <option key={name} value={name}>{name}</option>)}</select></label><label className="block text-sm font-medium">数值变量<select value={valueColumn} onChange={(event) => setValueColumn(event.target.value)} className="mt-1 w-full rounded border border-slate-300 p-2"><option value="">选择数值变量</option>{numeric.map((name) => <option key={name} value={name}>{name}</option>)}</select></label><p className="sm:col-span-2 text-sm text-slate-500">t 检验要求恰好两组；Levene 检验提示方差不齐时自动采用 Welch t。ANOVA 显著时自动生成 Tukey HSD 结果。</p></div> : type === "regression" ? <div className="mt-5"><label className="block text-sm font-medium">因变量<select value={dependentVariable} onChange={(event) => { setDependentVariable(event.target.value); setPredictors((items) => items.filter((item) => item !== event.target.value)); }} className="mt-1 w-full rounded border border-slate-300 p-2"><option value="">选择数值因变量</option>{numeric.map((name) => <option key={name} value={name}>{name}</option>)}</select></label><p className="mb-2 mt-4 text-sm font-medium">自变量（仅支持数值字段）</p><div className="grid grid-cols-1 gap-2 sm:grid-cols-2">{numeric.filter((name) => name !== dependentVariable).map((name) => <label key={name} className="flex items-center gap-2 rounded border p-2 text-sm"><input type="checkbox" checked={predictors.includes(name)} onChange={() => togglePredictor(name)} />{name}</label>)}</div><p className="mt-3 text-sm text-slate-500">OLS 会显示 R²、系数、95% CI、VIF、有效样本量和缺失排除信息；分类自变量第一版不支持。</p></div> : type === "pearson" || type === "spearman" ? <div className="mt-5 grid gap-4 sm:grid-cols-2"><label className="block text-sm font-medium">X<select value={x} onChange={(event) => setX(event.target.value)} className="mt-1 w-full rounded border border-slate-300 p-2"><option value="">选择数值变量</option>{numeric.map((name) => <option key={name} value={name}>{name}</option>)}</select></label><label className="block text-sm font-medium">Y<select value={y} onChange={(event) => setY(event.target.value)} className="mt-1 w-full rounded border border-slate-300 p-2"><option value="">选择数值变量</option>{numeric.filter((name) => name !== x).map((name) => <option key={name} value={name}>{name}</option>)}</select></label></div> : null}<button onClick={() => void runNewAnalysis()} disabled={!taskId || !datasetId || !version || busy} className="mt-6 rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">运行分析</button>{analysis && <button onClick={() => void rerun()} disabled={busy} className="ml-2 rounded border border-slate-300 px-4 py-2 text-sm disabled:opacity-50">重新运行</button>}<div className="mt-6 border-t pt-4"><label className="block text-sm font-medium">插入位置<select value={sectionId} onChange={(event) => setSectionId(event.target.value)} className="mt-1 w-full rounded border border-slate-300 p-2">{(lab?.sections || []).map((section) => <option key={section.id} value={section.id}>{section.number} {section.title}</option>)}</select></label><button onClick={() => void insert("table")} disabled={!analysis || result?.status !== "ready" || busy} className="mt-3 rounded bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-50">插入统计表</button>{result?.result.method !== "descriptive" && <><button onClick={() => void insert("chart")} disabled={!analysis || result?.status !== "ready" || busy} className="ml-2 rounded border border-blue-300 bg-blue-50 px-3 py-2 text-sm text-blue-800 disabled:opacity-50">插入图表</button>{result?.result.method === "ols" && <><button onClick={() => void insert("residual")} disabled={busy} className="ml-2 rounded border px-3 py-2 text-sm">插入残差图</button><button onClick={() => void insert("coefficient")} disabled={busy} className="ml-2 rounded border px-3 py-2 text-sm">插入系数图</button></>}</>}</div></section>
      <aside className="space-y-4"><section className="rounded-xl border bg-white p-4 shadow-sm"><h2 className="mb-3 font-semibold">结果</h2>{result ? <div className="space-y-4">{result.status === "failed" ? <p className="rounded bg-red-50 p-3 text-sm text-red-700">分析未完成：{result.warnings.join("；")}</p> : <>{result.result.method === "descriptive" ? <><h3 className="text-sm font-medium">数值变量</h3><div className="overflow-auto rounded border"><table className="min-w-full text-xs"><thead className="bg-slate-50"><tr><th className="p-2 text-left">变量</th><th className="p-2">N</th><th className="p-2">Missing</th><th className="p-2">Mean</th><th className="p-2">Median</th><th className="p-2">Std</th></tr></thead><tbody>{(result.result.numeric || []).map((item) => <tr key={item.variable} className="border-t"><td className="p-2">{item.variable}</td><td className="p-2 text-center">{item.count}</td><td className="p-2 text-center">{item.missing}</td><td className="p-2 text-center">{number(item.mean)}</td><td className="p-2 text-center">{number(item.median)}</td><td className="p-2 text-center">{number(item.std)}</td></tr>)}</tbody></table></div><h3 className="text-sm font-medium">分类变量</h3>{(result.result.categorical || []).map((item) => <div key={item.variable} className="rounded border p-2 text-sm"><p className="font-medium">{item.variable} · N={item.count} · Missing={item.missing}</p>{item.frequency.map((row) => <p key={row.category} className="mt-1 text-xs text-slate-600">{row.category}: {row.frequency} ({row.percentage.toFixed(2)}%)</p>)}</div>)}</> : <GroupResult result={result} />}{result.warnings.length > 0 && <div className="rounded bg-amber-50 p-3 text-sm text-amber-800">Warning：{result.warnings.join("；")}</div>}</>}</div> : <p className="text-sm text-slate-500">运行或选择历史分析后显示结构化结果。</p>}</section>{(notice || error) && <div className={`rounded-xl border p-3 text-sm ${error ? "border-red-200 bg-red-50 text-red-700" : "border-emerald-200 bg-emerald-50 text-emerald-700"}`}>{error || notice}</div>}</aside>
    </main></div>;
}
