/* AI-Researcher · 研启智链 — Research Overview Dashboard (Part 1) */

(function () {
  "use strict";

  /* ------------------------------------------------------------------
   * 研究证据覆盖趋势 — ECharts Line Chart（Part 1 §12）
   * 数据固定：T-5:48 T-4:55 T-3:61 T-2:67 T-1:69 当前:62
   * 折线 #165DFF · 3px · 数据点圆形 6px · 虚线网格 #E2E8F0
   * ------------------------------------------------------------------ */
  var SERIES = [
    { label: "T-5", value: 48 },
    { label: "T-4", value: 55 },
    { label: "T-3", value: 61 },
    { label: "T-2", value: 67 },
    { label: "T-1", value: 69 },
    { label: "当前", value: 62 },
  ];

  var chartEl = document.getElementById("coverage-chart");
  var chart = null;

  function buildOption(points) {
    return {
      grid: { left: 46, right: 18, top: 24, bottom: 28 },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#FFFFFF",
        borderColor: "#E5E7EB",
        borderWidth: 1,
        padding: [8, 12],
        textStyle: { color: "#334155", fontSize: 12 },
        axisPointer: { lineStyle: { color: "#CBD5E1" } },
        formatter: function (params) {
          var item = params && params[0];
          if (!item) return "";
          return item.axisValueLabel + "　证据覆盖 <b>" + item.value + "%</b>";
        },
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: points.map(function (p) { return p.label; }),
        axisLine: { lineStyle: { color: "#E2E8F0" } },
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
        axisLabel: {
          color: "#94A3B8",
          fontSize: 12,
          formatter: "{value}%",
        },
        splitLine: {
          lineStyle: { type: "dashed", color: "#E2E8F0" },
        },
      },
      series: [
        {
          type: "line",
          data: points.map(function (p) { return p.value; }),
          smooth: false,
          symbol: "circle",
          symbolSize: 6,
          lineStyle: { color: "#165DFF", width: 3 },
          itemStyle: { color: "#165DFF", borderColor: "#FFFFFF", borderWidth: 2 },
          emphasis: { itemStyle: { color: "#165DFF" } },
        },
      ],
    };
  }

  function renderChart() {
    if (!chartEl || typeof echarts === "undefined") return;
    if (!chart) chart = echarts.init(chartEl);
    chart.setOption(buildOption(SERIES), true);
  }

  function bindPeriodSelect() {
    var select = document.getElementById("period-select");
    if (!select) return;
    select.addEventListener("change", function () {
      var span = parseInt(select.value, 10);
      var points = SERIES.slice(Math.max(0, SERIES.length - span));
      if (chart) chart.setOption(buildOption(points), true);
    });
  }

  function handleResize() {
    if (chart) chart.resize();
  }

  renderChart();
  bindPeriodSelect();
  window.addEventListener("resize", handleResize);
})();
