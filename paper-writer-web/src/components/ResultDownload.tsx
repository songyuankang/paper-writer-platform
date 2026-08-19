import { useState } from "react";
import { downloadUrl, exportPaper } from "../api/paper";
import TemplateManagerModal from "./TemplateManagerModal";

interface ResultDownloadProps {
  taskId: string;
  files: string[];
}

export default function ResultDownload({ taskId, files }: ResultDownloadProps) {
  const [templateModalOpen, setTemplateModalOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const hasReview = files.includes("格式意见整理.md");

  const links: { label: string; href: string; desc: string }[] = [];
  if (hasReview) {
    links.push({
      label: "格式意见.md",
      href: downloadUrl(taskId, "格式意见整理.md"),
      desc: "格式检查与修改建议",
    });
  }
  links.push({
    label: "全部下载（ZIP）",
    href: downloadUrl(taskId),
    desc: "内容与检查报告",
  });

  /** 导出：选择排版模板 → 后端按模板渲染 docx → 下载。 */
  async function handleExport(templateId: string) {
    setTemplateModalOpen(false);
    setExporting(true);
    try {
      await exportPaper(taskId, templateId);
      window.location.href = downloadUrl(taskId, "论文.docx");
    } catch (err) {
      alert(err instanceof Error ? err.message : "导出失败");
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="rounded-2xl border border-green-200 bg-green-50 p-5">
      <div className="mb-3 flex items-center gap-2">
        <span className="text-lg">🎉</span>
        <h3 className="font-semibold text-green-800">生成完成，请导出论文</h3>
      </div>
      <button
        type="button"
        onClick={() => setTemplateModalOpen(true)}
        disabled={exporting}
        className="mb-3 w-full rounded-xl bg-black py-2.5 text-center text-sm font-semibold text-white transition hover:bg-neutral-700 disabled:opacity-50"
      >
        {exporting ? "导出中…" : "导出论文（选择排版格式）"}
      </button>
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

      <TemplateManagerModal
        open={templateModalOpen}
        onClose={() => setTemplateModalOpen(false)}
        selectMode
        onSelectTemplate={(id) => void handleExport(id)}
      />
    </div>
  );
}
