<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { can } from '../auth'
import { errorMessage, http } from '@/shared/http'
import SecretInput from '@/shared/SecretInput.vue'
import TestResult from '@/shared/TestResult.vue'

const providers = ref<any[]>([])
const models = ref<any[]>([])
const results = reactive<Record<string, any>>({})
const editable = can('sys.setting.edit')
const providerName = computed(() => Object.fromEntries(providers.value.map((p) => [p.id, p.name])))

const pDialog = ref(false)
const pEditing = ref<any | null>(null)
const pForm = reactive({ name: '', base_url: '', api_key: '', clear_api_key: false, timeout_seconds: 60, enabled: true })

const mDialog = ref(false)
const mEditing = ref<any | null>(null)
const CAP_OPTIONS = [
  { value: 'text', label: '文本' },
  { value: 'vision', label: '视觉' },
  { value: 'multimodal', label: '多模态' },
  { value: 'embedding', label: 'Embedding' },
]
const TIER_OPTIONS = [
  { value: 'large', label: '大模型' },
  { value: 'small', label: '小模型' },
]
const capLabel = (v: string) => CAP_OPTIONS.find((o) => o.value === v)?.label ?? v
const tierLabel = (v: string) => TIER_OPTIONS.find((o) => o.value === v)?.label ?? v

const mForm = reactive({
  provider_id: undefined as number | undefined, model_name: '', display_name: '',
  temperature: undefined as number | undefined, max_tokens: undefined as number | undefined,
  max_input_tokens: undefined as number | undefined,
  purpose_tags: '', enabled: true,
  capabilities: ['text'] as string[], model_tier: 'large' as 'large' | 'small',
})
const remoteModels = ref<string[]>([])
const remoteLoading = ref(false)
const remoteHint = ref('')
let displayNameTouched = false
let fetchSeq = 0

