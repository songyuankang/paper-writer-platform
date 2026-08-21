import { describe, expect, it } from "vitest";
import type { DraftChartSpec } from "../api/paper";
import { buildInlineChartOption, hasRenderableChartSpec } from "./inlineChartOption";

type InspectableOption = {
  series?: Array<{ type?: string; yAxisIndex?: number; data?: unknown[] }>;
  xAxis?: { data?: string[] };
  legend?: { show?: boolean };
};

describe("正文 ChartSpec 动态渲染", () => {
  it("将既有柱状 ChartSpec 映射为 ECharts 柱状系列并保留双轴信息", () => {
    const spec: DraftChartSpec = {
      schema_version: 2,
      kind: "bar",
      title: "算法性能比较",
      caption: "来源：实验数据集。",
      data: {
        categories: ["YOLOv5", "YOLOv8"],
        series: [
          { name: "准确率", values: [92.1, 95.3], axis: "left" },
          { name: "推理时间", values: [18, 12], axis: "right" },
        ],
      },
    };

    expect(hasRenderableChartSpec(spec)).toBe(true);
    const option = buildInlineChartOption(spec) as InspectableOption;
    expect(option.xAxis?.data).toEqual(["YOLOv5", "YOLOv8"]);
    expect(option.series?.map((item) => item.type)).toEqual(["bar", "bar"]);
    expect(option.series?.[1]?.yAxisIndex).toBe(1);
    expect(option.legend?.show).toBe(true);
  });

  it("将饼图 ChartSpec 映射为 ECharts 饼图并保留原始名称和值", () => {
    const spec: DraftChartSpec = {
      schema_version: 2,
      kind: "pie",
      title: "研究方法分布",
      caption: "",
      data: {
        categories: [],
        series: [],
        pie: [
          { name: "蒸馏", value: 4 },
          { name: "剪枝", value: 3 },
        ],
      },
    };

    expect(hasRenderableChartSpec(spec)).toBe(true);
    const option = buildInlineChartOption(spec) as InspectableOption;
    expect(option.series?.[0]?.type).toBe("pie");
    expect(option.series?.[0]?.data).toEqual([
      { name: "蒸馏", value: 4 },
      { name: "剪枝", value: 3 },
    ]);
  });

  it("对没有可绘制 ChartSpec 的旧 FigureBlock 返回 false，以便继续显示 SVG/PNG ChartAsset", () => {
    expect(hasRenderableChartSpec(undefined)).toBe(false);
    expect(hasRenderableChartSpec({
      schema_version: 2,
      kind: "line",
      title: "旧图",
      caption: "",
      data: { categories: [], series: [] },
    })).toBe(false);
  });
});
