import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { DraftChartSpec } from "../api/paper";
import { buildInlineChartOption, hasRenderableChartSpec } from "./inlineChartOption";

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
]);

type Props = {
  spec: DraftChartSpec;
  title: string;
  onRenderFailure?: () => void;
};

/**
 * 正文动态渲染器。
 *
 * 该组件仅将持久化的 ChartSpec v2 转为浏览器侧 ECharts option；
 * ChartAsset 仍由后端保留给 DOCX、打印和旧稿兼容路径使用。
 */
export default function InlineChartRenderer({ spec, title, onRenderFailure }: Props) {
  const elementRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = elementRef.current;
    if (!element || !hasRenderableChartSpec(spec)) {
      onRenderFailure?.();
      return undefined;
    }

    let chart: echarts.ECharts | null = null;
    try {
      chart = echarts.init(element, undefined, { renderer: "canvas" });
      chart.setOption(buildInlineChartOption(spec), { notMerge: true, lazyUpdate: false });
    } catch {
      chart?.dispose();
      onRenderFailure?.();
      return undefined;
    }

    const observer = new ResizeObserver(() => chart?.resize());
    observer.observe(element);
    return () => {
      observer.disconnect();
      chart?.dispose();
    };
  }, [spec, onRenderFailure]);

  return (
    <div
      ref={elementRef}
      className="min-h-[320px] w-full"
      role="img"
      aria-label={`${title || "图表"}（动态交互图表）`}
      data-chart-renderer="echarts"
    />
  );
}