async function load() {
  try {
    providers.value = (await http.get<any>('/v1/admin/llm/providers')).items
    models.value = (await http.get<any>('/v1/admin/llm/models')).items
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
  await loadRouting()
}

// ---- 模型路由：同池最大尝试次数 + (能力 × 规模) 池 ----
const maxFailover = ref(3)
// 来自 GET /defaults，保存次数时原样带回，避免模型列表未到时把全局默认清空
const globalDefaultModelId = ref<number | null>(null)
const defaultsLoaded = ref(false)
const routes = ref<any[]>([])
const routeWarnings = ref<string[]>([])
const modelById = computed<Record<number, any>>(() => Object.fromEntries(models.value.map((m) => [m.id, m])))
// 能力 × 规模 全部组合，未配置的显示为空池
const routeRows = computed(() => CAP_OPTIONS.flatMap((c) => TIER_OPTIONS.map((t) => {
  const r = routes.value.find((x) => x.capability === c.value && x.model_tier === t.value)
  return { capability: c.value, model_tier: t.value, configured: Boolean(r), enabled: r?.enabled ?? true, model_ids: (r?.model_ids ?? []) as number[] }
})))
const modelLabel = (id: number) => {
  const m = modelById.value[id]
  return m ? `${m.display_name || m.model_name}` : `#${id}（已删除）`
}
const poolMatches = (id: number) => {
  const m = modelById.value[id]
  return Boolean(m && (m.capabilities ?? []).includes(rForm.capability) && m.model_tier === rForm.model_tier)
}

async function loadRouting() {
  try {
    const d = await http.get<any>('/v1/admin/llm/defaults')
    maxFailover.value = d.max_failover
    globalDefaultModelId.value = d.global_default_model_id ?? null
    defaultsLoaded.value = true
    routes.value = (await http.get<any>('/v1/admin/llm/routes')).items
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function saveDefaults() {
  if (!defaultsLoaded.value) return
  try {
    // 只改 max_failover，带回 GET /defaults 的全局默认，不从模型列表推导
    const defaultId = globalDefaultModelId.value
    await http.put('/v1/admin/llm/defaults', { global_default_model_id: defaultId, max_failover: maxFailover.value })
    ElMessage.success('已保存')
    await loadRouting()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

const rDialog = ref(false)
const rForm = reactive({ capability: 'text', model_tier: 'large', enabled: true, model_ids: [] as number[] })
const rShowAll = ref(false)
const rPick = ref<number | undefined>(undefined)
const rCandidates = computed(() => models.value.filter((m) =>
  m.enabled && !rForm.model_ids.includes(m.id)
  && (rShowAll.value || ((m.capabilities ?? []).includes(rForm.capability) && m.model_tier === rForm.model_tier))))

function openRoute(row: { capability: string; model_tier: string; enabled: boolean; model_ids: number[] }) {
  Object.assign(rForm, { capability: row.capability, model_tier: row.model_tier, enabled: row.enabled, model_ids: [...row.model_ids] })
  rShowAll.value = false
  rPick.value = undefined
  rDialog.value = true
}

function addRouteModel() {
  if (rPick.value === undefined) return
  rForm.model_ids.push(rPick.value)
  rPick.value = undefined
}

function moveRouteModel(i: number, delta: number) {
  const j = i + delta
  const ids = rForm.model_ids
  if (j < 0 || j >= ids.length) return
  ;[ids[i], ids[j]] = [ids[j], ids[i]]
}

async function saveRoute() {
  try {
    const r = await http.put<any>('/v1/admin/llm/routes', { ...rForm })
    rDialog.value = false
    routeWarnings.value = r.warnings ?? []
    if (routeWarnings.value.length) ElMessage.warning('已保存，但存在不匹配的模型，详见页面提示')
    else ElMessage.success('已保存')
    await loadRouting()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function removeRoute(row: { capability: string; model_tier: string }) {
  await ElMessageBox.confirm(`删除「${capLabel(row.capability)} / ${tierLabel(row.model_tier)}」路由池？`, '确认', { type: 'warning' })
  try {
    await http.del(`/v1/admin/llm/routes/${row.capability}/${row.model_tier}`)
    routeWarnings.value = []
    await loadRouting()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function setDefault(m: any) {
  await ElMessageBox.confirm(`将「${m.display_name || m.model_name}」设为全局默认模型？将覆盖当前默认。`, '确认', { type: 'warning' })
  try {
    await http.post(`/v1/admin/llm/models/${m.id}/set-default`)
    ElMessage.success('已设为默认')
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

function openProvider(p?: any) {
  pEditing.value = p ?? null
  Object.assign(pForm, p
    ? { name: p.name, base_url: p.base_url, api_key: '', clear_api_key: false, timeout_seconds: p.timeout_seconds, enabled: p.enabled }
    : { name: '', base_url: '', api_key: '', clear_api_key: false, timeout_seconds: 60, enabled: true })
  pDialog.value = true
}

async function saveProvider() {
  const body = { ...pForm, api_key: pForm.api_key || null }
  try {
    if (pEditing.value) await http.put(`/v1/admin/llm/providers/${pEditing.value.id}`, body)
    else await http.post('/v1/admin/llm/providers', body)
    pDialog.value = false
    ElMessage.success('已保存')
    load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function removeProvider(p: any) {
  await ElMessageBox.confirm(`删除提供方「${p.name}」？其 API Key 也会被删除。`, '确认', { type: 'warning' })
  try {
    await http.del(`/v1/admin/llm/providers/${p.id}`)
    load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function fetchRemoteModels() {
  const providerId = mForm.provider_id
  if (!providerId || !mDialog.value) {
    remoteModels.value = []
    remoteHint.value = ''
    return
  }
  const seq = ++fetchSeq
  remoteLoading.value = true
  remoteHint.value = ''
  try {
    const body = await http.get<any>(`/v1/admin/llm/providers/${providerId}/remote-models`)
    if (seq !== fetchSeq) return
    if (!body.ok) {
      remoteModels.value = []
      remoteHint.value = `无法获取模型列表：${body.error || '未知错误'}`
      ElMessage.warning(remoteHint.value)
      return
    }
    remoteModels.value = body.models ?? []
    if (!remoteModels.value.length) {
      remoteHint.value = '该提供方未返回模型列表，可手动输入模型名'
      ElMessage.info(remoteHint.value)
    } else if (body.truncated) {
      remoteHint.value = '仅显示前 200 个，可用搜索或手动输入'
      ElMessage.info(remoteHint.value)
    } else {
      remoteHint.value = `已加载 ${body.model_count} 个远端模型`
    }
  } catch (e) {
    if (seq !== fetchSeq) return
    remoteModels.value = []
    remoteHint.value = `无法获取模型列表：${errorMessage(e)}`
    ElMessage.warning(remoteHint.value)
  } finally {
    if (seq === fetchSeq) remoteLoading.value = false
  }
}

function openModel(m?: any) {
  mEditing.value = m ?? null
  displayNameTouched = Boolean(m?.display_name)
  Object.assign(mForm, m
    ? {
      ...m, purpose_tags: (m.purpose_tags ?? []).join(', '), temperature: m.temperature ?? undefined, max_tokens: m.max_tokens ?? undefined,
      max_input_tokens: m.max_input_tokens ?? undefined,
      capabilities: [...(m.capabilities ?? ['text'])], model_tier: m.model_tier ?? 'large',
    }
    : {
      provider_id: providers.value[0]?.id, model_name: '', display_name: '', temperature: undefined, max_tokens: undefined,
      max_input_tokens: undefined,
      purpose_tags: '', enabled: true, capabilities: ['text'], model_tier: 'large',
    })
  remoteModels.value = []
  remoteHint.value = ''
  mDialog.value = true
  void fetchRemoteModels()
}

function onModelNameChange(name: string | null) {
  if (!name) return
  if (!displayNameTouched || !mForm.display_name) {
    mForm.display_name = name
    displayNameTouched = false
  }
}

function onDisplayNameInput() {
  displayNameTouched = Boolean(mForm.display_name)
}

async function saveModel() {
  if (!mForm.capabilities.length) {
    ElMessage.warning('请至少选择一种能力')
    return
  }
  const body = {
    provider_id: mForm.provider_id, model_name: mForm.model_name, display_name: mForm.display_name,
    temperature: mForm.temperature ?? null, max_tokens: mForm.max_tokens ?? null,
    max_input_tokens: mForm.max_input_tokens ?? null, enabled: mForm.enabled,
    capabilities: mForm.capabilities, model_tier: mForm.model_tier,
    purpose_tags: mForm.purpose_tags.split(',').map((s) => s.trim()).filter(Boolean),
  }
  try {
    if (mEditing.value) await http.put(`/v1/admin/llm/models/${mEditing.value.id}`, body)
    else await http.post('/v1/admin/llm/models', body)
    mDialog.value = false
    ElMessage.success('已保存')
    load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function removeModel(m: any) {
  await ElMessageBox.confirm(`删除模型「${m.model_name}」？`, '确认', { type: 'warning' })
  try {
    await http.del(`/v1/admin/llm/models/${m.id}`)
    load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function test(kind: 'providers' | 'models', id: number) {
  results[`${kind}-${id}`] = { pending: true }
  try {
    results[`${kind}-${id}`] = await http.post(`/v1/admin/llm/${kind}/${id}/test`)
  } catch (e) {
    delete results[`${kind}-${id}`]
    ElMessage.error(errorMessage(e))
  }
}

watch(() => mForm.provider_id, () => {
  if (mDialog.value) void fetchRemoteModels()
})

onMounted(load)
</script>

<template>
  <el-card header="LLM 提供方" style="margin-bottom: 16px">
    <div class="page-toolbar">
      <el-text type="info">OpenAI 兼容协议；API Key 只写不读。修改对新运行生效。</el-text>
      <el-button v-if="editable" type="primary" @click="openProvider()">新增提供方</el-button>
    </div>
    <el-table :data="providers" empty-text="暂无数据">
      <el-table-column prop="name" label="名称" width="140" />
      <el-table-column prop="base_url" label="Base URL" />
      <el-table-column label="API Key" width="170"><template #default="{ row }">{{ row.api_key.display }}</template></el-table-column>
      <el-table-column label="状态" width="80"><template #default="{ row }">{{ row.enabled ? '启用' : '停用' }}</template></el-table-column>
      <el-table-column label="连接测试" min-width="220">
        <template #default="{ row }">
          <el-text v-if="results[`providers-${row.id}`]?.pending">检测中…</el-text>
          <TestResult v-else :result="results[`providers-${row.id}`] ?? null" />
        </template>
      </el-table-column>
      <el-table-column v-if="editable" label="操作" width="200">
        <template #default="{ row }">
          <el-button link @click="test('providers', row.id)">测试</el-button>
          <el-button link @click="openProvider(row)">编辑</el-button>
          <el-button link type="danger" @click="removeProvider(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-card header="LLM 模型">
    <div class="page-toolbar">
      <el-text type="info">模型测试会向提供方发送一次最小请求（会产生少量真实用量）。</el-text>
      <el-button v-if="editable" type="primary" :disabled="!providers.length" @click="openModel()">新增模型</el-button>
    </div>
    <el-table :data="models" empty-text="暂无数据">
      <el-table-column label="提供方" width="140"><template #default="{ row }">{{ providerName[row.provider_id] }}</template></el-table-column>
      <el-table-column label="模型名" min-width="160">
        <template #default="{ row }">
          {{ row.model_name }}
          <el-tag v-if="row.is_default" type="warning" size="small" effect="dark" style="margin-left: 6px">★ 默认</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="能力" width="170">
        <template #default="{ row }">
          <el-tag v-for="c in row.capabilities ?? []" :key="c" size="small" style="margin: 0 4px 2px 0">{{ capLabel(c) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="规模" width="90"><template #default="{ row }">{{ tierLabel(row.model_tier) }}</template></el-table-column>
      <el-table-column label="温度" width="80"><template #default="{ row }">{{ row.temperature ?? '默认' }}</template></el-table-column>
      <el-table-column label="输出 Token" width="110"><template #default="{ row }">{{ row.max_tokens ?? '默认' }}</template></el-table-column>
      <el-table-column label="输入窗口" width="110"><template #default="{ row }">{{ row.max_input_tokens ?? '100000' }}</template></el-table-column>
      <el-table-column label="用途（兼容）" width="120"><template #default="{ row }">{{ row.purpose_tags.join('、') || '—' }}</template></el-table-column>
      <el-table-column label="状态" width="80"><template #default="{ row }">{{ row.enabled ? '启用' : '停用' }}</template></el-table-column>
      <el-table-column label="连接测试" min-width="220">
        <template #default="{ row }">
          <el-text v-if="results[`models-${row.id}`]?.pending">检测中…</el-text>
          <TestResult v-else :result="results[`models-${row.id}`] ?? null" />
        </template>
      </el-table-column>
      <el-table-column v-if="editable" label="操作" width="260">
        <template #default="{ row }">
          <el-button link :disabled="row.is_default || !row.enabled" @click="setDefault(row)">设为默认</el-button>
          <el-button link @click="test('models', row.id)">测试</el-button>
          <el-button link @click="openModel(row)">编辑</el-button>
          <el-button link type="danger" @click="removeModel(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-card header="模型路由" style="margin-top: 16px">
    <div class="page-toolbar">
      <el-text type="info">按「能力 × 规模」维护模型池，按顺序尝试；空池将回落到全局默认模型或旧的用途标签匹配。</el-text>
      <div v-if="editable" class="failover-row">
        <el-text>同池最大尝试次数</el-text>
        <el-input-number v-model="maxFailover" :min="1" :max="10" size="small" />
        <el-button type="primary" size="small" :disabled="!defaultsLoaded" @click="saveDefaults">保存</el-button>
      </div>
    </div>
    <el-alert v-for="(w, i) in routeWarnings" :key="i" :title="w" type="warning" show-icon :closable="false" style="margin-bottom: 8px" />
    <el-table :data="routeRows" empty-text="暂无数据">
      <el-table-column label="能力" width="120"><template #default="{ row }">{{ capLabel(row.capability) }}</template></el-table-column>
      <el-table-column label="规模" width="100"><template #default="{ row }">{{ tierLabel(row.model_tier) }}</template></el-table-column>
      <el-table-column label="模型池（按顺序）" min-width="260">
        <template #default="{ row }">
          <el-text v-if="!row.model_ids.length" type="info">{{ row.configured ? '空池' : '未配置' }}（使用全局默认 / 兼容链）</el-text>
          <template v-else>
            <el-tag v-for="(id, i) in row.model_ids" :key="id" size="small" style="margin: 0 4px 2px 0">{{ i + 1 }}. {{ modelLabel(id) }}</el-tag>
          </template>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">{{ row.configured ? (row.enabled ? '启用' : '停用') : '—' }}</template>
      </el-table-column>
      <el-table-column v-if="editable" label="操作" width="130">
        <template #default="{ row }">
          <el-button link @click="openRoute(row)">编辑</el-button>
          <el-button v-if="row.configured" link type="danger" @click="removeRoute(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-dialog v-model="rDialog" :title="`编辑路由池：${capLabel(rForm.capability)} / ${tierLabel(rForm.model_tier)}`" width="560px" :teleported="true" append-to="body">
    <el-form label-width="110px">
      <el-form-item label="启用"><el-switch v-model="rForm.enabled" /></el-form-item>
      <el-form-item label="模型顺序">
        <div class="route-list">
          <el-text v-if="!rForm.model_ids.length" type="info">暂无模型，请在下方添加</el-text>
          <div v-for="(id, i) in rForm.model_ids" :key="id" class="route-item">
            <span>{{ i + 1 }}. {{ modelLabel(id) }}</span>
            <el-tag v-if="!poolMatches(id)" type="warning" size="small">能力/规模不匹配</el-tag>
            <span class="route-ops">
              <el-button link :disabled="i === 0" @click="moveRouteModel(i, -1)">上移</el-button>
              <el-button link :disabled="i === rForm.model_ids.length - 1" @click="moveRouteModel(i, 1)">下移</el-button>
              <el-button link type="danger" @click="rForm.model_ids.splice(i, 1)">移除</el-button>
            </span>
          </div>
        </div>
      </el-form-item>
      <el-form-item label="添加模型">
        <div class="model-name-row">
          <el-select v-model="rPick" filterable clearable placeholder="选择启用中的模型" style="flex: 1">
            <el-option v-for="m in rCandidates" :key="m.id" :label="`${m.display_name || m.model_name}（${providerName[m.provider_id] ?? '?'}）`" :value="m.id" />
          </el-select>
          <el-button :disabled="rPick === undefined" @click="addRouteModel">添加</el-button>
        </div>
        <el-checkbox v-model="rShowAll" style="margin-top: 4px">显示能力/规模不匹配的模型（保存时会有警告，运行时跳过）</el-checkbox>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="rDialog = false">取消</el-button>
      <el-button type="primary" @click="saveRoute">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="pDialog" :title="pEditing ? '编辑提供方' : '新增提供方'" width="560px" :teleported="true" append-to="body">
    <el-form label-width="110px">
      <el-form-item label="名称"><el-input v-model="pForm.name" /></el-form-item>
      <el-form-item label="Base URL"><el-input v-model="pForm.base_url" placeholder="https://api.example.com/v1" /></el-form-item>
      <el-form-item label="API Key">
        <SecretInput v-model="pForm.api_key" :display="pEditing?.api_key.display" :is-set="pEditing?.api_key.is_set"
          clearable @clear="pForm.clear_api_key = true" />
        <el-text v-if="pForm.clear_api_key" type="danger" size="small">保存后将清除 API Key</el-text>
      </el-form-item>
      <el-form-item label="超时（秒）"><el-input-number v-model="pForm.timeout_seconds" :min="1" :max="600" /></el-form-item>
      <el-form-item label="启用"><el-switch v-model="pForm.enabled" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="pDialog = false">取消</el-button>
      <el-button type="primary" @click="saveProvider">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="mDialog" :title="mEditing ? '编辑模型' : '新增模型'" width="560px" :teleported="true" append-to="body">
    <el-form label-width="110px">
      <el-form-item label="提供方">
        <el-select v-model="mForm.provider_id" style="width: 100%">
          <el-option v-for="p in providers" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="模型名">
        <div class="model-name-row">
          <el-select
            v-model="mForm.model_name"
            filterable
            allow-create
            default-first-option
            clearable
            :loading="remoteLoading"
            placeholder="从列表选择或手动输入"
            style="flex: 1"
            @change="onModelNameChange"
          >
            <el-option v-for="id in remoteModels" :key="id" :label="id" :value="id" />
            <el-option
              v-if="mForm.model_name && !remoteModels.includes(mForm.model_name)"
              :label="mForm.model_name"
              :value="mForm.model_name"
            />
          </el-select>
          <el-button :loading="remoteLoading" :disabled="!mForm.provider_id" @click="fetchRemoteModels">刷新</el-button>
        </div>
        <el-text v-if="remoteHint" type="info" size="small">{{ remoteHint }}</el-text>
      </el-form-item>
      <el-form-item label="显示名"><el-input v-model="mForm.display_name" @input="onDisplayNameInput" /></el-form-item>
      <el-form-item label="能力">
        <el-select v-model="mForm.capabilities" multiple style="width: 100%" placeholder="至少选择一项">
          <el-option v-for="o in CAP_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="规模">
        <el-radio-group v-model="mForm.model_tier">
          <el-radio v-for="o in TIER_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="温度"><el-input-number v-model="mForm.temperature" :min="0" :max="2" :step="0.1" /></el-form-item>
      <el-form-item label="输出 Token"><el-input-number v-model="mForm.max_tokens" :min="1" /></el-form-item>
      <el-form-item label="输入窗口 Token">
        <el-input-number v-model="mForm.max_input_tokens" :min="1" :max="10000000" />
        <span class="form-hint">模型上下文窗口（输入侧）。留空=默认 100000；按厂商手册填写</span>
      </el-form-item>
      <el-form-item label="用途标签"><el-input v-model="mForm.purpose_tags" placeholder="兼容旧逻辑，建议改用能力/规模与路由池（逗号分隔）" /></el-form-item>
      <el-form-item label="启用"><el-switch v-model="mForm.enabled" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="mDialog = false">取消</el-button>
      <el-button type="primary" @click="saveModel">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.failover-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.route-list {
  width: 100%;
}
.route-item {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 2px 0;
}
.route-ops {
  margin-left: auto;
  white-space: nowrap;
}
.model-name-row {
  display: flex;
  gap: 8px;
  width: 100%;
  align-items: center;
}
.form-hint {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
