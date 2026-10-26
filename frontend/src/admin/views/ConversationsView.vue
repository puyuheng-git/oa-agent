<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { errorMessage, http } from '@/shared/http'
import { formatTime } from '@/shared/format'
import { can } from '../auth'
import { ROLE_LABELS, buildTimeline, type ThreadDetail } from '../conversations'
import { NO_DATA, formatDuration, formatSummary, statusLabel, statusType } from '../runs'

interface ThreadItem {
  thread_id: string
  oa: string
  channel: string
  first_at: string
  last_at: string
  message_count: number
  first_message: string
}

const route = useRoute()
const router = useRouter()

const rows = ref<ThreadItem[]>([])
const total = ref(0)
const loading = ref(false)
const filters = reactive({ oa: '', keyword: '', page: 1 })
const range = ref<[Date, Date] | null>(null)

function rangeParams() {
  return range.value ? { start: range.value[0].toISOString(), end: range.value[1].toISOString() } : {}
}

async function load() {
  loading.value = true
  try {
    const data = await http.get<{ items: ThreadItem[]; total: number }>('/v1/admin/conversations', {
      ...filters,
      ...rangeParams(),
      page_size: 20,
    })
    rows.value = data.items
    total.value = data.total
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    loading.value = false
  }
}

function search() {
  filters.page = 1
  load()
}

const detail = ref<ThreadDetail | null>(null)
const detailOpen = ref(false)
const timeline = computed(() => (detail.value ? buildTimeline(detail.value) : []))

async function openThread(threadId: string) {
  detailOpen.value = true
  detail.value = null
  try {
    detail.value = await http.get<ThreadDetail>(`/v1/admin/conversations/${threadId}`)
  } catch (e) {
    detailOpen.value = false
    ElMessage.error(errorMessage(e))
  }
}

function closeThread() {
  if (route.query.thread) router.replace({ query: { ...route.query, thread: undefined } })
}

watch(
  () => route.query.thread,
  (t) => {
    if (typeof t === 'string' && t) openThread(t)
  },
  { immediate: true },
)

const exporting = ref(false)

async function exportJsonl() {
  if (!range.value) {
    ElMessage.warning('请先选择导出的时间范围（最长 92 天）')
    return
  }
  exporting.value = true
  try {
    const qs = new URLSearchParams({ ...rangeParams(), ...(filters.oa ? { oa: filters.oa } : {}) } as Record<string, string>)
    const resp = await fetch(`/v1/admin/conversations/export?${qs}`, { credentials: 'same-origin' })
    if (!resp.ok) {
      const body = await resp.json().catch(() => null)
      throw new Error(body?.error?.message ?? `导出失败（HTTP ${resp.status}）`)
    }
    const blob = await resp.blob()
    const name = /filename="([^"]+)"/.exec(resp.headers.get('Content-Disposition') ?? '')?.[1] ?? 'conversations.jsonl'
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = name
    a.click()
    URL.revokeObjectURL(a.href)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    exporting.value = false
  }
}

onMounted(load)
</script>

