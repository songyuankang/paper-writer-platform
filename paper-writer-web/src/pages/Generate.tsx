import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  API_BASE,
  fetchPaperContent,
  fetchModels,
  fetchTaskStatus,
  generatePaper,
  generateOutline,
  type ModelConfig,
  type OutlineResult,
  type PaperContentManifest,
  type TaskInfo,
} from "../api/paper";
import OutlineEditor from "../components/OutlineEditor";
import ProgressBar from "../components/ProgressBar";
import ResultDownload from "../components/ResultDownload";

const MAJORS = ["教育学", "计算机", "经管", "医学"];

const PAPER_TYPES = [
  { label: "课程论文", value: "课程论文" },
  { label: "本科毕业论文", value: "毕业论文" },
  { label: "文献综述", value: "文献综述" },
  // 后端当前支持的类型为：课程论文/毕业论文/期刊论文/实证研究/文献综述
  { label: "开题报告", value: "课程论文" },
  { label: "调研报告", value: "课程论文" },
];

const REF_STYLES = [
  { label: "GB/T 7714", value: "gb7714" },
  { label: "APA", value: "apa" },
  { label: "MLA", value: "mla" },
];

type GenMode = "auto" | "outline" | "ai_outline";

const MODES: { value: GenMode; label: string; desc: string }[] = [
  { value: "auto", label: "自动生成论文", desc: "按论文类型自动规划结构" },
  { value: "outline", label: "根据我的大纲生成", desc: "粘贴自己的章节大纲" },
  { value: "ai_outline", label: "AI 生成大纲后确认", desc: "先生成大纲再确认" },
];

const CHART_GROUPS: { label: string; types: { key: string; label: string }[] }[] = [
  {
    label: "比较类",
    types: [
      { key: "bar", label: "柱状图" },
      { key: "horizontal_bar", label: "条形图" },
      { key: "radar", label: "雷达图" },
      { key: "stacked_bar", label: "分向条形图" },
    ],
  },
  {
    label: "趋势类",
    types: [
      { key: "line", label: "折线图" },
      { key: "area", label: "面积图" },
      { key: "heatmap", label: "热力图" },
      { key: "stock", label: "股价图" },
    ],
  },
  {
    label: "分布类",
    types: [
      { key: "histogram", label: "直方图" },
      { key: "boxplot", label: "箱线图" },
      { key: "violin", label: "小提琴图" },
      { key: "scatter", label: "散点图" },
    ],
  },
  {
    label: "构成类",
    types: [
      { key: "pie", label: "饼图" },
      { key: "treemap", label: "树状图" },
      { key: "sunburst", label: "旭日图" },
      { key: "decomposition_tree", label: "分解树" },
    ],
  },
  {
    label: "流程类",
    types: [
      { key: "sankey", label: "桑基图" },
      { key: "funnel", label: "漏斗图" },
      { key: "flowchart", label: "流程图" },
      { key: "chord", label: "和弦图" },
    ],
  },
];

const MAJOR_RECOMMEND: Record<string, string[]> = {
  计算机: ["flowchart", "line", "bar"],
  教育学: ["bar", "pie", "radar"],
  经管: ["line", "heatmap", "sankey"],
  医学: ["bar", "histogram", "boxplot"],
};

function stageLabel(progress: number): string {
  if (progress <= 0) return "等待提交…";
  if (progress < 10) return "正在初始化";
  if (progress < 30) return "正在解析模板";
  if (progress < 60) return "正在生成论文结构";
  if (progress < 80) return "正在生成正文";
  if (progress < 100) return "正在生成图表与检查";
  return "完成";
}

