<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { errorMessage, http } from '@/shared/http'
import { formatTime } from '@/shared/format'
import {
  NO_DATA,
  formatMs,
  formatRate,
  rangeParams,
  type RoutingEvent,
  type RoutingRunItem,
  type RoutingStats,
} from '../routing'

const route = useRoute()
const router = useRouter()
const activeTab = ref('process')

const FILTER_KEYS = ['run_id', 'oa', 'routing_mode', 'tool', 'skill', 'start', 'end'] as const
type FilterKey = (typeof FILTER_KEYS)[number]

const filters = reactive<Record<FilterKey, string> & {
  clarified: string
  fallback: string
  page: number
}>({
  run_id: '',
  oa: '',
  routing_mode: '',
  tool: '',
  skill: '',
  start: '',
  end: '',
  clarified: '',
  fallback: '',
  page: 1,
})
const timeRange = ref<[Date, Date] | null>(null)
const rows = ref<RoutingRunItem[]>([])
const total = ref(0)
const loading = ref(false)
const PAGE_SIZE = 20

const drawer = ref(false)
const detailLoading = ref(false)
const detail = ref<{
  run: { run_id: string; oa: string; started_at: string; run_status: string; thread_id: string }
  routing_events: RoutingEvent[]
  tool_call_events: RoutingEvent[]
  connector_events: RoutingEvent[]
  connector_status: string
  empty_routing: boolean
} | null>(null)

const statsLoading = ref(false)
const stats = ref<RoutingStats | null>(null)
const statsRange = ref<'24h' | '7d' | '30d'>('24h')

function fromQuery() {
  const q = route.query
  for (const k of FILTER_KEYS) filters[k] = typeof q[k] === 'string' ? (q[k] as string) : ''
  filters.clarified = typeof q.clarified === 'string' ? q.clarified : ''
  filters.fallback = typeof q.fallback === 'string' ? q.fallback : ''
  filters.page = Number(q.page) || 1
  timeRange.value = filters.start && filters.end ? [new Date(filters.start), new Date(filters.end)] : null
  if (q.tab === 'stats') activeTab.value = 'stats'
}

async function loadList() {
  loading.value = true
  try {
    const params: Record<string, string | number | null | undefined> = {
      page: filters.page,
      page_size: PAGE_SIZE,
    }
    for (const k of FILTER_KEYS) if (filters[k]) params[k] = filters[k].trim()
    if (filters.clarified === 'true' || filters.clarified === 'false') params.clarified = filters.clarified
    if (filters.fallback === 'true' || filters.fallback === 'false') params.fallback = filters.fallback
    const data = await http.get<{ items: RoutingRunItem[]; total: number }>('/v1/admin/routing/runs', params)
    rows.value = data.items
    total.value = data.total
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    loading.value = false
  }
}

async function openDetail(row: RoutingRunItem) {
  drawer.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await http.get(`/v1/admin/routing/runs/${row.run_id}`)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    detailLoading.value = false
  }
}

async function loadStats() {
  statsLoading.value = true
  try {
    stats.value = await http.get<RoutingStats>('/v1/admin/routing/stats', rangeParams(statsRange.value))
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    statsLoading.value = false
  }
}

function pushQuery() {
  const query: Record<string, string> = {}
  for (const k of FILTER_KEYS) if (filters[k]) query[k] = filters[k].trim()
  if (filters.clarified) query.clarified = filters.clarified
  if (filters.fallback) query.fallback = filters.fallback
  if (filters.page > 1) query.page = String(filters.page)
  if (activeTab.value === 'stats') query.tab = 'stats'
  router.replace({ path: '/routing', query })
}

function search() {
  ;[filters.start, filters.end] = timeRange.value ? timeRange.value.map((d) => d.toISOString()) : ['', '']
  filters.page = 1
  pushQuery()
}

function reset() {
  router.replace({ path: '/routing' })
}

function onPage(p: number) {
  filters.page = p
  pushQuery()
}

watch(
  () => route.query,
  () => {
    if (route.path !== '/routing') return
    fromQuery()
    if (activeTab.value === 'stats') loadStats()
    else loadList()
  },
)

watch(activeTab, (tab) => {
  if (tab === 'stats') loadStats()
  else loadList()
  pushQuery()
})

onMounted(() => {
  fromQuery()
  if (activeTab.value === 'stats') loadStats()
  else loadList()
})
</script>

