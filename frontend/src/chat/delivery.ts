import type { Reply } from './api'
import type { AgentTask, DeliverySummary } from './types'

/** 从真实 Reply 结构化数据生成交付摘要；无数据时返回 null。 */
export function deliveryFromReply(reply: Reply | undefined): DeliverySummary | null {
  if (!reply?.data) return null
  if (reply.data.kind === 'table') {
    const n = reply.data.total ?? reply.data.items.length
    return {
      title: reply.data.title || '查询结果已就绪',
      highlights: [
        { label: '记录数', value: `已查询 ${n} 条` },
        { label: '工具', value: reply.data.tool || '—' },
        ...(reply.chain?.length ? [{ label: '调用链', value: reply.chain.join(' → ') }] : []),
      ],
      mock: false,
      hasStructuredData: true,
    }
  }
  if (reply.data.kind === 'record') {
    return {
      title: reply.data.title || '详情已就绪',
      highlights: [
        { label: '结果', value: '已获取 1 条详情' },
        { label: '工具', value: reply.data.tool || '—' },
      ],
      mock: false,
      hasStructuredData: true,
    }
  }
  return null
}

/** 演示模式：从 Mock 任务生成交付摘要，必须带 mock: true。 */
export function deliveryFromMockTask(task: AgentTask | null): DeliverySummary | null {
  if (!task?.mock) return null
  if (task.status !== 'completed' && task.status !== 'waiting_approval') return null
  const toolOk = task.tools.filter((t) => t.status === 'succeeded').length
  const highlights = [
    { label: '步骤', value: `已完成 ${task.steps.filter((s) => s.status === 'completed').length} / ${task.steps.length}` },
    { label: '工具', value: toolOk ? `成功调用 ${toolOk} 个工具` : '暂无成功工具调用' },
  ]
  if (task.artifacts.length) {
    highlights.push({ label: '文件', value: `已生成 ${task.artifacts.length} 个文件` })
  }
  if (task.approvals.some((a) => a.status === 'pending')) {
    highlights.push({ label: '审批', value: '有待核实事项，请在右侧处理' })
  }
  return {
    title: '任务交付摘要（演示）',
    highlights,
    mock: true,
    artifacts: task.artifacts.filter((a) => a.status === 'ready'),
    hasStructuredData: false,
  }
}

/** 合并真实与演示：优先真实结构化结果；演示仅在无真实数据时补充。 */
export function buildDelivery(reply: Reply | undefined, task: AgentTask | null): DeliverySummary | null {
  const real = deliveryFromReply(reply)
  if (real) {
    if (task?.mock && task.artifacts.length) {
      return { ...real, artifacts: [...(real.artifacts ?? []), ...task.artifacts.filter((a) => a.status === 'ready')] }
    }
    return real
  }
  return deliveryFromMockTask(task)
}
