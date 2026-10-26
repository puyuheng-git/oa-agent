<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errorMessage, http } from '@/shared/http'
import { formatTime } from '@/shared/format'
import { can } from '../auth'
import { TASK_STATUS } from '../ops'
import {
  EVENT_LABELS,
  NODE_LABELS,
  NO_DATA,
  describeEvent,
  formatDuration,
  formatSummary,
  statusLabel,
  statusType,
  type RunDetail,
  type RunEvent,
} from '../runs'

const route = useRoute()
const router = useRouter()
const runId = computed(() => String(route.params.runId))

const run = ref<RunDetail | null>(null)
const events = ref<RunEvent[]>([])
const hasMore = ref(false)
const loadError = ref('')
const loadingMore = ref(false)
const showCheckpoints = ref(false)

async function loadEvents(afterSeq = 0) {
  const data = await http.get<{ items: RunEvent[]; has_more: boolean }>(`/v1/admin/runs/${runId.value}/events`, {
    after_seq: afterSeq,
    limit: 200,
  })
  events.value = afterSeq ? [...events.value, ...data.items] : data.items
  hasMore.value = data.has_more
}

async function loadAll() {
  loadError.value = ''
  try {
    run.value = await http.get<RunDetail>(`/v1/admin/runs/${runId.value}`)
    await loadEvents()
  } catch (e) {
    loadError.value = errorMessage(e)
  }
}

onMounted(loadAll)
watch(runId, () => {
  run.value = null
  events.value = []
  loadAll()
})

const operating = ref(false)

async function operate(action: 'cancel' | 'retry') {
  const title = action === 'cancel' ? '取消运行' : '重试运行（以员工会话重新执行原消息，生成新运行）'
  let reason = ''
  try {
    reason = (
      await ElMessageBox.prompt('请填写原因（写入审计）', title, {
        inputValidator: (v: string) => (v && v.trim().length >= 2) || '至少 2 个字',
      })
    ).value.trim()
  } catch {
    return
  }
  operating.value = true
  try {
    const r = await http.post<{ run_status?: string; new_run_id?: string; new_run_status?: string }>(
      `/v1/admin/runs/${runId.value}/${action}`,
      { reason },
    )
    if (action === 'retry' && r.new_run_id) {
      ElMessage.success(`已重试，新运行状态：${statusLabel(r.new_run_status || '')}`)
      router.push(`/runs/${r.new_run_id}`)
    } else {
      ElMessage.success(`已提交，当前状态：${statusLabel(r.run_status || '')}`)
      await loadAll()
    }
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    operating.value = false
  }
}

async function more() {
  loadingMore.value = true
  try {
    await loadEvents(events.value[events.value.length - 1]?.seq ?? 0)
  } finally {
    loadingMore.value = false
  }
}

const shown = computed(() =>
  showCheckpoints.value ? events.value : events.value.filter((e) => !e.event_type.startsWith('checkpoint_')),
)

function isFailure(e: RunEvent): boolean {
  return e.status === 'error' || e.event_type === 'node_error' || !!e.error_code
}

function dotType(e: RunEvent): 'danger' | 'success' | 'primary' | 'info' {
  if (isFailure(e) || (e.event_type === 'run_end' && e.status !== 'succeeded')) return 'danger'
  if (e.event_type === 'run_end') return 'success'
  if (e.event_type.startsWith('checkpoint_')) return 'info'
  return 'primary'
}

function offsetMs(e: RunEvent): string {
  if (!run.value) return ''
  const ms = new Date(e.occurred_at).getTime() - new Date(run.value.started_at).getTime()
  return Number.isFinite(ms) ? `+${ms} ms` : ''
}

const userMessage = computed(() => {
  const start = events.value.find((e) => e.event_type === 'run_start')
  return start ? describeEvent(start).find((l) => l.label === '用户输入')?.text ?? '' : ''
})

function hasDetails(e: RunEvent): boolean {
  return !!(e.input_summary || e.output_summary || e.error_summary || e.metadata_json)
}
</script>