function FieldLabel({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return (
    <div className="mb-1.5">
      <span className="text-sm font-medium text-slate-700">{children}</span>
      {hint && <span className="ml-2 text-xs text-slate-400">{hint}</span>}
    </div>
  );
}

const inputCls =
  "w-full rounded-xl border border-neutral-300 bg-white px-3 py-2.5 text-sm text-neutral-900 outline-none transition placeholder:text-neutral-400 focus:border-black focus:ring-2 focus:ring-neutral-200";

export default function Generate() {
  const [title, setTitle] = useState("");
  const [major, setMajor] = useState("");
  const [customMajor, setCustomMajor] = useState("");
  const [paperType, setPaperType] = useState("课程论文");
  const [wordCount, setWordCount] = useState(3000);
  const [chartEnabled, setChartEnabled] = useState(false);
  const [chartTypeCounts, setChartTypeCounts] = useState<Record<string, number>>({});
  const [specialRequirements, setSpecialRequirements] = useState("");
  const [models, setModels] = useState<ModelConfig[]>([]);
const [modelId, setModelId] = useState("");
const [contentManifest, setContentManifest] = useState<PaperContentManifest | null>(null);
  const [refStyle, setRefStyle] = useState("gb7714");
const [genMode, setGenMode] = useState<GenMode>("auto");
  const [outlineText, setOutlineText] = useState("");
  const [aiOutline, setAiOutline] = useState<OutlineResult | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  const [task, setTask] = useState<TaskInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const pollRef = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    fetchModels()
      .then((list) => setModels(list.filter((m) => m.enabled)))
      .catch(() => setModels([]));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setAiError(null);

    if (!title.trim()) {
      setError("请填写论文标题");
      return;
    }
    if (wordCount < 1000 || wordCount > 20000) {
      setError("字数需在 1000–20000 之间");
      return;
    }
    const effectiveMajor = getEffectiveMajor();
    if (!effectiveMajor) {
      setError("请填写专业");
      return;
    }
    if (genMode !== "auto" && !outlineText.trim()) {
      setError(genMode === "ai_outline" ? "请先生成大纲或填写大纲内容" : "请填写论文大纲");
      return;
    }

    setSubmitting(true);
    setTask(null);
    try {
      const isOutlineMode = genMode !== "auto";
      const chartTypesExpanded: string[] = [];
      for (const [type, qty] of Object.entries(chartTypeCounts)) {
        for (let i = 0; i < qty; i++) {
          chartTypesExpanded.push(type);
        }
      }
      const chartTotal = chartTypesExpanded.length;
      const { task_id } = await generatePaper({
        title: title.trim(),
        major: effectiveMajor,
        paper_type: paperType,
        word_count: wordCount,
        chart_enabled: chartEnabled,
        chart_config: chartEnabled
          ? { enabled: true, count: chartTotal, types: chartTypesExpanded }
          : null,
        special_requirements: specialRequirements.trim(),
        model_id: modelId || undefined,
        reference_style: refStyle,
        generation_mode: isOutlineMode ? "outline" : undefined,
        outline: isOutlineMode ? outlineText.trim() : undefined,
      });

      startProgressStream(task_id);
    } catch (err) {
      setSubmitting(false);
      setError(err instanceof Error ? err.message : "提交失败，请检查后端服务是否已启动");
    }
  }

  function startProgressStream(taskId: string) {
    const fallbackPoll = () => {
      if (pollRef.current !== null) {
        return; // 已有轮询在跑
      }
      pollRef.current = window.setInterval(async () => {
        try {
          const info = await fetchTaskStatus(taskId);
          setTask(info);
          if (info.status === "completed" || info.status === "failed") {
            if (pollRef.current !== null) {
              window.clearInterval(pollRef.current);
              pollRef.current = null;
            }
            setSubmitting(false);
          }
        } catch {
          if (pollRef.current !== null) {
            window.clearInterval(pollRef.current);
            pollRef.current = null;
          }
          setSubmitting(false);
        }
      }, 1500);
    };

    if (typeof EventSource === "undefined") {
      fallbackPoll();
      return;
    }
    const es = new EventSource(`${API_BASE}/api/generate/stream/${taskId}`);
    let finished = false;
    const finish = () => {
      if (finished) {
        return;
      }
      finished = true;
      es.close();
      setSubmitting(false);
    };
    es.addEventListener("progress", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent<string>).data);
        setTask({
          task_id: taskId,
          status: data.status,
          progress: data.progress,
          message: data.message,
          current_stage: data.current_stage,
          current_chapter: data.current_chapter,
          chapter_count: data.chapter_count,
          error: null,
          files: [],
        });
        if (data.status === "completed" || data.status === "failed") {
          finish();
          void fetchTaskStatus(taskId).then(setTask).catch(() => undefined);
          if (data.status === "completed") {
            void fetchPaperContent(taskId)
              .then(setContentManifest)
              .catch(() => undefined);
          }
        }
      } catch {
        // 忽略无法解析的事件
      }
    });
    es.onerror = () => {
      finish();
      fallbackPoll();
    };
  }

  function getEffectiveMajor(): string {
    return major === "custom" ? customMajor.trim() : major;
  }

  function recommendedChartTypes(): string[] {
    const m = getEffectiveMajor();
    for (const [key, types] of Object.entries(MAJOR_RECOMMEND)) {
      if (m.includes(key)) {
        return types;
      }
    }
    return ["bar", "line", "pie"];
  }

  function toggleChartType(key: string) {
    setChartTypeCounts((prev) => {
      const next = { ...prev };
      if (next[key]) {
        delete next[key];
      } else {
        next[key] = 1;
      }
      return next;
    });
  }

  function changeTypeCount(key: string, delta: number) {
    setChartTypeCounts((prev) => {
      const current = prev[key] ?? 0;
      const nextValue = current + delta;
      if (nextValue < 1 || nextValue > 20) {
        return prev;
      }
      const total = Object.values(prev).reduce((a, b) => a + b, 0);
      if (total + delta > 20) {
        return prev;
      }
      return { ...prev, [key]: nextValue };
    });
  }

  function applyRecommendedTypes(types: string[]) {
    const next: Record<string, number> = {};
    for (const t of types) {
      next[t] = 1;
    }
    setChartTypeCounts(next);
  }

  async function handleGenerateOutline() {
    setAiError(null);
    setError(null);
    const effectiveMajor = getEffectiveMajor();
    if (!title.trim()) {
      setAiError("请先填写论文标题");
      return;
    }
    if (!effectiveMajor) {
      setAiError("请填写专业");
      return;
    }
    if (wordCount < 1000 || wordCount > 20000) {
      setAiError("字数需在 1000–20000 之间");
      return;
    }
    setAiLoading(true);
    try {
      const result = await generateOutline({
        title: title.trim(),
        major: effectiveMajor,
        paper_type: paperType,
        word_count: wordCount,
        model_id: modelId || undefined,
      });
      setAiOutline(result);
      setOutlineText(result.outline);
    } catch (err) {
      setAiError(err instanceof Error ? err.message : "生成大纲失败");
    } finally {
      setAiLoading(false);
    }
  }

  const running = task !== null && task.status !== "completed" && task.status !== "failed";

  return (
    <div className="min-h-screen bg-white px-4 py-8 sm:py-12">
      <div className="mx-auto w-full max-w-2xl">
        <header className="mb-8 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-slate-800">
              论文生成助手
            </h1>
            <p className="mt-2 text-sm text-slate-500">
              输入论文需求，自动生成论文草稿、示例图表与格式意见
            </p>
          </div>
          <Link
            to="/"
            className="shrink-0 rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm text-slate-600 transition hover:border-indigo-300 hover:text-indigo-600"
          >
            首页
          </Link>
          <Link
            to="/history"
            className="shrink-0 rounded-xl border border-neutral-300 bg-white px-4 py-2 text-sm text-neutral-600 transition hover:border-neutral-400 hover:text-black"
          >
            历史记录
          </Link>
          <Link
            to="/settings/models"
            className="shrink-0 rounded-xl border border-neutral-300 bg-white px-4 py-2 text-sm text-neutral-600 transition hover:border-neutral-400 hover:text-black"
          >
            模型设置
          </Link>
        </header>

        <form
          onSubmit={handleSubmit}
          className="space-y-5 rounded-2xl border border-neutral-200 bg-white p-5 sm:p-7"
        >
          {/* 生成方式 */}
          <div>
            <FieldLabel>论文生成方式</FieldLabel>
            <div className="grid gap-2 sm:grid-cols-3">
              {MODES.map((m) => {
                const active = genMode === m.value;
                return (
                  <button
                    type="button"
                    key={m.value}
                    onClick={() => setGenMode(m.value)}
                    className={`flex items-start gap-2 rounded-xl border px-3 py-2.5 text-left transition ${
                      active
                        ? "border-black bg-white ring-2 ring-neutral-200"
                        : "border-neutral-300 bg-white hover:border-black"
                    }`}
                  >
                    <span
                      className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2 ${
                        active
                          ? "border-black"
                          : "border-neutral-300"
                      }`}
                    >
                      {active && (
                        <span className="h-2 w-2 rounded-full bg-black" />
                      )}
                    </span>
                    <span>
                      <span className="block text-sm font-medium text-slate-700">
                        {m.label}
                      </span>
                      <span className="block text-xs text-slate-400">{m.desc}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* AI 模型选择 */}
          {models.length > 0 && (
            <div>
              <FieldLabel hint="留空使用默认模型">AI 模型</FieldLabel>
              <select
                className={inputCls}
                value={modelId}
                onChange={(e) => setModelId(e.target.value)}
              >
                <option value="">默认模型</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                    {m.is_default ? "（默认）" : ""}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* 论文标题 */}
          <div>
            <FieldLabel>论文标题</FieldLabel>
            <input
              className={inputCls}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="例如：数字化转型对企业绩效的影响研究"
              maxLength={200}
            />
          </div>

          {/* 专业 + 论文类型 */}
          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <FieldLabel>专业</FieldLabel>
              <select
                className={inputCls}
                value={major}
                onChange={(e) => setMajor(e.target.value)}
              >
                <option value="">请选择</option>
                {MAJORS.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
                <option value="custom">自定义</option>
              </select>
              {major === "custom" && (
                <input
                  className={`${inputCls} mt-2`}
                  value={customMajor}
                  onChange={(e) => setCustomMajor(e.target.value)}
                  placeholder="请输入专业名称"
                  maxLength={100}
                />
              )}
            </div>
            <div>
              <FieldLabel>论文类型</FieldLabel>
              <select
                className={inputCls}
                value={paperType}
                onChange={(e) => setPaperType(e.target.value)}
              >
                {PAPER_TYPES.map((t) => (
                  <option key={t.label} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-xs text-slate-400">
                开题报告/调研报告暂映射为课程论文结构
              </p>
            </div>
          </div>

          {/* 字数 + 图表开关 */}
          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <FieldLabel hint="1000–20000 字">字数</FieldLabel>
              <input
                type="number"
                className={inputCls}
                value={wordCount}
                min={1000}
                max={20000}
                onChange={(e) => setWordCount(Number(e.target.value))}
              />
            </div>
            <div>
              <FieldLabel>图表生成</FieldLabel>
              <div className="grid grid-cols-2 gap-2">
                {[
                  { value: true, label: "开启" },
                  { value: false, label: "关闭" },
                ].map((opt) => {
                  const active = chartEnabled === opt.value;
                  return (
                    <button
                      type="button"
                      key={String(opt.value)}
                      onClick={() => {
                        setChartEnabled(opt.value);
                        if (
                          opt.value &&
                          Object.keys(chartTypeCounts).length === 0
                        ) {
                          applyRecommendedTypes(recommendedChartTypes());
                        }
                      }}
                      className={`rounded-xl border px-3 py-2.5 text-sm transition ${
                        active
                          ? "border-black bg-black text-white"
                          : "border-slate-300 bg-white text-slate-600 hover:border-black"
                      }`}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* 图表设置 */}
          {chartEnabled && (
            <div className="space-y-4 rounded-xl border border-neutral-200 bg-neutral-50 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm text-slate-600">
                  总体生成数量：
                  <span className="font-semibold text-black">
                    {Object.values(chartTypeCounts).reduce((a, b) => a + b, 0)}
                  </span>{" "}
                  张（由各类型数量合计，不可直接修改）
                </p>
                <button
                  type="button"
                  onClick={() => applyRecommendedTypes(recommendedChartTypes())}
                  className="rounded-lg border border-neutral-300 bg-white px-3 py-1.5 text-xs text-neutral-700 transition hover:bg-neutral-100"
                >
                  按专业智能推荐
                </button>
              </div>

              <div>
                <p className="mb-1.5 text-sm font-medium text-slate-700">
                  图表类型与数量
                </p>
                <div className="space-y-2">
                  {CHART_GROUPS.map((group) => (
                    <div
                      key={group.label}
                      className="rounded-xl border border-slate-200 bg-white p-3"
                    >
                      <p className="mb-1.5 text-xs font-medium text-slate-400">
                        {group.label}
                      </p>
                      <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                        {group.types.map((t) => {
                          const qty = chartTypeCounts[t.key] ?? 0;
                          const checked = qty > 0;
                          return (
                            <div
                              key={t.key}
                              className={`flex cursor-pointer items-center gap-2 rounded-lg border px-2.5 py-1.5 text-sm transition ${
                                checked
                                  ? "border-black bg-neutral-50 text-black"
                                  : "border-slate-200 text-slate-600 hover:border-neutral-300"
                              }`}
                            >
                              <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2">
                                <input
                                  type="checkbox"
                                  className="h-3.5 w-3.5 shrink-0 accent-black"
                                  checked={checked}
                                  onChange={() => toggleChartType(t.key)}
                                />
                                <span className="truncate">{t.label}</span>
                              </label>
                              {checked && (
                                <div className="flex shrink-0 items-center gap-1">
                                  <button
                                    type="button"
                                    onClick={() => changeTypeCount(t.key, -1)}
                                    disabled={qty <= 1}
                                    className="flex h-5 w-5 items-center justify-center rounded border border-slate-300 bg-white text-slate-500 hover:border-neutral-400 disabled:opacity-30"
                                  >
                                    −
                                  </button>
                                  <span className="w-5 text-center text-xs font-medium">
                                    {qty}
                                  </span>
                                  <button
                                    type="button"
                                    onClick={() => changeTypeCount(t.key, 1)}
                                    disabled={
                                      qty >= 20 ||
                                      Object.values(chartTypeCounts).reduce(
                                        (a, b) => a + b,
                                        0,
                                      ) >= 20
                                    }
                                    className="flex h-5 w-5 items-center justify-center rounded border border-slate-300 bg-white text-slate-500 hover:border-neutral-400 disabled:opacity-30"
                                  >
                                    +
                                  </button>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* 参考文献格式 */}
          <div>
            <FieldLabel>参考文献格式</FieldLabel>
            <div className="grid grid-cols-3 gap-2">
              {REF_STYLES.map((s) => (
                <button
                  key={s.value}
                  type="button"
                  onClick={() => setRefStyle(s.value)}
                  className={`rounded-xl border px-3 py-2.5 text-sm transition ${
                    refStyle === s.value
                      ? "border-black bg-black text-white"
                      : "border-slate-300 bg-white text-slate-600 hover:border-black"
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          {/* 大纲模式 */}
          {genMode === "ai_outline" && (
            <div className="space-y-2">
              <button
                type="button"
                onClick={handleGenerateOutline}
                disabled={aiLoading}
                className="w-full rounded-xl bg-black py-2.5 text-sm font-medium text-white transition hover:bg-neutral-700 disabled:bg-slate-300"
              >
                {aiLoading ? "正在生成大纲…" : "生成大纲"}
              </button>
              {aiError && (
                <p className="text-sm text-red-500">{aiError}</p>
              )}
            </div>
          )}
          {genMode !== "auto" && (
            <div>
              <FieldLabel hint="多行文本，支持章节上移/下移与保存">
                论文大纲
              </FieldLabel>
              <OutlineEditor
                value={outlineText}
                onChange={setOutlineText}
                totalWords={wordCount}
                aiChapters={genMode === "ai_outline" ? aiOutline?.chapters ?? null : null}
              />
            </div>
          )}

          {/* 高级设置 */}
          <details className="group rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <summary className="cursor-pointer select-none text-sm font-medium text-slate-600 transition hover:text-black">
              高级设置
            </summary>
            <div className="mt-3">
              <FieldLabel hint="可选，不填写不影响生成">
                特殊要求
              </FieldLabel>
              <textarea
                value={specialRequirements}
                onChange={(e) => setSpecialRequirements(e.target.value)}
                rows={3}
                maxLength={1000}
                placeholder={
                  "可填写额外论文要求，例如：\n- 增加案例分析\n- 强化某章节\n- 调整写作风格\n- 增加数据分析"
                }
                className="w-full resize-y rounded-xl border border-neutral-300 bg-white px-3 py-2.5 text-sm text-neutral-900 outline-none transition placeholder:text-neutral-300 focus:border-black focus:ring-2 focus:ring-neutral-200"
              />
            </div>
          </details>

          {error && (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={
              submitting ||
              running ||
              (genMode !== "auto" && !outlineText.trim())
            }
            className="w-full rounded-xl bg-black py-3 text-sm font-semibold text-white transition hover:bg-neutral-700 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none"
          >
            {submitting || running
              ? "正在生成…"
              : genMode === "auto"
                ? "开始生成论文"
                : genMode === "outline"
                  ? "按大纲生成论文"
                  : "确认大纲并生成论文"}
          </button>
        </form>

        {/* 进度 */}
        {running && task && (
          <div className="mt-5">
            <ProgressBar
              progress={task.progress}
              label={task.message ?? stageLabel(task.progress)}
            />
          </div>
        )}

        {/* 完成 */}
        {task?.status === "completed" && (
          <div className="mt-5 space-y-3">
            {/* 论文内容预览（第一阶段产物，不含 Word） */}
            {contentManifest && (
              <div className="rounded-2xl border border-neutral-200 bg-white p-5">
                <div className="mb-2 flex items-center justify-between">
                  <h2 className="font-semibold text-slate-700">论文内容预览</h2>
                  <span className="text-xs text-slate-400">
                    第一阶段 · 纯内容（未排版）
                  </span>
                </div>
                {contentManifest.abstract && (
                  <p className="mb-2 text-sm leading-6 text-slate-600">
                    <span className="font-medium text-slate-700">摘要：</span>
                    {contentManifest.abstract}
                  </p>
                )}
                <ol className="space-y-1">
                  {contentManifest.chapters.map(
                    (ch: { title: string; text: string }, i: number) => (
                      <li key={`${ch.title}-${i}`} className="text-sm text-slate-600">
                        <span className="font-medium text-slate-700">{ch.title}</span>
                        {ch.text && (
                          <p className="mt-0.5 line-clamp-2 text-slate-500">
                            {ch.text.replace(/^#+\s*/gm, "")}
                          </p>
                        )}
                      </li>
                    ),
                  )}
                </ol>
                {contentManifest.conclusion && (
                  <p className="mt-2 text-sm leading-6 text-slate-600">
                    <span className="font-medium text-slate-700">结论：</span>
                    {contentManifest.conclusion.slice(0, 200)}
                    {contentManifest.conclusion.length > 200 ? "…" : ""}
                  </p>
                )}
                <Link
                  to={`/format/${task.task_id}`}
                  className="mt-3 block w-full rounded-xl bg-black py-2.5 text-center text-sm font-semibold text-white hover:bg-neutral-700"
                >
                  下一步：进入格式处理
                </Link>
              </div>
            )}
            <div className="grid grid-cols-2 gap-2">
              <Link
                to={`/preview/${task.task_id}`}
                className="rounded-xl bg-black py-3 text-center text-sm font-semibold text-white transition hover:bg-neutral-700"
              >
                在线查看论文
              </Link>
              <Link
                to={`/preview/${task.task_id}?print=1`}
                className="rounded-xl border border-neutral-300 bg-white py-3 text-center text-sm font-semibold text-neutral-700 transition hover:bg-neutral-100"
              >
                下载 PDF
              </Link>
            </div>
            <ResultDownload taskId={task.task_id} files={task.files} />
          </div>
        )}

        {/* 失败 */}
        {task?.status === "failed" && (
          <div className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-5 text-sm text-red-600">
            生成失败：{task.error ?? "未知错误"}。请检查 paper-writer-api 日志后重试。
          </div>
        )}
      </div>
    </div>
  );
}
