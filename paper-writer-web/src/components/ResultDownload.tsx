import { downloadUrl } from "../api/paper";

interface ResultDownloadProps {
  taskId: string;
  files: string[];
}

export default function ResultDownload({ taskId, files }: ResultDownloadProps) {
  const hasDocx = files.includes("论文.docx");
  const hasReview = files.includes("格式意见整理.md");
  const figure =
    files.find((f) => f.startsWith("charts/figure_")) ??
    files.find((f) => f.startsWith("figures/"));
  const hasChartData = files.includes("charts/chart_data.json");

  const links: { label: string; href: string; desc: string }[] = [];
  if (hasDocx) {
    links.push({
      label: "论文.docx",
      href: downloadUrl(taskId, "论文.docx"),
      desc: "论文成稿",
    });
  }
  if (hasReview) {
    links.push({
      label: "格式意见.md",
      href: downloadUrl(taskId, "格式意见整理.md"),
      desc: "格式检查与修改建议",
    });
  }
  if (figure) {
    links.push({
      label: "图表文件",
      href: downloadUrl(taskId, figure),
      desc: "数据图表 PNG",
    });
  }
  if (hasChartData) {
    links.push({
      label: "图表数据",
      href: downloadUrl(taskId, "charts/chart_data.json"),
      desc: "chart_data.json",
    });
  }
  links.push({
    label: "全部下载（ZIP）",
    href: downloadUrl(taskId),
    desc: "论文 + 图表 + 检查报告",
  });

  return (
    <div className="rounded-2xl border border-green-200 bg-green-50 p-5">
      <div className="mb-3 flex items-center gap-2">
        <span className="text-lg">🎉</span>
        <h3 className="font-semibold text-green-800">生成完成，请下载结果</h3>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {links.map((link) => (
          <a
            key={link.label}
            href={link.href}
            className="flex flex-col gap-0.5 rounded-xl border border-green-200 bg-white px-3 py-2.5 text-sm transition hover:border-green-400 hover:shadow"
          >
            <span className="font-medium text-green-700">{link.label}</span>
            <span className="text-xs text-slate-400">{link.desc}</span>
          </a>
        ))}
      </div>
    </div>
  );
}
