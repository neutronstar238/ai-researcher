import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

import type { CoveragePoint } from "../../features/dashboard/api";

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

export function EvidenceCoverageChart({ data }: { data: CoveragePoint[] }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption({
      grid: { left: 40, right: 16, top: 20, bottom: 24 },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#fff",
        borderColor: "#E5E7EB",
        textStyle: { color: "#334155", fontSize: 12 },
        formatter: (params: unknown) => {
          const item = (params as { dataIndex: number }[])?.find((p) => p !== null);
          const idx = item ? (item as { dataIndex: number }).dataIndex : 0;
          const point = data[idx];
          return point ? `${point.label}　证据覆盖 <b>${point.coverage}%</b>` : "";
        },
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: data.map((p) => p.label),
        axisLine: { lineStyle: { color: "#E5E7EB" } },
        axisTick: { show: false },
        axisLabel: { color: "#94A3B8", fontSize: 12 },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 100,
        interval: 25,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: "#94A3B8", fontSize: 12, formatter: "{value}%" },
        splitLine: { lineStyle: { type: "dashed", color: "#E5E7EB" } },
      },
      series: [
        {
          type: "line",
          data: data.map((p) => p.coverage),
          smooth: false,
          symbol: "circle",
          symbolSize: 7,
          lineStyle: { color: "#165DFF", width: 2 },
          itemStyle: { color: "#165DFF", borderColor: "#fff", borderWidth: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(22,93,255,0.16)" },
              { offset: 1, color: "rgba(22,93,255,0)" },
            ]),
          },
        },
      ],
    });

    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [data]);

  return <div ref={ref} style={{ width: "100%", height: 180 }} />;
}