<template>
  <el-card shadow="never">
    <el-tabs v-model="activeTab">
      <el-tab-pane label="过程明细" name="process">
        <el-form inline @submit.prevent="search">
          <el-form-item label="run_id"><el-input v-model="filters.run_id" clearable style="width: 220px" /></el-form-item>
          <el-form-item label="员工 OA"><el-input v-model="filters.oa" clearable style="width: 120px" /></el-form-item>
          <el-form-item label="路由模式"><el-input v-model="filters.routing_mode" clearable style="width: 160px" placeholder="如 legacy_prompt" /></el-form-item>
          <el-form-item label="Tool"><el-input v-model="filters.tool" clearable style="width: 180px" /></el-form-item>
          <el-form-item label="Skill"><el-input v-model="filters.skill" clearable style="width: 140px" /></el-form-item>
          <el-form-item label="澄清">
            <el-select v-model="filters.clarified" clearable style="width: 100px" placeholder="全部">
              <el-option label="是" value="true" /><el-option label="否" value="false" />
            </el-select>
          </el-form-item>
          <el-form-item label="fallback">
            <el-select v-model="filters.fallback" clearable style="width: 100px" placeholder="全部">
              <el-option label="是" value="true" /><el-option label="否" value="false" />
            </el-select>
          </el-form-item>
          <el-form-item label="时间">
            <el-date-picker v-model="timeRange" type="datetimerange" start-placeholder="起" end-placeholder="止" />
          </el-form-item>
          <el-button type="primary" native-type="submit">查询</el-button>
          <el-button @click="reset">重置</el-button>
        </el-form>

        <el-table v-loading="loading" :data="rows" :empty-text="NO_DATA" class="clickable" @row-click="openDetail">
          <el-table-column label="时间" width="170">
            <template #default="{ row }">{{ formatTime(row.started_at) }}</template>
          </el-table-column>
          <el-table-column label="run_id" min-width="220">
            <template #default="{ row }">
              <el-link type="primary" @click.stop="router.push(`/runs/${row.run_id}`)">{{ row.run_id }}</el-link>
            </template>
          </el-table-column>
          <el-table-column prop="oa" label="OA" width="100" />
          <el-table-column prop="mode" label="模式" width="140">
            <template #default="{ row }">{{ row.mode || '—' }}</template>
          </el-table-column>
          <el-table-column label="阶段" min-width="160">
            <template #default="{ row }">{{ row.stages_summary || '—' }}</template>
          </el-table-column>
          <el-table-column label="Skill/Tool" min-width="200">
            <template #default="{ row }">{{ row.skill || '—' }} / {{ row.tool || '—' }}</template>
          </el-table-column>
          <el-table-column prop="action" label="action" width="90" />
          <el-table-column label="耗时" width="90">
            <template #default="{ row }">{{ formatMs(row.routing_duration_ms) }}</template>
          </el-table-column>
          <el-table-column label="Tool 成败" width="100">
            <template #default="{ row }">{{ row.tool_ok ?? 0 }} / {{ row.tool_fail ?? 0 }}</template>
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
      </el-tab-pane>

      <el-tab-pane label="统计详情" name="stats">
        <div style="margin-bottom: 12px">
          <el-radio-group v-model="statsRange" @change="loadStats">
            <el-radio-button value="24h">近 24 小时</el-radio-button>
            <el-radio-button value="7d">近 7 天</el-radio-button>
            <el-radio-button value="30d">近 30 天</el-radio-button>
          </el-radio-group>
        </div>
        <div v-loading="statsLoading">
          <el-alert v-if="stats?.trace_note" type="info" :closable="false" :title="stats.trace_note" style="margin-bottom: 12px" />
          <template v-if="!stats || stats.empty">
            <el-empty :description="NO_DATA" />
          </template>
          <template v-else>
            <el-row :gutter="16">
              <el-col :span="8">
                <el-statistic title="路由决策运行数" :value="stats.decision_runs ?? 0" />
              </el-col>
              <el-col :span="8">
                <el-statistic title="澄清率" :value="formatRate(stats.clarify_rate)" />
              </el-col>
              <el-col :span="8">
                <el-statistic title="fallback 率" :value="formatRate(stats.fallback_rate)" />
              </el-col>
            </el-row>
            <el-row :gutter="16" style="margin-top: 16px">
              <el-col :span="8">
                <el-statistic title="Tool 调用成功率" :value="formatRate(stats.tool_calls.success_rate)" />
                <div class="muted">合计 {{ stats.tool_calls.total }}（成功 {{ stats.tool_calls.ok }} / 失败 {{ stats.tool_calls.fail }}）</div>
              </el-col>
              <el-col :span="8">
                <el-statistic title="平均路由耗时" :value="formatMs(stats.avg_routing_ms)" />
                <div class="muted">P95：{{ formatMs(stats.p95_routing_ms, stats.p95_routing_label) }}</div>
              </el-col>
              <el-col :span="8">
                <el-statistic title="平均 Tool 耗时" :value="formatMs(stats.avg_tool_ms)" />
                <div class="muted">P95：{{ formatMs(stats.p95_tool_ms, stats.p95_tool_label) }}</div>
              </el-col>
            </el-row>

            <h4 style="margin-top: 24px">按模式</h4>
            <el-table :data="stats.runs_by_mode" :empty-text="NO_DATA" size="small">
              <el-table-column prop="mode" label="模式" />
              <el-table-column prop="count" label="运行数" width="120" />
              <el-table-column label="占比" width="120">
                <template #default="{ row }">
                  {{ formatRate(stats.mode_share.find((m) => m.mode === row.mode)?.share ?? null) }}
                </template>
              </el-table-column>
            </el-table>

            <el-row :gutter="16" style="margin-top: 16px">
              <el-col :span="12">
                <h4>Top Tool</h4>
                <el-table :data="stats.top_tools" :empty-text="NO_DATA" size="small">
                  <el-table-column prop="name" label="Tool" />
                  <el-table-column prop="count" label="次数" width="80" />
                </el-table>
              </el-col>
              <el-col :span="12">
                <h4>Top Skill</h4>
                <el-table :data="stats.top_skills" :empty-text="NO_DATA" size="small">
                  <el-table-column prop="name" label="Skill" />
                  <el-table-column prop="count" label="次数" width="80" />
                </el-table>
              </el-col>
            </el-row>
            <p class="muted" style="margin-top: 12px">误选相关：{{ stats.misselect }}</p>
          </template>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="drawer" title="调用过程" size="520px">
      <div v-loading="detailLoading">
        <template v-if="detail">
          <p>
            <el-link type="primary" @click="router.push(`/runs/${detail.run.run_id}`)">打开运行详情 {{ detail.run.run_id }}</el-link>
          </p>
          <h4>路由时间线</h4>
          <el-empty v-if="detail.empty_routing" :description="NO_DATA" />
          <el-timeline v-else>
            <el-timeline-item
              v-for="e in detail.routing_events"
              :key="e.event_id"
              :timestamp="formatTime(e.occurred_at)"
            >
              <div><strong>{{ e.event_type }}</strong> <span v-if="e.duration_ms != null">({{ formatMs(e.duration_ms) }})</span></div>
              <pre class="meta">{{ JSON.stringify(e.metadata || {}, null, 2) }}</pre>
            </el-timeline-item>
          </el-timeline>

          <h4>执行时间线（Tool）</h4>
          <el-empty v-if="!detail.tool_call_events.length" :description="NO_DATA" />
          <el-timeline v-else>
            <el-timeline-item
              v-for="e in detail.tool_call_events"
              :key="e.event_id"
              :timestamp="formatTime(e.occurred_at)"
              :type="e.status === 'ok' ? 'success' : e.status === 'error' ? 'danger' : undefined"
            >
              {{ e.event_type }} · {{ e.tool_name || '—' }} · {{ e.status || '—' }}
              <span v-if="e.duration_ms != null"> · {{ formatMs(e.duration_ms) }}</span>
            </el-timeline-item>
          </el-timeline>

          <h4>出站连接器</h4>
          <p class="muted">{{ detail.connector_status }}</p>
          <el-empty v-if="!detail.connector_events.length" description="未使用 / 未配置" />
        </template>
      </div>
    </el-drawer>
  </el-card>
</template>

<style scoped>
.clickable :deep(tbody tr) { cursor: pointer; }
.muted { color: var(--el-text-color-secondary); font-size: 12px; margin-top: 4px; }
.meta {
  margin: 4px 0 0;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  background: var(--el-fill-color-light);
  padding: 6px 8px;
  border-radius: 4px;
}
</style>
