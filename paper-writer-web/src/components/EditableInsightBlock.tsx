import { useState } from "react";
import type { DraftInsightBlock, DraftParagraph } from "../api/paper";

type Props = {
  block: DraftParagraph;
  index: number;
  onDelete: () => void;
  onMove: (direction: "up" | "down") => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
};

const GROUP_COLORS: Record<string, string> = {
  input: "#E8F0FE", process: "#EAF7EE", output: "#FFF3E0", constraint: "#FCE8E6",
};

function Evidence({ evidence = [], status }: { evidence?: Array<{ excerpt: string }>; status?: string }) {
  const [open, setOpen] = useState(false);
  const text = status === "user_data" ? "数据来源：用户数据表" : status === "outline_synthesis" ? "结构归纳：基于论文题目、目录与关键词" : "内容归纳：基于已列正文证据";
  return <div className="mt-3 border-t border-neutral-100 pt-3 text-xs text-neutral-500"><div className="flex items-center justify-between gap-3"><span>{text}</span>{evidence.length > 0 && <button type="button" onClick={() => setOpen(!open)} className="text-neutral-700 underline">{open ? "收起证据" : "查看证据（" + evidence.length + "）"}</button>}</div>{open && <ul className="mt-2 list-disc space-y-1 pl-5 leading-5">{evidence.map((item, index) => <li key={index}>{item.excerpt}</li>)}</ul>}</div>;
}

function ThreeLineTable({ table }: { table: NonNullable<DraftParagraph["insight"]>["table"] }) {
  if (!table) return null;
  return <div className="overflow-x-auto"><table className="w-full min-w-[560px] border-collapse text-sm text-neutral-800"><thead className="border-y-2 border-neutral-900"><tr>{table.headers.map((header) => <th key={header} className="px-3 py-2 text-center font-semibold">{header}</th>)}</tr></thead><tbody className="border-b-2 border-neutral-900">{table.rows.map((row, rowIndex) => <tr key={rowIndex} className="hover:bg-neutral-50">{table.headers.map((_, cellIndex) => <td key={cellIndex} className="px-3 py-2 align-top leading-6">{row[cellIndex] || "—"}</td>)}</tr>)}</tbody></table></div>;
}

function Framework({ framework }: { framework: NonNullable<DraftParagraph["insight"]>["framework"] }) {
  if (!framework) return null;
  return <div className="mt-4 grid gap-3 md:grid-cols-4">{framework.nodes.map((node) => <div key={node.id} className="rounded-md border border-neutral-200 px-3 py-3 text-center text-sm text-neutral-800" style={{ background: GROUP_COLORS[node.group] || "#F9FAFB" }}>{node.label}</div>)}</div>;
}

function VerifiedChart({ chart }: { chart: NonNullable<DraftParagraph["insight"]>["chart"] }) {
  if (!chart) return null;
  const values = chart.series.flatMap((series) => series.values);
  const max = Math.max(1, ...values);
  return <div className="mt-4 overflow-x-auto"><svg viewBox="0 0 760 280" className="h-auto min-w-[560px] w-full" role="img" aria-label={chart.title}>{[0, .25, .5, .75, 1].map((ratio) => <line key={ratio} x1="52" x2="736" y1={38 + 190 * ratio} y2={38 + 190 * ratio} stroke="#E5E7EB" />)}{chart.categories.map((category, index) => <text key={category} x={52 + (684 / chart.categories.length) * index + (684 / chart.categories.length) / 2} y="252" textAnchor="middle" fontSize="11" fill="#4B5563">{category}</text>)}{chart.series.map((series, seriesIndex) => series.values.map((value, index) => { const barWidth = Math.min(38, 0.54 * (684 / chart.categories.length) / chart.series.length); const x = 52 + (684 / chart.categories.length) * index + (684 / chart.categories.length) / 2 - (barWidth * chart.series.length) / 2 + barWidth * seriesIndex; const h = value / max * 190; const y = 228 - h; const color = ["#4F6FBE", "#70AD47", "#E9AD38"][seriesIndex % 3]; return <g key={series.name + index}><rect x={x} y={y} width={barWidth} height={h} rx="2" fill={color} /><text x={x + barWidth / 2} y={y - 6} textAnchor="middle" fontSize="10" fill={color}>{value}</text></g>; }))}</svg></div>;
}

export default function EditableInsightBlock({ block, index, onDelete, onMove, canMoveUp, canMoveDown }: Props) {
  // 创建与重生成接口返回的是扁平的 DraftInsightBlock；加载历史草稿时仍兼容旧的嵌套 insight 字段。
  const insight = block.insight ?? (block.type === "insight" ? (block as unknown as DraftInsightBlock) : null);
  if (!insight) return null;
  const typeName: Record<string, string> = { chart: "数据图表", comparison_table: "对比分析表", problem_solution_table: "问题—对策表", method_table: "方法比较表", framework_diagram: "研究框架图", three_line_table: "三线表" };
  return <article className="my-5 overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-sm" data-insight-block={block.id}><div className="flex flex-wrap items-center gap-2 border-b border-neutral-200 bg-neutral-50 px-3 py-2 text-xs text-neutral-600"><span className="font-medium text-neutral-800">{typeName[insight.kind] || "总结块"}</span><span className="rounded bg-emerald-50 px-2 py-1 text-emerald-700">{insight.scope === "full_paper" ? "全文总结" : insight.scope === "chapter" ? "章节总结" : "小节总结"}</span><button type="button" aria-label="上移总结块" onClick={() => onMove("up")} disabled={!canMoveUp} className="ml-auto rounded px-2 py-1 hover:bg-neutral-200 disabled:opacity-30">↑</button><button type="button" aria-label="下移总结块" onClick={() => onMove("down")} disabled={!canMoveDown} className="rounded px-2 py-1 hover:bg-neutral-200 disabled:opacity-30">↓</button><button type="button" aria-label="删除总结块" onClick={onDelete} className="rounded px-2 py-1 text-red-600 hover:bg-red-50">⌫</button></div><div className="px-6 py-5"><h4 className="text-center text-base font-semibold text-neutral-900">{insight.title}</h4>{insight.kind === "chart" ? <VerifiedChart chart={insight.chart} /> : insight.kind === "framework_diagram" ? <Framework framework={insight.framework} /> : <div className="mt-4"><ThreeLineTable table={insight.table} /></div>}<p className="mt-3 text-center text-xs leading-5 text-neutral-500">{insight.caption}</p><Evidence evidence={insight.evidence} status={insight.source_status} /><p className="mt-2 text-center text-xs text-neutral-400">块版本 {insight.version} · 图/表 {index + 1}</p></div></article>;
}
