import { useState } from "react";
import { Link } from "react-router-dom";
import {
  fetchModels,
  polishText,
  POLISH_OPERATIONS,
  type ModelConfig,
  type PolishOperation,
} from "../api/paper";

const inputCls =
  "w-full rounded-xl border border-neutral-300 bg-white px-3 py-2.5 text-sm text-neutral-900 outline-none transition placeholder:text-neutral-400 focus:border-black focus:ring-2 focus:ring-neutral-200";

export default function Polish() {
  const [text, setText] = useState("");
  const [operation, setOperation] = useState<PolishOperation>("polish");
  const [instruction, setInstruction] = useState("");
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [modelId, setModelId] = useState("");
  const [result, setResult] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadedModels, setLoadedModels] = useState(false);

  const activeOp =
    POLISH_OPERATIONS.find((o) => o.value === operation) ?? POLISH_OPERATIONS[0];
  const needInstruction = operation === "rewrite" || operation === "translate";

  function ensureModels() {
    if (loadedModels) {
      return;
    }
    setLoadedModels(true);
    fetchModels()
      .then((list) => setModels(list.filter((m) => m.enabled)))
      .catch(() => setModels([]));
  }

  async function handleSubmit() {
    setError(null);
    if (!text.trim()) {
      setError("请粘贴需要处理的文本");
      return;
    }
    if (needInstruction && !instruction.trim()) {
      setError(
        operation === "translate"
          ? "请填写目标语言，例如：英文、日文、法文"
          : "请填写修改要求",
      );
      return;
    }
    setLoading(true);
    try {
      const res = await polishText({
        text: text.trim(),
        operation,
        instruction: instruction.trim(),
        model_id: modelId || undefined,
      });
      setResult(res.text);
    } catch (err) {
      setError(err instanceof Error ? err.message : "处理失败，请检查后端服务");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-white">
      <header className="sticky top-0 z-20 border-b border-neutral-200 bg-white">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-4 py-3">
          <Link to="/" className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-black text-sm font-bold text-white">
              论
            </span>
            <span className="text-lg font-bold text-slate-800">论文生成助手</span>
          </Link>
          <nav className="flex items-center gap-2 text-sm">
            <Link to="/history" className="rounded-lg px-3 py-1.5 text-slate-600 transition hover:bg-slate-100">
              历史记录
            </Link>
            <Link to="/settings/models" className="rounded-lg px-3 py-1.5 text-slate-600 transition hover:bg-slate-100">
              模型设置
            </Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 py-10">
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-bold text-slate-800">段落优化</h1>
          <p className="mt-2 text-sm text-slate-500">
            保持观点不变，对语言、逻辑、结构和表达方式进行完善，可大幅提高论文的质量和可读性
          </p>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-lg sm:p-7">
          {/* 操作类型 */}
          <div className="mb-5 grid grid-cols-3 gap-2 sm:grid-cols-5">
            {POLISH_OPERATIONS.map((op) => {
              const active = operation === op.value;
              return (
                <button
                  type="button"
                  key={op.value}
                  onClick={() => setOperation(op.value)}
                  className={`flex flex-col items-center rounded-xl border px-2 py-3 text-center transition ${
                    active
                      ? "border-black bg-white ring-2 ring-neutral-200"
                      : "border-neutral-200 bg-white hover:border-black"
                  }`}
                >
                  <span
                    className={`text-sm font-semibold ${
                      active ? "text-black" : "text-neutral-700"
                    }`}
                  >
                    {op.label}
                  </span>
                  <span className="mt-1 text-[10px] leading-tight text-slate-400">
                    {op.desc}
                  </span>
                </button>
              );
            })}
          </div>

          {/* 补充要求 */}
          {needInstruction && (
            <div className="mb-5">
              <label className="mb-1.5 block text-sm font-medium text-slate-700">
                {operation === "translate" ? "目标语言" : "修改要求"}
              </label>
              <input
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder={
                  operation === "translate"
                    ? "例如：英文、日文、法文"
                    : "例如：使表述更正式、补充数据支撑等"
                }
                className={inputCls}
              />
            </div>
          )}

          {/* 原文 */}
          <div className="mb-4">
            <label className="mb-1.5 block text-sm font-medium text-slate-700">
              粘贴原文
            </label>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onFocus={ensureModels}
              placeholder="粘贴需要优化的段落文本（支持多段）…"
              rows={8}
              className={`${inputCls} leading-relaxed`}
            />
            <p className="mt-1 text-right text-xs text-slate-400">{text.length} 字</p>
          </div>

          {/* 模型选择 */}
          {models.length > 0 && (
            <div className="mb-5">
              <label className="mb-1.5 block text-sm font-medium text-slate-700">
                AI 模型
              </label>
              <select
                value={modelId}
                onChange={(e) => setModelId(e.target.value)}
                className={`${inputCls} max-w-xs`}
              >
                <option value="">默认模型</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}（{m.model}）
                  </option>
                ))}
              </select>
            </div>
          )}

          {error && (
            <div className="mb-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <button
            type="button"
            onClick={handleSubmit}
            disabled={loading}
            className="w-full rounded-xl bg-black px-6 py-3 text-sm font-bold text-white transition hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? "处理中…" : `开始${activeOp.label}`}
          </button>

          {/* 结果 */}
          {result && (
            <div className="mt-6 rounded-xl border border-green-200 bg-green-50 p-5">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-sm font-bold text-green-800">
                  {activeOp.label}结果
                </h3>
                <button
                  type="button"
                  onClick={() => navigator.clipboard.writeText(result)}
                  className="rounded-lg border border-green-300 bg-white px-3 py-1 text-xs text-green-700 transition hover:bg-green-100"
                >
                  复制结果
                </button>
              </div>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
                {result}
              </p>
            </div>
          )}
        </div>

        <p className="mt-4 text-center text-xs text-slate-400">
          段落优化为独立功能，不写入论文任务；如需修改论文内的段落，请在「在线预览」中使用段落操作。
        </p>
      </main>
    </div>
  );
}
