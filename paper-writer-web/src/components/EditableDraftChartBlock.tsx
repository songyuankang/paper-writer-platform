import { useEffect, useMemo, useState } from "react";
import { fetchDraftChartAsset, type DraftParagraph } from "../api/paper";

type ChartPatch = { title?: string; caption?: string; display_scale?: number };

type Props = {
  taskId: string;
  block: DraftParagraph;
  index: number;
  onUpdate?: (patch: ChartPatch) => Promise<void> | void;
  onRegenerate?: () => Promise<void> | void;
  onDelete: () => void;
  onMove: (direction: "up" | "down") => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
};

const SCALE_OPTIONS = [0.5, 0.75, 1] as const;
const COLORS = ["#2f5597", "#70ad47", "#ed7d31", "#a5a5a5"];

function text(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function chartData(block: DraftParagraph) {
  const spec = block.chart_spec;
  const legacy = block.chart;
  return {
    kind: spec?.kind ?? legacy?.kind ?? "bar",
    categories: spec?.data?.categories ?? legacy?.categories ?? [],
    series: spec?.data?.series ?? legacy?.series ?? [],
    pie: spec?.data?.pie ?? legacy?.pie ?? [],
  };
}

function FallbackCanvas({ block }: { block: DraftParagraph }) {
  const chart = chartData(block);
  const all = chart.series.flatMap((item) => item.values ?? []).filter((value) => Number.isFinite(value));
  const maximum = Math.max(1, ...all);
  const width = 920;
  const height = 320;
  const left = 58;
  const top = 50;
  const plotWidth = width - left - 36;
  const plotHeight = height - top - 54;
  const categoryWidth = chart.categories.length ? plotWidth / chart.categories.length : plotWidth;

  if (chart.kind === "pie" && chart.pie.length) {
    const total = chart.pie.reduce((sum, item) => sum + Math.max(0, item.value || 0), 0) || 1;
    let cursor = 0;
    const gradient = chart.pie.map((item, index) => {
      const start = cursor;
      cursor += Math.max(0, item.value || 0) / total * 100;
      return COLORS[index % COLORS.length] + " " + start + "% " + cursor + "%";
    }).join(", ");
    return <div className="flex min-h-[300px] items-center justify-center gap-10 px-6 py-6"><div className="h-52 w-52 rounded-full" style={{ background: "conic-gradient(" + gradient + ")" }} /><div className="space-y-2 text-sm text-neutral-600">{chart.pie.map((item, index) => <div key={item.name} className="flex items-center gap-2"><span className="h-3 w-3 rounded-sm" style={{ background: COLORS[index % COLORS.length] }} />{item.name}<span className="ml-2 font-medium text-neutral-900">{item.value}</span></div>)}</div></div>;
  }

  return <svg viewBox={"0 0 " + width + " " + height} className="h-auto w-full min-w-[560px]" role="img" aria-label={text(block.title, "图表预览")}>
    {[0, 0.25, 0.5, 0.75, 1].map((ratio) => <g key={ratio}><line x1={left} x2={width - 28} y1={top + plotHeight * ratio} y2={top + plotHeight * ratio} stroke="#e5e7eb" /><text x={left - 10} y={top + plotHeight * ratio + 4} textAnchor="end" fontSize="11" fill="#8a8a8a">{Math.round(maximum * (1 - ratio) * 10) / 10}</text></g>)}
    {chart.categories.map((category, index) => <text key={category + index} x={left + categoryWidth * index + categoryWidth / 2} y={height - 22} textAnchor="middle" fontSize="11" fill="#5f6368">{category}</text>)}
    {chart.series.map((item, seriesIndex) => {
      const isLine = chart.kind === "line" || (chart.kind === "mixed" && seriesIndex > 0);
      const color = COLORS[seriesIndex % COLORS.length];
      const points = item.values.map((value, index) => [left + categoryWidth * index + categoryWidth / 2, top + plotHeight - (value / maximum) * plotHeight] as const);
      if (isLine) return <g key={item.name}><polyline points={points.map((point) => point.join(",")).join(" ")} fill="none" stroke={color} strokeWidth="2.5" />{points.map((point, index) => <circle key={index} cx={point[0]} cy={point[1]} r="3.5" fill="white" stroke={color} strokeWidth="2" />)}</g>;
      const barWidth = Math.min(46, categoryWidth * 0.56 / Math.max(1, chart.series.length));
      return <g key={item.name}>{item.values.map((value, index) => { const barHeight = (value / maximum) * plotHeight; const x = left + categoryWidth * index + categoryWidth / 2 - barWidth * chart.series.length / 2 + (seriesIndex * barWidth); const y = top + plotHeight - barHeight; return <rect key={index} x={x} y={y} width={barWidth - 2} height={barHeight} rx="2" fill={color} />; })}</g>;
    })}
  </svg>;
}

function ChartAsset({ taskId, block }: { taskId: string; block: DraftParagraph }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const assetId = block.asset?.id;

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setUrl(null);
    setFailed(false);
    if (!assetId) return () => undefined;
    void fetchDraftChartAsset(taskId, block.id, "svg")
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        if (active) setUrl(objectUrl);
      })
      .catch(() => { if (active) setFailed(true); });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [taskId, block.id, assetId, block.version]);

  if (url && !failed) {
    return <img src={url} onError={() => setFailed(true)} className="h-auto w-full" alt={text(block.title, "图表")} />;
  }
  return <FallbackCanvas block={block} />;
}

