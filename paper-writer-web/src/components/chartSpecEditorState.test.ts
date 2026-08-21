import { describe, expect, it } from "vitest";
import { validateEditableChartSpec } from "./chartSpecEditorState";

const base = {
  id: "chart_example",
  schema_version: 2,
  kind: "bar",
  title: "模型准确率比较",
  caption: "正文内编辑示例。",
  binding: { dataset_id: "ds_1", dataset_version: 1, source_table_id: "table_1" },
  provenance: { status: "verified" },
  appearance: { legend: true, x_label: "模型", y_label: "准确率" },
  data: {
    categories: ["YOLOv5", "YOLOv8"],
    series: [{ name: "准确率", values: [92.1, 96], axis: "left" }],
  },
};

describe("正文 ChartSpec 编辑校验", () => {
  it("保留结构化业务数据并接受编辑后的散点图", () => {
    const result = validateEditableChartSpec({ ...base, kind: "scatter" });
    expect(result.kind).toBe("scatter");
    expect(result.data?.series[0].values).toEqual([92.1, 96]);
    expect(result.binding?.source_table_id).toBe("table_1");
  });

  it("拒绝字符串数值，避免将表格文本误写为图表业务数据", () => {
    const invalid = structuredClone(base);
    invalid.data.series[0].values[1] = "96" as unknown as number;
    expect(() => validateEditableChartSpec(invalid)).toThrow("有限数值");
  });

  it("拒绝不支持的图表类型", () => {
    expect(() => validateEditableChartSpec({ ...base, kind: "radar" })).toThrow("图表类型");
  });
});
