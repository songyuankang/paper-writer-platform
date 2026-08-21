import type { EChartsCoreOption } from "echarts/core";
import type { DraftChartSpec } from "../api/paper";

export type ChartSpecAppearance = {
  x_axis_title?: string;
  y_axis_title?: string;
  y_axis_right_title?: string;
  show_legend?: boolean;
  color_palette?: string[];
};

const DEFAULT_COLORS = ["#2f5597", "#70ad47", "#ed7d31", "#a5a5a5", "#8064a2", "#00a6a6"];

function appearanceOf(spec: DraftChartSpec): ChartSpecAppearance {
  return ((spec as DraftChartSpec & { appearance?: ChartSpecAppearance }).appearance || {});
}

function numberValues(values: number[] | undefined): number[] {
  return (values || []).map((value) => Number(value)).map((value) => Number.isFinite(value) ? value : 0);
}

export function hasRenderableChartSpec(spec?: DraftChartSpec): spec is DraftChartSpec {
  if (!spec) return false;
  const data = spec.data || spec;
  if (spec.kind === "pie") {
    return Boolean(data.pie?.some((item) => item.name && Number.isFinite(Number(item.value))));
  }
  return Boolean(
    data.categories?.length
    && data.series?.some((series) => series.values?.some((value) => Number.isFinite(Number(value)))),
  );
}

/**
 * 将既有 ChartSpec v2 映射到 ECharts option。
 * 该函数不持久化 ECharts option；ChartSpec 始终是唯一业务数据格式。
 */
export function buildInlineChartOption(spec: DraftChartSpec): EChartsCoreOption {
  const data = spec.data || spec;
  const appearance = appearanceOf(spec);
  const colors = appearance.color_palette?.length ? appearance.color_palette : DEFAULT_COLORS;
  const title = spec.title || "图表";

  if (spec.kind === "pie") {
    return {
      color: colors,
      animationDuration: 300,
      tooltip: { trigger: "item", valueFormatter: (value: string | number) => String(value) },
      legend: { show: appearance.show_legend ?? true, bottom: 4, type: "scroll" },
      series: [{
        name: title,
        type: "pie",
        radius: ["34%", "68%"],
        center: ["50%", "47%"],
        avoidLabelOverlap: true,
        label: { formatter: "{b}: {d}%" },
        data: (data.pie || []).map((item) => ({ name: item.name, value: Number(item.value) || 0 })),
      }],
    } as EChartsCoreOption;
  }

  const categories = (data.categories || []).map((item) => String(item));
  const series = data.series || [];
  const hasRightAxis = series.some((item) => item.axis === "right");
  const yAxis = hasRightAxis
    ? [
        { type: "value", name: appearance.y_axis_title || "", axisLabel: { color: "#64748b" }, splitLine: { lineStyle: { color: "#e5e7eb" } } },
        { type: "value", name: appearance.y_axis_right_title || "", axisLabel: { color: "#64748b" }, splitLine: { show: false } },
      ]
    : { type: "value", name: appearance.y_axis_title || "", axisLabel: { color: "#64748b" }, splitLine: { lineStyle: { color: "#e5e7eb" } } };

  return {
    color: colors,
    animationDuration: 300,
    animationEasing: "cubicOut",
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { show: appearance.show_legend ?? series.length > 1, bottom: 2, type: "scroll" },
    grid: { top: 28, right: hasRightAxis ? 56 : 28, bottom: 54, left: 54, containLabel: true },
    xAxis: {
      type: "category",
      name: appearance.x_axis_title || "",
      data: categories,
      axisLabel: { color: "#64748b", interval: 0, rotate: categories.some((value) => value.length > 10) ? 24 : 0 },
      axisLine: { lineStyle: { color: "#cbd5e1" } },
    },
    yAxis,
    series: series.map((item, index) => {
      const useLine = spec.kind === "line" || (spec.kind === "mixed" && index > 0);
      return {
        name: item.name || `系列 ${index + 1}`,
        type: useLine ? "line" : "bar",
        yAxisIndex: hasRightAxis && item.axis === "right" ? 1 : 0,
        data: numberValues(item.values),
        smooth: useLine,
        symbol: useLine ? "circle" : undefined,
        symbolSize: useLine ? 6 : undefined,
        barMaxWidth: useLine ? undefined : 46,
        emphasis: { focus: "series" },
      };
    }),
  } as EChartsCoreOption;
}
