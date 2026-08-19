import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  deleteHistoryRecord,
  downloadUrl,
  exportPaper,
  fetchHistory,
  fetchHistoryRecord,
  fetchTaskStatus,
  generatePaper,
  type HistoryRecord,
} from "../api/paper";
import TemplateManagerModal from "../components/TemplateManagerModal";

type StatusFilter = "all" | "active" | "completed" | "failed";

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return iso;
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

function statusBadge(status: string): { label: string; cls: string } {
  switch (status) {
    case "completed":
      return { label: "✓ 已完成", cls: "bg-green-100 text-green-700" };
    case "failed":
      return { label: "✕ 失败", cls: "bg-red-100 text-red-600" };
    default:
      return { label: "⏳ 生成中", cls: "bg-amber-100 text-amber-700" };
  }
}

export default function HistoryPage({
  embedded = false,
  onOpenPreview,
}: {
  embedded?: boolean;
  onOpenPreview?: (taskId: string) => void;
}) {
  const navigate = useNavigate();
  const [records, setRecords] = useState<HistoryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [regeneratingId, setRegeneratingId] = useState<string | null>(null);
  const [exportTaskId, setExportTaskId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  /** 导出：选择模板 → 后端按模板渲染 → 下载 docx。 */
  async function handleExport(templateId: string) {
    const taskId = exportTaskId;
    if (!taskId) {
      return;
    }
    setExportTaskId(null);
    setExporting(true);
    try {
      await exportPaper(taskId, templateId);
      window.location.href = downloadUrl(taskId, "论文.docx");
    } catch (err) {
      alert(err instanceof Error ? err.message : "导出失败");
    } finally {
      setExporting(false);
    }
  }

  async function refresh() {
    try {
      const list = await fetchHistory();
      setRecords(list);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载历史记录失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  const filtered = useMemo(() => {
    const kw = search.trim().toLowerCase();
    return records.filter((r) => {
      if (kw && !r.title.toLowerCase().includes(kw)) {
        return false;
      }
      if (statusFilter === "completed" && r.status !== "completed") {
        return false;
      }
      if (statusFilter === "failed" && r.status !== "failed") {
        return false;
      }
      if (
        statusFilter === "active" &&
        r.status !== "pending" &&
        r.status !== "generating"
      ) {
        return false;
      }
      return true;
    });
  }, [records, search, statusFilter]);

  async function handleDelete(record: HistoryRecord) {
    if (!window.confirm(`确定删除《${record.title}》的记录与全部生成文件吗？`)) {
      return;
    }
    try {
      await deleteHistoryRecord(record.task_id);
      setRecords((prev) => prev.filter((r) => r.task_id !== record.task_id));
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "删除失败");
    }
  }

  async function handleRegenerate(record: HistoryRecord) {
    setRegeneratingId(record.task_id);
    try {
      const detail = await fetchHistoryRecord(record.task_id);
      const p = (detail.params ?? {}) as Record<string, any>;
      const { task_id } = await generatePaper({
        title: String(p.title ?? record.title),
        major: String(p.major ?? record.major),
        paper_type: String(p.paper_type ?? record.paper_type),
        word_count: Number(p.word_count ?? record.word_count),
        reference_style: String(p.reference_style ?? "gb7714"),
        generation_mode: p.generation_mode === "outline" ? "outline" : undefined,
        outline: p.outline ? String(p.outline) : undefined,
        special_requirements: p.special_requirements
          ? String(p.special_requirements)
          : undefined,
        model_id: p.model_id ? String(p.model_id) : undefined,
        school_template: null,
      });
      window.alert("已提交重新生成，完成后将自动进入预览页");
      const timer = window.setInterval(async () => {
        try {
          const info = await fetchTaskStatus(task_id);
          if (info.status === "completed" || info.status === "failed") {
            window.clearInterval(timer);
            if (info.status === "completed") {
              if (!embedded) navigate(`/preview/${task_id}`);
            } else {
              window.alert(`重新生成失败：${info.error ?? "未知错误"}`);
              setRegeneratingId(null);
            }
          }
        } catch {
          window.clearInterval(timer);
          setRegeneratingId(null);
        }
      }, 1500);
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "重新生成失败");
      setRegeneratingId(null);
    }
  }

  return (
    <div className={embedded ? "min-h-0 bg-white px-0 py-0" : "min-h-screen bg-white px-4 py-8"}>
      <div className={embedded ? "w-full" : "mx-auto w-full max-w-5xl"}>
        {!embedded && (
        <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-slate-800">论文生成记录</h1>
            <p className="mt-1 text-sm text-slate-500">
              查看历史生成任务，支持再次预览、下载与重新生成
            </p>
          </div>
          <Link
            to="/create"
            className="rounded-xl bg-black px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700"
          >
            + 去生成论文
          </Link>
        </header>
        )}

        {/* 搜索与筛选 */}
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="按论文标题搜索…"
            className="w-full max-w-xs rounded-xl border border-neutral-300 bg-white px-3 py-2 text-sm outline-none focus:border-black focus:ring-2 focus:ring-neutral-200"
          />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            className="rounded-xl border border-neutral-300 bg-white px-3 py-2 text-sm outline-none focus:border-black"
          >
            <option value="all">全部状态</option>
            <option value="active">生成中</option>
            <option value="completed">已完成</option>
            <option value="failed">失败</option>
          </select>
          <span className="text-xs text-slate-400">
            {filtered.length} 条记录（按时间倒序）
          </span>
        </div>

        {error && (
          <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
            {error}
          </div>
        )}

        {loading ? (
          <p className="py-10 text-center text-slate-400">正在加载…</p>
        ) : filtered.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white py-14 text-center">
            <p className="text-slate-400">暂无符合条件的生成记录</p>
            {!embedded && (
              <Link to="/create" className="mt-2 inline-block text-sm text-neutral-600 hover:text-black">
                去生成第一篇论文
              </Link>
            )}
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((record) => {
              const badge = statusBadge(record.status);
              const done = record.status === "completed";
              return (
                <div
                  key={record.task_id}
                  className="flex flex-col rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
                >
                  <div className="mb-2 flex items-start justify-between gap-2">
                    <h3 className="min-w-0 flex-1 truncate font-semibold text-slate-800">
                      {record.title || "（无标题）"}
                    </h3>
                    <span
                      className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${badge.cls}`}
                    >
                      {badge.label}
                    </span>
                  </div>
                  <p className="mb-1 text-sm text-slate-500">
                    专业：{record.major || "—"}
                  </p>
                  <p className="mb-1 text-sm text-slate-500">
                    字数：{record.word_count} · 类型：
                    {record.paper_type || "—"}
                  </p>
                  <p className="mb-2 text-sm text-slate-500">
                    时间：{formatTime(record.created_at)}
                  </p>
                  {record.error_message && (
                    <p className="mb-2 break-words rounded-lg bg-red-50 px-2 py-1 text-xs text-red-500">
                      {record.error_message}
                    </p>
                  )}
                  <div className="mt-auto grid grid-cols-2 gap-1.5 pt-2">
                    <button
                      type="button"
                      onClick={() => {
                        if (embedded) {
                          onOpenPreview?.(record.task_id);
                        } else {
                          navigate(`/create/body?task=${record.task_id}`);
                        }
                      }}
                      className="rounded-lg bg-black py-1.5 text-center text-sm font-medium text-white hover:bg-neutral-700"
                    >
                      {embedded ? "查看" : "编辑"}
                    </button>
                    <button
                      type="button"
                      disabled={!done || exporting}
                      onClick={() => setExportTaskId(record.task_id)}
                      className={`rounded-lg border py-1.5 text-center text-sm font-medium transition ${
                        done
                          ? "border-neutral-300 text-neutral-700 hover:bg-neutral-100"
                          : "cursor-not-allowed border-slate-200 text-slate-300"
                      }`}
                    >
                      {exporting ? "导出中…" : "下载"}
                    </button>
                    <button
                      type="button"
                      disabled={regeneratingId !== null}
                      onClick={() => handleRegenerate(record)}
                      className="rounded-lg border border-neutral-200 py-1.5 text-sm text-neutral-600 hover:border-neutral-400 disabled:opacity-40"
                    >
                      {regeneratingId === record.task_id
                        ? "重新生成中…"
                        : "重新生成"}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(record)}
                      className="rounded-lg border border-slate-200 py-1.5 text-sm text-slate-400 hover:border-red-300 hover:text-red-500"
                    >
                      删除
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <TemplateManagerModal
        open={exportTaskId !== null}
        onClose={() => setExportTaskId(null)}
        selectMode
        onSelectTemplate={(id) => void handleExport(id)}
      />
    </div>
  );
}
