<script setup lang="ts">
/**
 * 新建 Tool / 接入业务接口 共用契约区：
 * 默认极简（参数表+测调）；专家模式展开身份/槽位/放置/Schema。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import CallSignatureEditor from './CallSignatureEditor.vue'
import ParamTableEditor from './ParamTableEditor.vue'
import SchemaTreeEditor from './SchemaTreeEditor.vue'
import SchemaValueEditor from './SchemaValueEditor.vue'
import { type FieldRow, type ToolForm } from '../catalogForm'
import {
  applySlotsToToolForm, inferInvokeCall, previewCall, slotsFromToolForm, type CallSlot,
} from '../callSignature'
import { buildWirePreview, formatWirePreview } from '../paramWire'
import { buildArgsFromValues, mergeValuesOnSchemaChange } from '../schemaValue'
import { flattenBagSchema, unwrapBagArgs } from '../wizardCallArgs'
import { mergeProbeResultFields } from '../probeResultFields'
import {
  ensureSimpleWireDefaults,
  formatMissingRequiredMessage,
  missingRequiredParamNames,
} from '../simpleWire'

const props = withDefaults(defineProps<{
  form: ToolForm
  slots: CallSlot[]
  methodName: string
  /** simple=业务极简；expert=研发全量 */
  contractMode?: 'simple' | 'expert'
  /** 是否展示测调区（新建/编辑/向导均为 true） */
  showProbe?: boolean
  probeBusy?: boolean
  probeOk?: boolean
  probeError?: string
  /** 测调实际发出的请求参数 JSON */
  probeArgsPreview?: string
  /** 测调返回数据 JSON */
  probePreview?: string
  enrichBusy?: boolean
  /** 测调用的操作类型 */
  op?: string
}>(), {
  contractMode: 'simple',
  showProbe: false,
  probeBusy: false,
  probeOk: false,
  probeError: '',
  probeArgsPreview: '',
  probePreview: '',
  enrichBusy: false,
  op: 'read',
})

const emit = defineEmits<{
  (e: 'update:slots', v: CallSlot[]): void
  (e: 'update:contractMode', v: 'simple' | 'expert'): void
  (e: 'probe', payload: {
    oa: string
    args: Record<string, unknown>
    call: string
    op: string
    mode: 'export' | 'http'
    identity_args: Record<string, string>
  }): void
  (e: 'enrich'): void
}>()

const isSimple = computed(() => props.contractMode !== 'expert')
const complexSigCollapse = ref<string[]>([])
const advancedSchemaCollapse = ref<string[]>([])
const probeOa = ref('')
const probeValues = ref<Record<string, unknown>>({})
const paramTableRef = ref<InstanceType<typeof ParamTableEditor> | null>(null)

watch(
  () => props.form.modelParams,
  (next, prev) => {
    if (props.showProbe) {
      // Schema 变更时保留已填值，并用 default 补齐新键
      probeValues.value = mergeValuesOnSchemaChange(prev ?? {}, next ?? {}, probeValues.value)
    }
  },
  { deep: true },
)

watch(
  () => props.showProbe,
  (on) => {
    if (on) seedProbeDefaults()
  },
)

/** 由身份/打包/顶层推导的只读调用预览 */
const callPreview = computed(() => previewCall(props.methodName, props.slots))

const hasExportTarget = computed(() =>
  !!(props.form.invoke_service.trim() && props.form.invoke_method.trim()),
)
const hasHttpTarget = computed(() =>
  !!(props.form.upstream.trim() && props.form.path.trim() && props.form.path.trim().startsWith('/')),
)
const probeMode = computed<'export' | 'http' | null>(() => {
  if (hasExportTarget.value) return 'export'
  if (hasHttpTarget.value) return 'http'
  return null
})
const canProbe = computed(() => props.showProbe && !!probeMode.value)
const probeHint = computed(() => {
  if (hasExportTarget.value) return ''
  if (hasHttpTarget.value) {
    const m = (props.form.method || 'GET').toUpperCase()
    return `将按业务上游 HTTP（${m}）测调，身份注入与运行时一致`
  }
  return '填写 Export 服务路径+方法，或填写业务上游与接口路径后可测调'
})

const needsBagField = computed(() => {
  if (props.form.identityPlacement === 'bag' && props.form.injectOa) return true
  return Object.values(props.form.modelParams).some((n) => n.placement === 'bag')
})

