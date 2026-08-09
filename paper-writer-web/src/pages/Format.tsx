import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  createFormatTask,
  fetchFormatStatus,
  fetchFormatTemplates,
  fetchPaperContent,
  formatDownloadUrl,
  startFormatTask,
  uploadFormatTemplate,
  type FormatTaskInfo,
  type FormatTemplate,
} from "../api/paper";

const REF_STYLES = [
  { label: "GB/T 7714", value: "gb7714" },
  { label: "APA", value: "apa" },
  { label: "MLA", value: "mla" },
];

interface Settings {
  use_template: boolean;
  toc: boolean;
  page_numbers: boolean;
  title_numbering: boolean;
  reference_style: string;
  auto_sort: boolean;
  auto_number: boolean;
  chart_numbering: string;
  chart_position: string;
}

const DEFAULT_SETTINGS: Settings = {
  use_template: true,
  toc: true,
  page_numbers: true,
  title_numbering: true,
  reference_style: "gb7714",
  auto_sort: true,
  auto_number: true,
  chart_numbering: "chapter",
  chart_position: "auto",
};

function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-600">
      <span>{label}</span>
      <input
        type="checkbox"
        className="h-4 w-4 accent-indigo-500"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
    </label>
  );
}

export default function FormatPage() {
  const { taskId = "" } = useParams();
  const [templates, setTemplates] = useState<FormatTemplate[]>([]);
  const [templateId, setTemplateId] = useState<string>("default");
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [formatTask, setFormatTask] = useState<FormatTaskInfo | null>(null);
  const [message, setMessage] = useState<{
    type: "ok" | "err";
    text: string;
  } | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [reportText, setReportText] = useState("");
  const [uploadMeta, setUploadMeta] = useState({
    name: "",
    school_name: "",
    major: "",
    paper_type: "",
  });
  const pollRef = useRef<number | null>(null);

  const refreshTemplates = useCallback(async () => {
    try {
      setTemplates(await fetchFormatTemplates());
    } catch {
      setTemplates([]);
    }
  }, []);

  useEffect(() => {
    void refreshTemplates();
    fetchPaperContent(taskId).catch(() => undefined);
  }, [taskId, refreshTemplates]);

  useEffect(
    () => () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
      }
    },
    [],
  );

  async function handleUpload() {
    if (!uploadMeta.name.trim()) {
      setMessage({ type: "err", text: "请填写模板名称" });
      return;
    }
    const input = document.querySelector<HTMLInputElement>("#template-file");
    const file = input?.files?.[0];
    if (!file) {
      setMessage({ type: "err", text: "请选择 .docx 模板文件" });
      return;
    }
    setUploading(true);
    try {
      const created = await uploadFormatTemplate(
        {
          name: uploadMeta.name.trim(),
          school_name: uploadMeta.school_name.trim(),
          major: uploadMeta.major.trim(),
          paper_type: uploadMeta.paper_type.trim(),
        },
        file,
      );
      setTemplateId(created.id);
      setUploadOpen(false);
      setMessage({ type: "ok", text: "模板已上传并解析" });
      await refreshTemplates();
    } catch (e) {
      setMessage({ type: "err", text: e instanceof Error ? e.message : "上传失败" });
    } finally {
      setUploading(false);
    }
  }

  async function handleStart() {
    setMessage(null);
    setReportText("");
    try {
      const created = await createFormatTask({
        task_id: taskId,
        template_id: settings.use_template && templateId !== "default"
          ? templateId
          : null,
        settings,
      });
      await startFormatTask(created.format_id);
      pollRef.current = window.setInterval(async () => {
        try {
          const info = await fetchFormatStatus(created.format_id);
          setFormatTask(info);
          if (info.status === "completed" || info.status === "failed") {
            if (pollRef.current !== null) {
              window.clearInterval(pollRef.current);
              pollRef.current = null;
            }
            if (info.status === "completed") {
              try {
                const res = await fetch(
                  formatDownloadUrl(created.format_id, "format_report.md"),
                );
                setReportText(await res.text());
              } catch {
                setReportText("");
              }
            } else {
              setMessage({ type: "err", text: info.message ?? "格式处理失败" });
            }
          }
        } catch {
          if (pollRef.current !== null) {
            window.clearInterval(pollRef.current);
            pollRef.current = null;
          }
        }
      }, 1500);
    } catch (e) {
      setMessage({ type: "err", text: e instanceof Error ? e.message : "创建任务失败" });
    }
  }

  const running =
    formatTask !== null &&
    formatTask.status !== "completed" &&
    formatTask.status !== "failed";
  const selectedTemplate = templates.find((t) => t.id === templateId);

  return (
    <div className="min-h-screen bg-white px-4 py-8">
      <div className="mx-auto w-full max-w-3xl">
        <header className="mb-6 flex items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-slate-800">论文格式处理</h1>
            <p className="mt-1 text-sm text-slate-500">
              内容生成已完成，本页面负责排版、目录、参考文献、图表与导出
            </p>
          </div>
          <Link
            to={`/preview/${taskId}`}
            className="rounded-xl border border-neutral-300 bg-white px-4 py-2 text-sm text-neutral-600 hover:border-neutral-400"
          >
            ← 返回内容预览
          </Link>
        </header>

        {message && (
          <div
            className={`mb-4 rounded-xl border px-4 py-3 text-sm ${
              message.type === "ok"
                ? "border-green-200 bg-green-50 text-green-700"
                : "border-red-200 bg-red-50 text-red-600"
            }`}
          >
            {message.text}
          </div>
        )}

        <div className="space-y-4">
          {/* 1. 学校模板 */}
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="mb-3 font-semibold text-slate-700">1. 学校模板选择</h2>
            <div className="mb-2 flex items-center justify-between rounded-xl bg-slate-50 px-3 py-2 text-sm">
              <span className="text-slate-600">
                当前模板：
                <span className="ml-1 font-medium text-slate-800">
                  {templateId === "default" || !selectedTemplate
                    ? "默认模板"
                    : selectedTemplate.name}
                </span>
              </span>
              <button
                type="button"
                onClick={() => setUploadOpen((v) => !v)}
                className="rounded-lg bg-black px-3 py-1.5 text-xs font-medium text-white hover:bg-neutral-700"
              >
                上传学校模板
              </button>
            </div>
            {templates.length > 0 && (
              <select
                value={templateId}
                onChange={(e) => setTemplateId(e.target.value)}
                className="w-full rounded-xl border border-neutral-300 bg-white px-3 py-2 text-sm outline-none focus:border-black"
              >
                <option value="default">默认模板</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                    {t.school_name ? `（${t.school_name}）` : ""}
                  </option>
                ))}
              </select>
            )}
            {selectedTemplate && templateId !== "default" && (
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-500 sm:grid-cols-4">
                <p>学校：{selectedTemplate.school_name || "—"}</p>
                <p>专业：{selectedTemplate.major || "—"}</p>
                <p>类型：{selectedTemplate.paper_type || "—"}</p>
                <p>更新：{selectedTemplate.updated_at.slice(0, 10)}</p>
              </div>
            )}

            {uploadOpen && (
              <div className="mt-3 space-y-2 rounded-xl border border-neutral-200 bg-neutral-50 p-3">
                <input
                  placeholder="模板名称（必填）"
                  value={uploadMeta.name}
                  onChange={(e) =>
                    setUploadMeta({ ...uploadMeta, name: e.target.value })
                  }
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none"
                />
                <div className="grid grid-cols-3 gap-2">
                  {(["school_name", "major", "paper_type"] as const).map((k) => (
                    <input
                      key={k}
                      placeholder={k === "school_name" ? "学校" : k === "major" ? "专业" : "论文类型"}
                      value={uploadMeta[k]}
                      onChange={(e) =>
                        setUploadMeta({ ...uploadMeta, [k]: e.target.value })
                      }
                      className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none"
                    />
                  ))}
                </div>
                <input
                  id="template-file"
                  type="file"
                  accept=".docx"
                  className="block w-full text-sm text-slate-500 file:mr-2 file:rounded-lg file:border-0 file:bg-black file:px-3 file:py-1.5 file:text-xs file:text-white"
                />
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setUploadOpen(false)}
                    className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-500"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    disabled={uploading}
                    onClick={handleUpload}
                    className="rounded-lg bg-black px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
                  >
                    {uploading ? "解析中…" : "上传并解析"}
                  </button>
                </div>
              </div>
            )}
          </section>

          {/* 2. 格式设置 */}
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="mb-3 font-semibold text-slate-700">2. 格式设置</h2>
            <Switch
              label="使用学校模板（关闭则使用默认格式）"
              checked={settings.use_template}
              onChange={(v) => setSettings({ ...settings, use_template: v })}
            />
          </section>

          {/* 3. 目录设置 */}
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="mb-3 font-semibold text-slate-700">3. 目录设置</h2>
            <div className="grid gap-2 sm:grid-cols-3">
              <Switch label="自动生成目录" checked={settings.toc}
                      onChange={(v) => setSettings({ ...settings, toc: v })} />
              <Switch label="更新页码" checked={settings.page_numbers}
                      onChange={(v) => setSettings({ ...settings, page_numbers: v })} />
              <Switch label="更新标题编号" checked={settings.title_numbering}
                      onChange={(v) => setSettings({ ...settings, title_numbering: v })} />
            </div>
          </section>

          {/* 4. 参考文献设置 */}
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="mb-3 font-semibold text-slate-700">4. 参考文献设置</h2>
            <div className="mb-2 flex items-center gap-2">
              <span className="text-sm text-slate-600">格式：</span>
              <select
                value={settings.reference_style}
                onChange={(e) =>
                  setSettings({ ...settings, reference_style: e.target.value })
                }
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none"
              >
                {REF_STYLES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <Switch label="自动排序" checked={settings.auto_sort}
                      onChange={(v) => setSettings({ ...settings, auto_sort: v })} />
              <Switch label="自动编号" checked={settings.auto_number}
                      onChange={(v) => setSettings({ ...settings, auto_number: v })} />
            </div>
          </section>

          {/* 5. 图表设置 */}
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="mb-3 font-semibold text-slate-700">5. 图表设置</h2>
            <div className="grid gap-2 sm:grid-cols-2">
              <Switch label="图表编号（图1-1 / 图1-2）" checked
                      onChange={() => undefined} />
              <Switch label="图表位置自动调整" checked={settings.chart_position === "auto"}
                      onChange={(v) =>
                        setSettings({
                          ...settings,
                          chart_position: v ? "auto" : "manual",
                        })
                      } />
            </div>
          </section>

          {/* 6. 生成 */}
          <button
            type="button"
            disabled={running}
            onClick={handleStart}
            className="w-full rounded-xl bg-black py-3 text-sm font-semibold text-white hover:bg-neutral-700 disabled:opacity-40"
          >
            {running
              ? `格式处理中…（${formatTask?.progress ?? 0}%）`
              : formatTask?.status === "completed"
                ? "重新开始格式处理"
                : "开始格式处理"}
          </button>

          {running && formatTask && (
            <div className="rounded-xl border border-neutral-200 bg-neutral-50 px-4 py-3 text-sm text-neutral-700">
              {formatTask.message ?? "正在处理…"}
            </div>
          )}

          {formatTask?.status === "completed" && (
            <section className="rounded-2xl border border-green-200 bg-green-50 p-5">
              <h2 className="mb-3 font-semibold text-green-800">
                格式处理完成
              </h2>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                <a
                  href={formatDownloadUrl(formatTask.id, "paper.docx")}
                  className="rounded-xl border border-green-200 bg-white px-3 py-2.5 text-center text-sm font-medium text-green-700 hover:border-green-400"
                >
                  论文.docx
                </a>
                <a
                  href={formatDownloadUrl(formatTask.id, "format_report.md")}
                  className="rounded-xl border border-green-200 bg-white px-3 py-2.5 text-center text-sm font-medium text-green-700 hover:border-green-400"
                >
                  FormatReport.md
                </a>
                <a
                  href={formatDownloadUrl(formatTask.id)}
                  className="rounded-xl border border-green-200 bg-white px-3 py-2.5 text-center text-sm font-medium text-green-700 hover:border-green-400"
                >
                  全部（ZIP）
                </a>
              </div>
              {reportText && (
                <pre className="mt-3 whitespace-pre-wrap rounded-xl bg-white p-3 text-xs text-slate-600">
                  {reportText}
                </pre>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
