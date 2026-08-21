import { lazy, Suspense, useEffect, useState } from "react";
import type { DraftParagraph } from "../api/paper";
import {
  EDITABLE_CHART_KINDS,
  editableSpec,
  type EditableChartKind,
  type EditableChartSpec,
  validateEditableChartSpec,
} from "./chartSpecEditorState";

const MonacoChartSpecEditor = lazy(() => import("./MonacoChartSpecEditor"));

type Props = {
  block: DraftParagraph;
  onClose: () => void;
  onSave: (chartSpec: EditableChartSpec) => Promise<void>;
};

const BTN = "rounded border border-neutral-200 bg-white px-3 py-1.5 text-xs text-neutral-700 transition hover:border-black hover:text-black disabled:opacity-40";

function copySpec(spec: EditableChartSpec): EditableChartSpec {
  return JSON.parse(JSON.stringify(spec)) as EditableChartSpec;
}

function normalizePie(spec: EditableChartSpec): EditableChartSpec {
  const next = copySpec(spec);
  const pie = next.data?.pie || [];
  next.data = {
    categories: pie.map((item) => item.name),
    series: [{ name: "数值", values: pie.map((item) => item.value), axis: "left" }],
    pie,
  };
  return next;
}

export default function ChartEditorDrawer({ block, onClose, onSave }: Props) {
  const [mode, setMode] = useState<"normal" | "json">("normal");
  const [spec, setSpec] = useState<EditableChartSpec>(() => editableSpec(block));
  const [jsonText, setJsonText] = useState(() => JSON.stringify(editableSpec(block), null, 2));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const next = editableSpec(block);
    setSpec(next);
    setJsonText(JSON.stringify(next, null, 2));
    setMode("normal");
    setError(null);
  }, [block.id, block.version, block.chart_spec]);

  const data = spec.data || { categories: [], series: [] };
  const categories = data.categories || [];
  const series = data.series || [];

  function changeKind(kind: EditableChartKind) {
    setSpec((current) => {
      const next = copySpec(current);
      next.kind = kind;
      if (kind === "pie") {
        const first = next.data?.series?.[0] || { name: "数值", values: categories.map(() => 0), axis: "left" as const };
        next.data = {
          categories: [...categories],
          series: [{ name: first.name || "数值", values: [...first.values], axis: "left" }],
          pie: categories.map((category, index) => ({ name: category, value: Number(first.values[index] || 0) })),
        };
        return next;
      }
      if (current.kind === "pie") {
        const pie = current.data?.pie || [];
        next.data = {
          categories: pie.map((item) => item.name),
          series: [{ name: "数值", values: pie.map((item) => item.value), axis: "left" }],
        };
      }
      return next;
    });
  }

  function updateCategory(index: number, value: string) {
    setSpec((current) => {
      const next = copySpec(current);
      if (next.kind === "pie") {
        const pie = next.data?.pie || [];
        pie[index] = { ...pie[index], name: value };
        next.data = { ...(next.data || { categories: [], series: [] }), pie };
        return normalizePie(next);
      }
      const nextCategories = [...(next.data?.categories || [])];
      nextCategories[index] = value;
      next.data = { ...(next.data || { categories: [], series: [] }), categories: nextCategories };
      return next;
    });
  }

  function updateValue(seriesIndex: number, categoryIndex: number, rawValue: string) {
    const value = rawValue === "" ? 0 : Number(rawValue);
    setSpec((current) => {
      const next = copySpec(current);
      if (next.kind === "pie") {
        const pie = next.data?.pie || [];
        pie[categoryIndex] = { ...pie[categoryIndex], value };
        next.data = { ...(next.data || { categories: [], series: [] }), pie };
        return normalizePie(next);
      }
      const nextSeries = [...(next.data?.series || [])];
      const item = { ...nextSeries[seriesIndex], values: [...(nextSeries[seriesIndex]?.values || [])] };
      item.values[categoryIndex] = value;
      nextSeries[seriesIndex] = item;
      next.data = { ...(next.data || { categories: [], series: [] }), series: nextSeries };
      return next;
    });
  }

  function updateSeriesName(index: number, value: string) {
    setSpec((current) => {
      const next = copySpec(current);
      const nextSeries = [...(next.data?.series || [])];
      nextSeries[index] = { ...nextSeries[index], name: value };
      next.data = { ...(next.data || { categories: [], series: [] }), series: nextSeries };
      return next;
    });
  }

  function addCategory() {
    setSpec((current) => {
      const next = copySpec(current);
      if (next.kind === "pie") {
        const pie = [...(next.data?.pie || []), { name: `类别 ${categories.length + 1}`, value: 0 }];
        next.data = { ...(next.data || { categories: [], series: [] }), pie };
        return normalizePie(next);
      }
      next.data = {
        ...(next.data || { categories: [], series: [] }),
        categories: [...(next.data?.categories || []), `类别 ${categories.length + 1}`],
        series: (next.data?.series || []).map((item) => ({ ...item, values: [...item.values, 0] })),
      };
      return next;
    });
  }

  function removeCategory(index: number) {
    if (categories.length <= 1) return;
    setSpec((current) => {
      const next = copySpec(current);
      if (next.kind === "pie") {
        const pie = (next.data?.pie || []).filter((_, itemIndex) => itemIndex !== index);
        next.data = { ...(next.data || { categories: [], series: [] }), pie };
        return normalizePie(next);
      }
      next.data = {
        ...(next.data || { categories: [], series: [] }),
        categories: (next.data?.categories || []).filter((_, itemIndex) => itemIndex !== index),
        series: (next.data?.series || []).map((item) => ({ ...item, values: item.values.filter((_, itemIndex) => itemIndex !== index) })),
      };
      return next;
    });
  }

  function addSeries() {
    if (series.length >= 8) return;
    setSpec((current) => {
      const next = copySpec(current);
      next.data = {
        ...(next.data || { categories: [], series: [] }),
        series: [...(next.data?.series || []), { name: `系列 ${(next.data?.series?.length || 0) + 1}`, values: categories.map(() => 0), axis: "left" }],
      };
      return next;
    });
  }

  function removeSeries(index: number) {
    if (series.length <= 1) return;
    setSpec((current) => {
      const next = copySpec(current);
      next.data = { ...(next.data || { categories: [], series: [] }), series: (next.data?.series || []).filter((_, itemIndex) => itemIndex !== index) };
      return next;
    });
  }

  function updateAppearance(key: "x_label" | "y_label" | "legend", value: string | boolean) {
    setSpec((current) => ({ ...current, appearance: { ...(current.appearance || {}), [key]: value } }));
  }

  async function save() {
    setError(null);
    let next: EditableChartSpec;
    try {
      next = mode === "json" ? validateEditableChartSpec(JSON.parse(jsonText)) : validateEditableChartSpec(spec);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ChartSpec 格式无效");
      return;
    }
    setBusy(true);
    try {
      await onSave(next);
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存图表失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[90] flex justify-end bg-black/40" role="dialog" aria-modal="true" aria-label="编辑图表">
      <aside className="flex h-full w-full max-w-[880px] flex-col bg-white shadow-2xl">
        <header className="flex items-center gap-3 border-b border-neutral-200 px-5 py-4">
          <div className="min-w-0 flex-1"><h3 className="text-base font-semibold">编辑图表</h3><p className="mt-0.5 truncate text-xs text-neutral-500">{block.figure_number ? `图${block.figure_number}` : "待编号图表"} · 修改将同步更新正文动态渲染与 DOCX 图表资产。</p></div>
          <button type="button" onClick={onClose} disabled={busy} className={BTN}>关闭</button>
        </header>
        <div className="flex items-center gap-2 border-b border-neutral-200 px-5 py-3 text-xs">
          <button type="button" onClick={() => { setMode("normal"); setError(null); }} className={mode === "normal" ? "rounded bg-black px-3 py-1.5 text-white" : BTN}>普通模式</button>
          <button type="button" onClick={() => { setJsonText(JSON.stringify(spec, null, 2)); setMode("json"); setError(null); }} className={mode === "json" ? "rounded bg-black px-3 py-1.5 text-white" : BTN}>JSON 模式</button>
          <span className="ml-auto text-neutral-500">数据绑定与来源追踪受保护，不可在此修改。</span>
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          {error && <p className="mb-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
          {mode === "normal" ? <div className="space-y-6">
            <section className="grid gap-4 sm:grid-cols-2">
              <label className="text-xs text-neutral-600">图表类型<select value={spec.kind} onChange={(event) => changeKind(event.target.value as EditableChartKind)} className="mt-1 w-full rounded border border-neutral-300 bg-white px-2 py-2 text-sm text-neutral-900">{EDITABLE_CHART_KINDS.map((kind) => <option key={kind} value={kind}>{({ bar: "柱状图", line: "折线图", pie: "饼图", scatter: "散点图" })[kind]}</option>)}</select></label>
              <label className="text-xs text-neutral-600">图表标题<input value={spec.title} onChange={(event) => setSpec((current) => ({ ...current, title: event.target.value }))} className="mt-1 w-full rounded border border-neutral-300 px-2 py-2 text-sm text-neutral-900" /></label>
              <label className="text-xs text-neutral-600">X 轴标题<input value={spec.appearance?.x_label || ""} onChange={(event) => updateAppearance("x_label", event.target.value)} className="mt-1 w-full rounded border border-neutral-300 px-2 py-2 text-sm text-neutral-900" /></label>
              <label className="text-xs text-neutral-600">Y 轴标题<input value={spec.appearance?.y_label || ""} onChange={(event) => updateAppearance("y_label", event.target.value)} className="mt-1 w-full rounded border border-neutral-300 px-2 py-2 text-sm text-neutral-900" /></label>
              <label className="text-xs text-neutral-600 sm:col-span-2">图注<textarea value={spec.caption} onChange={(event) => setSpec((current) => ({ ...current, caption: event.target.value }))} className="mt-1 min-h-[68px] w-full rounded border border-neutral-300 px-2 py-2 text-sm text-neutral-900" /></label>
              <label className="flex items-center gap-2 text-sm text-neutral-700 sm:col-span-2"><input type="checkbox" checked={spec.appearance?.legend !== false} onChange={(event) => updateAppearance("legend", event.target.checked)} />显示图例</label>
            </section>
            <section><div className="mb-2 flex items-center justify-between"><div><h4 className="text-sm font-semibold text-neutral-900">图表数据</h4><p className="mt-1 text-xs text-neutral-500">直接修改类别、系列名称与数值；保存后写入 ChartSpec.data。</p></div><div className="flex gap-2"><button type="button" onClick={addCategory} className={BTN}>+ 类别</button>{spec.kind !== "pie" && <button type="button" onClick={addSeries} disabled={series.length >= 8} className={BTN}>+ 系列</button>}</div></div>
              <div className="overflow-auto rounded border border-neutral-200"><table className="min-w-full text-sm"><thead className="bg-neutral-50"><tr><th className="border-b p-2 text-left">类别</th>{series.map((item, index) => <th className="min-w-[130px] border-b border-l p-2" key={index}><div className="flex items-center gap-1"><input value={item.name} onChange={(event) => updateSeriesName(index, event.target.value)} className="w-full bg-transparent text-center font-semibold outline-none" />{spec.kind !== "pie" && <button type="button" onClick={() => removeSeries(index)} className="text-xs text-red-500" aria-label="删除系列">×</button>}</div></th>)}<th className="border-b border-l p-2" /></tr></thead><tbody>{categories.map((category, categoryIndex) => <tr key={categoryIndex}><td className="border-b p-1"><input value={category} onChange={(event) => updateCategory(categoryIndex, event.target.value)} className="w-full bg-transparent px-2 py-1.5 outline-none focus:bg-amber-50" /></td>{series.map((item, seriesIndex) => <td className="border-b border-l p-1" key={seriesIndex}><input type="number" step="any" value={spec.kind === "pie" ? (spec.data?.pie?.[categoryIndex]?.value ?? 0) : (item.values[categoryIndex] ?? 0)} onChange={(event) => updateValue(seriesIndex, categoryIndex, event.target.value)} className="w-full bg-transparent px-2 py-1.5 text-center outline-none focus:bg-amber-50" /></td>)}<td className="border-b border-l p-1 text-center"><button type="button" onClick={() => removeCategory(categoryIndex)} disabled={categories.length <= 1} className="text-xs text-red-500 disabled:opacity-30">删除</button></td></tr>)}</tbody></table></div>
            </section>
          </div> : <section><p className="mb-3 text-xs leading-5 text-neutral-500">编辑完整 ChartSpec JSON。保存前会校验 JSON、schema、图表类型、类别、系列及数值。数据绑定和来源快照在后端受保护，修改它们会被拒绝。</p><Suspense fallback={<div className="flex h-[420px] items-center justify-center rounded border border-neutral-200 text-sm text-neutral-500">正在加载 JSON 编辑器…</div>}><MonacoChartSpecEditor value={jsonText} onChange={setJsonText} /></Suspense></section>}
        </div>
        <footer className="flex items-center gap-3 border-t border-neutral-200 px-5 py-4"><span className="flex-1 text-xs text-neutral-500">保存后后端将使用同一 ChartSpec 重新生成 PNG/SVG ChartAsset，DOCX 导出保持一致。</span><button type="button" onClick={onClose} disabled={busy} className={BTN}>取消</button><button type="button" onClick={() => void save()} disabled={busy} className="rounded bg-black px-4 py-2 text-xs font-semibold text-white disabled:opacity-40">{busy ? "保存并生成资产…" : "保存图表"}</button></footer>
      </aside>
    </div>
  );
}
