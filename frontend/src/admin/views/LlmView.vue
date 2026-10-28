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
const mForm = reactive({
  provider_id: undefined as number | undefined, model_name: '', display_name: '',
  temperature: undefined as number | undefined, max_tokens: undefined as number | undefined,
  purpose_tags: '', enabled: true,
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
    ? { ...m, purpose_tags: (m.purpose_tags ?? []).join(', '), temperature: m.temperature ?? undefined, max_tokens: m.max_tokens ?? undefined }
    : { provider_id: providers.value[0]?.id, model_name: '', display_name: '', temperature: undefined, max_tokens: undefined, purpose_tags: '', enabled: true })
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
  const body = {
    provider_id: mForm.provider_id, model_name: mForm.model_name, display_name: mForm.display_name,
    temperature: mForm.temperature ?? null, max_tokens: mForm.max_tokens ?? null, enabled: mForm.enabled,
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
      <el-table-column prop="model_name" label="模型名" />
      <el-table-column label="温度" width="80"><template #default="{ row }">{{ row.temperature ?? '默认' }}</template></el-table-column>
      <el-table-column label="最大 Token" width="110"><template #default="{ row }">{{ row.max_tokens ?? '默认' }}</template></el-table-column>
      <el-table-column label="用途" width="140"><template #default="{ row }">{{ row.purpose_tags.join('、') || '—' }}</template></el-table-column>
      <el-table-column label="状态" width="80"><template #default="{ row }">{{ row.enabled ? '启用' : '停用' }}</template></el-table-column>
      <el-table-column label="连接测试" min-width="220">
        <template #default="{ row }">
          <el-text v-if="results[`models-${row.id}`]?.pending">检测中…</el-text>
          <TestResult v-else :result="results[`models-${row.id}`] ?? null" />
        </template>
      </el-table-column>
      <el-table-column v-if="editable" label="操作" width="200">
        <template #default="{ row }">
          <el-button link @click="test('models', row.id)">测试</el-button>
          <el-button link @click="openModel(row)">编辑</el-button>
          <el-button link type="danger" @click="removeModel(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-dialog v-model="pDialog" :title="pEditing ? '编辑提供方' : '新增提供方'" width="560px">
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

  <el-dialog v-model="mDialog" :title="mEditing ? '编辑模型' : '新增模型'" width="560px">
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
      <el-form-item label="温度"><el-input-number v-model="mForm.temperature" :min="0" :max="2" :step="0.1" /></el-form-item>
      <el-form-item label="最大 Token"><el-input-number v-model="mForm.max_tokens" :min="1" /></el-form-item>
      <el-form-item label="用途标签"><el-input v-model="mForm.purpose_tags" placeholder="如 intent, answer（逗号分隔）" /></el-form-item>
      <el-form-item label="启用"><el-switch v-model="mForm.enabled" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="mDialog = false">取消</el-button>
      <el-button type="primary" @click="saveModel">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.model-name-row {
  display: flex;
  gap: 8px;
  width: 100%;
  align-items: center;
}
</style>
