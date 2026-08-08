import { Link } from "react-router-dom";

const NAV = [
  { label: "毕业论文", to: "/create?type=毕业论文" },
  { label: "课程论文", to: "/create?type=课程论文" },
  { label: "开题报告", to: "/create?type=开题报告" },
  { label: "文献综述", to: "/create?type=文献综述" },
  { label: "段落优化", to: "/polish" },
  { label: "格式排版", to: "/create?type=毕业论文" },
  { label: "模板管理", to: "/templates" },
];

const TYPE_CARDS = [
  {
    title: "毕业论文（本科）",
    en: "Undergraduate Thesis",
    points: ["全文 10000~20000 字", "三级大纲结构", "更高的学术深度和研究难度"],
    to: "/create?type=毕业论文",
    accent: "from-indigo-500 to-blue-600",
  },
  {
    title: "课程论文",
    en: "Course Paper",
    points: ["即学年论文、小论文", "培养综合运用专业知识", "为毕业论文奠定基础"],
    to: "/create?type=课程论文",
    accent: "from-emerald-500 to-teal-600",
  },
  {
    title: "开题报告",
    en: "Opening Report",
    points: ["选题背景与意义", "国内外研究现状", "研究内容、方法与进度安排"],
    to: "/create?type=开题报告",
    accent: "from-amber-500 to-orange-600",
  },
  {
    title: "文献综述",
    en: "Literature Review",
    points: ["全面整理归纳参考文献", "含引言、现状研究", "综合性阐述与述评"],
    to: "/create?type=文献综述",
    accent: "from-rose-500 to-pink-600",
  },
];

