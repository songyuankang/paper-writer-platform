import type { FullPaperPipelineState } from "../api/paper";

export interface VisualizationPlanStatusView {
  text: string;
  tone: "success" | "warning" | "neutral";
  title: string;
}

/**
 * Convert durable VisualizationPlan summary data into a user-facing body-editor
 * status.  The function intentionally never treats total_items as ready-to-insert
 * candidates: only generated plan items are genuinely ready.
 */
export function visualizationPlanStatus(
  pipeline: FullPaperPipelineState | undefined,
  pipelineRunning: boolean,
): VisualizationPlanStatusView | null {
  const insertions = pipeline?.visualization_insertions || [];
  if (insertions.length) {
    return {
      text: `已插入 ${insertions.map((item) => item.label).join("、")}`,
      tone: "success",
      title: insertions.map((item) => `${item.label} ${item.title}`).join("；"),
    };
  }

  const plan = pipeline?.visualization_plan;
  if (!plan) return null;
  const notices = plan.notices || [];
  const ready = plan.ready_candidate_count || 0;
  const broken = plan.broken_count || 0;
  const planned = plan.planned_count || 0;
  const generated = plan.generated_count || 0;
  const total = plan.total_items || 0;
  const reasonSummary = plan.items_summary?.map((item) => item.reason).filter(Boolean).join("；") || notices.join("；");

  if (ready > 0) return { text: `已找到 ${ready} 个可插入研究图表`, tone: "success", title: reasonSummary };
  if (broken > 0) return { text: `有 ${broken} 个研究图表生成失败，可查看原因`, tone: "warning", title: reasonSummary };
  if (pipelineRunning && plan.status === "preparing") return { text: "正在准备全文研究资料与证据", tone: "neutral", title: reasonSummary };
  if (total > 0 && planned + generated > 0) return { text: `已规划 ${total} 个研究图表，正在准备`, tone: "success", title: reasonSummary };
  const datasetNotice = notices.find((notice) => notice.includes("实验图已跳过"));
  if (datasetNotice) return { text: datasetNotice, tone: "neutral", title: reasonSummary };
  return { text: "当前章节暂未规划研究图表", tone: "neutral", title: reasonSummary };
}
