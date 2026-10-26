/**
 * Agent 任务适配层：真实后端未就绪时使用 Mock，并显式标记 mock: true。
 * 接入真实 Agent 后，将 RealAgentAdapter 接到 SSE / REST，Mock 仅保留给本地演示开关。
 */

import type { AgentTask, ApprovalItem, ArtifactFile, ToolCallEvent } from '../types'

export interface AgentEventHandlers {
  onTask?: (task: AgentTask | null) => void
  onError?: (message: string) => void
}

export interface AgentAdapter {
  /** 数据来源标识，UI 用来展示「演示」角标 */
  readonly source: 'mock' | 'live'
  startFromUserMessage(message: string): void
  stop(): void
  approve(id: string): Promise<ApprovalItem>
  reject(id: string, reason?: string): Promise<ApprovalItem>
  listArtifacts(): ArtifactFile[]
  dispose(): void
}

/** 演示任务：含工具/文件步骤。真实对话默认不含，有工具/产物时再由 UI 分区展示。 */
const MOCK_STEPS = [
  { id: 'understand', title: '理解需求' },
  { id: 'plan', title: '制定计划' },
  { id: 'tools', title: '调用工具' },
  { id: 'files', title: '处理文件' },
  { id: 'check', title: '检查结果' },
  { id: 'deliver', title: '交付文件' },
] as const

const LIVE_STEPS = [
  { id: 'understand', title: '理解需求' },
  { id: 'plan', title: '制定计划' },
  { id: 'check', title: '检查结果' },
] as const

function emptyTask(name: string, mock: boolean): AgentTask {
  const now = Date.now()
  const base = mock ? MOCK_STEPS : LIVE_STEPS
  return {
    id: `task_${now}`,
    name,
    status: 'idle',
    progress: 0,
    createdAt: now,
    elapsedMs: 0,
    steps: base.map((s) => ({ ...s, status: 'pending' as const })),
    tools: [],
    artifacts: [],
    approvals: [],
    mock,
  }
}

/** 从真实 run_status 映射到 AgentStatus（无细粒度步骤时仅更新顶层状态） */
export function mapRunStatus(runStatus: string): AgentTask['status'] {
  switch (runStatus) {
    case 'queued':
      return 'queued'
    case 'running':
    case 'streaming':
      return 'running'
    case 'waiting_input':
      return 'waiting_input'
    case 'waiting_approval':
    case 'intervention':
      return 'waiting_approval'
    case 'succeeded':
    case 'completed':
      return 'completed'
    case 'failed':
      return 'failed'
    case 'cancelled':
      return 'cancelled'
    default:
      return 'running'
  }
}

/**
 * Mock 适配器：用定时推进演示步骤/工具/审批。
 * 结果带 mock: true，不得当作真实业务执行结果。
 */
export class MockAgentAdapter implements AgentAdapter {
  readonly source = 'mock' as const
  private timers: number[] = []
  private task: AgentTask | null = null
  private tickTimer: number | undefined
  private handlers: AgentEventHandlers

  constructor(handlers: AgentEventHandlers) {
    this.handlers = handlers
  }

  startFromUserMessage(message: string) {
    this.stop()
    const title = message.length > 28 ? `${message.slice(0, 28)}…` : message
    this.task = emptyTask(title || '未命名任务', true)
    this.task.status = 'queued'
    this.task.progress = 5
    this.emit()
    this.schedule(400, () => this.advanceToRunning())
    this.startElapsed()
  }

  /** 与真实流式回复同步：仅更新顶层状态，不伪造工具结果 */
  syncLiveStatus(status: AgentTask['status'], name?: string) {
    // 仅在无任务或从演示切到真实时新建；复用已有 live 任务以保留 createdAt/elapsedMs
    if (!this.task || this.task.mock) {
      this.task = emptyTask(name || '当前对话任务', false)
    } else if (name) {
      this.task.name = name
    }
    const startedAt = this.task.createdAt
    this.task.status = status
    if (status === 'running' || status === 'queued') {
      this.task.progress = Math.max(this.task.progress, 15)
      if (this.task.steps[0].status === 'pending') this.task.steps[0].status = 'running'
    }
    if (status === 'completed') {
      this.task.progress = 100
      this.task.steps = this.task.steps.map((s) =>
        s.status === 'pending' || s.status === 'running' ? { ...s, status: 'completed' } : s,
      )
    }
    if (status === 'failed' || status === 'cancelled') {
      const running = this.task.steps.find((s) => s.status === 'running')
      if (running) running.status = 'failed'
    }
    if (status === 'running' || status === 'queued') {
      this.startElapsed()
    } else {
      // 先结算时长再 emit，避免结束后显示 0ms
      this.task.elapsedMs = Math.max(this.task.elapsedMs, Date.now() - startedAt)
      this.clearElapsed(false)
    }
    this.emit()
  }

  stop() {
    this.timers.forEach((t) => window.clearTimeout(t))
    this.timers = []
    this.clearElapsed()
    if (this.task && (this.task.status === 'running' || this.task.status === 'queued')) {
      this.task.status = 'cancelled'
      this.task.steps = this.task.steps.map((s) =>
        s.status === 'running' ? { ...s, status: 'failed' } : s,
      )
      this.emit()
    }
  }

  async approve(id: string): Promise<ApprovalItem> {
    await delay(500)
    const item = this.findApproval(id)
    item.status = 'approved'
    if (this.task) {
      this.task.status = 'running'
      this.schedule(600, () => this.finishDelivery())
    }
    this.emit()
    return { ...item }
  }

  async reject(id: string): Promise<ApprovalItem> {
    await delay(500)
    const item = this.findApproval(id)
    item.status = 'rejected'
    if (this.task) this.task.status = 'cancelled'
    this.emit()
    return { ...item }
  }