<template>
  <div>
    <el-page-header @back="router.back()" style="margin-bottom: 12px">
      <template #content>
        <span>运行详情 · {{ runId }}</span>
      </template>
      <template v-if="run && can('ops.run.operate')" #extra>
        <el-button v-if="run.can_cancel" type="warning" plain :loading="operating" @click="operate('cancel')">
          取消运行
        </el-button>
        <el-button v-if="run.can_retry" type="primary" plain :loading="operating" @click="operate('retry')">
          重试
        </el-button>
      </template>
    </el-page-header>

    <el-result v-if="loadError" icon="error" :title="loadError" />

    <template v-else-if="run">
      <el-alert
        v-if="run.error_code"
        type="error"
        show-icon
        :closable="false"
        :title="`${run.error_code}${run.failed_node ? ` · 失败节点 ${run.failed_node}` : ''}`"
        :description="run.error_summary || ''"
        style="margin-bottom: 12px"
      />
      <el-alert
        v-if="run.suspected_stuck"
        type="warning"
        show-icon
        :closable="false"
        title="疑似卡住：运行中超过阈值但尚未超时，巡检到超时会标记为 timed_out"
        style="margin-bottom: 12px"
      />

      <el-alert
        v-if="run.waiting_human"
        type="warning"
        show-icon
        :closable="false"
        title="该运行正在等待人工介入"
        style="margin-bottom: 12px"
      >
        <el-link v-if="can('ops.intervention.handle')" type="primary" @click="router.push('/interventions')">
          前往介入中心处理
        </el-link>
      </el-alert>

      <el-card shadow="never">
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="状态">
            <el-tag :type="statusType(run.run_status)">{{ statusLabel(run.run_status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="员工 OA">{{ run.oa }}</el-descriptions-item>
          <el-descriptions-item label="渠道">{{ run.channel }}</el-descriptions-item>
          <el-descriptions-item label="开始">{{ formatTime(run.started_at) }}</el-descriptions-item>
          <el-descriptions-item label="结束">{{ formatTime(run.ended_at) }}</el-descriptions-item>
          <el-descriptions-item label="耗时">{{ run.ended_at ? formatDuration(run.duration_ms) : '—' }}</el-descriptions-item>
          <el-descriptions-item label="Workflow">{{ run.workflow_id }} v{{ run.workflow_version }}</el-descriptions-item>
          <el-descriptions-item label="Agent">{{ run.agent_id }}</el-descriptions-item>
          <el-descriptions-item label="配置发布">{{ run.config_release_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="Tool / 模型调用">{{ run.tool_call_count }} / {{ run.model_call_count }}</el-descriptions-item>
          <el-descriptions-item label="业务">
            {{ run.business_type || '—' }}<template v-if="run.business_record_id"> #{{ run.business_record_id }}</template>
          </el-descriptions-item>
          <el-descriptions-item label="会话">
            <el-link type="primary" @click="router.push({ path: '/runs', query: { thread_id: run.thread_id } })">
              {{ run.thread_id }}（共 {{ run.thread_run_count }} 次运行）
            </el-link>
            <el-link v-if="can('ops.run.view_sensitive')" type="primary" style="margin-left: 12px"
              @click="router.push({ path: '/conversations', query: { thread: run.thread_id } })">
              查看完整对话
            </el-link>
          </el-descriptions-item>
          <el-descriptions-item label="用户输入" :span="3">
            <span v-if="userMessage">{{ userMessage }}</span>
            <span v-else class="muted">{{ NO_DATA }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="Token" :span="3">
            <template v-if="run.usage?.length">
              <div v-for="(u, i) in run.usage" :key="i">{{ u.provider }} / {{ u.model }}：{{ JSON.stringify(u.usage) }}</div>
            </template>
            <span v-else class="muted">{{ NO_DATA }}</span>
          </el-descriptions-item>
          <el-descriptions-item v-if="run.parent_run_id || run.child_runs.length" label="重试链路" :span="3">
            <template v-if="run.parent_run_id">
              重试自
              <el-link type="primary" @click="router.push(`/runs/${run.parent_run_id}`)">{{ run.parent_run_id }}</el-link>
            </template>
            <div v-for="c in run.child_runs" :key="c.run_id">
              重试为
              <el-link type="primary" @click="router.push(`/runs/${c.run_id}`)">{{ c.run_id }}</el-link>
              <el-tag size="small" :type="statusType(c.run_status)" style="margin-left: 6px">{{ statusLabel(c.run_status) }}</el-tag>
            </div>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card v-if="run.interventions.length" shadow="never" style="margin-top: 12px" header="人工介入任务">
        <el-table :data="run.interventions" size="small">
          <el-table-column label="任务" prop="task_id" min-width="200" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="TASK_STATUS[row.status]?.type">{{ TASK_STATUS[row.status]?.label || row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="原因" prop="reason" min-width="220" show-overflow-tooltip />
          <el-table-column label="创建" width="170">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="处理人 / 结果" width="180">
            <template #default="{ row }">{{ row.handled_by || '—' }}<template v-if="row.result"> · {{ row.result }}</template></template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never" style="margin-top: 12px">
        <template #header>
          <div class="tl-header">
            <span>事件时间线（{{ run.event_count }} 条）</span>
            <el-checkbox v-model="showCheckpoints">显示检查点事件</el-checkbox>
          </div>
        </template>
        <el-empty v-if="!events.length" :description="NO_DATA" />
        <el-timeline v-else>
          <el-timeline-item
            v-for="e in shown"
            :key="e.event_id"
            :type="dotType(e)"
            :timestamp="`#${e.seq} · ${formatTime(e.occurred_at)} · ${offsetMs(e)}`"
            placement="top"
          >
            <div :class="['ev', { fail: isFailure(e) }]">
              <b>{{ EVENT_LABELS[e.event_type] || e.event_type }}</b>
              <el-tag v-if="e.node_name" size="small" :type="isFailure(e) ? 'danger' : 'info'" style="margin-left: 6px">
                {{ NODE_LABELS[e.node_name] ? `${NODE_LABELS[e.node_name]}（${e.node_name}）` : e.node_name }}
              </el-tag>
              <span v-if="e.tool_name" class="meta">{{ e.tool_name }}<template v-if="e.tool_version"> v{{ e.tool_version }}</template></span>
              <span v-if="e.status" class="meta">{{ e.status }}</span>
              <span v-if="e.duration_ms !== null" class="meta">{{ formatDuration(e.duration_ms) }}</span>
              <span v-if="e.error_code" class="meta err">{{ e.error_code }}</span>
            </div>
            <div v-for="(line, i) in describeEvent(e)" :key="i" class="ev-line">
              <span class="ev-label">{{ line.label }}</span>
              <div :class="['ev-text', line.tone]">{{ line.text }}</div>
            </div>
            <el-collapse v-if="hasDetails(e)" class="ev-detail">
              <el-collapse-item title="原始记录（JSON）">
                <div v-if="e.error_summary"><b>错误：</b><pre>{{ e.error_summary }}</pre></div>
                <div v-if="e.input_summary"><b>输入：</b><pre>{{ formatSummary(e.input_summary) }}</pre></div>
                <div v-if="e.output_summary"><b>输出：</b><pre>{{ formatSummary(e.output_summary) }}</pre></div>
                <div v-if="e.metadata_json"><b>元数据：</b><pre>{{ formatSummary(e.metadata_json) }}</pre></div>
              </el-collapse-item>
            </el-collapse>
          </el-timeline-item>
        </el-timeline>
        <el-button v-if="hasMore" :loading="loadingMore" @click="more">加载更多</el-button>
        <el-text v-if="events.length < run.event_count && !hasMore" type="info" size="small">
          部分事件可能仍在写入或待补写
        </el-text>
      </el-card>
    </template>

    <el-skeleton v-else :rows="6" />
  </div>
</template>

<style scoped>
.tl-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.ev .meta {
  margin-left: 8px;
  color: var(--tech-text-2);
  font-size: 12px;
}
.ev .err {
  color: var(--tech-danger);
}
.ev.fail b {
  color: var(--tech-danger);
}
.ev-line {
  display: flex;
  gap: 8px;
  margin-top: 6px;
  font-size: 13px;
}
.ev-label {
  flex: 0 0 72px;
  color: var(--tech-text-2);
}
.ev-text {
  flex: 1;
  min-width: 0;
  white-space: pre-wrap;
  word-break: break-all;
}
.ev-text.user {
  background: rgba(34, 211, 238, 0.08);
  border-left: 3px solid var(--tech-cyan);
  padding: 4px 8px;
}
.ev-text.reply {
  background: rgba(52, 211, 153, 0.08);
  border-left: 3px solid var(--tech-success);
  padding: 4px 8px;
  max-height: 240px;
  overflow: auto;
}
.ev-text.code {
  font-family: Consolas, monospace;
  font-size: 12px;
  background: var(--tech-code-bg);
  padding: 4px 8px;
}
.ev-detail {
  margin-top: 4px;
}
.ev-detail pre {
  margin: 2px 0 6px;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 12px;
  background: var(--tech-code-bg);
  padding: 6px;
}
.muted {
  color: var(--tech-text-3);
}
</style>
