import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  createModel,
  deleteModel,
  fetchModels,
  setDefaultModel,
  testModel,
  updateModel,
  type ModelConfig,
  type ModelConfigInput,
} from "../api/paper";

const PROVIDERS = [
  "OpenAI Compatible",
  "DeepSeek",
  "Anthropic",
  "Google",
  "OpenRouter",
  "Ollama",
  "Custom",
];

interface FormState {
  id: string | null;
  name: string;
  provider: string;
  base_url: string;
  api_key: string;
  model: string;
  is_default: boolean;
  enabled: boolean;
}

const EMPTY_FORM: FormState = {
  id: null,
  name: "",
  provider: "OpenAI Compatible",
  base_url: "",
  api_key: "",
  model: "",
  is_default: false,
  enabled: true,
};

export default function SettingsModels({ embedded = false }: { embedded?: boolean }) {
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [message, setMessage] = useState<{
    type: "ok" | "err";
    text: string;
  } | null>(null);
  const [oneTimeKey, setOneTimeKey] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setModels(await fetchModels());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载模型列表失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function openCreate() {
    setForm({ ...EMPTY_FORM });
    setShowKey(false);
    setOneTimeKey(null);
  }

  function openEdit(model: ModelConfig) {
    setForm({
      id: model.id,
      name: model.name,
      provider: model.provider,
      base_url: model.base_url,
      api_key: "",
      model: model.model,
      is_default: model.is_default,
      enabled: model.enabled,
    });
    setShowKey(false);
    setOneTimeKey(null);
  }

  async function save() {
    if (!form) {
      return;
    }
    if (!form.name.trim() || !form.base_url.trim() || !form.model.trim()) {
      setMessage({ type: "err", text: "请填写模型名称、API Base URL 与 Model" });
      return;
    }
    if (!form.id && !form.api_key.trim()) {
      setMessage({ type: "err", text: "请填写 API Key" });
      return;
    }
    const input: ModelConfigInput = {
      name: form.name.trim(),
      provider: form.provider,
      base_url: form.base_url.trim(),
      model: form.model.trim(),
      is_default: form.is_default,
      enabled: form.enabled,
    };
    if (form.api_key.trim()) {
      input.api_key = form.api_key.trim();
    }
    setSaving(true);
    setMessage(null);
    try {
      if (form.id) {
        await updateModel(form.id, input);
        setMessage({ type: "ok", text: "模型已更新" });
      } else {
        const created = await createModel(input);
        if (created.api_key) {
          setOneTimeKey(created.api_key);
        }
        setMessage({ type: "ok", text: "模型已创建" });
      }
      setForm(null);
      await refresh();
    } catch (e) {
      setMessage({ type: "err", text: e instanceof Error ? e.message : "保存失败" });
    } finally {
      setSaving(false);
    }
  }

  async function handleTest(payload: { id: string } | ModelConfigInput) {
    try {
      const result = await testModel(payload);
      setMessage({ type: "ok", text: result.message });
    } catch (e) {
      setMessage({
        type: "err",
        text: e instanceof Error ? e.message : "连接失败",
      });
    }
  }

  async function handleDelete(model: ModelConfig) {
    if (!window.confirm(`确定删除模型「${model.name}」吗？`)) {
      return;
    }
    try {
      await deleteModel(model.id);
      await refresh();
    } catch (e) {
      setMessage({ type: "err", text: e instanceof Error ? e.message : "删除失败" });
    }
  }

  async function handleToggle(model: ModelConfig) {
    try {
      await updateModel(model.id, {
        name: model.name,
        provider: model.provider,
        base_url: model.base_url,
        model: model.model,
        enabled: !model.enabled,
      });
      await refresh();
    } catch (e) {
      setMessage({ type: "err", text: e instanceof Error ? e.message : "操作失败" });
    }
  }

  const inputCls =
    "w-full rounded-xl border border-neutral-300 bg-white px-3 py-2 text-sm outline-none focus:border-black focus:ring-2 focus:ring-neutral-200";

  return (
    <div className={embedded ? "min-h-0 bg-white px-0 py-0" : "min-h-screen bg-white px-4 py-8"}>
      <div className={embedded ? "w-full" : "mx-auto w-full max-w-5xl"}>
        {!embedded && (
        <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-slate-800">AI 模型配置</h1>
            <p className="mt-1 text-sm text-slate-500">
              管理 OpenAI 兼容接口的模型，生成论文时自动使用默认或所选模型
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Link
              to="/"
              className="rounded-xl border border-neutral-300 bg-white px-4 py-2 text-sm text-neutral-600 hover:border-neutral-400"
            >
              ← 返回生成页
            </Link>
            <button
              type="button"
              onClick={openCreate}
              className="rounded-xl bg-black px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700"
            >
              + 新增模型
            </button>
          </div>
        </header>
        )}

        {embedded && (
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <div>
              <p className="text-sm font-semibold text-slate-800">模型列表</p>
              <p className="mt-0.5 text-xs text-slate-500">添加并测试新的 OpenAI 兼容模型，无需离开编辑页。</p>
            </div>
            <button
              type="button"
              onClick={openCreate}
              className="rounded-lg bg-black px-4 py-2 text-sm font-medium text-white transition hover:bg-neutral-700"
            >
              + 添加新模型
            </button>
          </div>
        )}

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

        {oneTimeKey && (
          <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
            新模型创建成功，API Key（仅此一次显示，请妥善保存）：
            <code className="break-all">{oneTimeKey}</code>
          </div>
        )}

        {error && (
          <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
            {error}
          </div>
        )}

        {loading ? (
          <p className="py-10 text-center text-slate-400">正在加载…</p>
        ) : models.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white py-14 text-center">
            <p className="text-slate-400">还没有配置模型，点击“新增模型”开始</p>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs text-slate-400">
                  <th className="px-4 py-3">模型名称</th>
                  <th className="px-4 py-3">Provider</th>
                  <th className="px-4 py-3">API 地址</th>
                  <th className="px-4 py-3">Model</th>
                  <th className="px-4 py-3">默认</th>
                  <th className="px-4 py-3">状态</th>
                  <th className="px-4 py-3">操作</th>
                </tr>
              </thead>
              <tbody>
                {models.map((m) => (
                  <tr
                    key={m.id}
                    className="border-b border-slate-100 last:border-0"
                  >
                    <td className="px-4 py-3 font-medium text-slate-700">
                      {m.name}
                    </td>
                    <td className="px-4 py-3 text-slate-500">{m.provider}</td>
                    <td className="max-w-[180px] truncate px-4 py-3 text-slate-500">
                      {m.base_url}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-500">
                      {m.model}
                    </td>
                    <td className="px-4 py-3">
                      {m.is_default ? (
                        <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs text-neutral-700">
                          默认
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() =>
                            setDefaultModel(m.id).then(refresh).catch((e) =>
                              setMessage({
                                type: "err",
                                text: e instanceof Error ? e.message : "设置失败",
                              }),
                            )
                          }
                          className="text-xs text-slate-400 hover:text-black"
                        >
                          设为默认
                        </button>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={() => handleToggle(m)}
                        className={`rounded-full px-2 py-0.5 text-xs ${
                          m.enabled
                            ? "bg-green-100 text-green-700"
                            : "bg-slate-100 text-slate-400"
                        }`}
                      >
                        {m.enabled ? "已启用" : "已禁用"}
                      </button>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => openEdit(m)}
                          className="text-xs text-black hover:text-neutral-700"
                        >
                          编辑
                        </button>
                        <button
                          type="button"
                          disabled={testingId === m.id}
                          onClick={() => {
                            setTestingId(m.id);
                            handleTest({ id: m.id }).finally(() =>
                              setTestingId(null),
                            );
                          }}
                          className="text-xs text-slate-500 hover:text-black disabled:opacity-40"
                        >
                          {testingId === m.id ? "测试中…" : "测试"}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(m)}
                          className="text-xs text-slate-400 hover:text-red-500"
                        >
                          删除
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* 新增/编辑表单 */}
        {form && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
            onClick={() => setForm(null)}
          >
            <div
              className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-5 shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <h2 className="mb-4 text-lg font-semibold text-slate-800">
                {form.id ? "编辑模型" : "新增模型"}
              </h2>
              <div className="space-y-3">
                <div>
                  <label className="mb-1 block text-sm text-slate-600">
                    模型名称（必填）
                  </label>
                  <input
                    className={inputCls}
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="例如：DeepSeek V3 / GPT-5 / Ollama"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm text-slate-600">
                    Provider（可选）
                  </label>
                  <select
                    className={inputCls}
                    value={form.provider}
                    onChange={(e) =>
                      setForm({ ...form, provider: e.target.value })
                    }
                  >
                    {PROVIDERS.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-sm text-slate-600">
                    API Base URL（必填）
                  </label>
                  <input
                    className={inputCls}
                    value={form.base_url}
                    onChange={(e) =>
                      setForm({ ...form, base_url: e.target.value })
                    }
                    placeholder="https://api.deepseek.com/v1"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm text-slate-600">
                    API Key（必填）
                  </label>
                  <div className="flex gap-1.5">
                    <input
                      type={showKey ? "text" : "password"}
                      className={inputCls}
                      value={form.api_key}
                      onChange={(e) =>
                        setForm({ ...form, api_key: e.target.value })
                      }
                      placeholder={
                        form.id ? "留空保持不变" : "sk-..."
                      }
                    />
                    <button
                      type="button"
                      onClick={() => setShowKey((v) => !v)}
                      className="shrink-0 rounded-xl border border-slate-300 px-3 text-xs text-slate-500"
                    >
                      {showKey ? "隐藏" : "显示"}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (form.api_key) {
                          void navigator.clipboard?.writeText(form.api_key);
                          setMessage({ type: "ok", text: "API Key 已复制" });
                        }
                      }}
                      className="shrink-0 rounded-xl border border-slate-300 px-3 text-xs text-slate-500"
                    >
                      复制
                    </button>
                  </div>
                </div>
                <div>
                  <label className="mb-1 block text-sm text-slate-600">
                    模型名称 Model（必填）
                  </label>
                  <input
                    className={inputCls}
                    value={form.model}
                    onChange={(e) =>
                      setForm({ ...form, model: e.target.value })
                    }
                    placeholder="deepseek-chat / gpt-5 / llama3.1:8b"
                  />
                </div>
                <div className="flex items-center gap-6">
                  <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-600">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-indigo-500"
                      checked={form.is_default}
                      onChange={(e) =>
                        setForm({ ...form, is_default: e.target.checked })
                      }
                    />
                    设为默认
                  </label>
                  <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-600">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-indigo-500"
                      checked={form.enabled}
                      onChange={(e) =>
                        setForm({ ...form, enabled: e.target.checked })
                      }
                    />
                    启用
                  </label>
                </div>
              </div>
              <div className="mt-4 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() =>
                    handleTest({
                      name: form.name,
                      provider: form.provider,
                      base_url: form.base_url,
                      api_key: form.api_key || undefined,
                      model: form.model,
                    })
                  }
                  className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-600"
                >
                  测试连接
                </button>
                <button
                  type="button"
                  onClick={() => setForm(null)}
                  className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-600"
                >
                  取消
                </button>
                <button
                  type="button"
                  disabled={saving}
                  onClick={save}
                  className="rounded-lg bg-black px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700 disabled:opacity-40"
                >
                  {saving ? "保存中…" : "保存"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
