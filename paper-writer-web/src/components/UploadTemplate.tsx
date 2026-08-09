import { useEffect, useRef, useState } from "react";
import {
  deleteTemplate,
  getLastUsedId,
  listTemplates,
  rememberLastUsed,
  renameTemplate,
  saveTemplate,
  type TemplateRecord,
} from "../utils/templateStore";

const MAX_SIZE = 20 * 1024 * 1024;

interface UploadTemplateProps {
  selected: TemplateRecord | null;
  onSelect: (template: TemplateRecord | null) => void;
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return "";
  }
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

export default function UploadTemplate({ selected, onSelect }: UploadTemplateProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [templates, setTemplates] = useState<TemplateRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  useEffect(() => {
    let cancelled = false;
    listTemplates()
      .then((rows) => {
        if (cancelled) {
          return;
        }
        setTemplates(rows);
        const lastId = getLastUsedId();
        const last = rows.find((t) => t.id === lastId);
        if (last) {
          onSelect(last);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError("读取本地模板失败");
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handlePick(f: File | undefined) {
    setError(null);
    if (!f) {
      return;
    }
    if (!/\.docx$/i.test(f.name)) {
      setError("仅支持 .docx 模板文件");
      return;
    }
    if (f.size > MAX_SIZE) {
      setError("模板文件不能超过 20 MB");
      return;
    }
    try {
      const record = await saveTemplate(f);
      setTemplates((prev) => [record, ...prev]);
      onSelect(record);
      rememberLastUsed(record.id);
    } catch {
      setError("保存模板到本地失败");
    }
  }

  function handleSelect(record: TemplateRecord) {
    onSelect(record);
    rememberLastUsed(record.id);
  }

  function handleDeselect() {
    onSelect(null);
    rememberLastUsed(null);
  }

  async function handleRenameSave(id: string) {
    const name = renameValue.trim();
    if (!name) {
      setRenamingId(null);
      return;
    }
    try {
      await renameTemplate(id, name);
      setTemplates((prev) =>
        prev.map((t) =>
          t.id === id ? { ...t, name, updatedAt: new Date().toISOString() } : t,
        ),
      );
      if (selected?.id === id) {
        onSelect({ ...selected, name });
      }
    } catch {
      setError("重命名失败");
    }
    setRenamingId(null);
  }

  async function handleDelete(id: string) {
    if (!window.confirm("确定删除该模板吗？此操作不可恢复。")) {
      return;
    }
    try {
      await deleteTemplate(id);
      setTemplates((prev) => prev.filter((t) => t.id !== id));
      if (selected?.id === id) {
        onSelect(null);
        rememberLastUsed(null);
      }
    } catch {
      setError("删除模板失败");
    }
  }

  return (
    <div className="space-y-3">
      {/* 上传 */}
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        className="w-full rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-600 transition hover:border-indigo-400 hover:bg-indigo-50"
      >
        选择学校模板（.docx，上传后自动保存到本机）
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".docx"
        className="hidden"
        onChange={(e) => {
          handlePick(e.target.files?.[0]);
          e.target.value = "";
        }}
      />

      {error && <p className="text-sm text-red-500">{error}</p>}

      {/* 当前选用 */}
      {selected && (
        <div className="flex items-center justify-between rounded-xl border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm">
          <div className="min-w-0">
            <p className="truncate font-medium text-slate-700">
              {selected.name}.docx
            </p>
            <p className="text-xs text-slate-400">
              {formatSize(selected.size)} · {formatDate(selected.updatedAt)}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs text-indigo-700">
              已选用
            </span>
            <button
              type="button"
              onClick={handleDeselect}
              className="text-xs text-slate-400 hover:text-red-500"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* 已保存模板 */}
      {templates.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-medium text-slate-400">
            已保存的模板（{templates.length}）
          </p>
          <ul className="space-y-1.5">
            {templates.map((t) => {
              const isRenaming = renamingId === t.id;
              const isSelected = selected?.id === t.id;
              return (
                <li
                  key={t.id}
                  className="flex items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm"
                >
                  <div className="min-w-0 flex-1">
                    {isRenaming ? (
                      <input
                        autoFocus
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            handleRenameSave(t.id);
                          } else if (e.key === "Escape") {
                            setRenamingId(null);
                          }
                        }}
                        className="w-full rounded-lg border border-indigo-300 px-2 py-1 text-sm outline-none focus:ring-2 focus:ring-indigo-100"
                        maxLength={60}
                      />
                    ) : (
                      <>
                        <p className="truncate font-medium text-slate-700">
                          {t.name}.docx
                        </p>
                        <p className="text-xs text-slate-400">
                          {formatSize(t.size)} · {formatDate(t.updatedAt)}
                        </p>
                      </>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {isRenaming ? (
                      <>
                        <button
                          type="button"
                          onClick={() => handleRenameSave(t.id)}
                          className="text-xs font-medium text-indigo-600 hover:text-indigo-800"
                        >
                          保存
                        </button>
                        <button
                          type="button"
                          onClick={() => setRenamingId(null)}
                          className="text-xs text-slate-400 hover:text-slate-600"
                        >
                          取消
                        </button>
                      </>
                    ) : (
                      <>
                        {isSelected ? (
                          <span className="text-xs text-green-600">已选用</span>
                        ) : (
                          <button
                            type="button"
                            onClick={() => handleSelect(t)}
                            className="text-xs font-medium text-indigo-600 hover:text-indigo-800"
                          >
                            选用
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => {
                            setRenamingId(t.id);
                            setRenameValue(t.name);
                          }}
                          className="text-xs text-slate-500 hover:text-slate-700"
                        >
                          重命名
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(t.id)}
                          className="text-xs text-slate-400 hover:text-red-500"
                        >
                          删除
                        </button>
                      </>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
