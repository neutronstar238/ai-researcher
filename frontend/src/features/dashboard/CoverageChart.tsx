import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef } from "react";
import type { RunRecord } from "../../lib/api/types";
import { coveragePercent } from "../../lib/domain/selectors";

interface CoveragePoint {
  coverage: number;
  label: string;
  runId: string;
}

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

function runTime(run: RunRecord): number {
  const value = Date.parse(run.finished_at ?? run.started_at ?? run.created_at);
  return Number.isNaN(value) ? 0 : value;
}

function realCoveragePoints(runs: RunRecord[]): CoveragePoint[] {
  return runs
    .flatMap((run) => {
      const coverage = coveragePercent(run.stages ?? []);
      return coverage === null ? [] : [{ coverage, label: run.direction, runId: run.run_id, time: runTime(run) }];
    })
    .sort((left, right) => left.time - right.time || left.runId.localeCompare(right.runId))
    .slice(-6)
    .map(({ coverage, label, runId }) => ({ coverage, label, runId }));
}

export function CoverageChart({ runs }: { runs: RunRecord[] }) {
  const chartElement = useRef<HTMLDivElement>(null);
  const points = useMemo(() => realCoveragePoints(runs), [runs]);
  const pointSignature = JSON.stringify(points);

  useEffect(() => {
    if (points.length < 2 || !chartElement.current) return;

    const chart = echarts.init(chartElement.current);
    chart.setOption({
      animation: false,
      grid: { bottom: 34, left: 44, right: 18, top: 20 },
      tooltip: { trigger: "axis", valueFormatter: (value: unknown) => `${String(value)}%` },
      xAxis: {
        type: "category",
        data: points.map((point) => point.label),
        axisLabel: { color: "#667085", formatter: (label: string) => label.length > 8 ? `${label.slice(0, 8)}…` : label },
      },
      yAxis: { type: "value", min: 0, max: 100, axisLabel: { formatter: "{value}%", color: "#667085" } },
      series: [{
        data: points.map((point) => point.coverage),
        type: "line",
        smooth: true,
        symbolSize: 7,
        lineStyle: { color: "#165dff", width: 2 },
        itemStyle: { color: "#165dff" },
      }],
    });

    const observer = typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(() => {
          try {
            chart.resize();
          } catch {
            // A detached chart can receive one final queued resize notification.
          }
        });
    observer?.observe(chartElement.current);

    return () => {
      observer?.disconnect();
      chart.dispose();
    };
  }, [pointSignature]);

  return (
    <section className="dashboard-card dashboard-secondary-card coverage-card" aria-labelledby="coverage-heading">
      <h2 id="coverage-heading">研究证据覆盖趋势</h2>
      {points.length < 2 ? (
        <p className="chart-empty">积累至少两个运行后显示趋势</p>
      ) : (
        <>
          <div className="coverage-chart" ref={chartElement} aria-hidden="true" />
          <table className="sr-only" aria-label="研究证据覆盖趋势数据">
            <thead><tr><th>运行</th><th>覆盖率</th></tr></thead>
            <tbody>
              {points.map((point) => (
                <tr key={point.runId}><th scope="row">{point.label}</th><td>{point.coverage}%</td></tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