  listArtifacts(): ArtifactFile[] {
    return this.task?.artifacts ?? []
  }

  dispose() {
    this.stop()
    this.task = null
    this.emit()
  }

  private findApproval(id: string): ApprovalItem {
    const item = this.task?.approvals.find((a) => a.id === id)
    if (!item) throw new Error('审批事项不存在或已处理')
    if (item.status !== 'pending') throw new Error('该审批已处理')
    return item
  }

  private advanceToRunning() {
    if (!this.task) return
    this.task.status = 'running'
    this.task.progress = 12
    this.setStep(0, 'running')
    this.emit()
    this.schedule(800, () => {
      this.setStep(0, 'completed')
      this.setStep(1, 'running')
      this.task!.progress = 28
      this.emit()
    })
    this.schedule(1600, () => {
      this.setStep(1, 'completed')
      this.setStep(2, 'running')
      this.task!.progress = 45
      this.pushTool({
        id: 'tool_1',
        name: 'oa.query_self_data',
        status: 'running',
        summary: '按员工身份查询本人业务数据（演示）',
      })
      this.emit()
    })
    this.schedule(2600, () => {
      this.updateTool('tool_1', {
        status: 'succeeded',
        durationMs: 920,
        summary: '返回结构化结果摘要（演示，非真实业务数据）',
      })
      this.setStep(2, 'completed')
      this.setStep(3, 'running')
      this.task!.progress = 62
      this.emit()
    })
    this.schedule(3400, () => {
      this.setStep(3, 'completed')
      this.setStep(4, 'running')
      this.task!.artifacts.push({
        id: 'art_1',
        name: '查询结果摘要.md',
        kind: 'markdown',
        sizeLabel: '2.1 KB',
        status: 'ready',
        previewable: true,
        previewNote: '演示预览：后端未提供文档转换服务时仅展示文本摘要。',
        downloadUrl: undefined,
      })
      this.task!.progress = 78
      this.emit()
    })
    this.schedule(4200, () => {
      this.setStep(4, 'completed')
      this.task!.status = 'waiting_approval'
      this.task!.progress = 88
      this.task!.approvals = [
        {
          id: 'appr_1',
          title: '确认导出本人查询结果',
          description: 'AI 请求将本次查询摘要标记为可下载文件。此操作为演示审批，不会写入真实业务系统。',
          risk: '演示风险提示：真实环境中敏感导出必须经独立审批 API，不能凭聊天文本“同意”自动执行。',
          status: 'pending',
        },
      ]
      this.emit()
    })
  }

  private finishDelivery() {
    if (!this.task) return
    this.setStep(5, 'completed')
    this.task.status = 'completed'
    this.task.progress = 100
    this.clearElapsed()
    this.emit()
  }

  private setStep(index: number, status: AgentTask['steps'][number]['status']) {
    if (!this.task) return
    const step = this.task.steps[index]
    if (!step) return
    step.status = status
    if (status === 'running') step.startedAt = Date.now()
    if (status === 'completed' || status === 'failed') step.finishedAt = Date.now()
  }

  private pushTool(ev: ToolCallEvent) {
    this.task?.tools.push(ev)
  }

  private updateTool(id: string, patch: Partial<ToolCallEvent>) {
    const t = this.task?.tools.find((x) => x.id === id)
    if (t) Object.assign(t, patch)
  }

  private schedule(ms: number, fn: () => void) {
    this.timers.push(window.setTimeout(fn, ms))
  }

  private startElapsed() {
    this.clearElapsed(false)
    const started = this.task?.createdAt ?? Date.now()
    const tick = () => {
      if (!this.task) return
      this.task.elapsedMs = Math.max(0, Date.now() - started)
      this.emit()
    }
    tick()
    this.tickTimer = window.setInterval(tick, 250)
  }

  private clearElapsed(finalize = true) {
    if (finalize && this.task) {
      this.task.elapsedMs = Math.max(0, Date.now() - this.task.createdAt)
    }
    if (this.tickTimer) window.clearInterval(this.tickTimer)
    this.tickTimer = undefined
  }

  private emit() {
    this.handlers.onTask?.(this.task ? structuredClone(this.task) : null)
  }
}

function delay(ms: number) {
  return new Promise((r) => setTimeout(r, ms))
}

/** 真实适配器占位：后续对接 Agent SSE（步骤/工具/文件/审批事件） */
export class LiveAgentAdapter implements AgentAdapter {
  readonly source = 'live' as const
  private task: AgentTask | null = null
  private handlers: AgentEventHandlers

  constructor(handlers: AgentEventHandlers) {
    this.handlers = handlers
  }

  startFromUserMessage(message: string) {
    this.task = emptyTask(message.slice(0, 28) || '当前任务', false)
    this.task.status = 'queued'
    this.emit()
  }

  syncFromRun(runStatus: string) {
    if (!this.task) this.task = emptyTask('当前任务', false)
    this.task.status = mapRunStatus(runStatus)
    this.emit()
  }

  stop() {
    if (this.task) {
      this.task.status = 'cancelled'
      this.emit()
    }
  }

  async approve(): Promise<ApprovalItem> {
    throw new Error('审批 API 尚未接入，请等待后端 /v1/chat/approvals 接口')
  }

  async reject(): Promise<ApprovalItem> {
    throw new Error('审批 API 尚未接入，请等待后端 /v1/chat/approvals 接口')
  }

  listArtifacts() {
    return this.task?.artifacts ?? []
  }

  dispose() {
    this.task = null
    this.emit()
  }

  private emit() {
    this.handlers.onTask?.(this.task ? structuredClone(this.task) : null)
  }
}
