<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errorMessage, http } from '@/shared/http'
import { formatTime } from '@/shared/format'
import { COMPAT_LEVEL, syncTag, type DiffChange, type ToolDetail, type ToolItem, type ToolKind } from '../ops'
import { resolveToolGuide } from '../toolGuides'

function paramEntries(params: Record<string, { type?: string; label?: string; description?: string; required?: boolean; enum?: string[] }> | undefined) {
  if (!params) return []
  return Object.entries(params).map(([name, rule]) => ({
    name,
    label: rule.label || name,
    type: rule.type || 'string',
    required: !!rule.required,
    description: rule.description || '',
    enum: rule.enum?.join(' / ') || '',
  }))
}
import AbilityHelpBanner from '../components/AbilityHelpBanner.vue'
import { emptyParam, emptyToolForm, toolFormFromSchema, toolPayload, type ToolForm } from '../catalogForm'

interface Upstream { key: string; label: string; base_url: string | null }

const items = ref<ToolItem[]>([])
const upstreams = ref<Upstream[]>([])
const defaultUpstreamKey = ref('office')
const kindFilter = ref<'' | ToolKind>('')
const KIND_LABEL: Record<ToolKind, string> = {
  office: 'OA 接口',
  open_oa_invoke: 'open-oa 调用',
  builtin: '内置',
  mcp: 'MCP',
}
const loading = ref(false)
const loadError = ref('')
const syncing = ref(false)
const report = ref<{ files: { file: string; ok: boolean; errors: string[] }[]; tools: any[] } | null>(null)

