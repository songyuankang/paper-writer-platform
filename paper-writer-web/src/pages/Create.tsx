import { useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import ProgressBar from "../components/ProgressBar";
import EditorModalShell from "../components/EditorModalShell";
import TemplateManagerModal from "../components/TemplateManagerModal";
import HistoryPage from "./History";
import SettingsModels from "./SettingsModels";
import {
  CreateWizardProvider,
  STEPS,
  useCreateWizard,
} from "./create/CreateWizardContext";

function CreateLayoutContent() {
  const location = useLocation();
  // 正文编辑器页：全屏（AI UniPaper 风格），不带步骤条/卡片壳
  const isBodyPage = location.pathname === "/create/body";
  const {
    typeDef,
    running,
    taskFailed,
    task,
    progress,
    step,
    stepBadge,
  } = useCreateWizard();
  const [templateManagerOpen, setTemplateManagerOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [modelSettingsOpen, setModelSettingsOpen] = useState(false);
  const [historyPreviewTaskId, setHistoryPreviewTaskId] = useState<string | null>(null);

  if (isBodyPage) {
    return <Outlet />;
  }

  return (
    <div className="min-h-screen bg-white">
      <header className="sticky top-0 z-20 border-b border-neutral-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-4">
            <Link to="/" className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-black text-sm font-bold text-white">
                论
              </span>
              <span className="text-lg font-bold text-neutral-900">
                论文生成助手
              </span>
            </Link>
            <span className="hidden rounded-full bg-neutral-100 px-3 py-1 text-xs font-medium text-neutral-700 sm:inline">
              {typeDef.label}
            </span>
          </div>
          <nav className="flex items-center gap-2 text-sm">
            <button type="button" onClick={() => setTemplateManagerOpen(true)}
              className="rounded-lg px-3 py-1.5 text-slate-600 transition hover:bg-slate-100"
            >模板管理</button>
            <button type="button" onClick={() => setHistoryOpen(true)}
              className="rounded-lg px-3 py-1.5 text-slate-600 transition hover:bg-slate-100"
            >历史记录</button>
            <button type="button" onClick={() => setModelSettingsOpen(true)}
              className="rounded-lg px-3 py-1.5 text-slate-600 transition hover:bg-slate-100"
            >模型设置</button>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-8">
        <div className="mb-8 grid grid-cols-2 gap-2 sm:grid-cols-5">
          {STEPS.map((s) => {
            // 以当前路由为准，避免已完成任务的 progress=100 覆盖当前页面步骤。
            const isActive = s.num === step;
            return (
              <div
                key={s.num}
                className={`flex flex-col items-center gap-1 rounded-2xl border px-2 py-3 text-center transition ${
                  isActive
                    ? "border-black bg-white"
                    : "border-transparent bg-white"
                }`}
              >
                <div className="flex items-center gap-1.5">
                  {stepBadge(s.num)}
                  <span
                    className={`text-sm font-semibold ${
                      isActive ? "text-black" : "text-neutral-500"
                    }`}
                  >
                    {s.num === 1 ? "① " : s.num === 2 ? "② " : s.num === 3 ? "③ " : s.num === 4 ? "④ " : "⑤ "}
                    {s.title}
                  </span>
                </div>
                <span className="text-[11px] uppercase tracking-wide text-slate-400">
                  {s.en}
                </span>
              </div>
            );
          })}
        </div>

        {running && (
          <div className="mb-6">
            <ProgressBar
              progress={progress}
              label={task?.message ?? "正在生成…"}
            />
          </div>
        )}
        {taskFailed && (
          <div className="mb-6 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            生成失败：{task?.error ?? "未知错误"}
          </div>
        )}

        <div className="rounded-2xl border border-neutral-200 bg-white p-5 sm:p-8">
          <Outlet />
        </div>
      </main>
      <TemplateManagerModal
        open={templateManagerOpen}
        onClose={() => setTemplateManagerOpen(false)}
      />
      <EditorModalShell
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        title="历史记录"
        description="查看、筛选、导出或重新生成任务，不离开创建向导。"
      >
        <HistoryPage
          embedded
          onOpenPreview={(taskId) => {
            setHistoryOpen(false);
            setHistoryPreviewTaskId(taskId);
          }}
        />
      </EditorModalShell>
      <EditorModalShell
        open={modelSettingsOpen}
        onClose={() => setModelSettingsOpen(false)}
        title="模型设置"
        description="管理写作模型配置，不离开当前创建向导。"
        className="max-w-[1120px]"
      >
        <SettingsModels embedded />
      </EditorModalShell>
      <EditorModalShell
        open={historyPreviewTaskId !== null}
        onClose={() => setHistoryPreviewTaskId(null)}
        title="历史论文预览"
        description="在当前创建向导的弹窗中查看历史论文。"
        className="max-w-[1200px]"
      >
        {historyPreviewTaskId && (
          <iframe
            title="历史论文预览"
            src={`/preview/${historyPreviewTaskId}`}
            className="h-[72vh] w-full rounded-lg border border-slate-200 bg-white"
          />
        )}
      </EditorModalShell>
    </div>
  );
}

export default function Create() {
  return (
    <CreateWizardProvider>
      <CreateLayoutContent />
    </CreateWizardProvider>
  );
}
