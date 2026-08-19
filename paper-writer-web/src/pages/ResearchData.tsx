import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  attachDataset,
  getDataset,
  getDatasetPreview,
  importDataset,
  listDatasets,
  type DatasetImportSelection,
  type DatasetSummary,
  type DatasetVersion,
} from "../api/paper";

const PAGE_SIZE = 50;

type DatasetDetail = { summary: DatasetSummary; versions: DatasetVersion[] };
type PendingImport = {
  file: File;
  selection: DatasetImportSelection;
};

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function formatDate(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

export default function ResearchData() {
  const [params] = useSearchParams();
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [version, setVersion] = useState<number | undefined>(undefined);
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof getDatasetPreview>> | null>(null);
  const [offset, setOffset] = useState(0);
  const [taskId, setTaskId] = useState(params.get("task_id") || "");
  const [uploadName, setUploadName] = useState("");
  const [description, setDescription] = useState("");
  const [targetDatasetId, setTargetDatasetId] = useState("");
  const [pendingImport, setPendingImport] = useState<PendingImport | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const uploadRef = useRef<HTMLInputElement>(null);

  const selectedVersion = useMemo(
    () => detail?.versions.find((item) => item.version === version) || (detail?.versions.length ? detail.versions[detail.versions.length - 1] : null) || null,
    [detail, version],
  );

  async function refresh(preferredId?: string) {
    const items = await listDatasets(taskId || undefined);
    setDatasets(items);
    const nextId = preferredId || (selectedId && items.some((item) => item.id === selectedId) ? selectedId : items[0]?.id || "");
    setSelectedId(nextId);
  }

  async function loadDetail(datasetId: string) {
    if (!datasetId) { setDetail(null); setPreview(null); return; }
    const next = await getDataset(datasetId) as DatasetDetail;
    setDetail(next);
    setVersion((current) => current && next.versions.some((item) => item.version === current) ? current : next.summary.latest_version);
    setOffset(0);
  }

  useEffect(() => { void refresh().catch((err) => setError(errorMessage(err, "无法加载研究数据集"))); }, [taskId]);
  useEffect(() => { void loadDetail(selectedId).catch((err) => setError(errorMessage(err, "无法读取数据集详情"))); }, [selectedId]);
  useEffect(() => {
    if (!selectedId || !version) { setPreview(null); return; }
    void getDatasetPreview(selectedId, version, PAGE_SIZE, offset).then(setPreview).catch((err) => setError(errorMessage(err, "无法读取数据预览")));
  }, [selectedId, version, offset]);

  async function handleFile(file: File) {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await importDataset({ file, name: uploadName, description, dataset_id: targetDatasetId || undefined, task_id: taskId || undefined });
      if (result.status === "sheet_selection_required") {
        setPendingImport({ file, selection: result });
        setNotice("该工作簿包含多个工作表，请选择要导入的 Sheet。");
        return;
      }
      setPendingImport(null);
      setNotice(result.dataset.deduplicated ? "检测到相同数据指纹，已复用现有版本。" : `已导入 Dataset v${result.dataset.version}。`);
      setTargetDatasetId(""); setUploadName(""); setDescription("");
      await refresh(result.dataset.dataset_id);
    } catch (err) { setError(errorMessage(err, "导入失败")); } finally { setBusy(false); }
  }

  async function finishSheet(sheet: string) {
    if (!pendingImport) return;
    setBusy(true); setError("");
    try {
      const result = await importDataset({
        import_token: pendingImport.selection.import_token,
        source_filename: pendingImport.selection.filename,
        name: uploadName,
        description,
        dataset_id: targetDatasetId || undefined,
        task_id: taskId || undefined,
        sheet,
      });
      if (result.status !== "imported") throw new Error("未能完成工作表导入");
      setPendingImport(null); setTargetDatasetId(""); setUploadName(""); setDescription("");
      setNotice(result.dataset.deduplicated ? "检测到相同数据指纹，已复用现有版本。" : `已导入 Sheet「${sheet}」，生成 Dataset v${result.dataset.version}。`);
      await refresh(result.dataset.dataset_id);
    } catch (err) { setError(errorMessage(err, "导入工作表失败")); } finally { setBusy(false); }
  }

  async function attachSelected() {
    if (!selectedId || !taskId) return;
    setBusy(true); setError("");
    try {
      await attachDataset(selectedId, taskId);
      setNotice("研究数据集已关联到该论文任务，可在 Visualization Lab 中选择。");
      await refresh(selectedId);
      await loadDetail(selectedId);
    } catch (err) { setError(errorMessage(err, "关联论文任务失败")); } finally { setBusy(false); }
  }

  return <div className="min-h-screen bg-slate-100 text-slate-900">
    <header className="border-b border-slate-200 bg-white px-5 py-3 shadow-sm"><div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-3"><Link to="/history" className="text-sm text-slate-500 hover:text-slate-900">← 论文记录</Link><div className="h-5 border-l border-slate-200" /><h1 className="mr-auto text-lg font-semibold">研究数据中心</h1><span className="text-xs text-slate-500">CSV / XLSX · 版本化 Dataset</span></div></header>
    <main className="mx-auto grid max-w-[1600px] grid-cols-1 gap-4 p-4 xl:grid-cols-[300px_minmax(560px,1fr)_330px]">
      <aside className="space-y-4"><section className="rounded-xl border bg-white p-4 shadow-sm"><h2 className="mb-3 font-semibold">导入研究数据</h2><input ref={uploadRef} type="file" accept=".csv,.xlsx" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) void handleFile(file); event.currentTarget.value = ""; }} />
        <label className="mb-3 block text-sm font-medium">数据集名称<input value={uploadName} onChange={(event) => setUploadName(event.target.value)} placeholder="留空使用文件名" className="mt-1 w-full rounded border border-slate-300 p-2 text-sm" /></label>
        <label className="mb-3 block text-sm font-medium">说明<textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} placeholder="可选：来源、样本范围等" className="mt-1 w-full resize-y rounded border border-slate-300 p-2 text-sm" /></label>
        <label className="mb-3 block text-sm font-medium">导入为<select value={targetDatasetId} onChange={(event) => setTargetDatasetId(event.target.value)} className="mt-1 w-full rounded border border-slate-300 p-2 text-sm"><option value="">新建 Dataset</option>{datasets.map((item) => <option key={item.id} value={item.id}>为「{item.name}」创建新版本</option>)}</select></label>
        <button onClick={() => uploadRef.current?.click()} disabled={busy} className="w-full rounded bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">上传 CSV / XLSX</button>
        {pendingImport && <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-3"><p className="mb-2 text-sm font-medium text-amber-900">选择工作表</p><div className="flex flex-wrap gap-2">{pendingImport.selection.sheets.map((sheet) => <button key={sheet} onClick={() => void finishSheet(sheet)} disabled={busy} className="rounded border border-amber-300 bg-white px-2 py-1 text-xs text-amber-900">{sheet}</button>)}</div></div>}
      </section><section className="rounded-xl border bg-white p-4 shadow-sm"><h2 className="mb-3 font-semibold">数据集列表</h2><div className="space-y-2">{datasets.length ? datasets.map((item) => <button key={item.id} onClick={() => setSelectedId(item.id)} className={`w-full rounded border p-3 text-left ${selectedId === item.id ? "border-blue-400 bg-blue-50" : "border-slate-200 hover:bg-slate-50"}`}><p className="truncate text-sm font-medium">{item.name}</p><p className="mt-1 text-xs text-slate-500">{item.row_count} 行 · {item.variable_count} 变量 · v{item.latest_version}</p><p className="mt-1 text-xs text-slate-400">{formatDate(item.updated_at)}</p></button>) : <p className="text-sm text-slate-500">尚无数据集。</p>}</div></section></aside>
      <section className="space-y-4"><section className="rounded-xl border bg-white p-5 shadow-sm">{detail && selectedVersion ? <><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">{detail.summary.name}</h2><p className="mt-1 text-sm text-slate-500">{detail.summary.description || "未填写数据集说明"}</p></div><select value={version || ""} onChange={(event) => { setVersion(Number(event.target.value)); setOffset(0); }} className="rounded border border-slate-300 p-2 text-sm">{detail.versions.map((item) => <option key={item.version} value={item.version}>版本 v{item.version} · {formatDate(item.created_at)}</option>)}</select></div><div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4"><div className="rounded bg-slate-50 p-3"><p className="text-xs text-slate-500">样本量</p><p className="mt-1 text-lg font-semibold">{selectedVersion.row_count}</p></div><div className="rounded bg-slate-50 p-3"><p className="text-xs text-slate-500">变量数</p><p className="mt-1 text-lg font-semibold">{selectedVersion.schema.length}</p></div><div className="rounded bg-slate-50 p-3"><p className="text-xs text-slate-500">重复记录</p><p className="mt-1 text-lg font-semibold">{selectedVersion.quality.duplicate_rows}</p></div><div className="rounded bg-slate-50 p-3"><p className="text-xs text-slate-500">文件来源</p><p className="mt-1 truncate text-sm font-semibold">{selectedVersion.source.filename}</p></div></div><div className="mt-5"><h3 className="mb-2 font-medium">字段与质量</h3><div className="overflow-auto rounded border"><table className="min-w-full text-sm"><thead className="bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-3 py-2">字段</th><th className="px-3 py-2">类型</th><th className="px-3 py-2">缺失</th><th className="px-3 py-2">唯一值</th><th className="px-3 py-2">基础统计</th><th className="px-3 py-2">提示</th></tr></thead><tbody>{selectedVersion.schema.map((column) => <tr key={column.name} className="border-t"><td className="px-3 py-2 font-medium">{column.name}</td><td className="px-3 py-2">{column.type}</td><td className="px-3 py-2">{column.missing_count}</td><td className="px-3 py-2">{column.unique_count}</td><td className="px-3 py-2 text-xs text-slate-600">{column.stats ? `均值 ${column.stats.mean.toFixed(2)} · 中位数 ${column.stats.median.toFixed(2)}` : "—"}</td><td className="max-w-56 px-3 py-2 text-xs text-amber-700">{column.warnings.join("；") || "—"}</td></tr>)}</tbody></table></div>{selectedVersion.quality.warnings.length > 0 && <p className="mt-2 text-sm text-amber-700">质量提示：{selectedVersion.quality.warnings.join("；")}</p>}</div></> : <div className="py-20 text-center text-sm text-slate-500">从左侧选择或导入研究数据集。</div>}</section>
      {preview && <section className="rounded-xl border bg-white p-5 shadow-sm"><div className="mb-3 flex items-center justify-between"><div><h2 className="font-semibold">数据预览</h2><p className="mt-1 text-xs text-slate-500">服务端分页读取，每次最多 {PAGE_SIZE} 行。</p></div><span className="text-xs text-slate-500">第 {preview.offset + 1}–{Math.min(preview.offset + preview.rows.length, preview.row_count)} / {preview.row_count} 行</span></div><div className="overflow-auto rounded border"><table className="min-w-full text-xs"><thead className="bg-slate-50"><tr>{preview.schema.map((column) => <th key={column.name} className="whitespace-nowrap border-b px-3 py-2 text-left">{column.name}</th>)}</tr></thead><tbody>{preview.rows.map((row, index) => <tr key={index}>{preview.schema.map((column) => <td key={column.name} className="max-w-56 truncate border-b px-3 py-2">{row[column.name]}</td>)}</tr>)}</tbody></table></div><div className="mt-3 flex justify-between"><button onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))} disabled={preview.offset === 0} className="rounded border px-3 py-1.5 text-sm disabled:opacity-40">上一页</button><button onClick={() => setOffset((current) => current + PAGE_SIZE)} disabled={!preview.has_more} className="rounded border px-3 py-1.5 text-sm disabled:opacity-40">下一页</button></div></section>}</section>
      <aside className="space-y-4"><section className="rounded-xl border bg-white p-4 shadow-sm"><h2 className="mb-3 font-semibold">关联论文任务</h2><p className="mb-3 text-sm text-slate-500">关联后，该数据集将出现在对应论文的 Visualization Lab 数据源中。</p><input value={taskId} onChange={(event) => setTaskId(event.target.value.trim())} placeholder="输入 32 位论文任务 ID" className="mb-3 w-full rounded border border-slate-300 p-2 text-sm" /><button onClick={() => void attachSelected()} disabled={!selectedId || !taskId || busy} className="w-full rounded bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">关联当前数据集</button>{selectedId && taskId && <Link to={`/lab/${taskId}`} className="mt-3 block rounded border border-blue-300 bg-blue-50 px-3 py-2 text-center text-sm text-blue-800">打开 Visualization Lab</Link>}</section><section className="rounded-xl border bg-white p-4 shadow-sm"><h2 className="mb-2 font-semibold">存储说明</h2><p className="text-sm leading-6 text-slate-600">数据行以受控 CSV 文件按版本保存，元数据、字段 Profile 与质量结果保存在独立数据中心目录，不会进入论文 draft.json。</p></section>{(notice || error) && <div className={`rounded-xl border p-3 text-sm ${error ? "border-red-200 bg-red-50 text-red-700" : "border-emerald-200 bg-emerald-50 text-emerald-700"}`}>{error || notice}</div>}</aside>
    </main>
  </div>;
}