const drawer = ref(false)
const detail = ref<ToolDetail | null>(null)
const guide = computed(() => resolveToolGuide(detail.value))
const guideParams = computed(() => paramEntries(guide.value?.model_params))
const diffRange = ref<{ from: number | null; to: number | null }>({ from: null, to: null })
const diff = ref<{ compat_level: string; changes: DiffChange[] } | null>(null)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const r = await http.get<{ items: ToolItem[]; upstreams: Upstream[]; default_upstream_key?: string }>(
      '/v1/admin/tools', { kind: kindFilter.value || undefined })
    items.value = r.items
    upstreams.value = r.upstreams
    defaultUpstreamKey.value = r.default_upstream_key
      || r.upstreams[0]?.key
      || 'open_oa'
  } catch (e) {
    loadError.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

async function sync() {
  syncing.value = true
  try {
    report.value = await http.post('/v1/admin/tools/sync')
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    syncing.value = false
  }
}

async function askReason(title: string): Promise<string | null> {
  try {
    const { value } = await ElMessageBox.prompt('请填写原因（写入审计）', title, {
      inputValidator: (v: string) => (v && v.trim().length >= 2) || '至少 2 个字',
    })
    return value.trim()
  } catch {
    return null
  }
}

async function toggle(tool: ToolItem) {
  const enable = !tool.enabled
  const reason = await askReason(enable ? `启用 ${tool.name}` : `停用 ${tool.name}（立即拒绝调用）`)
  if (!reason) return
  try {
    await http.post(`/v1/admin/tools/${tool.name}/${enable ? 'enable' : 'disable'}`, { reason })
    ElMessage.success(enable ? '已启用' : '已停用')
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
  await load()
  if (detail.value?.name === tool.name) await open(tool.name)
}

async function open(name: string) {
  drawer.value = true
  diff.value = null
  try {
    detail.value = await http.get<ToolDetail>(`/v1/admin/tools/${name}`)
    const versions = detail.value.versions
    diffRange.value = {
      from: versions.find((v) => v.is_current)?.version_no ?? null,
      to: versions.find((v) => v.is_pending)?.version_no ?? versions[0]?.version_no ?? null,
    }
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function loadDiff() {
  if (!detail.value || !diffRange.value.from || !diffRange.value.to) return
  try {
    diff.value = await http.get(`/v1/admin/tools/${detail.value.name}/diff`, {
      from_no: diffRange.value.from,
      to_no: diffRange.value.to,
    })
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function activate(versionNo: number) {
  if (!detail.value) return
  const reason = await askReason(`激活 ${detail.value.name} v${versionNo}`)
  if (!reason) return
  try {
    await http.post(`/v1/admin/tools/${detail.value.name}/activate`, { version_no: versionNo, reason })
    ElMessage.success(`已激活 v${versionNo}`)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
  await load()
  await open(detail.value.name)
}

function needsOpenOaRepair(d: ToolDetail | null): boolean {
  if (!d) return false
  const reasons = d.unregistered_reasons || []
  return reasons.some((r) => r.includes('invoke_service') || r.includes('open_oa_invoke 须为 POST'))
}

async function repairOpenOa() {
  if (!detail.value) return
  let invokeService = 'out_attendance/go_out_application'
  let invokeMethod = ''
  // 从 tool 名猜 Export 方法：search_application_list → searchApplicationList
  const parts = detail.value.name.split('_').filter(Boolean)
  if (parts.length) {
    invokeMethod = parts[0] + parts.slice(1).map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join('')
  }
  try {
    const svc = await ElMessageBox.prompt('ANew 服务路径（invoke_service）', `修复 ${detail.value.name}`, {
      inputValue: invokeService,
      inputValidator: (v: string) => (v && v.trim().includes('/')) || '形如 module/export',
    })
    invokeService = svc.value.trim()
    const method = await ElMessageBox.prompt('Export 方法名（invoke_method）', `修复 ${detail.value.name}`, {
      inputValue: invokeMethod || 'searchApplicationList',
      inputValidator: (v: string) => (v && v.trim().length >= 2) || '请填写方法名',
    })
    invokeMethod = method.value.trim()
  } catch {
    return
  }
  const reasonText = await askReason(`修复 open-oa：${detail.value.name}`)
  if (!reasonText) return
  try {
    await http.post(`/v1/admin/tools/${detail.value.name}/repair-open-oa`, {
      invoke_service: invokeService,
      invoke_method: invokeMethod,
      reason: reasonText,
    })
    ElMessage.success('已修复并重新注册')
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
  await load()
  await open(detail.value.name)
}

function upstreamLabel(key: string | null): string {
  if (!key || key === 'office') return ''
  return upstreams.value.find((u) => u.key === key)?.label ?? `${key}（未配置）`
}

function fmt(v: unknown): string {
  return v === null || v === undefined ? '—' : typeof v === 'string' ? v : JSON.stringify(v)
}

// ---- 新建 / 编辑 ----
const editor = ref(false)
const editing = ref(false)
const saving = ref(false)
const form = ref<ToolForm>(emptyToolForm())
const reason = ref('')

function create() {
  editing.value = false
  form.value = emptyToolForm(defaultUpstreamKey.value)
  reason.value = ''
  draftWarnings.value = []
  skillDraft.value = null
  editor.value = true
}

// ---- 从 Apipost 导入（只生成草稿，保存仍走新建 Tool） ----
interface SkillDraft {
  name: string
  display_name: string
  description: string
  instructions: string
  examples: string[]
  tools: string[]
}
interface ApipostDraft {
  form: Record<string, any>
  warnings: string[]
  source: { name?: string; url?: string }
  skill?: SkillDraft
}
const importer = ref(false)
const importUrl = ref('')
const importLlm = ref(true)
const importing = ref(false)
const drafts = ref<ApipostDraft[]>([])
const importErrors = ref<string[]>([])
const draftWarnings = ref<string[]>([])
const skillDraft = ref<SkillDraft | null>(null)
const withSkill = ref(true)

function openImporter() {
  importUrl.value = ''
  drafts.value = []
  importErrors.value = []
  importer.value = true
}

async function runImport() {
  importing.value = true
  drafts.value = []
  importErrors.value = []
  try {
    const r = await http.post<{ drafts: ApipostDraft[]; errors: string[] }>('/v1/admin/tools/import/apipost', {
      url: importUrl.value.trim(),
      use_llm: importLlm.value,
    })
    drafts.value = r.drafts
    importErrors.value = r.errors
    if (r.drafts.length === 1 && !r.errors.length) useDraft(r.drafts[0])
    else if (!r.drafts.length) ElMessage.warning('没有可导入的接口')
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    importing.value = false
  }
}

function useDraft(d: ApipostDraft) {
  editing.value = false
  form.value = toolFormFromSchema(d.form)
  reason.value = `从 Apipost 导入：${d.source?.name || d.form.name}`.slice(0, 200)
  draftWarnings.value = d.warnings
  skillDraft.value = d.skill || null
  withSkill.value = !!d.skill
  importer.value = false
  editor.value = true
}

// ---- Export 向导：填服务路径 → 点选方法 → 表单配参 → 测通入库 ----
interface WizardMethod {
  name: string
  param_names?: string[]
  param_count?: number
  summary?: string
  already_added?: boolean
  tool_name?: string | null
}
interface WizardObjectEntry {
  key: string
  value: string
}
interface WizardParamRow {
  name: string
  label: string
  type: string
  required: boolean
  description: string
  testValue: string
  /** 对象/数组形参：键值对（数组类型只用 value） */
  objectEntries: WizardObjectEntry[]
  position?: number
  kind?: string
}
interface WizardResultRow {
  field: string
  label: string
}
const CALL_OPTIONS = [
  { value: 'one_by_params', label: '整包参数（一个数组传入）' },
  { value: 'page_list', label: '分页列表（参数 + 页码 + 条数）' },
  { value: 'named_args', label: '按参数名逐个传入' },
]
const OP_OPTIONS = [
  { value: 'read', label: '读取' },
  { value: 'write', label: '写入' },
]
const RISK_OPTIONS = [
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
]
const RESULT_KIND_OPTIONS = [
  { value: 'list', label: '列表' },
  { value: 'object', label: '单条对象' },
]
const PARAM_TYPE_OPTIONS = [
  { value: 'string', label: '文本' },
  { value: 'integer', label: '整数' },
  { value: 'number', label: '数字' },
  { value: 'boolean', label: '是/否' },
  { value: 'object', label: '对象/字典' },
  { value: 'array', label: '数组' },
  { value: 'file', label: '文件路径/ID' },
]

const wizardOpen = ref(false)
const wizardBusy = ref(false)
const wizardError = ref('')
const wizardProbeOk = ref(false)
const wizardProbePreview = ref('')
const wizardStep = ref<'pick' | 'config'>('pick')
const wizard = ref({
  service: '',
  method: '',
  methods: [] as WizardMethod[],
  methodFilter: '',
  call: 'one_by_params',
  op: 'read',
  risk: 'low',
  name: '',
  summary: '',
  oa: '',
  reason: '',
  paramRows: [] as WizardParamRow[],
  resultKind: 'list',
  resultRows: [{ field: 'id', label: '编号' }] as WizardResultRow[],
})

const wizardFilteredMethods = computed(() => {
  const q = wizard.value.methodFilter.trim().toLowerCase()
  if (!q) return wizard.value.methods
  return wizard.value.methods.filter((m) => {
    const hay = `${m.name} ${m.summary || ''} ${m.tool_name || ''}`.toLowerCase()
    return hay.includes(q)
  })
})

function openExportWizard() {
  wizardOpen.value = true
  wizardError.value = ''
  wizardProbeOk.value = false
  wizardProbePreview.value = ''
  wizardStep.value = 'pick'
  wizard.value.methods = []
  wizard.value.method = ''
  wizard.value.methodFilter = ''
  wizard.value.paramRows = []
  wizard.value.resultRows = [{ field: 'id', label: '编号' }]
}

async function wizardDiscover() {
  const service = wizard.value.service.trim()
  if (!service) {
    ElMessage.warning('请填写服务路径，例如 out_attendance/go_out_application')
    return
  }
  wizardBusy.value = true
  wizardError.value = ''
  wizardProbeOk.value = false
  wizardStep.value = 'pick'
  wizard.value.method = ''
  try {
    const r = await http.post<{ methods: WizardMethod[] }>('/v1/admin/tools/export-wizard/discover', { service })
    wizard.value.methods = Array.isArray(r.methods) ? r.methods : []
    if (!wizard.value.methods.length) ElMessage.warning('未找到公开方法，请确认服务路径是否正确')
    else ElMessage.success(`已拉取 ${wizard.value.methods.length} 个公开方法`)
  } catch (e) {
    wizardError.value = errorMessage(e)
  } finally {
    wizardBusy.value = false
  }
}

function wizardDefaultEntriesFromDefault(def: unknown): WizardObjectEntry[] {
  if (def && typeof def === 'object' && !Array.isArray(def)) {
    return Object.entries(def as Record<string, unknown>).map(([key, value]) => ({
      key,
      value: value === undefined || value === null ? '' : String(value),
    }))
  }
  if (Array.isArray(def)) {
    return def.map((value) => ({
      key: '',
      value: value === undefined || value === null ? '' : String(value),
    }))
  }
  return [{ key: '', value: '' }]
}

async function wizardPickMethod(row: WizardMethod) {
  wizard.value.method = row.name
  wizardStep.value = 'config'
  wizardBusy.value = true
  wizardError.value = ''
  wizardProbeOk.value = false
  wizardProbePreview.value = ''
  try {
    const d = await http.post<{
      call_suggest?: string
      summary?: string
      param_count?: number
      params?: {
        name: string
        type?: string
        label?: string
        required?: boolean
        description?: string
        default?: unknown
        position?: number
        kind?: string
      }[]
    }>('/v1/admin/tools/export-wizard/describe', {
      service: wizard.value.service.trim(),
      method: row.name,
    })
    wizard.value.call = d.call_suggest || 'named_args'
    wizard.value.summary = d.summary || row.summary || row.name
    wizard.value.name = row.name.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase().slice(0, 64)
    // 每个形参单独一行可配（含数组/对象/文件），不再过滤 params/data
    wizard.value.paramRows = (d.params || [])
      .filter((p) => !!p?.name)
      .map((p) => {
        const type = p.type || 'string'
        const isBag = type === 'object' || type === 'array'
        const defaultText =
          p.default === undefined || p.default === null || isBag
            ? ''
            : String(p.default)
        return {
          name: p.name,
          label: p.label || p.name,
          type,
          required: !!p.required,
          description: p.description || '',
          testValue: defaultText,
          objectEntries: isBag ? wizardDefaultEntriesFromDefault(p.default) : [],
          position: p.position,
          kind: p.kind,
        }
      })
    if (wizard.value.call === 'page_list') {
      const names = new Set(wizard.value.paramRows.map((p) => p.name))
      if (!names.has('page')) {
        wizard.value.paramRows.push({
          name: 'page',
          label: '页码',
          type: 'integer',
          required: false,
          description: '从 1 开始',
          testValue: '1',
          objectEntries: [],
        })
      }
      if (!names.has('limit')) {
        wizard.value.paramRows.push({
          name: 'limit',
          label: '每页条数',
          type: 'integer',
          required: false,
          description: '建议不超过 20',
          testValue: '5',
          objectEntries: [],
        })
      }
      wizard.value.resultKind = 'list'
    }
  } catch (e) {
    wizardError.value = errorMessage(e)
  } finally {
    wizardBusy.value = false
  }
}

function wizardAddParamRow() {
  wizard.value.paramRows.push({
    name: '',
    label: '',
    type: 'string',
    required: false,
    description: '',
    testValue: '',
    objectEntries: [],
  })
}

function wizardAddObjectEntry(row: WizardParamRow) {
  if (!row.objectEntries) row.objectEntries = []
  row.objectEntries.push({ key: '', value: '' })
}

function wizardRemoveObjectEntry(row: WizardParamRow, idx: number) {
  row.objectEntries.splice(idx, 1)
}

function wizardOnParamTypeChange(row: WizardParamRow) {
  if ((row.type === 'object' || row.type === 'array') && (!row.objectEntries || !row.objectEntries.length)) {
    row.objectEntries = [{ key: '', value: '' }]
  }
}

function wizardRemoveParamRow(idx: number) {
  wizard.value.paramRows.splice(idx, 1)
}

function wizardAddResultRow() {
  wizard.value.resultRows.push({ field: '', label: '' })
}

function wizardRemoveResultRow(idx: number) {
  wizard.value.resultRows.splice(idx, 1)
}

function wizardBuildArgs(): Record<string, unknown> {
  const args: Record<string, unknown> = {}
  for (const row of wizard.value.paramRows) {
    const key = row.name.trim()
    if (!key) continue
    if (row.type === 'object') {
      const obj: Record<string, string> = {}
      for (const e of row.objectEntries || []) {
        const k = (e.key || '').trim()
        if (!k) continue
        obj[k] = e.value
      }
      // 即使为空对象也传，便于 named_args 命中数组形参
      args[key] = obj
      continue
    }
    if (row.type === 'array') {
      const list = (row.objectEntries || [])
        .map((e) => e.value)
        .filter((v) => v !== '')
      args[key] = list
      continue
    }
    const raw = row.testValue
    if (raw === '' || raw === undefined) continue
    if (row.type === 'integer') {
      const n = Number.parseInt(raw, 10)
      if (!Number.isNaN(n)) args[key] = n
      continue
    }
    if (row.type === 'number') {
      const n = Number(raw)
      if (!Number.isNaN(n)) args[key] = n
      continue
    }
    if (row.type === 'boolean') {
      args[key] = raw === '1' || raw.toLowerCase() === 'true' || raw === '是'
      continue
    }
    // string / file
    args[key] = raw
  }
  return args
}

function wizardBuildModelParams(): Record<string, Record<string, unknown>> {
  const mp: Record<string, Record<string, unknown>> = {}
  for (const row of wizard.value.paramRows) {
    const key = row.name.trim()
    if (!key) continue
    mp[key] = {
      type: row.type || 'string',
      label: row.label.trim() || key,
      required: !!row.required,
      description: row.description.trim(),
    }
  }
  return mp
}

async function wizardProbe() {
  if (!wizard.value.oa.trim()) {
    ElMessage.warning('请填写测试员工 OA 账号')
    return
  }
  if (!wizard.value.method) {
    ElMessage.warning('请先选择方法')
    return
  }
  const args = wizardBuildArgs()
  wizardBusy.value = true
  wizardError.value = ''
  wizardProbeOk.value = false
  try {
    const r = await http.post<{ data: unknown }>('/v1/admin/tools/export-wizard/probe', {
      service: wizard.value.service.trim(),
      method: wizard.value.method.trim(),
      oa: wizard.value.oa.trim(),
      args,
      call: wizard.value.call,
      op: wizard.value.op,
    })
    wizardProbeOk.value = true
    wizardProbePreview.value = JSON.stringify(r.data, null, 2).slice(0, 4000)
    ElMessage.success('测试成功，可以入库')
  } catch (e) {
    wizardProbeOk.value = false
    wizardError.value = errorMessage(e)
  } finally {
    wizardBusy.value = false
  }
}

async function wizardSave() {
  if (!wizardProbeOk.value) {
    ElMessage.warning('请先测试成功再入库')
    return
  }
  if (!wizard.value.name.trim()) {
    ElMessage.warning('请填写工具名称')
    return
  }
  const resultRows = wizard.value.resultRows
    .map((r) => ({ field: r.field.trim(), label: r.label.trim() }))
    .filter((r) => r.field)
  if (!resultRows.length) {
    ElMessage.warning('请至少添加一个返回字段')
    return
  }
  const fields = resultRows.map((r) => r.field)
  const labels: Record<string, string> = {}
  for (const r of resultRows) labels[r.field] = r.label || r.field
  const reasonText = wizard.value.reason.trim() || `接入方法 ${wizard.value.method}`
  wizardBusy.value = true
  wizardError.value = ''
  try {
    await http.post('/v1/admin/tools/export-wizard/save', {
      reason: reasonText,
      service: wizard.value.service.trim(),
      method: wizard.value.method.trim(),
      oa: wizard.value.oa.trim(),
      args: wizardBuildArgs(),
      call: wizard.value.call,
      op: wizard.value.op,
      risk: wizard.value.risk,
      name: wizard.value.name.trim(),
      summary: wizard.value.summary.trim(),
      model_params: wizardBuildModelParams(),
      result: {
        kind: wizard.value.resultKind,
        fields,
        labels,
        list_columns: wizard.value.resultKind === 'list' ? fields.slice(0, 6) : [],
      },
    })
    ElMessage.success('已入库，请到列表中启用')
    wizardOpen.value = false
    kindFilter.value = 'open_oa_invoke'
    await load()
  } catch (e) {
    wizardError.value = errorMessage(e)
  } finally {
    wizardBusy.value = false
  }
}

async function createSkill(draft: SkillDraft, toolName: string) {
  try {
    await http.post('/v1/admin/skills', { ...draft, tools: [toolName], reason: reason.value.trim() })
    ElMessage.success(`已创建配套 Skill：${draft.display_name}`)
  } catch (e) {
    ElMessage.error(`Tool 已保存，但配套 Skill 创建失败：${errorMessage(e)}（可到 Skill 管理手工创建）`)
  }
}

const metaEditor = ref(false)
const metaForm = ref({ name: '', summary: '', kind: '' as string })

function isExtensionTool(tool: { kind?: string | null } | null | undefined): boolean {
  return tool?.kind === 'builtin' || tool?.kind === 'mcp'
}

/** OA / open-oa：有契约版本链，可激活历史版本 */
function isOfficeTool(tool: { kind?: string | null } | null | undefined): boolean {
  return !isExtensionTool(tool)
}

async function edit(name: string) {
  try {
    const d = await http.get<ToolDetail>(`/v1/admin/tools/${name}`)
    reason.value = ''
    draftWarnings.value = []
    skillDraft.value = null
    // 内置 / MCP：实现在代码或远端，表单只改正文摘要
    if (isExtensionTool(d)) {
      metaForm.value = { name: d.name, summary: d.summary || '', kind: d.kind || '' }
      metaEditor.value = true
      return
    }
    if (!d.current_schema) {
      ElMessage.warning('该 Tool 没有有效版本，无法编辑（可尝试「从文件导入」或「接入业务接口」）')
      return
    }
    editing.value = true
    form.value = toolFormFromSchema(d.current_schema)
    // 配置里若仍是 office，把展示值对齐到已配置的上游 key，避免「未配置」误导
    if (!upstreams.value.some((u) => u.key === form.value.upstream)) {
      if (form.value.upstream === 'open_oa' && upstreams.value.some((u) => u.key === 'office')) {
        form.value.upstream = 'office'
      } else if (defaultUpstreamKey.value) {
        form.value.upstream = defaultUpstreamKey.value
      }
    }
    editor.value = true
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function saveMeta() {
  if (reason.value.trim().length < 2) {
    ElMessage.warning('请填写变更原因（至少 2 个字，写入审计）')
    return
  }
  if (!metaForm.value.summary.trim()) {
    ElMessage.warning('请填写摘要')
    return
  }
  saving.value = true
  try {
    // 内置/MCP 走元数据更新；其余字段占位满足接口校验
    await http.put(`/v1/admin/tools/${metaForm.value.name}`, {
      name: metaForm.value.name,
      summary: metaForm.value.summary.trim(),
      description: '',
      method: 'GET',
      upstream: defaultUpstreamKey.value || 'office',
      path: '/',
      timeout_seconds: 10,
      inject_identity_fields: [],
      top_level_fields: [],
      query_params_field: null,
      identity_params: {},
      model_params: {},
      result: { kind: 'object', fields: [], labels: {}, list_columns: [] },
      reason: reason.value.trim(),
    })
    ElMessage.success('已保存')
    metaEditor.value = false
    await load()
    if (detail.value?.name === metaForm.value.name) await open(metaForm.value.name)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    saving.value = false
  }
}

async function removeTool(row: ToolItem) {
  const reasonText = await askReason(`删除 Tool：${row.name}`)
  if (!reasonText) return
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.name}」？依赖它的 Skill 将变为不可用。内置 Tool 删除后不会在「从文件导入」时自动恢复。`,
      '删除 Tool',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await http.del(`/v1/admin/tools/${row.name}`, { reason: reasonText })
    ElMessage.success('已删除')
    if (detail.value?.name === row.name) {
      drawer.value = false
      detail.value = null
    }
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

function addField() {
  form.value.fields.push({ key: '', label: '', inList: form.value.result_kind === 'list' })
}

async function save() {
  if (reason.value.trim().length < 2) {
    ElMessage.warning('请填写变更原因（至少 2 个字，写入审计）')
    return
  }
  saving.value = true
  try {
    const body = { ...toolPayload(form.value), reason: reason.value.trim() }
    const r = editing.value
      ? await http.put<{ result: string; version_no?: number }>(`/v1/admin/tools/${form.value.name}`, body)
      : await http.post<{ result: string; version_no?: number }>('/v1/admin/tools', body)
    const tag = syncTag(r.result)
    if (r.result === 'breaking_pending') ElMessage.warning(`已保存为待激活版本 v${r.version_no}（不兼容变更，需在详情中激活）`)
    else ElMessage.success(`${tag.label}${r.version_no ? ` · v${r.version_no}` : ''}`)
    editor.value = false
    if (!editing.value && skillDraft.value && withSkill.value) await createSkill(skillDraft.value, form.value.name.trim())
    skillDraft.value = null
    await load()
    if (detail.value?.name === form.value.name) await open(form.value.name)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <AbilityHelpBanner focus="tool" />
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="全部 Tool 均可编辑与删除。OA / open-oa 改契约表单；内置与 MCP 只改摘要。删除需填审计原因。员工身份由服务端注入。"
      style="margin-bottom: 12px"
    />
    <div style="margin-bottom: 12px">
      <el-button type="primary" @click="create">新建 Tool</el-button>
      <el-tooltip content="粘贴 Apipost 接口文档分享链接，自动生成 Tool 草稿（检查后再保存）">
        <el-button @click="openImporter">从 Apipost 导入</el-button>
      </el-tooltip>
      <el-tooltip content="填写服务路径，点选 Export 公开方法，表单配置后测试入库">
        <el-button @click="openExportWizard">接入业务接口</el-button>
      </el-tooltip>
      <el-tooltip content="从仓库 openapi/*.yaml 批量导入；同名 Tool 会被文件中的定义覆盖（按版本规则）">
        <el-button :loading="syncing" @click="sync">从文件导入</el-button>
      </el-tooltip>
      <el-button @click="load">刷新</el-button>
      <el-radio-group v-model="kindFilter" style="margin-left: 12px" @change="load">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="office">OA 接口</el-radio-button>
        <el-radio-button value="open_oa_invoke">open-oa 调用</el-radio-button>
        <el-radio-button value="builtin">内置</el-radio-button>
        <el-radio-button value="mcp">MCP</el-radio-button>
      </el-radio-group>
    </div>

    <el-alert v-if="report" type="success" :closable="true" style="margin-bottom: 12px" @close="report = null">
      <template #title>导入完成</template>
      <div v-for="f in report.files" :key="f.file">
        {{ f.file }}：<b :style="{ color: f.ok ? 'var(--tech-success)' : 'var(--tech-danger)' }">{{ f.ok ? '解析成功' : '解析失败（已保留旧版本）' }}</b>
        <div v-for="e in f.errors" :key="e" style="color: var(--tech-danger)">· {{ e }}</div>
      </div>
      <div v-for="t in report.tools" :key="t.name">{{ t.name }}：{{ syncTag(t.result).label }}<template v-if="t.version_no"> v{{ t.version_no }}</template></div>
    </el-alert>

    <el-result v-if="loadError" icon="error" :title="loadError" />
    <el-table v-else v-loading="loading" :data="items" empty-text="暂无数据">
      <el-table-column label="Tool" min-width="260">
        <template #default="{ row }">
          <el-link type="primary" @click="open(row.name)">{{ row.name }}</el-link>
          <el-tag v-if="row.kind" size="small" effect="plain" style="margin-left: 6px">{{ KIND_LABEL[row.kind as ToolKind] || row.kind }}</el-tag>
          <div class="muted">{{ row.summary }}</div>
          <div v-if="row.path" class="muted">
            <el-tag v-if="upstreamLabel(row.upstream)" size="small" type="info">{{ upstreamLabel(row.upstream) }}</el-tag>
            <code>{{ row.method }} {{ row.path }}</code>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="运行时" width="110">
        <template #default="{ row }">
          <el-tooltip v-if="!row.registered" :content="row.unregistered_reasons.join('；')">
            <el-tag type="danger">未注册</el-tag>
          </el-tooltip>
          <el-tag v-else type="success">已注册</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="启用" width="90">
        <template #default="{ row }">
          <el-switch :model-value="row.enabled" @click="toggle(row)" />
        </template>
      </el-table-column>
      <el-table-column label="风险" width="110">
        <template #default="{ row }">
          {{ row.risk_level }}<template v-if="row.requires_confirmation"> · 需确认</template>
        </template>
      </el-table-column>
      <el-table-column label="版本" width="160">
        <template #default="{ row }">
          v{{ row.current_version_no ?? '—' }}
          <el-tag v-if="row.pending_version_no" type="warning" size="small">待激活 v{{ row.pending_version_no }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最近变更" min-width="200">
        <template #default="{ row }">
          <el-tag size="small" :type="syncTag(row.last_sync_result).type">{{ syncTag(row.last_sync_result).label }}</el-tag>
          <span class="muted">{{ formatTime(row.last_sync_at) }}</span>
          <el-tooltip v-if="row.last_sync_error" :content="row.last_sync_error">
            <span class="err">查看错误</span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="来源" width="150">
        <template #default="{ row }">{{ row.source_file === 'admin' ? '管理后台' : row.source_file }}</template>
      </el-table-column>
      <el-table-column label="" width="140" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="edit(row.name)">编辑</el-button>
          <el-button link type="danger" @click="removeTool(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="metaEditor"
      :title="`编辑 ${metaForm.kind === 'mcp' ? 'MCP' : '内置'} Tool：${metaForm.name}`"
      width="520px"
      :close-on-click-modal="false"
      :teleported="true"
      append-to="body"
    >
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="实现与参数定义不在此修改；可改摘要说明，并用列表启停控制是否开放。"
        style="margin-bottom: 12px"
      />
      <el-form label-width="80px">
        <el-form-item label="摘要" required>
          <el-input v-model="metaForm.summary" maxlength="255" show-word-limit />
        </el-form-item>
        <el-form-item label="原因" required>
          <el-input v-model="reason" type="textarea" :rows="2" maxlength="200" show-word-limit placeholder="写入审计，至少 2 个字" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="metaEditor = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveMeta">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editor" :title="editing ? `编辑 Tool：${form.name}` : '新建 Tool'" width="1100px" :close-on-click-modal="false" :teleported="true" append-to="body" align-center>
      <el-alert
        v-if="draftWarnings.length"
        type="warning"
        :closable="false"
        show-icon
        title="导入草稿，保存前请逐项核对"
        style="margin-bottom: 12px"
      >
        <ul class="warn-list">
          <li v-for="(w, i) in draftWarnings" :key="i">{{ w }}</li>
        </ul>
      </el-alert>
      <el-form label-width="130px" size="default">
        <h4 class="sec">基本信息</h4>
        <el-form-item label="Tool 名" required>
          <el-input v-model="form.name" :disabled="!!editing" placeholder="如 query_my_leave_list（小写字母、数字、下划线，创建后不可改）" />
        </el-form-item>
        <el-form-item label="名称说明" required>
          <el-input v-model="form.summary" maxlength="255" placeholder="如：查询本人请假记录" />
        </el-form-item>
        <el-form-item label="用途说明">
          <el-input v-model="form.description" type="textarea" :rows="2" maxlength="2000" show-word-limit
            placeholder="给模型看：什么问题该用这个 Tool、能查到什么" />
        </el-form-item>
        <el-form-item label="业务上游" required>
          <el-select v-model="form.upstream" style="width: 420px">
            <el-option v-for="u in upstreams" :key="u.key" :value="u.key"
              :label="`${u.label}（${u.base_url || '未设置'}）`" />
            <el-option v-if="!upstreams.some((u) => u.key === form.upstream)" :value="form.upstream"
              :label="`${form.upstream}（未配置）`" />
          </el-select>
          <span class="hint">上游在「连接配置 → 业务上游 / 连接器」的「业务上游地址」中维护；改上游属于不兼容变更。</span>
        </el-form-item>
        <el-form-item label="接口路径" required>
          <el-input v-model="form.path" placeholder="所选地址下的相对路径，如 /hr/leave/index">
            <template #prepend>GET</template>
          </el-input>
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="form.timeout_seconds" :min="1" :max="60" />
        </el-form-item>

        <h4 class="sec">身份与传参</h4>
        <el-form-item label="注入员工身份">
          <el-switch v-model="form.injectOa" />
          <span class="hint">开启后服务端把当前员工 <code>oa</code> 写入 JSON 参数；模型/客户端给的 oa 一律丢弃。参数表中不能出现 oa。</span>
        </el-form-item>
        <el-form-item label="JSON 参数字段">
          <el-input v-model="form.query_params_field" style="width: 240px" placeholder="如 queryParams" />
          <span class="hint">非「顶层」的参数打包成 JSON 放进这个查询参数；留空则所有参数直接作为查询参数（此时不能注入身份）。</span>
        </el-form-item>
        <el-form-item label="身份查询参数">
          <el-input v-model="form.identityParams" style="width: 240px" placeholder="如 user_id，多个用逗号分隔" />
          <span class="hint">这些查询参数由服务端填入当前员工 oa，模型无法指定、也不能出现在参数表中。须由业务上游按 token 校验该值，否则不安全。</span>
        </el-form-item>

        <h4 class="sec">模型可填的参数</h4>
        <el-table :data="form.params" size="small" border>
          <el-table-column label="参数名" width="130">
            <template #default="{ row }"><el-input v-model="row.name" size="small" /></template>
          </el-table-column>
          <el-table-column label="显示名" width="110">
            <template #default="{ row }"><el-input v-model="row.label" size="small" /></template>
          </el-table-column>
          <el-table-column label="类型" width="160">
            <template #default="{ row }">
              <el-select v-model="row.type" size="small" style="width: 76px">
                <el-option label="文本" value="string" />
                <el-option label="整数" value="integer" />
              </el-select>
              <el-select v-if="row.type === 'string'" v-model="row.format" size="small" style="width: 70px">
                <el-option label="—" value="" />
                <el-option label="日期" value="date" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="必填" width="56">
            <template #default="{ row }"><el-checkbox v-model="row.required" /></template>
          </el-table-column>
          <el-table-column label="可选值" min-width="150">
            <template #default="{ row }"><el-input v-model="row.enumText" size="small" placeholder="0=未报销, 1=已报销" /></template>
          </el-table-column>
          <el-table-column label="最小/最大" width="150">
            <template #default="{ row }">
              <el-input-number v-model="row.minimum" size="small" :controls="false" style="width: 60px" :value-on-clear="null" />
              <el-input-number v-model="row.maximum" size="small" :controls="false" style="width: 60px" :value-on-clear="null" />
            </template>
          </el-table-column>
          <el-table-column label="默认值" width="80">
            <template #default="{ row }"><el-input v-model="row.defaultValue" size="small" /></template>
          </el-table-column>
          <el-table-column label="说明（给模型）" min-width="150">
            <template #default="{ row }"><el-input v-model="row.description" size="small" /></template>
          </el-table-column>
          <el-table-column label="顶层" width="56">
            <template #default="{ row }"><el-checkbox v-model="row.topLevel" /></template>
          </el-table-column>
          <el-table-column label="" width="56">
            <template #default="{ $index }">
              <el-button link type="danger" size="small" @click="form.params.splice($index, 1)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-button size="small" style="margin: 6px 0 4px" @click="form.params.push(emptyParam())">添加参数</el-button>
        <div class="hint">删除参数、新增必填参数、收紧可选值等属于不兼容变更，保存后需在详情中激活。</div>

        <h4 class="sec">返回结果</h4>
        <el-form-item label="结果类型">
          <el-radio-group v-model="form.result_kind">
            <el-radio value="list">列表（表格展示）</el-radio>
            <el-radio value="object">单条记录（详情展示）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-table :data="form.fields" size="small" border>
          <el-table-column label="字段（office-api 返回的键）" min-width="200">
            <template #default="{ row }"><el-input v-model="row.key" size="small" /></template>
          </el-table-column>
          <el-table-column label="显示名称" min-width="160">
            <template #default="{ row }"><el-input v-model="row.label" size="small" placeholder="留空：详情中不显示" /></template>
          </el-table-column>
          <el-table-column v-if="form.result_kind === 'list'" label="列表中显示" width="100">
            <template #default="{ row }"><el-checkbox v-model="row.inList" /></template>
          </el-table-column>
          <el-table-column label="" width="70">
            <template #default="{ $index }">
              <el-button link type="danger" size="small" @click="form.fields.splice($index, 1)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-button size="small" style="margin: 6px 0 4px" @click="addField">添加字段</el-button>
        <div class="hint">只有列在这里的字段会返回给员工（白名单），其余字段丢弃。未勾选「列表中显示」时默认显示前 6 个字段。</div>

        <h4 class="sec">变更原因</h4>
        <el-form-item label="原因" required>
          <el-input v-model="reason" maxlength="200" placeholder="写入审计，至少 2 个字" />
        </el-form-item>
        <template v-if="skillDraft && !editing">
          <h4 class="sec">配套 Skill（LLM 生成）</h4>
          <el-form-item label="同时创建">
            <el-checkbox v-model="withSkill">保存 Tool 后创建 Skill「{{ skillDraft.display_name }}」（{{ skillDraft.name }}）</el-checkbox>
          </el-form-item>
          <template v-if="withSkill">
            <el-form-item label="Skill 名">
              <el-input v-model="skillDraft.name" />
            </el-form-item>
            <el-form-item label="显示名称">
              <el-input v-model="skillDraft.display_name" />
            </el-form-item>
            <el-form-item label="用途说明">
              <el-input v-model="skillDraft.description" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item label="使用说明">
              <el-input v-model="skillDraft.instructions" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item label="示例问题">
              <div>
                <el-tag v-for="(q, i) in skillDraft.examples" :key="i" closable style="margin: 0 6px 6px 0" @close="skillDraft.examples.splice(i, 1)">{{ q }}</el-tag>
              </div>
            </el-form-item>
          </template>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="editor = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="importer" title="从 Apipost 导入" width="720px" :close-on-click-modal="false" :teleported="true" append-to="body">
      <el-form label-width="100px">
        <el-form-item label="分享链接" required>
          <el-input
            v-model="importUrl"
            placeholder="https://docs.apipost.net/docs/detail/xxxx?target_id=yyyy"
            @keyup.enter="runImport"
          />
        </el-form-item>
        <el-form-item label="">
          <el-checkbox v-model="importLlm">用 LLM 补全名称、说明、列表列和配套 Skill</el-checkbox>
        </el-form-item>
      </el-form>
      <div class="hint" style="margin-bottom: 8px">
        仅支持 docs.apipost.net 的公开分享链接（不支持密码保护的文档），仅导入 GET 接口；结果只填入表单，检查后点保存才生效。凭据类字段（如 auth_key、token）不会进入结果白名单。
      </div>
      <el-alert v-for="(e, i) in importErrors" :key="`e${i}`" type="error" :closable="false" :title="e" style="margin-bottom: 6px" />
      <el-table v-if="drafts.length" :data="drafts" size="small" border>
        <el-table-column label="接口" min-width="200">
          <template #default="{ row }">{{ row.source?.name || row.form.name }}</template>
        </el-table-column>
        <el-table-column label="Tool 名" min-width="180">
          <template #default="{ row }"><code>{{ row.form.name }}</code></template>
        </el-table-column>
        <el-table-column label="提示" width="70">
          <template #default="{ row }">{{ row.warnings.length }}</template>
        </el-table-column>
        <el-table-column label="" width="100">
          <template #default="{ row }"><el-button link type="primary" @click="useDraft(row)">填入表单</el-button></template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="importer = false">关闭</el-button>
        <el-button type="primary" :loading="importing" :disabled="importUrl.trim().length < 10" @click="runImport">解析</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="wizardOpen" title="接入业务接口向导" width="960px" :close-on-click-modal="false" top="4vh" :teleported="true" append-to="body">
      <div class="hint" style="margin-bottom: 10px">
        ① 填写服务路径并拉取方法 → ② 点击某一方法 → ③ 填写中文配置与测试值 → ④ 测试成功后入库。服务路径对应 Service 模块，例如
        <code>out_attendance/go_out_application</code>。
      </div>
      <el-alert v-if="wizardError" type="error" :closable="false" :title="wizardError" style="margin-bottom: 8px" />

      <el-form label-width="120px">
        <el-form-item label="服务路径" required>
          <div style="display: flex; gap: 8px; width: 100%">
            <el-input
              v-model="wizard.service"
              placeholder="例如 out_attendance/go_out_application"
              @keyup.enter="wizardDiscover"
            />
            <el-button type="primary" :loading="wizardBusy" @click="wizardDiscover">拉取方法列表</el-button>
          </div>
          <div class="hint">对应目录 service-app/src/service/…/Export.php，将列出该文件全部公开方法。</div>
        </el-form-item>
      </el-form>

      <template v-if="wizardStep === 'pick'">
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px">
          <strong>请点击选择方法</strong>
          <el-input
            v-model="wizard.methodFilter"
            placeholder="按方法名 / 说明筛选"
            clearable
            style="max-width: 280px; margin-left: auto"
          />
          <span class="hint">共 {{ wizard.methods.length }} 个</span>
        </div>
        <el-table
          v-loading="wizardBusy"
          :data="wizardFilteredMethods"
          size="small"
          border
          max-height="420"
          highlight-current-row
          empty-text="请先拉取方法列表"
          @row-click="wizardPickMethod"
        >
          <el-table-column label="方法名" min-width="200">
            <template #default="{ row }">
              <el-button link type="primary">{{ row.name }}</el-button>
            </template>
          </el-table-column>
          <el-table-column label="参数个数" width="90" align="center">
            <template #default="{ row }">
              {{ row.param_count ?? row.param_names?.length ?? '—' }}
            </template>
          </el-table-column>
          <el-table-column label="说明" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">{{ row.summary || '—' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="160">
            <template #default="{ row }">
              <el-tag v-if="row.already_added" type="success" size="small">已添加</el-tag>
              <span v-if="row.already_added && row.tool_name" class="hint" style="margin-left: 4px">{{ row.tool_name }}</span>
              <el-tag v-else type="info" size="small" effect="plain">未添加</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-else>
        <div style="margin-bottom: 10px">
          <el-button link type="primary" @click="wizardStep = 'pick'">← 返回方法列表</el-button>
          <span style="margin-left: 8px">当前方法：<code>{{ wizard.method }}</code></span>
        </div>
        <el-form label-width="120px">
          <el-form-item label="工具名称" required>
            <el-input v-model="wizard.name" maxlength="64" placeholder="对话里使用的工具英文名，建议小写+下划线" />
            <div class="hint">入库后的 Tool 唯一名，例如 query_my_travel_expense_list</div>
          </el-form-item>
          <el-form-item label="用途说明">
            <el-input v-model="wizard.summary" maxlength="255" placeholder="给管理员和模型看的中文说明" />
          </el-form-item>
          <el-form-item label="调用方式">
            <el-select v-model="wizard.call" style="width: 100%">
              <el-option v-for="o in CALL_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
            </el-select>
            <div class="hint">决定参数如何传给 PHP 方法；分页接口一般选「分页列表」</div>
          </el-form-item>
          <el-form-item label="操作类型">
            <el-radio-group v-model="wizard.op">
              <el-radio-button v-for="o in OP_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</el-radio-button>
            </el-radio-group>
            <div class="hint">写入类会要求确认与幂等键</div>
          </el-form-item>
          <el-form-item label="风险等级">
            <el-radio-group v-model="wizard.risk">
              <el-radio-button v-for="o in RISK_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <el-form-item label="请求参数">
            <div style="width: 100%">
              <div class="hint" style="margin-bottom: 6px">
                每个形参单独配置类型与测试值（含对象/数组/文件）。对象用键值对、数组用多行值；「测试值」仅本页试调。
              </div>
              <el-table :data="wizard.paramRows" size="small" border empty-text="暂无参数，可点击下方添加">
                <el-table-column label="#" width="48" align="center">
                  <template #default="{ row }">{{ row.position || '' }}</template>
                </el-table-column>
                <el-table-column label="参数名" width="120">
                  <template #default="{ row }"><el-input v-model="row.name" placeholder="英文名" /></template>
                </el-table-column>
                <el-table-column label="中文名" width="110">
                  <template #default="{ row }"><el-input v-model="row.label" placeholder="展示名" /></template>
                </el-table-column>
                <el-table-column label="类型" width="130">
                  <template #default="{ row }">
                    <el-select v-model="row.type" style="width: 100%" @change="wizardOnParamTypeChange(row)">
                      <el-option v-for="o in PARAM_TYPE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column label="必填" width="64" align="center">
                  <template #default="{ row }"><el-checkbox v-model="row.required" /></template>
                </el-table-column>
                <el-table-column label="说明" min-width="100">
                  <template #default="{ row }"><el-input v-model="row.description" placeholder="可选" /></template>
                </el-table-column>
                <el-table-column label="测试值" min-width="220">
                  <template #default="{ row }">
                    <template v-if="row.type === 'object' || row.type === 'array'">
                      <div
                        v-for="(e, i) in row.objectEntries"
                        :key="i"
                        style="display: flex; gap: 4px; margin-bottom: 4px; align-items: center"
                      >
                        <el-input
                          v-if="row.type === 'object'"
                          v-model="e.key"
                          placeholder="键"
                          style="width: 40%"
                        />
                        <el-input v-model="e.value" :placeholder="row.type === 'array' ? '数组项' : '值'" />
                        <el-button link type="danger" @click="wizardRemoveObjectEntry(row, i)">删</el-button>
                      </div>
                      <el-button link type="primary" @click="wizardAddObjectEntry(row)">加一项</el-button>
                    </template>
                    <el-input
                      v-else-if="row.type === 'boolean'"
                      v-model="row.testValue"
                      placeholder="true / false / 是"
                    />
                    <el-input
                      v-else
                      v-model="row.testValue"
                      :placeholder="row.type === 'file' ? '文件路径或 ID' : '试调时用'"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="" width="64">
                  <template #default="{ $index }">
                    <el-button link type="danger" @click="wizardRemoveParamRow($index)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
              <el-button style="margin-top: 6px" @click="wizardAddParamRow">添加参数</el-button>
            </div>
          </el-form-item>

          <el-form-item label="返回形态">
            <el-radio-group v-model="wizard.resultKind">
              <el-radio-button v-for="o in RESULT_KIND_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="返回字段" required>
            <div style="width: 100%">
              <div class="hint" style="margin-bottom: 6px">白名单字段：只有这里列出的字段会回给模型。「字段名」为接口里的英文键，「中文名」用于展示。</div>
              <el-table :data="wizard.resultRows" size="small" border>
                <el-table-column label="字段名" min-width="140">
                  <template #default="{ row }"><el-input v-model="row.field" placeholder="如 id、date" /></template>
                </el-table-column>
                <el-table-column label="中文名" min-width="140">
                  <template #default="{ row }"><el-input v-model="row.label" placeholder="如 单号、日期" /></template>
                </el-table-column>
                <el-table-column label="" width="64">
                  <template #default="{ $index }">
                    <el-button link type="danger" @click="wizardRemoveResultRow($index)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
              <el-button style="margin-top: 6px" @click="wizardAddResultRow">添加返回字段</el-button>
            </div>
          </el-form-item>

          <el-form-item label="测试员工" required>
            <el-input v-model="wizard.oa" placeholder="员工 OA 账号（USER_ID）" style="max-width: 280px" />
            <div class="hint">用该员工身份真实调用接口，请使用你有权限的测试账号</div>
          </el-form-item>
          <el-form-item label="审计原因">
            <el-input v-model="wizard.reason" maxlength="200" placeholder="写入操作审计，可留空自动生成" />
          </el-form-item>
        </el-form>

        <el-alert
          v-if="wizardProbeOk"
          type="success"
          :closable="false"
          title="测试成功，可以入库"
          style="margin-bottom: 8px"
        />
        <div v-if="wizardProbePreview" class="hint" style="margin-bottom: 4px">测试返回预览（仅供核对）：</div>
        <pre v-if="wizardProbePreview" class="hint" style="max-height: 180px; overflow: auto; white-space: pre-wrap">{{ wizardProbePreview }}</pre>
      </template>

      <template #footer>
        <el-button @click="wizardOpen = false">关闭</el-button>
        <template v-if="wizardStep === 'config'">
          <el-button :loading="wizardBusy" @click="wizardProbe">测试接口</el-button>
          <el-button type="primary" :loading="wizardBusy" :disabled="!wizardProbeOk" @click="wizardSave">测试成功后入库</el-button>
        </template>
      </template>
    </el-dialog>

    <el-drawer v-model="drawer" :title="detail?.name || 'Tool'" size="720px" :teleported="true" append-to="body">
      <el-skeleton v-if="!detail" :rows="6" />
      <template v-else>
        <el-alert
          v-if="!detail.registered"
          type="warning"
          :closable="false"
          show-icon
          :title="`未注册到运行时：${detail.unregistered_reasons.join('；')}`"
          style="margin-bottom: 12px"
        />
        <el-alert
          v-if="needsOpenOaRepair(detail)"
          type="error"
          :closable="false"
          show-icon
          title="这是 open-oa 调用 Tool，编辑时曾丢失 ANew 目标。请点「修复 open-oa」补回 service/method，或用「接入业务接口」同名覆盖。"
          style="margin-bottom: 12px"
        />
        <div style="margin-bottom: 12px; display: flex; gap: 8px; flex-wrap: wrap">
          <el-button type="primary" plain size="small" @click="edit(detail.name)">编辑</el-button>
          <el-button
            v-if="needsOpenOaRepair(detail) || detail.kind === 'open_oa_invoke'"
            type="warning"
            plain
            size="small"
            @click="repairOpenOa"
          >
            修复 open-oa
          </el-button>
          <el-button type="danger" plain size="small" @click="removeTool(detail)">删除</el-button>
        </div>

        <template v-if="guide">
          <h4>实现说明</h4>
          <p class="guide-summary">{{ guide.summary || detail.summary || '—' }}</p>
          <dl class="guide-meta">
            <div v-if="guide.runtime"><dt>运行时</dt><dd>{{ guide.runtime }}</dd></div>
            <div v-if="guide.builtin_id"><dt>内置 ID</dt><dd><code>{{ guide.builtin_id }}</code></dd></div>
            <div v-if="guide.mcp_server">
              <dt>MCP 连接</dt>
              <dd>
                {{ guide.mcp_server.display_name || guide.mcp_server.name || guide.mcp_server.id }}
                <span v-if="guide.mcp_server.transport" class="muted">· {{ guide.mcp_server.transport }}</span>
                <el-tag v-if="guide.mcp_server.missing" size="small" type="danger" style="margin-left: 6px">连接缺失</el-tag>
              </dd>
            </div>
            <div v-if="guide.mcp_tool_name"><dt>远端工具名</dt><dd><code>{{ guide.mcp_tool_name }}</code></dd></div>
            <div v-if="guide.http">
              <dt>HTTP</dt>
              <dd>
                <code>{{ guide.http.method || '—' }} {{ guide.http.path || '—' }}</code>
                <span v-if="guide.http.upstream" class="muted">· 上游 {{ guide.http.upstream }}</span>
              </dd>
            </div>
            <div v-if="guide.http?.invoke_service">
              <dt>ANew</dt>
              <dd>
                <code>{{ guide.http.invoke_service }}.{{ guide.http.invoke_method || '—' }}</code>
              </dd>
            </div>
            <div v-if="guide.risk_level"><dt>风险等级</dt><dd>{{ guide.risk_level }}</dd></div>
          </dl>
          <p v-if="guide.how" class="guide-how">{{ guide.how }}</p>
          <p v-if="guide.description" class="guide-desc">{{ guide.description }}</p>
          <ul v-if="guide.constraints?.length" class="warn-list">
            <li v-for="(c, i) in guide.constraints" :key="i">{{ c }}</li>
          </ul>
          <p v-if="guide.edit_hint" class="muted">{{ guide.edit_hint }}</p>

          <h4 v-if="guideParams.length">模型可填参数</h4>
          <el-table v-if="guideParams.length" :data="guideParams" size="small" empty-text="无">
            <el-table-column label="参数" prop="name" width="120" />
            <el-table-column label="说明" min-width="160">
              <template #default="{ row }">{{ row.label }}{{ row.description ? `：${row.description}` : '' }}</template>
            </el-table-column>
            <el-table-column label="类型" width="90" prop="type" />
            <el-table-column label="必填" width="70">
              <template #default="{ row }">{{ row.required ? '是' : '否' }}</template>
            </el-table-column>
            <el-table-column label="枚举" min-width="100">
              <template #default="{ row }">{{ row.enum || '—' }}</template>
            </el-table-column>
          </el-table>

          <h4 v-if="guide.sandbox_policy || detail.sandbox_policy">沙箱策略</h4>
          <pre
            v-if="guide.sandbox_policy || detail.sandbox_policy"
            class="schema"
          >{{ JSON.stringify(guide.sandbox_policy || detail.sandbox_policy, null, 2) }}</pre>

          <h4 v-if="guide.result">结果形态</h4>
          <pre v-if="guide.result" class="schema">{{ JSON.stringify(guide.result, null, 2) }}</pre>

          <h4 v-if="guide.input_schema">MCP inputSchema</h4>
          <pre v-if="guide.input_schema" class="schema">{{ JSON.stringify(guide.input_schema, null, 2) }}</pre>
        </template>

        <h4>{{ isOfficeTool(detail) ? '版本' : (detail.versions?.length ? '同步记录' : '版本') }}</h4>
        <el-empty
          v-if="!detail.versions?.length"
          :description="guide ? '此类 Tool 无版本链（实现见上方「实现说明」）' : '此类 Tool 无版本链'"
          :image-size="48"
        />
        <template v-else>
          <el-table :data="detail.versions" size="small">
            <el-table-column label="版本" width="80">
              <template #default="{ row }">v{{ row.version_no }}</template>
            </el-table-column>
            <el-table-column label="规范版本" prop="spec_version" width="90" />
            <el-table-column label="兼容性" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="COMPAT_LEVEL[row.compat_level]?.type">{{ COMPAT_LEVEL[row.compat_level]?.label || row.compat_level }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="哈希" prop="schema_hash" width="150" />
            <el-table-column label="同步时间" width="160">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="" min-width="120">
              <template #default="{ row }">
                <el-tag v-if="row.is_current" type="success" size="small">当前</el-tag>
                <el-tag v-if="row.is_pending" type="warning" size="small">待激活</el-tag>
                <el-button v-if="!row.is_current" link type="primary" size="small" @click="activate(row.version_no)">激活</el-button>
              </template>
            </el-table-column>
          </el-table>

          <h4>版本对比</h4>
          <div style="display: flex; gap: 8px; align-items: center">
            <el-select v-model="diffRange.from" style="width: 110px">
              <el-option v-for="v in detail.versions" :key="v.version_no" :label="`v${v.version_no}`" :value="v.version_no" />
            </el-select>
            →
            <el-select v-model="diffRange.to" style="width: 110px">
              <el-option v-for="v in detail.versions" :key="v.version_no" :label="`v${v.version_no}`" :value="v.version_no" />
            </el-select>
            <el-button @click="loadDiff">对比</el-button>
          </div>
          <template v-if="diff">
            <p>
              结论：<el-tag :type="COMPAT_LEVEL[diff.compat_level]?.type || 'info'">{{ COMPAT_LEVEL[diff.compat_level]?.label || '无变化' }}</el-tag>
            </p>
            <el-table :data="diff.changes" size="small" empty-text="无差异">
              <el-table-column label="字段" prop="field" width="200" />
              <el-table-column label="变化" width="80" prop="change" />
              <el-table-column label="旧" min-width="140">
                <template #default="{ row }"><code>{{ fmt(row.old) }}</code></template>
              </el-table-column>
              <el-table-column label="新" min-width="140">
                <template #default="{ row }"><code>{{ fmt(row.new) }}</code></template>
              </el-table-column>
              <el-table-column label="" width="80">
                <template #default="{ row }"><el-tag v-if="row.breaking" type="danger" size="small">不兼容</el-tag></template>
              </el-table-column>
            </el-table>
          </template>

          <h4>当前版本定义</h4>
          <pre class="schema">{{ JSON.stringify(detail.current_schema, null, 2) }}</pre>
        </template>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.warn-list {
  margin: 4px 0 0;
  padding-left: 18px;
  line-height: 1.7;
}
.muted {
  color: var(--tech-text-2);
  font-size: 12px;
  margin-left: 4px;
}
.err {
  color: var(--tech-danger);
  font-size: 12px;
  margin-left: 6px;
  cursor: help;
}
.schema {
  background: var(--tech-code-bg);
  padding: 8px;
  font-size: 12px;
  max-height: 360px;
  overflow: auto;
}
.guide-summary {
  margin: 0 0 8px;
  font-size: 14px;
  color: var(--tech-text-1);
}
.guide-how,
.guide-desc {
  margin: 8px 0;
  line-height: 1.65;
  color: var(--tech-text-1);
  white-space: pre-wrap;
}
.guide-meta {
  margin: 0 0 8px;
  display: grid;
  gap: 6px;
}
.guide-meta > div {
  display: grid;
  grid-template-columns: 88px 1fr;
  gap: 8px;
  font-size: 13px;
  line-height: 1.5;
}
.guide-meta dt {
  margin: 0;
  color: var(--tech-text-2);
}
.guide-meta dd {
  margin: 0;
  word-break: break-all;
}
code {
  font-size: 12px;
  word-break: break-all;
}
.sec {
  margin: 14px 0 8px;
  border-left: 3px solid var(--tech-cyan);
  padding-left: 8px;
}
.hint {
  color: var(--tech-text-2);
  font-size: 12px;
  margin-left: 8px;
  line-height: 1.6;
}
</style>