const wirePreviewText = computed(() => {
  const top = (props.form.topLevelFields || '').split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean)
  const preview = buildWirePreview({
    isExport: hasExportTarget.value,
    method: props.form.method || 'GET',
    contentType: props.form.content_type || null,
    bagField: props.form.query_params_field,
    identityParamName: props.form.identityParamName,
    injectOa: props.form.injectOa,
    identityPlacement: props.form.identityPlacement,
    modelParams: props.form.modelParams,
    topLevelFields: top,
    values: props.showProbe ? probeValues.value : {},
    previewOa: probeOa.value.trim() || '<oa>',
  })
  return `${preview.note}\n${formatWirePreview(preview)}`
})

const simpleWireSummary = computed(() => {
  const id = props.form.injectOa
    ? `身份自动注入（${props.form.identityParamName || 'oa'}）`
    : '未注入身份'
  const call = props.form.invoke_call || '—'
  if (hasExportTarget.value) return `${id} · call=${call}`
  const m = (props.form.method || 'GET').toUpperCase()
  return `${id} · HTTP ${m}`
})

function setContractMode(mode: 'simple' | 'expert') {
  emit('update:contractMode', mode)
}

/** 复杂形参编辑器为源：写回 form，再通知父组件更新槽位 */
function onSlotsUpdate(slots: CallSlot[]) {
  applySlotsToToolForm(props.form, slots)
  props.form.invoke_call = inferInvokeCall(slots)
  emit('update:slots', slots)
}

/** 身份/打包改动时反推槽位预览；form 为源 */
function syncSlotsFromIdentity() {
  if (props.form.injectOa && props.form.identityPlacement === 'bag' && !props.form.query_params_field.trim()) {
    props.form.query_params_field = 'params'
  }
  const next = slotsFromToolForm(props.form)
  props.form.invoke_call = inferInvokeCall(next)
  emit('update:slots', next)
}

function onParamTableChange() {
  syncSlotsFromIdentity()
}

function addField() {
  props.form.fields.push({
    key: '', label: '', inList: props.form.result_kind === 'list',
  })
}

function seedProbeDefaults() {
  if (!props.showProbe) return
  probeValues.value = mergeValuesOnSchemaChange({}, props.form.modelParams, probeValues.value)
}

function buildProbeArgs(): Record<string, unknown> {
  const call = inferInvokeCall(props.slots)
  const raw = buildArgsFromValues(props.form.modelParams, probeValues.value)
  return unwrapBagArgs(call, raw)
}

/** 按表单「写入参数名」生成强制身份实参，不写死 oa/userId */
function buildIdentityArgs(oa: string): Record<string, string> {
  if (!props.form.injectOa) return {}
  const key = (props.form.identityParamName || 'oa').trim() || 'oa'
  return { [key]: oa }
}

function runProbe() {
  if (!probeOa.value.trim() || !probeMode.value) return
  paramTableRef.value?.flush()
  ensureSimpleWireDefaults(props.form, props.contractMode)
  const missing = missingRequiredParamNames(props.form.modelParams, probeValues.value)
  if (missing.length) {
    ElMessage.warning(formatMissingRequiredMessage(missing))
    return
  }
  const call = inferInvokeCall(props.slots)
  props.form.invoke_call = call
  const oa = probeOa.value.trim()
  emit('probe', {
    oa,
    args: buildProbeArgs(),
    call,
    op: props.op || 'read',
    mode: probeMode.value,
    identity_args: buildIdentityArgs(oa),
  })
}

function runEnrich() {
  if (!props.probeOk) return
  emit('enrich')
}

/** 父组件测调成功后调用，回填返回字段 */
function applyProbeData(data: unknown) {
  const kind = props.form.result_kind === 'object' ? 'object' : 'list'
  const existing = props.form.fields.map((f) => ({ field: f.key, label: f.label }))
  const merged = mergeProbeResultFields(data, existing, kind)
  if (!merged.length) return 0
  props.form.fields = merged.map((r) => ({
    key: r.field,
    label: r.label,
    inList: kind === 'list',
  })) as FieldRow[]
  if (Array.isArray(data) || (data && typeof data === 'object' && Array.isArray((data as { list?: unknown }).list))) {
    props.form.result_kind = 'list'
  }
  return merged.length
}

/**
 * 保存前同步槽位与 invoke_call。
 * 日常路径以 form 为准；仅展开「复杂调用形参」时槽位可能是源。
 */
