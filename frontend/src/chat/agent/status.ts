import type { AgentStatus, StepStatus, ToolCallStatus } from '../types'

export interface StatusMeta {
  label: string
  color: string
  bg: string
}

const AGENT: Record<AgentStatus, StatusMeta> = {
  idle: { label: '空闲', color: '#8492A6', bg: '#F5F8FC' },
  queued: { label: '排队中', color: '#0075C7', bg: '#EAF5FF' },
  running: { label: '执行中', color: '#008AE7', bg: '#EAF5FF' },
  waiting_input: { label: '等待补充信息', color: '#F79009', bg: '#FFFAEB' },
  waiting_approval: { label: '等待审批', color: '#F79009', bg: '#FFFAEB' },
  completed: { label: '已完成', color: '#12B76A', bg: '#ECFDF3' },
  failed: { label: '执行失败', color: '#F04438', bg: '#FEF3F2' },
  cancelled: { label: '已取消', color: '#8492A6', bg: '#F5F8FC' },
}

const STEP: Record<StepStatus, StatusMeta> = {
  pending: { label: '待执行', color: '#8492A6', bg: '#F5F8FC' },
  running: { label: '执行中', color: '#008AE7', bg: '#EAF5FF' },
  completed: { label: '已完成', color: '#12B76A', bg: '#ECFDF3' },
  failed: { label: '失败', color: '#F04438', bg: '#FEF3F2' },
  skipped: { label: '已跳过', color: '#8492A6', bg: '#F5F8FC' },
}

const TOOL: Record<ToolCallStatus, StatusMeta> = {
  pending: { label: '等待', color: '#8492A6', bg: '#F5F8FC' },
  running: { label: '调用中', color: '#008AE7', bg: '#EAF5FF' },
  succeeded: { label: '成功', color: '#12B76A', bg: '#ECFDF3' },
  failed: { label: '失败', color: '#F04438', bg: '#FEF3F2' },
}

export function agentStatusMeta(s: AgentStatus): StatusMeta {
  return AGENT[s]
}

export function stepStatusMeta(s: StepStatus): StatusMeta {
  return STEP[s]
}

export function toolStatusMeta(s: ToolCallStatus): StatusMeta {
  return TOOL[s]
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`
  const sec = Math.floor(ms / 1000)
  if (sec < 60) return `${sec} 秒`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m} 分 ${s} 秒`
}

export function formatTime(ts: number): string {
  return new Date(ts).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}
