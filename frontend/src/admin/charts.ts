import type { EChartsCoreOption } from 'echarts/core'
import { RUN_STATUS, type RunStats } from './runs'

export const CHART_COLORS = {
  cyan: '#22d3ee',
  violet: '#6366f1',
  blue: '#3b82f6',
  success: '#34d399',
  warning: '#fbbf24',
  danger: '#f43f5e',
  info: '#64748b',
  text: '#94a3b8',
  grid: 'rgba(100, 140, 200, 0.12)',
}

/** 主页 HUD 冷色调色板：与核心青 / 靛蓝统一，异常用品红、紫区分 */
export const HUD_COLORS = {
  cyan: '#22d3ee',
  sky: '#38bdf8',
  indigo: '#818cf8',
  violet: '#a78bfa',
  magenta: '#f472b6',
  slate: '#64748b',
}

export const STATUS_HUE: Record<string, string> = {
  succeeded: HUD_COLORS.cyan,
  running: HUD_COLORS.sky,
  queued: HUD_COLORS.slate,
  waiting_confirmation: HUD_COLORS.indigo,
  waiting_human: HUD_COLORS.indigo,
  cancel_requested: HUD_COLORS.violet,
  failed: HUD_COLORS.magenta,
  timed_out: HUD_COLORS.violet,
  cancelled: HUD_COLORS.slate,
  expired: HUD_COLORS.slate,
}

const TOOLTIP = {
  backgroundColor: 'rgba(10, 18, 34, 0.95)',
  borderColor: 'rgba(34, 211, 238, 0.4)',
  textStyle: { color: '#e2e8f0', fontSize: 12 },
  extraCssText: 'box-shadow: 0 0 16px rgba(34,211,238,0.25); backdrop-filter: blur(6px);',
}

const linear = (from: string, to: string) => ({
  type: 'linear',
  x: 0,
  y: 0,
  x2: 0,
  y2: 1,
  colorStops: [
    { offset: 0, color: from },
    { offset: 1, color: to },
  ],
})

/** 按天趋势：成功 / 失败 / 超时堆叠柱 + 运行总数面积线。无数据返回 null。 */
export function trendOption(stats: RunStats): EChartsCoreOption | null {
  if (!stats.daily.length) return null
  const bar = (name: string, key: 'succeeded' | 'failed' | 'timed_out', color: string) => ({
    name,
    type: 'bar',
    stack: 'status',
    barMaxWidth: 16,
    itemStyle: { color: linear(`${color}99`, `${color}0d`), borderColor: `${color}cc`, borderWidth: 1, borderRadius: [2, 2, 0, 0] },
    data: stats.daily.map((d) => d[key]),
  })
  const points = stats.daily.map((d) => [d.date.slice(5), d.total])
  const last = points[points.length - 1]
  const effects: Record<string, unknown>[] = [
    {
      name: '最新',
      type: 'effectScatter',
      silent: true,
      z: 5,
      symbolSize: 8,
      rippleEffect: { brushType: 'stroke', scale: 4, period: 3 },
      itemStyle: { color: CHART_COLORS.cyan, shadowBlur: 10, shadowColor: CHART_COLORS.cyan },
      tooltip: { show: false },
      data: [last],
    },
  ]
  if (points.length > 1) {
    effects.push({
      name: '流光',
      type: 'lines',
      coordinateSystem: 'cartesian2d',
      polyline: true,
      silent: true,
      z: 4,
      lineStyle: { opacity: 0 },
      effect: { show: true, period: 3.5, trailLength: 0.35, symbol: 'circle', symbolSize: 5, color: '#cffafe' },
      data: [{ coords: points }],
    })
  }
  return {
    tooltip: { ...TOOLTIP, trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(34,211,238,0.06)' } } },
    legend: {
      top: 0,
      right: 0,
      data: ['成功', '失败', '超时', '运行总数'],
      textStyle: { color: CHART_COLORS.text, fontSize: 11 },
      itemWidth: 10,
      itemHeight: 6,
    },
    grid: { left: 8, right: 12, top: 36, bottom: 4, containLabel: true },
    xAxis: {
      type: 'category',
      data: stats.daily.map((d) => d.date.slice(5)),
      axisLine: { lineStyle: { color: CHART_COLORS.grid } },
      axisTick: { show: false },
      axisLabel: { color: CHART_COLORS.text, fontFamily: 'Consolas, monospace' },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: CHART_COLORS.grid, type: 'dashed' } },
      axisLabel: { color: CHART_COLORS.text, fontFamily: 'Consolas, monospace' },
    },
    series: [
      bar('成功', 'succeeded', STATUS_HUE.succeeded),
      bar('失败', 'failed', STATUS_HUE.failed),
      bar('超时', 'timed_out', STATUS_HUE.timed_out),
      {
        name: '运行总数',
        type: 'line',
        smooth: false,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { width: 1.5, color: 'rgba(207,250,254,0.85)', shadowBlur: 8, shadowColor: CHART_COLORS.cyan },
        itemStyle: { color: '#cffafe', borderColor: CHART_COLORS.cyan, borderWidth: 1 },
        areaStyle: { color: linear('rgba(34,211,238,0.16)', 'rgba(34,211,238,0)') },
        data: stats.daily.map((d) => d.total),
      },
      ...effects,
    ],
  }
}

export interface StatusRing {
  id: string
  label: string
  value: number
  ratio: number
  color: string
}

/** 状态同心弧：只含数量 > 0 的状态，按数量降序；全部为 0 返回空数组。 */
export function statusRings(stats: RunStats): StatusRing[] {
  const items = Object.entries(RUN_STATUS)
    .map(([id, meta]) => ({ id, label: meta.label, value: stats.by_status[id] ?? 0, color: STATUS_HUE[id] ?? HUD_COLORS.slate }))
    .filter((d) => d.value > 0)
  const total = items.reduce((s, d) => s + d.value, 0)
  return items.sort((a, b) => b.value - a.value).map((d) => ({ ...d, ratio: d.value / total }))
}

/** 仪表刻度：240° 范围（-120°..120°，0° 为正上方、顺时针），按成功率点亮。 */
export function gaugeTicks(rate: number | null, count: number): { angle: number; on: boolean }[] {
  const lit = rate === null || rate === undefined ? 0 : Math.round(rate * count)
  return Array.from({ length: count }, (_, i) => ({ angle: -120 + (240 * i) / (count - 1), on: i < lit }))
}

/** SVG 圆弧路径：角度以正上方为 0°、顺时针。 */
export function arcPath(cx: number, cy: number, r: number, start: number, sweep: number): string {
  const pt = (deg: number) => {
    const a = (deg * Math.PI) / 180
    return `${(cx + r * Math.sin(a)).toFixed(2)} ${(cy - r * Math.cos(a)).toFixed(2)}`
  }
  const s = Math.min(sweep, 359.99)
  return `M ${pt(start)} A ${r} ${r} 0 ${s > 180 ? 1 : 0} 1 ${pt(start + s)}`
}