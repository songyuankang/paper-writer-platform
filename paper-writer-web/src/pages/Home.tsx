import { Link } from "react-router-dom";

const NAV = [
  ["毕业论文", "/create?type=毕业论文"], ["课程论文", "/create?type=课程论文"],
  ["开题报告", "/create?type=开题报告"], ["文献综述", "/create?type=文献综述"],
  ["段落优化", "/polish"], ["格式排版", "/create?type=毕业论文"], ["模板管理", "/templates"],
];

const TYPES: Array<[string, string, string[], string]> = [
  ["毕业论文（本科）", "Undergraduate Thesis", ["全文 10000~20000 字", "三级大纲结构", "更高的学术深度和研究难度"], "/create?type=毕业论文"],
  ["课程论文", "Course Paper", ["即学年论文、小论文", "培养综合运用专业知识", "为毕业论文奠定基础"], "/create?type=课程论文"],
  ["开题报告", "Opening Report", ["选题背景与意义", "国内外研究现状", "研究内容、方法与进度安排"], "/create?type=开题报告"],
  ["文献综述", "Literature Review", ["全面整理归纳参考文献", "含引言、现状研究", "综合性阐述与述评"], "/create?type=文献综述"],
];

const FEATURES = [
  ["01", "AI 智能创作", "免提示词，4 步快速完成高质量初稿，支持自动大纲与逐章生成"],
  ["02", "本地私有化", "数据保存在本地，隐私安全，可自由配置自己的 AI 模型"],
  ["03", "图表与排版", "自动生成数据图表，一键格式处理，导出标准 Word 文档"],
  ["04", "在线修订", "章节 / 段落级 AI 润色扩写，版本管理可随时恢复"],
];

