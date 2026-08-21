import { describe, expect, it } from "vitest";
import { visualizationPlanStatus } from "./visualizationPlanStatus";

describe("visualizationPlanStatus", () => {
  it("uses a preparing message before a final plan exists", () => {
    expect(visualizationPlanStatus({ visualization_plan: { status: "preparing" } }, true)?.text)
      .toBe("正在准备全文研究资料与证据");
  });

  it("does not describe planned items as ready candidates", () => {
    expect(visualizationPlanStatus({ visualization_plan: { status: "planned", total_items: 3, planned_count: 3 } }, true)?.text)
      .toBe("已规划 3 个研究图表，正在准备");
  });

  it("shows an actionable ready count only after candidates are generated", () => {
    expect(visualizationPlanStatus({ visualization_plan: { status: "running", total_items: 4, generated_count: 2, ready_candidate_count: 2 } }, true)?.text)
      .toBe("已找到 2 个可插入研究图表");
  });

  it("explains an omitted experiment chart when no research dataset exists", () => {
    expect(visualizationPlanStatus({ visualization_plan: { status: "completed", notices: ["实验图已跳过：尚未添加研究数据。"] } }, false)?.text)
      .toBe("实验图已跳过：尚未添加研究数据。");
  });
});
