import { http } from '@/shared/http'
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

/** 从事件 metadata 取单个字符串展示字段；缺失或非标量则「暂无数据」。 */
export function metadataDisplayField(
  metadata: Record<string, unknown> | null | undefined,
  key: string,
): string {
  if (!metadata) return NO_DATA
  const v = metadata[key]
  if (v == null || v === '') return NO_DATA
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  return NO_DATA
}

export interface RoutingEventMetadataDisplay {
  connectorId: string
}

/** 调用过程页：connector_id（仅读 metadata，不编造）。 */
export function routingEventMetadataDisplay(
  metadata: Record<string, unknown> | null | undefined,
): RoutingEventMetadataDisplay {
  return {
    connectorId: metadataDisplayField(metadata, 'connector_id'),
  }
}

export { rangeParams }

export const ROUTING_BASE = '/v1/admin/routing'
export const TOOLS_PATH = '/tools'
export const ORPHANS_API = '/v1/admin/tools/orphans'

/** 迁移草稿时写入的契约默认，与后端 apply_contract_routing 一致。 */
export const CONTRACT_MODE = 'deterministic_first'
export const CONTRACT_FALLBACK = 'skill_then_tool'

const ROUTING_MODE_LABELS: Record<string, string> = {
  legacy_prompt: '提示词海选（兼容/待迁移）',
  skill_then_tool: '先选 Skill 再选 Tool',
  retrieve_then_tool: '检索召回再精选',
  meta_search: '元工具渐进披露',
  deterministic_first: '确定性优先',
  router_then_fill: '小路由大填参',
}

export interface ConfigTruthWorkflow {
  workflow_id: string
  release_id: string
  tool_routing_mode: string
  matches_global: boolean
}

export interface LegacyPromptRelease {
  workflow_id: string
  release_id: string
  version_no: number
  tool_routing_mode: string
  matches_global: boolean
}

export interface ConfigTruth {
  global_mode: string
  global_fallback: string
  active_workflows: ConfigTruthWorkflow[]
  legacy_prompt_releases: LegacyPromptRelease[]
  note: string
}

export interface DraftVersionView {
  version_id: string
  version_no: number
  status: string
  content: Record<string, unknown>
  content_hash: string
}

export interface MigrateContractResult {
  draft_version: DraftVersionView
  next_step: string
}

export interface AckKeepLegacyResult {
  release_id: string
  acked: boolean
}

export interface OrphanToolItem {
  name: string
  kind: string
  enabled: boolean
}

export interface ContractDiffLine {
  key: string
  label: string
  before: string
  after: string
}

/** 路由模式中文名；空值用「暂无数据」，未知值原样展示。 */
export function routingModeLabel(mode: string | null | undefined): string {
  if (mode == null || String(mode).trim() === '') return NO_DATA
  const raw = String(mode).trim()
  const label = ROUTING_MODE_LABELS[raw]
  return label ? `${label}（${raw}）` : raw
}

/**
 * 迁移确认用的前后对照。
 * 真相接口只带回当前 tool_routing_mode；回退与澄清的变更前记为暂无数据，不编造。
 */
export function contractMigrateDiff(currentMode: string | null | undefined): ContractDiffLine[] {
  const mode = typeof currentMode === 'string' ? currentMode.trim() : ''
  return [
    { key: 'tool_routing_mode', label: '路由模式', before: mode || NO_DATA, after: CONTRACT_MODE },
    { key: 'deterministic_fallback_mode', label: '未命中回退', before: NO_DATA, after: CONTRACT_FALLBACK },
    { key: 'routing_clarify_on_low_confidence', label: '低置信澄清', before: NO_DATA, after: 'true' },
  ]
}

/** 与后端 ConfirmReasonIn 一致：2～200 字。不合规则返回提示，否则 null。 */
export function auditReasonError(reason: string): string | null {
  const text = reason.trim()
  if (text.length < 2 || text.length > 200) return '原因需为 2～200 个字'
  return null
}

export function fetchConfigTruth(includeAcked = false): Promise<ConfigTruth> {
  const params: Record<string, string> = {}
  if (includeAcked) params.include_acked = 'true'
  return http.get<ConfigTruth>(`${ROUTING_BASE}/config-truth`, params)
}

export function migrateContract(releaseId: string, reason: string): Promise<MigrateContractResult> {
  return http.post<MigrateContractResult>(
    `${ROUTING_BASE}/releases/${encodeURIComponent(releaseId)}/migrate-contract`,
    { confirm: true, reason },
  )
}

export function ackKeepLegacy(releaseId: string, reason: string): Promise<AckKeepLegacyResult> {
  return http.post<AckKeepLegacyResult>(
    `${ROUTING_BASE}/releases/${encodeURIComponent(releaseId)}/ack-keep-legacy`,
    { confirm: true, reason },
  )
}

export function fetchOrphanTools(): Promise<{ items: OrphanToolItem[] }> {
  return http.get<{ items: OrphanToolItem[] }>(ORPHANS_API)
}
