import { rangeParams } from './runs'

export const NO_DATA = '暂无数据'

export interface RoutingRunItem {
  run_id: string
  oa: string
  started_at: string | null
  run_status: string
  mode: string | null
  action: string | null
  skill: string | null
  tool: string | null
  fallback_from: string | null
  clarified: boolean
  routing_duration_ms: number | null
  stages_summary: string
  tool_ok: number | null
  tool_fail: number | null
}

export interface RoutingEvent {
  event_id: string
  seq: number
  event_type: string
  occurred_at: string
  duration_ms: number | null
  status: string | null
  tool_name: string | null
  metadata: Record<string, unknown> | null
}

export interface RoutingStats {
  empty: boolean
  runs_by_mode: { mode: string; count: number }[]
  mode_share: { mode: string; count: number; share: number | null }[]
  tool_calls: { total: number; ok: number; fail: number; success_rate: number | null }
  clarify_rate: number | null
  fallback_rate: number | null
  avg_routing_ms: number | null
  avg_tool_ms: number | null
  p95_routing_ms: number | null
  p95_tool_ms: number | null
  p95_routing_label: string | null
  p95_tool_label: string | null
  top_tools: { name: string; count: number }[]
  top_skills: { name: string; count: number }[]
  misselect: string
  decision_runs?: number
  trace_note: string | null
  generated_at?: string
}

export function formatRate(v: number | null | undefined): string {
  if (v == null) return NO_DATA
  return `${(v * 100).toFixed(1)}%`
}

export function formatMs(v: number | null | undefined, fallbackLabel?: string | null): string {
  if (v == null) return fallbackLabel || NO_DATA
  if (v < 1000) return `${v} ms`
  return `${(v / 1000).toFixed(2)} s`
}

export { rangeParams }