export default function EditableDraftChartBlock({ taskId, block, index, onUpdate, onRegenerate, onDelete, onMove, canMoveUp, canMoveDown }: Props) {
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(text(block.title, "图表"));
  const [caption, setCaption] = useState(text(block.caption));
  const scale = block.display_scale ?? 0.75;
  const chart = chartData(block);
  const provenance = block.provenance === "user_provided" ? "来源：论文数据表" : block.provenance === "model_generated" ? "来源：模型生成" : "数据示意";
  const label = useMemo(() => ({ bar: "柱状图", line: "折线图", mixed: "柱线混合图", pie: "饼图" }[chart.kind] || "图表"), [chart.kind]);
  const figureNumber = block.figure_number || `图${index + 1}`;
  const stale = block.status === "stale";

  async function savePatch(patch: ChartPatch) { if (!onUpdate) return; setBusy(true); try { await onUpdate(patch); } finally { setBusy(false); } }
  async function regenerate() { if (!onRegenerate) return; setBusy(true); try { await onRegenerate(); } finally { setBusy(false); } }

  return <article className={`my-5 overflow-hidden rounded-lg border bg-white shadow-sm ${stale ? "border-amber-300" : "border-neutral-200"}`} data-chart-block={block.id}>
    <div className="flex flex-wrap items-center gap-2 border-b border-neutral-200 bg-neutral-50 px-3 py-2 text-xs text-neutral-600">
      <span className="font-medium text-neutral-800">{label}</span><span className="text-neutral-300">|</span>
      <button type="button" onClick={regenerate} disabled={busy} className="rounded px-2 py-1 hover:bg-neutral-200 disabled:opacity-50">{busy ? "计算中…" : stale ? "↻ 重新计算" : "↻ 重新计算"}</button>
      <span className="rounded bg-emerald-50 px-2 py-1 text-emerald-700">{provenance}</span>
      {stale && <span className="rounded bg-amber-100 px-2 py-1 text-amber-800">数据表已修改</span>}
      <span className="ml-auto">图表比例</span>
      <select aria-label="图表比例" value={scale} disabled={busy} onChange={(event) => void savePatch({ display_scale: Number(event.target.value) })} className="rounded border border-neutral-300 bg-white px-2 py-1">
        {SCALE_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
      <button type="button" aria-label="编辑图表" onClick={() => setEditing((value) => !value)} className="rounded px-2 py-1 hover:bg-neutral-200">✎</button>
      <button type="button" aria-label="上移图表" onClick={() => onMove("up")} disabled={!canMoveUp} className="rounded px-2 py-1 hover:bg-neutral-200 disabled:opacity-30">↑</button>
      <button type="button" aria-label="下移图表" onClick={() => onMove("down")} disabled={!canMoveDown} className="rounded px-2 py-1 hover:bg-neutral-200 disabled:opacity-30">↓</button>
      <button type="button" aria-label="删除图表" onClick={onDelete} className="rounded px-2 py-1 text-red-600 hover:bg-red-50">⌫</button>
    </div>
    {stale && <p className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-800">{block.stale_reason || "关联论文表格已变更；请重新计算后再导出。"}</p>}
    {editing && <div className="grid gap-3 border-b border-neutral-200 bg-white px-4 py-3 sm:grid-cols-2"><label className="text-xs text-neutral-600">图表标题<input value={title} maxLength={80} onChange={(event) => setTitle(event.target.value)} onBlur={() => void savePatch({ title })} className="mt-1 w-full rounded border border-neutral-300 px-2 py-1.5 text-sm text-neutral-900" /></label><label className="text-xs text-neutral-600">图注<textarea value={caption} maxLength={180} onChange={(event) => setCaption(event.target.value)} onBlur={() => void savePatch({ caption })} className="mt-1 min-h-[60px] w-full rounded border border-neutral-300 px-2 py-1.5 text-sm text-neutral-900" /></label></div>}
    <div className="mx-auto" style={{ width: String(scale * 100) + "%", minWidth: "min(100%, 560px)" }}><div className="px-5 pt-5 text-center"><h4 className="text-base font-semibold text-neutral-900">{block.title}</h4></div><ChartAsset taskId={taskId} block={block} /><div className="px-5 pb-4 text-center"><p className="text-sm font-medium text-neutral-800">{figureNumber} {block.title}</p><p className="mt-1 text-xs text-neutral-500">{block.caption}</p>{block.provenance !== "user_provided" && <p className="mt-1 text-xs text-amber-700">数据为模型/示意生成，未自动检索或核验外部来源。</p>}</div></div>
  </article>;
}