function flush() {
  paramTableRef.value?.flush()
  ensureSimpleWireDefaults(props.form, props.contractMode)
  const complexOpen = !isSimple.value && complexSigCollapse.value.includes('sig')
  if (complexOpen) {
    if (props.form.injectOa && props.form.identityPlacement === 'bag') {
      const bag = props.slots.find((s) => s.role === 'bag')
      if (bag?.name.trim()) props.form.query_params_field = bag.name.trim()
      const scalars = props.slots.filter((s) => s.role === 'scalar')
      props.form.topLevelFields = scalars.map((s) => s.name.trim()).filter(Boolean).join(', ')
      props.form.invoke_call = inferInvokeCall(props.slots)
    } else {
      applySlotsToToolForm(props.form, props.slots)
      props.form.invoke_call = inferInvokeCall(props.slots)
    }
    return
  }
  const next = slotsFromToolForm(props.form)
  props.form.invoke_call = inferInvokeCall(next)
  emit('update:slots', next)
}

/** 向导入库：整包 call 再摊平袋字段（与运行时 args 形态一致） */
function flattenModelParamsForSave() {
  const call = props.form.invoke_call || inferInvokeCall(props.slots)
  props.form.modelParams = flattenBagSchema(call, props.form.modelParams, probeValues.value)
}

function getProbeOa() {
  return probeOa.value.trim()
}

function reloadFromForm() {
  ensureSimpleWireDefaults(props.form, props.contractMode)
  syncSlotsFromIdentity()
  paramTableRef.value?.reload()
  seedProbeDefaults()
}

function syncParamRowsFromForm() {
  paramTableRef.value?.reload()
}

defineExpose({
  flush,
  flattenModelParamsForSave,
  applyProbeData,
  syncParamRowsFromForm,
  reloadFromForm,
  getProbeOa,
  buildProbeArgs,
  buildIdentityArgs,
})
</script>