export default function Home() {
  return <div className="min-h-screen bg-white text-[#17191c]">
    <header className="mx-auto flex max-w-[1200px] items-center justify-between px-6 py-6 lg:px-8">
      <Link to="/" className="group flex items-center gap-3.5 text-[#17191c]"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[11px] bg-[#17191c] font-serif text-[15px] text-white transition group-hover:bg-[#5d2a1a]">论</span><span className="font-serif text-[20px] font-normal leading-none tracking-[-0.035em]">论文生成助手</span></Link>
      <nav className="hidden items-center gap-7 text-[14px] text-[#777b86] xl:flex">{NAV.map(([label, to]) => <Link key={label} to={to} className="transition hover:text-[#17191c]">{label}</Link>)}</nav>
      <div className="flex items-center gap-4 text-[14px]"><Link to="/history" className="hidden text-[#777b86] transition hover:text-[#17191c] sm:block">历史记录</Link><Link to="/settings/models" className="hidden text-[#777b86] transition hover:text-[#17191c] md:block">模型设置</Link><Link to="/create" className="rounded-full bg-[#17191c] px-5 py-2.5 text-white transition hover:bg-[#5d2a1a]">开始创作</Link></div>
    </header>
    <main>
      <section className="mx-auto max-w-[1200px] px-6 pb-24 pt-20 text-center lg:px-8 lg:pt-28"><h1 className="mx-auto max-w-4xl font-serif text-[48px] font-normal leading-[1.15] tracking-[-0.04em] sm:text-[64px] lg:text-[76px]">让论文创作，回到<br /><em className="font-normal">思考本身</em></h1><p className="mx-auto mt-8 max-w-xl text-[17px] leading-[1.5] text-[#777b86]">免账号 · 免提示词 · 数据本地保存。论文选题、摘要、参考文献与正文，四步完成高质量初稿。</p><div className="mt-9 flex flex-wrap items-center justify-center gap-3"><Link to="/create" className="rounded-full bg-[#17191c] px-6 py-3 text-[16px] text-white transition hover:bg-[#5d2a1a]">开始创作 →</Link><Link to="/polish" className="rounded-full border border-[#17191c] px-6 py-3 text-[16px] transition hover:bg-[#f2f2f3]">段落优化</Link></div><div className="mx-auto mt-20 grid max-w-4xl gap-4 text-left sm:grid-cols-3"><div className="rounded-[20px] bg-[#f2f2f3] p-5 sm:translate-y-5"><div className="text-[13px] text-[#979799]">创作流程</div><div className="mt-3 font-serif text-3xl">4 步</div><div className="mt-1 text-[14px] text-[#777b86]">从选题到完整初稿</div></div><div className="rounded-[24px] bg-[#fbe1d1] p-6 text-[#5d2a1a]"><div className="text-[13px]">本地 AI 工作台</div><div className="mt-8 text-[20px] leading-[1.35]">清晰的结构，安静的界面，专注于你的研究。</div></div><div className="rounded-[20px] bg-[#f2f2f3] p-5 sm:translate-y-5"><div className="text-[13px] text-[#979799]">内容保存</div><div className="mt-3 font-serif text-3xl">本地</div><div className="mt-1 text-[14px] text-[#777b86]">数据始终掌握在你手中</div></div></div></section>
      <section className="bg-[#fafafb] px-6 py-20 lg:px-8 lg:py-24"><div className="mx-auto max-w-[1200px]"><div className="mb-12 flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div><h2 className="font-serif text-[42px] font-normal tracking-[-0.03em] sm:text-[52px]">选择你的起点</h2><p className="mt-3 text-[17px] text-[#777b86]">不同结构，同样简单的创作体验。</p></div><Link to="/create" className="text-[16px] transition hover:underline">查看全部 →</Link></div><div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">{TYPES.map(([title, en, points, to]) => <Link key={title} to={to} className="group flex min-h-[260px] flex-col rounded-[24px] bg-[#f2f2f3] p-6 transition hover:-translate-y-1 hover:bg-white hover:shadow-[0_0_0_1px_rgba(4,23,43,.05),0_16px_24px_-12px_rgba(0,0,0,.16)]"><span className="text-[13px] text-[#979799]">{en}</span><h3 className="mt-6 text-[20px] font-[480] tracking-[-0.02em]">{title}</h3><ul className="mt-4 flex-1 space-y-2 text-[14px] leading-[1.45] text-[#777b86]">{(points as string[]).map((point) => <li key={point}>· {point}</li>)}</ul><span className="mt-5 text-[15px] transition group-hover:translate-x-1">开始创作 →</span></Link>)}</div></div></section>
      <section className="mx-auto max-w-[1200px] px-6 py-20 lg:px-8 lg:py-24"><div className="grid gap-12 lg:grid-cols-[.85fr_1.15fr] lg:gap-24"><div><h2 className="font-serif text-[42px] font-normal leading-[1.2] tracking-[-0.03em] sm:text-[52px]">一套安静而<br /><em>可靠</em>的工具</h2><p className="mt-6 max-w-sm text-[17px] leading-[1.5] text-[#777b86]">把复杂的论文流程拆解成清晰、可控、随时可以回来的每一步。</p></div><div className="divide-y divide-[#ececec]">{FEATURES.map(([number, title, desc]) => <div key={title} className="grid gap-4 py-6 sm:grid-cols-[48px_180px_1fr] sm:items-start"><span className="text-[14px] text-[#979799]">{number}</span><h3 className="text-[20px] font-[480]">{title}</h3><p className="text-[15px] leading-[1.5] text-[#777b86]">{desc}</p></div>)}</div></div></section>
      <section className="px-6 pb-20 lg:px-8 lg:pb-24"><div className="mx-auto max-w-[1200px] rounded-[24px] bg-[#17191c] px-8 py-14 text-center text-white sm:py-16"><h2 className="font-serif text-[38px] font-normal tracking-[-0.03em] sm:text-[48px]">现在开始写下第一段</h2><p className="mt-4 text-[16px] text-[#a3a6af]">选择论文类型，回到你的研究。</p><Link to="/create" className="mt-8 inline-block rounded-full bg-white px-6 py-3 text-[16px] text-[#17191c] transition hover:bg-[#fbe1d1]">立即开始创作 →</Link></div></section>
    </main>
    <footer className="border-t border-[#ececec] px-6 py-8 text-center text-[14px] text-[#979799]">论文生成助手 · 本地 AI 论文创作平台</footer>
  </div>;
}
