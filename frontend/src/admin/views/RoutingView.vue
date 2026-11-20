<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { errorMessage, http } from '@/shared/http'
import { formatTime } from '@/shared/format'
import {
  NO_DATA,
  TOOLS_PATH,
  ackKeepLegacy,
  auditReasonError,
  contractMigrateDiff,
  fetchConfigTruth,
  fetchOrphanTools,
  formatMs,
  formatRate,
  migrateContract,
  rangeParams,
  routingEventMetadataDisplay,
  routingModeLabel,
  type ConfigTruth,
  type ContractDiffLine,
  type LegacyPromptRelease,
  type OrphanToolItem,
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

const truthLoading = ref(false)
const truth = ref<ConfigTruth | null>(null)
const includeAcked = ref(false)
const orphanItems = ref<OrphanToolItem[] | null>(null)

const migrateOpen = ref(false)
const migrateSaving = ref(false)
const migrateRow = ref<LegacyPromptRelease | null>(null)
const migrateReason = ref('')
const migrateDiff = ref<ContractDiffLine[]>([])

const ackOpen = ref(false)
const ackSaving = ref(false)
const ackRow = ref<LegacyPromptRelease | null>(null)
const ackReason = ref('')

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

async function loadTruth() {
  truthLoading.value = true
  try {
    truth.value = await fetchConfigTruth(includeAcked.value)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    truthLoading.value = false
  }
}

async function loadOrphans() {
  try {
    const data = await fetchOrphanTools()
    orphanItems.value = data.items
  } catch {
    orphanItems.value = null
  }
}

function openMigrate(row: LegacyPromptRelease) {
  migrateRow.value = row
  migrateDiff.value = contractMigrateDiff(row.tool_routing_mode)
  migrateReason.value = ''
  migrateOpen.value = true
}

async function submitMigrate() {
  const row = migrateRow.value
  if (!row) return
  const err = auditReasonError(migrateReason.value)
  if (err) {
    ElMessage.warning(err)
    return
  }
  migrateSaving.value = true
  try {
    const saved = await migrateContract(row.release_id, migrateReason.value.trim())
    ElMessage.success(`已写入草稿 v${saved.draft_version.version_no}，请自行发布`)
    migrateOpen.value = false
    await loadTruth()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    migrateSaving.value = false
  }
}

function openAck(row: LegacyPromptRelease) {
  ackRow.value = row
  ackReason.value = ''
  ackOpen.value = true
}

async function submitAck() {
  const row = ackRow.value
  if (!row) return
  const err = auditReasonError(ackReason.value)
  if (err) {
    ElMessage.warning(err)
    return
  }
  ackSaving.value = true
  try {
    await ackKeepLegacy(row.release_id, ackReason.value.trim())
    ElMessage.success('已标记保留海选')
    ackOpen.value = false
    await loadTruth()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    ackSaving.value = false
  }
}

function openTools() {
  router.push(TOOLS_PATH)
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

watch(includeAcked, () => {
  loadTruth()
})

watch(activeTab, (tab) => {
  if (tab === 'stats') loadStats()
  else loadList()
  pushQuery()
})

onMounted(() => {
  fromQuery()
  loadTruth()
  loadOrphans()
  if (activeTab.value === 'stats') loadStats()
  else loadList()
})
</script>

<template>
  <el-card shadow="never" class="truth-card" v-loading="truthLoading">
    <template #header>
      <div class="truth-head">
        <span>配置真相</span>
        <el-checkbox v-model="includeAcked">含已确认保留海选</el-checkbox>
      </div>
    </template>
    <el-alert v-if="truth?.note" type="info" :closable="false" :title="truth.note" />
    <el-descriptions :column="2" border size="small" style="margin-top: 12px">
      <el-descriptions-item label="全局路由模式">{{ routingModeLabel(truth?.global_mode) }}</el-descriptions-item>
      <el-descriptions-item label="全局未命中回退">{{ routingModeLabel(truth?.global_fallback) }}</el-descriptions-item>
    </el-descriptions>

    <h4>在用工作流</h4>
    <el-table :data="truth?.active_workflows ?? []" :empty-text="NO_DATA" size="small">
      <el-table-column prop="workflow_id" label="工作流" min-width="160" />
      <el-table-column prop="release_id" label="当前发布" min-width="180" />
      <el-table-column label="快照模式" min-width="200">
        <template #default="{ row }">{{ routingModeLabel(row.tool_routing_mode) }}</template>
      </el-table-column>
      <el-table-column label="与全局一致" width="110">
        <template #default="{ row }">{{ row.matches_global ? '是' : '否' }}</template>
      </el-table-column>
    </el-table>

    <h4>待迁移（提示词海选）</h4>
    <el-table :data="truth?.legacy_prompt_releases ?? []" :empty-text="NO_DATA" size="small">
      <el-table-column prop="workflow_id" label="工作流" min-width="140" />
      <el-table-column prop="release_id" label="发布" min-width="160" />
      <el-table-column label="版本" width="80">
        <template #default="{ row }">{{ row.version_no ?? NO_DATA }}</template>
      </el-table-column>
      <el-table-column label="快照模式" min-width="180">
        <template #default="{ row }">{{ routingModeLabel(row.tool_routing_mode) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button type="primary" link @click="openMigrate(row)">迁移到契约默认</el-button>
          <el-button link @click="openAck(row)">保留海选</el-button>
        </template>
      </el-table-column>
    </el-table>
    <p class="muted">迁移只写入该工作流草稿，不改已发布快照，也不改进行中的运行。写完后请自行校验并发布。</p>
    <h4>孤儿清单</h4>
    <el-table :data="orphanItems ?? []" :empty-text="NO_DATA" size="small">
      <el-table-column prop="name" label="名称" min-width="180" />
      <el-table-column prop="kind" label="类型" width="140" />
      <el-table-column label="启用" width="90">
        <template #default="{ row }">{{ row.enabled ? '是' : '否' }}</template>
      </el-table-column>
    </el-table>
    <p class="truth-foot">
      <el-link @click="openTools">打开工具页</el-link>
      <span class="muted">{{ orphanItems == null ? NO_DATA : `${orphanItems.length} 个` }}</span>
    </p>
  </el-card>

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

    <el-drawer v-model="drawer" title="调用过程" size="520px" :teleported="true" append-to="body">
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
          <el-table v-else :data="detail.tool_call_events" size="small" :empty-text="NO_DATA">
            <el-table-column label="时间" width="150">
              <template #default="{ row }">{{ formatTime(row.occurred_at) }}</template>
            </el-table-column>
            <el-table-column prop="event_type" label="类型" width="120" />
            <el-table-column label="Tool" min-width="140">
              <template #default="{ row }">{{ row.tool_name || '—' }}</template>
            </el-table-column>
            <el-table-column label="connector_id" width="100">
              <template #default="{ row }">{{ routingEventMetadataDisplay(row.metadata).connectorId }}</template>
            </el-table-column>
            <el-table-column label="状态" width="72">
              <template #default="{ row }">{{ row.status || '—' }}</template>
            </el-table-column>
            <el-table-column label="耗时" width="88">
              <template #default="{ row }">{{ formatMs(row.duration_ms) }}</template>
            </el-table-column>
          </el-table>

          <h4>出站连接器</h4>
          <p class="muted">{{ detail.connector_status }}</p>
          <el-table
            v-if="detail.connector_events.length"
            :data="detail.connector_events"
            size="small"
            :empty-text="NO_DATA"
            style="margin-top: 8px"
          >
            <el-table-column prop="event_type" label="类型" />
            <el-table-column label="connector_id" width="120">
              <template #default="{ row }">{{ routingEventMetadataDisplay(row.metadata).connectorId }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="未使用 / 未配置" />
        </template>
      </div>
    </el-drawer>
  </el-card>

  <el-dialog
    v-model="migrateOpen"
    title="迁移到契约默认"
    width="640px"
    :close-on-click-modal="false"
    :teleported="true"
    append-to="body"
  >
    <p>
      工作流 {{ migrateRow?.workflow_id || NO_DATA }}，发布 {{ migrateRow?.release_id || NO_DATA }}。
      确认后只改草稿，已发布内容保持原样。
    </p>
    <el-table :data="migrateDiff" size="small" :empty-text="NO_DATA">
      <el-table-column prop="label" label="配置项" width="140" />
      <el-table-column label="变更前" min-width="180">
        <template #default="{ row }">{{ row.key === 'tool_routing_mode' ? routingModeLabel(row.before) : row.before }}</template>
      </el-table-column>
      <el-table-column label="草稿将写入" min-width="180">
        <template #default="{ row }">{{ row.key === 'routing_clarify_on_low_confidence' ? '开启（true）' : routingModeLabel(row.after) }}</template>
      </el-table-column>
    </el-table>
    <p class="muted">回退与低置信澄清的变更前值接口未返回，表中记为「{{ NO_DATA }}」。</p>
    <el-form label-width="72px" style="margin-top: 12px" @submit.prevent="submitMigrate">
      <el-form-item label="原因">
        <el-input v-model="migrateReason" maxlength="200" show-word-limit placeholder="至少 2 个字，写入审计" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="migrateOpen = false">取消</el-button>
      <el-button type="primary" :loading="migrateSaving" @click="submitMigrate">确认迁移</el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="ackOpen"
    title="保留海选"
    width="480px"
    :close-on-click-modal="false"
    :teleported="true"
    append-to="body"
  >
    <p>
      确认发布 {{ ackRow?.release_id || NO_DATA }} 继续使用提示词海选。只记审计，不改快照；默认清单不再列出此项。
    </p>
    <el-form label-width="72px" @submit.prevent="submitAck">
      <el-form-item label="原因">
        <el-input v-model="ackReason" maxlength="200" show-word-limit placeholder="至少 2 个字，写入审计" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="ackOpen = false">取消</el-button>
      <el-button type="primary" :loading="ackSaving" @click="submitAck">确认保留</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.truth-card { margin-bottom: 12px; }
.truth-head { display: flex; align-items: center; justify-content: space-between; }
.truth-foot { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
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