<template>
  <el-card>
    <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 12px"
      title="此处为员工对话原文（含业务与个人信息，仅密钥类已打码）。查看与导出都会记入审计。" />
    <el-form inline @submit.prevent="search">
      <el-form-item label="员工 OA"><el-input v-model="filters.oa" clearable style="width: 140px" /></el-form-item>
      <el-form-item label="关键词"><el-input v-model="filters.keyword" clearable placeholder="对话内容" style="width: 180px" /></el-form-item>
      <el-form-item label="时间">
        <el-date-picker v-model="range" type="datetimerange" start-placeholder="开始" end-placeholder="结束" />
      </el-form-item>
      <el-button type="primary" native-type="submit">查询</el-button>
      <el-button v-if="can('ops.conversation.export')" :loading="exporting" @click="exportJsonl">导出 JSONL（训练用）</el-button>
    </el-form>

    <el-table v-loading="loading" :data="rows" :empty-text="NO_DATA" @row-click="(r: ThreadItem) => openThread(r.thread_id)">
      <el-table-column label="最近消息" width="180"><template #default="{ row }">{{ formatTime(row.last_at) }}</template></el-table-column>
      <el-table-column prop="oa" label="员工" width="120" />
      <el-table-column prop="channel" label="渠道" width="80" />
      <el-table-column prop="first_message" label="首条提问" min-width="260" show-overflow-tooltip />
      <el-table-column prop="message_count" label="消息数" width="80" />
      <el-table-column label="会话" min-width="200" prop="thread_id" show-overflow-tooltip />
    </el-table>
    <el-pagination v-model:current-page="filters.page" :total="total" :page-size="20" layout="total, prev, pager, next"
      style="margin-top: 12px" @current-change="load" />
  </el-card>

  <el-drawer v-model="detailOpen" size="60%" :title="detail ? `完整对话 · ${detail.oa} · ${detail.thread_id}` : '完整对话'"
    @closed="closeThread">
    <el-skeleton v-if="!detail" :rows="8" />
    <div v-else class="conv">
      <template v-for="item in timeline" :key="item.key">
        <div v-if="item.kind === 'message'" :class="['msg', item.message.role]">
          <div class="msg-head">
            <b>{{ item.message.role === 'user' ? `员工 ${detail.oa}` : '助手' }}</b>
            <span class="meta">{{ formatTime(item.message.created_at) }}</span>
            <el-link type="primary" class="meta" @click="router.push(`/runs/${item.message.run_id}`)">{{ item.message.run_id }}</el-link>
            <el-tag v-if="item.message.role === 'user' && detail.run_status[item.message.run_id]" size="small"
              :type="statusType(detail.run_status[item.message.run_id])">
              {{ statusLabel(detail.run_status[item.message.run_id]) }}
            </el-tag>
            <el-tag v-if="item.message.error_code" size="small" type="danger">{{ item.message.error_code }}</el-tag>
          </div>
          <div class="msg-body">{{ item.message.content || '（空）' }}</div>
          <el-collapse v-if="item.message.data" class="sub">
            <el-collapse-item title="结构化数据（员工页面表格的原始数据）">
              <pre>{{ formatSummary(item.message.data) }}</pre>
            </el-collapse-item>
          </el-collapse>
        </div>
        <div v-else class="model">
          <el-collapse>
            <el-collapse-item>
              <template #title>
                <span>模型调用 · {{ item.call.provider }} / {{ item.call.model }}</span>
                <el-tag size="small" :type="item.call.status === 'ok' ? 'success' : 'danger'" style="margin-left: 8px">{{ item.call.status }}</el-tag>
                <span class="meta">{{ formatDuration(item.call.duration_ms) }}</span>
              </template>
              <div v-for="(m, i) in item.call.messages" :key="i" class="model-part">
                <div class="label">{{ ROLE_LABELS[m.role] ?? m.role }}</div>
                <pre>{{ m.content }}</pre>
              </div>
              <div class="model-part">
                <div class="label">模型输出</div>
                <pre>{{ item.call.output_text ?? '（无）' }}</pre>
              </div>
              <div v-if="item.call.error_summary" class="model-part">
                <div class="label">错误</div>
                <pre>{{ item.call.error_summary }}</pre>
              </div>
              <div class="model-part">
                <div class="label">Token</div>
                <pre>{{ item.call.usage ? formatSummary(item.call.usage) : NO_DATA }}</pre>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.conv {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.msg {
  max-width: 85%;
  border-radius: 6px;
  padding: 8px 12px;
}
.msg.user {
  align-self: flex-end;
  background: rgba(34, 211, 238, 0.08);
}
.msg.assistant {
  align-self: flex-start;
  background: rgba(52, 211, 153, 0.08);
}
.msg-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.msg-body {
  white-space: pre-wrap;
  word-break: break-all;
}
.meta {
  color: var(--tech-text-2);
  font-size: 12px;
  margin-left: 8px;
}
.model {
  align-self: stretch;
  border: 1px dashed var(--el-border-color);
  border-radius: 6px;
  padding: 0 12px;
}
.model-part .label {
  color: var(--tech-text-2);
  font-size: 12px;
  margin-top: 6px;
}
pre {
  margin: 2px 0;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 12px;
  background: var(--tech-code-bg);
  padding: 6px;
}
.sub {
  margin-top: 6px;
}
</style>