<template>
  <div class="contract-form">
    <div class="mode-bar">
      <span class="mode-label">配置模式</span>
      <el-radio-group
        :model-value="contractMode"
        size="small"
        @update:model-value="(v: string | number | boolean | undefined) => setContractMode(v === 'expert' ? 'expert' : 'simple')"
      >
        <el-radio-button value="simple">极简</el-radio-button>
        <el-radio-button value="expert">专家</el-radio-button>
      </el-radio-group>
      <span class="hint mode-hint">{{ isSimple ? '业务默认：只填参数说明与测调值' : '可改身份、形参槽位、放置与编码' }}</span>
    </div>

    <template v-if="isSimple">
      <div class="simple-summary">{{ simpleWireSummary }} · 员工身份由服务端写入，模型无法伪造</div>
    </template>
    <template v-else>
      <h4 class="sec">身份注入</h4>
      <el-form-item label="注入员工身份">
        <el-switch v-model="form.injectOa" @change="syncSlotsFromIdentity" />
        <span class="hint">开启后由服务端写入当前员工账号，模型无法伪造。</span>
      </el-form-item>
      <template v-if="form.injectOa">
        <el-form-item label="写入参数名" required>
          <el-input
            v-model="form.identityParamName"
            style="width: 200px"
            placeholder="如 oa 或 user_id"
            @change="syncSlotsFromIdentity"
          />
        </el-form-item>
        <el-form-item label="身份放在哪">
          <el-radio-group v-model="form.identityPlacement" @change="syncSlotsFromIdentity">
            <el-radio value="independent">独立参数</el-radio>
            <el-radio value="bag">写入打包字段内</el-radio>
          </el-radio-group>
        </el-form-item>
      </template>
      <el-form-item v-if="needsBagField || form.query_params_field" label="打包字段名">
        <el-input
          v-model="form.query_params_field"
          style="width: 200px"
          placeholder="如 params、queryParams"
          @change="syncSlotsFromIdentity"
        />
        <span class="hint">参数表「装入袋」或身份进袋时使用。</span>
      </el-form-item>

      <h4 class="sec">调用签名</h4>
      <div class="preview-box">
        <code class="preview-code">{{ callPreview }}</code>
      </div>
      <div class="hint sync-hint">
        call={{ form.invoke_call || '—' }}
        · 注入={{ form.injectOa ? '是' : '否' }}
        · 身份键={{ form.identityParamName || '—' }}
        · 打包={{ form.query_params_field || '（无）' }}
      </div>
      <el-collapse v-model="complexSigCollapse" style="margin-bottom: 8px">
        <el-collapse-item title="复杂调用形参（多袋等）" name="sig">
          <CallSignatureEditor
            :method-name="methodName"
            :slots="slots"
            @update:slots="onSlotsUpdate"
          />
        </el-collapse-item>
      </el-collapse>
    </template>

    <h4 class="sec">模型可填的参数</h4>
    <div v-if="!isSimple" class="hint" style="margin-bottom: 8px; margin-left: 0">
      表格维护顶层参数的类型、放置与编码；嵌套结构用下方高级 Schema。
    </div>
    <ParamTableEditor
      ref="paramTableRef"
      :form="form"
      :is-export="hasExportTarget"
      :simple="isSimple"
      @change="onParamTableChange"
    />
    <el-collapse v-if="!isSimple" v-model="advancedSchemaCollapse" style="margin: 8px 0">
      <el-collapse-item title="高级：Schema 树（嵌套 object/array）" name="schema">
        <SchemaTreeEditor v-model="form.modelParams" mode="params" />
      </el-collapse-item>
    </el-collapse>

    <h4 class="sec">请求预览</h4>
    <div class="hint" style="margin-bottom: 4px; margin-left: 0">按当前参数表与测试值即时生成（测调前可核对）。</div>
    <pre class="probe-pre wire-pre">{{ wirePreviewText }}</pre>

    <template v-if="showProbe">
      <h4 class="sec">测试接口</h4>
      <el-alert
        v-if="!canProbe || probeHint"
        type="info"
        :closable="false"
        :title="probeHint || '填写 Export 服务路径与方法名，或业务上游与接口路径后可测调'"
        style="margin-bottom: 8px"
      />
      <el-form-item label="测试员工" required>
        <el-input v-model="probeOa" placeholder="员工 OA 账号" style="max-width: 280px" />
        <span class="hint">用该员工身份真实调用</span>
      </el-form-item>
      <el-form-item label="测试值">
        <div style="width: 100%">
          <SchemaValueEditor v-model="probeValues" :schema="form.modelParams" />
        </div>
      </el-form-item>
      <el-form-item label="">
        <el-button type="primary" :loading="probeBusy" :disabled="!canProbe || !probeOa.trim()" @click="runProbe">
          测试接口
        </el-button>
        <el-tag v-if="probeOk" type="success" style="margin-left: 8px">测调成功</el-tag>
        <el-button
          v-if="probeOk"
          type="success"
          plain
          style="margin-left: 8px"
          :loading="enrichBusy"
          @click="runEnrich"
        >
          用模型生成完整 Schema
        </el-button>
        <span v-if="probeOk" class="hint">空字段补全，已有文案保留；可再手工改</span>
      </el-form-item>
      <el-alert v-if="probeError" type="error" :closable="false" :title="probeError" style="margin-bottom: 8px" />
      <div v-if="probeArgsPreview || probePreview" class="probe-blocks">
        <div v-if="probeArgsPreview" class="probe-block">
          <div class="probe-label">请求参数</div>
          <pre class="probe-pre">{{ probeArgsPreview }}</pre>
        </div>
        <div v-if="probePreview" class="probe-block">
          <div class="probe-label">返回数据</div>
          <pre class="probe-pre">{{ probePreview }}</pre>
        </div>
      </div>
    </template>

    <h4 class="sec">返回结果</h4>
    <el-form-item label="结果类型">
      <el-radio-group v-model="form.result_kind">
        <el-radio value="list">列表</el-radio>
        <el-radio value="object">单条记录</el-radio>
      </el-radio-group>
    </el-form-item>
    <div class="hint" style="margin-bottom: 6px; margin-left: 0">
      白名单字段；测调成功后可自动回填。字段名支持多级点路径（如 user.name、get.params1）。
    </div>
    <el-table :data="form.fields" size="small" border>
      <el-table-column label="字段名" min-width="180">
        <template #default="{ row }"><el-input v-model="row.key" size="small" placeholder="如 id" /></template>
      </el-table-column>
      <el-table-column label="显示名称" min-width="140">
        <template #default="{ row }"><el-input v-model="row.label" size="small" /></template>
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
  </div>
</template>

<style scoped>
.mode-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.mode-label {
  font-size: 13px;
  font-weight: 600;
}
.mode-hint {
  margin-left: 0;
}
.simple-summary {
  margin-bottom: 12px;
  padding: 8px 12px;
  font-size: 12px;
  color: var(--el-text-color-regular);
  background: var(--el-fill-color-light);
  border-radius: 6px;
  line-height: 1.5;
}
.sec {
  margin: 16px 0 10px;
  font-size: 14px;
  font-weight: 600;
}
.hint {
  margin-left: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
.sync-hint {
  margin: 4px 0 8px;
  display: block;
  margin-left: 0;
}
.preview-box {
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}
.preview-code {
  font-size: 13px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  word-break: break-all;
}
.probe-blocks {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 8px;
}
.probe-label {
  margin-bottom: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-regular);
}
.probe-pre {
  max-height: 180px;
  overflow: auto;
  white-space: pre-wrap;
  font-size: 12px;
  padding: 8px;
  margin: 0;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}
.wire-pre {
  max-height: 220px;
  margin-bottom: 8px;
}
</style>
