import type { Reply } from './api'

/** Agent 运行状态（与后端约定对齐，前端统一展示） */
export type AgentStatus =
  | 'idle'
  | 'queued'
  | 'running'
  | 'waiting_input'
  | 'waiting_approval'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type StepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'

export type ToolCallStatus = 'pending' | 'running' | 'succeeded' | 'failed'

export type ArtifactKind = 'pdf' | 'docx' | 'xlsx' | 'csv' | 'markdown' | 'image' | 'generic'

export type ArtifactStatus = 'generating' | 'ready' | 'failed'

export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'error'

/** 对话内任务交付摘要（真实结果或明确标记的演示） */
export interface DeliveryHighlight {
  label: string
  value: string
}

export interface DeliverySummary {
  title: string
  highlights: DeliveryHighlight[]
  /** true = 演示数据，非真实业务结果 */
  mock: boolean
  artifacts?: ArtifactFile[]
  /** 是否可展开查看结构化表格/详情 */
  hasStructuredData: boolean
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  reply?: Reply
  runId?: string
  streaming?: boolean
  createdAt: number
  attachments?: PendingAttachment[]
  delivery?: DeliverySummary
}

export interface PendingAttachment {
  id: string
  name: string
  size: number
  mime: string
  /** 仅本地预览，未上传服务端 */
  file?: File
  previewUrl?: string
}

export interface LocalConversation {
  /** 后端 thread_id */
  id: string
  /** 后端 title；空表示新会话 */
  title: string | null
  updatedAt: number
  messages: ChatMessage[]
  lastChannel?: string | null
}

export interface TaskStep {
  id: string
  title: string
  status: StepStatus
  detail?: string
  startedAt?: number
  finishedAt?: number
}

export interface ToolCallEvent {
  id: string
  name: string
  status: ToolCallStatus
  durationMs?: number
  summary?: string
}

export interface ArtifactFile {
  id: string
  name: string
  kind: ArtifactKind
  sizeLabel: string
  status: ArtifactStatus
  /** Mock / 真实下载地址；空表示不可下载 */
  downloadUrl?: string
  previewable: boolean
  previewNote?: string
}

export interface ApprovalItem {
  id: string
  title: string
  description: string
  risk: string
  status: ApprovalStatus
}

export interface AgentTask {
  id: string
  name: string
  status: AgentStatus
  progress: number
  createdAt: number
  /** 已执行毫秒数（展示用） */
  elapsedMs: number
  steps: TaskStep[]
  tools: ToolCallEvent[]
  artifacts: ArtifactFile[]
  approvals: ApprovalItem[]
  /** true = 演示数据，非真实 Agent 执行结果 */
  mock: boolean
}

export type NavKey =
  | 'conversations'
  | 'workspace'
  | 'tasks'
  | 'documents'
  | 'knowledge'
  | 'tools'
  | 'approvals'
  | 'settings'
