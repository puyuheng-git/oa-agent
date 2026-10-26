<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { errorMessage, http } from '@/shared/http'
import { formatTime } from '@/shared/format'
import { NO_DATA, RUN_STATUS, formatDuration, statusLabel, statusType, type RunItem } from '../runs'

const route = useRoute()
const router = useRouter()

const FILTER_KEYS = ['status', 'oa', 'run_id', 'thread_id', 'error_code', 'failed_node', 'start', 'end'] as const
type FilterKey = (typeof FILTER_KEYS)[number]

const filters = reactive<Record<FilterKey, string> & { stuck_only: boolean; page: number }>({
  status: '',
  oa: '',
  run_id: '',
  thread_id: '',
  error_code: '',
  failed_node: '',
  start: '',
  end: '',
  stuck_only: false,
  page: 1,
})
const timeRange = ref<[Date, Date] | null>(null)
const rows = ref<RunItem[]>([])
const total = ref(0)
const loading = ref(false)
const PAGE_SIZE = 20

function fromQuery() {
  const q = route.query
  for (const k of FILTER_KEYS) filters[k] = typeof q[k] === 'string' ? (q[k] as string) : ''
  filters.stuck_only = q.stuck_only === 'true'
  filters.page = Number(q.page) || 1
  timeRange.value = filters.start && filters.end ? [new Date(filters.start), new Date(filters.end)] : null
}

async function load() {
  loading.value = true
  try {
    const data = await http.get<{ items: RunItem[]; total: number }>('/v1/admin/runs', {
      ...Object.fromEntries(FILTER_KEYS.map((k) => [k, filters[k]])),
      stuck_only: filters.stuck_only ? 'true' : '',
      page: filters.page,
      page_size: PAGE_SIZE,
    })
    rows.value = data.items
    total.value = data.total
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    loading.value = false
  }
}

function pushQuery() {
  const query: Record<string, string> = {}
  for (const k of FILTER_KEYS) if (filters[k]) query[k] = filters[k].trim()
  if (filters.stuck_only) query.stuck_only = 'true'
  if (filters.page > 1) query.page = String(filters.page)
  router.replace({ path: '/runs', query })
}

function search() {
  ;[filters.start, filters.end] = timeRange.value ? timeRange.value.map((d) => d.toISOString()) : ['', '']
  filters.page = 1
  pushQuery()
}

function reset() {
  router.replace({ path: '/runs' })
}

function onPage(p: number) {
  filters.page = p
  pushQuery()
}

watch(
  () => route.query,
  () => {
    if (route.path !== '/runs') return
    fromQuery()
    load()
  },
)

onMounted(() => {
  fromQuery()
  load()
})
</script>

<template>
  <el-card shadow="never">
    <el-form inline @submit.prevent="search">
      <el-form-item label="状态">
        <el-select v-model="filters.status" clearable style="width: 130px" placeholder="全部">
          <el-option v-for="(meta, s) in RUN_STATUS" :key="s" :label="meta.label" :value="s" />
        </el-select>
      </el-form-item>
      <el-form-item label="员工 OA"><el-input v-model="filters.oa" clearable style="width: 130px" /></el-form-item>
      <el-form-item label="run_id"><el-input v-model="filters.run_id" clearable style="width: 220px" /></el-form-item>
      <el-form-item label="thread_id"><el-input v-model="filters.thread_id" clearable style="width: 220px" /></el-form-item>
      <el-form-item label="错误码"><el-input v-model="filters.error_code" clearable style="width: 200px" /></el-form-item>
      <el-form-item label="失败节点"><el-input v-model="filters.failed_node" clearable style="width: 120px" /></el-form-item>
      <el-form-item label="开始时间">
        <el-date-picker v-model="timeRange" type="datetimerange" start-placeholder="起" end-placeholder="止" />
      </el-form-item>
      <el-form-item label="仅疑似卡住"><el-switch v-model="filters.stuck_only" /></el-form-item>
      <el-button type="primary" native-type="submit">查询</el-button>
      <el-button @click="reset">重置</el-button>
    </el-form>

    <el-table v-loading="loading" :data="rows" :empty-text="NO_DATA" @row-click="(row: RunItem) => router.push(`/runs/${row.run_id}`)" class="clickable">
      <el-table-column label="开始时间" width="170">
        <template #default="{ row }">{{ formatTime(row.started_at) }}</template>
      </el-table-column>
      <el-table-column label="run_id" min-width="230">
        <template #default="{ row }"><el-link type="primary">{{ row.run_id }}</el-link></template>
      </el-table-column>
      <el-table-column prop="oa" label="员工 OA" width="110" />
      <el-table-column label="Workflow" width="130">
        <template #default="{ row }">{{ row.workflow_id }} v{{ row.workflow_version }}</template>
      </el-table-column>
      <el-table-column label="状态" width="150">
        <template #default="{ row }">
          <el-tag :type="statusType(row.run_status)">{{ statusLabel(row.run_status) }}</el-tag>
          <el-tag v-if="row.suspected_stuck" type="warning" effect="dark" style="margin-left: 4px">疑似卡住</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="耗时" width="100">
        <template #default="{ row }">{{ row.ended_at ? formatDuration(row.duration_ms) : '—' }}</template>
      </el-table-column>
      <el-table-column label="Tool/模型" width="90">
        <template #default="{ row }">{{ row.tool_call_count }} / {{ row.model_call_count }}</template>
      </el-table-column>
      <el-table-column label="错误" min-width="200">
        <template #default="{ row }">
          <span v-if="row.error_code" class="err">{{ row.error_code }}<template v-if="row.failed_node"> @ {{ row.failed_node }}</template></span>
          <span v-else>—</span>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      :current-page="filters.page"
      :total="total"
      :page-size="PAGE_SIZE"
      layout="total, prev, pager, next"
      style="margin-top: 12px"
      @current-change="onPage"
    />
  </el-card>
</template>

<style scoped>
.clickable :deep(.el-table__row) {
  cursor: pointer;
}
.err {
  color: var(--tech-danger);
}
</style>
