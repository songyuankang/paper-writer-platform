import { useEffect, useState } from "react";
import {
  fetchDraftChartVersions,
  restoreDraftChartVersion,
  type ChartVersionHistory,
  type ChartVersionSummary,
} from "../api/paper";

type Props = {
  taskId: string;
  figureId: string;
  onClose: () => void;
  onRestored: () => Promise<void> | void;
};

const REASON_LABEL: Record<ChartVersionSummary["reason"], string> = {
  initial: "首次生成",
  user_edit: "用户修改",
  ai_regenerate: "AI 重新生成",
  recompute: "重新计算",
  restore: "恢复历史版本",
};

const EDITOR_LABEL: Record<ChartVersionSummary["editor"]["type"], string> = {
  user: "用户",
  ai: "AI",
  system: "系统",
};

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

export default function ChartVersionHistoryDrawer({ taskId, figureId, onClose, onRestored }: Props) {
  const [history, setHistory] = useState<ChartVersionHistory | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      setHistory(await fetchDraftChartVersions(taskId, figureId));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法加载图表版本历史");
    }
  }

  useEffect(() => { void load(); }, [taskId, figureId]);

  async function restore(version: ChartVersionSummary) {
    if (version.is_current || busy) return;
    if (!window.confirm(`恢复到该版本不会删除后续历史，而会创建新的恢复版本。是否继续？`)) return;
    setBusy(version.id);
    setError(null);
    try {
      await restoreDraftChartVersion(taskId, figureId, version.id);
      await onRestored();
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "恢复图表版本失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="fixed inset-0 z-[92] flex justify-end bg-black/40" role="dialog" aria-modal="true" aria-label="图表版本历史">
      <aside className="flex h-full w-full max-w-[520px] flex-col bg-white shadow-2xl">
        <header className="flex items-center gap-3 border-b border-neutral-200 px-5 py-4">
          <div className="min-w-0 flex-1"><h3 className="text-base font-semibold text-neutral-900">图表版本历史</h3><p className="mt-1 text-xs text-neutral-500">每次编辑、AI 重新生成、重新计算和恢复均保留为不可变审计记录。</p></div>
          <button type="button" onClick={onClose} className="rounded border border-neutral-200 px-3 py-1.5 text-xs text-neutral-700 hover:border-black">关闭</button>
        </header>
        <div className="flex-1 overflow-y-auto p-5">
          {error && <p className="mb-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
          {!history && !error && <p className="py-10 text-center text-sm text-neutral-500">正在加载版本历史…</p>}
          <ol className="space-y-3">{history?.versions.map((version, index) => <li key={version.id} className={`rounded-lg border p-4 ${version.is_current ? "border-black bg-neutral-50" : "border-neutral-200 bg-white"}`}>
            <div className="flex items-start gap-3"><div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-black text-xs font-semibold text-white">v{history.versions.length - index}</div><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><strong className="text-sm text-neutral-900">{REASON_LABEL[version.reason]}</strong>{version.is_current && <span className="rounded bg-black px-2 py-0.5 text-[11px] text-white">当前版本</span>}<span className="rounded bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">{EDITOR_LABEL[version.editor.type]}</span></div><p className="mt-1 text-xs text-neutral-500">{version.editor.name || EDITOR_LABEL[version.editor.type]} · {formatTime(version.created_at)}</p><p className="mt-2 text-xs text-neutral-600">来源快照：{version.source_count} 项{version.parent_version_id ? " · 保留父版本关系" : ""}</p></div></div>
            <div className="mt-3 flex justify-end"><button type="button" disabled={Boolean(version.is_current) || busy !== null} onClick={() => void restore(version)} className="rounded border border-neutral-300 px-3 py-1.5 text-xs text-neutral-700 hover:border-black disabled:cursor-not-allowed disabled:opacity-40">{busy === version.id ? "正在恢复…" : version.is_current ? "当前使用中" : "恢复此版本"}</button></div>
          </li>)}</ol>
        </div>
      </aside>
    </div>
  );
}