const FEATURES = [
  {
    icon: "⚡",
    title: "AI 智能创作",
    desc: "免提示词，4 步快速完成高质量初稿，支持自动大纲与逐章生成",
  },
  {
    icon: "🔒",
    title: "本地私有化",
    desc: "数据保存在本地，隐私安全，可自由配置自己的 AI 模型",
  },
  {
    icon: "📊",
    title: "图表与排版",
    desc: "自动生成数据图表，一键格式处理，导出标准 Word 文档",
  },
  {
    icon: "🔄",
    title: "在线修订",
    desc: "章节 / 段落级 AI 润色扩写，版本管理可随时恢复",
  },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-white">
      {/* 顶部导航 */}
      <header className="sticky top-0 z-20 border-b border-slate-100 bg-white/85 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-8">
            <Link to="/" className="flex items-center gap-2">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-black text-lg font-bold text-white">
                论
              </span>
              <span className="text-xl font-bold text-slate-800">论文生成助手</span>
            </Link>
            <nav className="hidden items-center gap-1 text-sm text-slate-600 lg:flex">
              {NAV.map((n) => (
                <Link
                  key={n.label}
                  to={n.to}
                  className="rounded-lg px-3 py-1.5 transition hover:bg-neutral-100 hover:text-black"
                >
                  {n.label}
                </Link>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Link
              to="/history"
              className="rounded-lg px-3 py-1.5 text-slate-600 transition hover:bg-slate-100"
            >
              历史记录
            </Link>
            <Link
              to="/settings/models"
              className="rounded-lg px-3 py-1.5 text-slate-600 transition hover:bg-slate-100"
            >
              模型设置
            </Link>
            <Link
              to="/create"
              className="ml-2 rounded-xl bg-black px-4 py-2 font-semibold text-white transition hover:bg-neutral-700"
            >
              开始创作
            </Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="bg-white">
        <div className="mx-auto max-w-6xl px-4 py-16 text-center sm:py-20">
          <div className="mx-auto mb-5 inline-flex items-center gap-2 rounded-full border border-neutral-200 bg-white px-4 py-1.5 text-xs text-neutral-700">
            <span className="h-2 w-2 animate-pulse rounded-full bg-black" />
            本地 AI 论文创作平台 · 免费使用
          </div>
          <h1 className="mx-auto max-w-3xl text-4xl font-extrabold leading-tight tracking-tight text-slate-900 sm:text-5xl">
            论文生成助手
            <span className="block text-neutral-900">
              专注大学论文 · 4 步快速完成初稿
            </span>
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-base leading-relaxed text-slate-500">
            免账号 · 免提示词 · 数据本地保存。论文选题 → 生成摘要 → 参考文献 →
            论文正文，4 步 20 分钟快速完成高质量初稿。
          </p>
          <div className="mt-8 flex items-center justify-center gap-4">
            <Link
              to="/create"
              className="rounded-2xl bg-black px-10 py-3.5 text-base font-bold text-white transition hover:bg-neutral-700"
            >
              开始创作 →
            </Link>
            <Link
              to="/polish"
              className="rounded-2xl border border-neutral-300 bg-white px-8 py-3.5 text-base font-semibold text-neutral-700 transition hover:border-neutral-400 hover:text-black"
            >
              段落优化
            </Link>
          </div>
        </div>
      </section>

      {/* 论文类型 */}
      <section className="mx-auto max-w-6xl px-4 py-12">
        <div className="mb-8 text-center">
          <h2 className="text-2xl font-bold text-slate-800">选择论文类型，开始创作</h2>
          <p className="mt-2 text-sm text-slate-500">多种论文结构，一键生成</p>
        </div>
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {TYPE_CARDS.map((c) => (
            <Link
              key={c.title}
              to={c.to}
              className="group flex flex-col rounded-2xl border border-neutral-200 bg-white p-6 transition hover:-translate-y-1 hover:border-black"
            >
              <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-black text-lg font-bold text-white">
                {c.title[0]}
              </div>
              <h3 className="text-base font-bold text-slate-800 group-hover:text-black">
                {c.title}
              </h3>
              <div className="mt-0.5 text-[11px] uppercase tracking-widest text-slate-400">
                {c.en}
              </div>
              <ul className="mt-3 flex-1 space-y-1.5">
                {c.points.map((p) => (
                  <li key={p} className="flex items-start gap-2 text-xs text-slate-500">
                    <span className="mt-0.5 text-black">✓</span>
                    {p}
                  </li>
                ))}
              </ul>
              <span className="mt-5 inline-flex items-center text-sm font-semibold text-black">
                开始创作
                <span className="ml-1 transition group-hover:translate-x-1">→</span>
              </span>
            </Link>
          ))}
        </div>
      </section>

      {/* 功能特性 */}
      <section className="border-t border-slate-100 bg-slate-50/60">
        <div className="mx-auto max-w-6xl px-4 py-12">
          <div className="mb-8 text-center">
            <h2 className="text-2xl font-bold text-slate-800">更多功能，由你探索</h2>
          </div>
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {FEATURES.map((f) => (
              <div
                key={f.title}
                className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
              >
                <div className="mb-3 text-3xl">{f.icon}</div>
                <h3 className="text-sm font-bold text-slate-800">{f.title}</h3>
                <p className="mt-1.5 text-xs leading-relaxed text-slate-500">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="mx-auto max-w-6xl px-4 py-14">
        <div className="rounded-3xl bg-black px-8 py-12 text-center text-white">
          <h2 className="text-2xl font-bold sm:text-3xl">现在就开始你的论文创作</h2>
          <p className="mt-3 text-sm text-neutral-300">
            选择论文类型，4 步完成高质量初稿
          </p>
          <Link
            to="/create"
            className="mt-6 inline-block rounded-2xl bg-white px-10 py-3 text-base font-bold text-black transition hover:bg-neutral-100"
          >
            立即开始创作
          </Link>
        </div>
      </section>

      <footer className="border-t border-slate-100 py-6 text-center text-xs text-slate-400">
        论文生成助手 · 本地 AI 论文创作平台
      </footer>
    </div>
  );
}
