import EditorModalShell from "./EditorModalShell";

interface OneClickConfirmModalProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  modelName?: string;
  currentWords: number;
  targetWords: number;
  sectionCount: number;
  busy: boolean;
}

/** 一键全文需用户明确确认，避免从顶部按钮误发生成任务。 */
export default function OneClickConfirmModal({
  open,
  onClose,
  onConfirm,
  modelName,
  currentWords,
  targetWords,
  sectionCount,
  busy,
}: OneClickConfirmModalProps) {
  return (
    <EditorModalShell
      open={open}
      onClose={onClose}
      title="生成全文确认"
      description="生成将在当前编辑器中异步进行，不会离开本页。"
      className="max-w-[620px]"
      closeOnBackdrop={!busy}
    >
      <div className="space-y-4 text-sm text-slate-700">
        <div className="grid grid-cols-2 gap-3 rounded-xl bg-slate-50 p-4 sm:grid-cols-4">
          <div><p className="text-xs text-slate-500">当前模型</p><p className="mt-1 truncate font-medium">{modelName || "默认模型"}</p></div>
          <div><p className="text-xs text-slate-500">当前字数</p><p className="mt-1 font-medium">{currentWords}</p></div>
          <div><p className="text-xs text-slate-500">目标字数</p><p className="mt-1 font-medium">{targetWords || "未设置"}</p></div>
          <div><p className="text-xs text-slate-500">待生成章节</p><p className="mt-1 font-medium">{sectionCount}</p></div>
        </div>
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800">
          将根据当前大纲和段落主旨生成正文。生成开始后，顶部按钮会显示“生成中”，以避免重复提交。
        </p>
        <div className="flex justify-end gap-3 border-t border-slate-200 pt-4">
          <button type="button" disabled={busy} onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:opacity-50">取消</button>
          <button type="button" disabled={busy} onClick={onConfirm} className="rounded-lg bg-black px-4 py-2 text-sm font-medium text-white transition hover:bg-neutral-700 disabled:opacity-50">{busy ? "启动中…" : "开始生成全文"}</button>
        </div>
      </div>
    </EditorModalShell>
  );
}
