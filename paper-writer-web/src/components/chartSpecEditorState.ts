import type { DraftChartSpec } from "../api/paper";

export const EDITABLE_CHART_KINDS = ["bar", "line", "pie", "scatter"] as const;
export type EditableChartKind = typeof EDITABLE_CHART_KINDS[number];

export type EditableChartAppearance = {
  x_label?: string;
  y_label?: string;
  legend?: boolean;
};

export type EditableChartSpec = DraftChartSpec & {
  id?: string;
  kind: EditableChartKind;
  appearance?: EditableChartAppearance;
  provenance?: Record<string, unknown>;
};

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function label(value: unknown, name: string): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${name}不能为空`);
  return value.trim();
}

/** Validate ChartSpec business data before it reaches the protected backend API. */
export function validateEditableChartSpec(raw: unknown): EditableChartSpec {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("ChartSpec 必须是 JSON 对象");
  const spec = raw as Record<string, unknown>;
  if (spec.schema_version !== 2) throw new Error("仅支持 schema_version 为 2 的 ChartSpec");
  if (!EDITABLE_CHART_KINDS.includes(spec.kind as EditableChartKind)) throw new Error("图表类型仅支持 bar、line、pie 或 scatter");
  const title = label(spec.title, "图表标题");
  if (typeof spec.caption !== "string") throw new Error("图注必须是文本");
  if (!spec.data || typeof spec.data !== "object" || Array.isArray(spec.data)) throw new Error("chart_spec.data 必须是对象");
  const data = spec.data as Record<string, unknown>;

  if (spec.kind === "pie") {
    if (!Array.isArray(data.pie) || data.pie.length < 1 || data.pie.length > 80) throw new Error("饼图需要 1 至 80 个数据项");
    const pie = data.pie.map((item, index) => {
      if (!item || typeof item !== "object") throw new Error(`第 ${index + 1} 个饼图数据项无效`);
      const value = item as Record<string, unknown>;
      if (!isFiniteNumber(value.value)) throw new Error(`第 ${index + 1} 个饼图数值必须是有限数值`);
      return { name: label(value.name, `第 ${index + 1} 个类别`), value: value.value };
    });
    return {
      ...(spec as unknown as EditableChartSpec),
      schema_version: 2,
      kind: "pie",
      title,
      caption: spec.caption,
      data: {
        categories: pie.map((item) => item.name),
        series: [{ name: "数值", values: pie.map((item) => item.value), axis: "left" }],
        pie,
      },
    };
  }

  if (!Array.isArray(data.categories) || data.categories.length < 1 || data.categories.length > 80) throw new Error("类别必须为 1 至 80 项数组");
  if (!Array.isArray(data.series) || data.series.length < 1 || data.series.length > 8) throw new Error("系列必须为 1 至 8 项数组");
  const categories = data.categories.map((item, index) => label(item, `第 ${index + 1} 个类别`));
  const series = data.series.map((item, index) => {
    if (!item || typeof item !== "object") throw new Error(`第 ${index + 1} 个系列无效`);
    const value = item as Record<string, unknown>;
    if (!Array.isArray(value.values) || value.values.length !== categories.length) throw new Error(`第 ${index + 1} 个系列的数值数量必须与类别数量一致`);
    if (value.axis !== "left" && value.axis !== "right") throw new Error(`第 ${index + 1} 个系列坐标轴必须为 left 或 right`);
    return {
      name: label(value.name, `第 ${index + 1} 个系列名称`),
      values: value.values.map((number, valueIndex) => {
        if (!isFiniteNumber(number)) throw new Error(`第 ${index + 1} 个系列第 ${valueIndex + 1} 个数值必须是有限数值`);
        return number;
      }),
      axis: value.axis as "left" | "right",
    };
  });
  return {
    ...(spec as unknown as EditableChartSpec),
    schema_version: 2,
    kind: spec.kind as EditableChartKind,
    title,
    caption: spec.caption,
    data: { categories, series },
  };
}

export function editableSpec(block: { chart_spec?: DraftChartSpec; title?: string; caption?: string }): EditableChartSpec {
  const source = block.chart_spec || {
    schema_version: 2,
    kind: "bar",
    title: block.title || "图表",
    caption: block.caption || "",
    data: { categories: ["类别 A", "类别 B"], series: [{ name: "数值", values: [0, 0], axis: "left" }] },
  };
  return JSON.parse(JSON.stringify(source)) as EditableChartSpec;
}
