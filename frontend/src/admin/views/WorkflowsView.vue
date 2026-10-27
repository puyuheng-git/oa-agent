<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errorMessage, http } from '@/shared/http'
import { formatTime } from '@/shared/format'
import { can } from '../auth'
import {
  DRAFT_STATUS,
  displayValue,
  groupFields,
  localValidate,
  type FieldDef,
  type WorkflowDetail,
  type WorkflowSchema,
} from '../ops'

const WF = '/v1/admin/workflows/oa_assistant'

const detail = ref<WorkflowDetail | null>(null)
const schema = ref<WorkflowSchema | null>(null)
const loadError = ref('')
const form = ref<Record<string, any> | null>(null)
const busy = ref(false)
const diffTitle = ref('')
const diffRows = ref<{ key: string; old: unknown; new: unknown }[] | null>(null)

const fields = computed<FieldDef[]>(() => schema.value?.fields ?? [])
const fieldOf = (key: string) => fields.value.find((f) => f.key === key)
const sections = computed(() => groupFields(fields.value, schema.value?.groups))
const draft = computed(() => detail.value?.draft ?? null)
// 旧版本没有的配置项按默认值显示与保存
const withDefaults = (content: Record<string, any>) => ({ ...(schema.value?.defaults ?? {}), ...content })
// 配置内容是纯 JSON；structuredClone 无法复制 Vue 响应式代理（DataCloneError）
const cloneJson = <T,>(value: T): T => JSON.parse(JSON.stringify(value))
const dirty = computed(
  () => !!form.value && JSON.stringify(form.value) !== JSON.stringify(draft.value ? withDefaults(draft.value.content) : null),
)
const localErrors = computed(() => (form.value ? localValidate(form.value, fields.value) : []))
const publishable = computed(
  () =>
    !!draft.value &&
    !dirty.value &&
    draft.value.status === 'validated' &&
    draft.value.validated_hash === draft.value.content_hash,
)

async function load() {
  loadError.value = ''
  try {
    const [d, s] = await Promise.all([http.get<WorkflowDetail>(WF), http.get<WorkflowSchema>(`${WF}/schema`)])
    detail.value = d
    schema.value = s
    form.value = d.draft ? cloneJson(withDefaults(d.draft.content)) : null
    if (d.draft) await showDiff(null, 'draft')
    else diffRows.value = null
  } catch (e) {
    loadError.value = errorMessage(e)
  }
}

const draftCard = ref<{ $el: HTMLElement } | null>(null)

function newDraft() {
  form.value = cloneJson(withDefaults(detail.value?.current_version?.content ?? {}))
  draftCard.value?.$el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function run<T>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> {
  busy.value = true
  try {
    const r = await fn()
    if (ok) ElMessage.success(ok)
    return r
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    busy.value = false
  }
}

async function saveDraft() {
  if (!form.value) return
  await run(() => http.put(`${WF}/draft`, { content: form.value }), '草稿已保存')
  await load()
}

async function validate() {
  if (dirty.value) await run(() => http.put(`${WF}/draft`, { content: form.value }))
  const r = await run(() => http.post<{ validation: { ok: boolean; errors: string[] } }>(`${WF}/draft/validate`))
  if (r) {
    if (r.validation.ok) ElMessage.success('校验通过，可以发布')
    else ElMessage.warning('校验未通过，请按提示修改')
  }
  await load()
}

async function discard() {
  if (!draft.value) {
    form.value = null
    return
  }
  try {
    await ElMessageBox.confirm('丢弃当前草稿？已发布版本不受影响。', '丢弃草稿')
  } catch {
    return
  }
  await run(() => http.del(`${WF}/draft`), '草稿已丢弃')
  await load()
}

async function askReason(title: string): Promise<string | null> {
  try {
    const { value } = await ElMessageBox.prompt('请填写原因（写入审计与发布记录）', title, {
      inputValidator: (v: string) => (v && v.trim().length >= 2) || '至少 2 个字',
    })
    return value.trim()
  } catch {
    return null
  }
}

async function publish() {
  if (!draft.value) return
  const reason = await askReason('发布配置（新运行立即使用；进行中的运行仍按原版本执行）')
  if (!reason) return
  const r = await run(
    () => http.post<{ version_no: number }>(`${WF}/publish`, { content_hash: draft.value!.content_hash, reason }),
  )
  if (r) ElMessage.success(`已发布 v${r.version_no}`)
  await load()
}

async function rollback(versionNo: number) {
  const reason = await askReason(`回滚到 v${versionNo}`)
  if (!reason) return
  const r = await run(() => http.post<{ version_no: number }>(`${WF}/rollback`, { version_no: versionNo, reason }))
  if (r) ElMessage.success(`已回滚，当前生效 v${r.version_no}`)
  await load()
}

async function showDiff(fromNo: number | null, to: string) {
  try {
    const params: Record<string, any> = { to }
    if (fromNo !== null) params.from_no = fromNo
    const r = await http.get<{ from: number | null; changes: { key: string; old: unknown; new: unknown }[] }>(
      `${WF}/diff`,
      params,
    )
    diffTitle.value = `v${r.from ?? '—'} → ${to === 'draft' ? '草稿' : `v${to}`}`
    diffRows.value = r.changes
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

onMounted(load)
</script>

<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="流程配置走「草稿 → 校验 → 发布」。已发布版本不可修改；每个运行绑定启动时的发布版本，发布或回滚不影响进行中的运行。"
      style="margin-bottom: 12px"
    />
    <el-result v-if="loadError" icon="error" :title="loadError" />
    <template v-else-if="detail && schema">
      <el-card shadow="never">
        <template #header>
          <div style="display: flex; align-items: center; justify-content: space-between">
            <span>当前生效（只读）</span>
            <el-button v-if="can('ops.config.edit') && !form" type="primary" size="small" @click="newDraft">修改配置</el-button>
            <el-button v-else-if="form" size="small" @click="draftCard?.$el.scrollIntoView({ behavior: 'smooth' })">
              查看草稿
            </el-button>
          </div>
        </template>
        <template v-if="detail.current_release && detail.current_version">
          <p>
            <b>v{{ detail.current_release.version_no }}</b>
            <span class="muted">
              {{ detail.current_release.release_type === 'rollback' ? '回滚' : '发布' }} · {{ detail.current_release.released_by }} ·
              {{ formatTime(detail.current_release.released_at) }} · {{ detail.current_release.reason }}
            </span>
          </p>
          <el-descriptions v-for="s in sections" :key="s.name" :title="s.name" :column="2" border size="small"
            style="margin-top: 8px">
            <el-descriptions-item v-for="f in s.fields" :key="f.key" :label="f.label">
              {{ displayValue(f, detail.current_version.content[f.key] ?? schema.defaults?.[f.key], schema) }}
            </el-descriptions-item>
          </el-descriptions>
        </template>
        <span v-else class="muted">暂无数据</span>
      </el-card>

      <el-card ref="draftCard" shadow="never" style="margin-top: 12px">
        <template #header>
          草稿
          <el-tag v-if="draft" size="small" :type="DRAFT_STATUS[draft.status]?.type" style="margin-left: 8px">
            {{ DRAFT_STATUS[draft.status]?.label }}
          </el-tag>
          <el-tag v-if="dirty" size="small" type="warning" style="margin-left: 4px">有未保存修改</el-tag>
        </template>
        <div v-if="!form">
          <template v-if="can('ops.config.edit')">
            <span class="muted">没有草稿。已发布版本不能直接改，点「修改配置」会复制当前版本为草稿，在草稿里修改。</span>
            <el-button type="primary" plain @click="newDraft">基于当前版本新建草稿</el-button>
          </template>
          <el-alert v-else type="warning" :closable="false" show-icon
            title="当前账号没有「Workflow 配置编辑」权限（ops.config.edit），只能查看。请在「角色与权限」中为角色分配该权限。" />
        </div>
        <template v-else>
          <el-alert type="info" :closable="false" style="margin-bottom: 8px"
            title="修改下方配置后依次点「保存草稿」→「校验」→「发布」，发布后新运行才会使用。" />
          <el-form label-width="220px" style="max-width: 900px">
            <template v-for="s in sections" :key="s.name">
            <el-divider content-position="left">{{ s.name }}</el-divider>
            <el-form-item v-for="f in s.fields" :key="f.key" :label="f.label">
              <el-select v-if="f.kind === 'enum'" v-model="form[f.key]" style="width: 100%">
                <el-option v-for="o in f.options" :key="o.value" :label="o.label" :value="o.value" />
              </el-select>
              <el-select
                v-else-if="f.kind === 'model'"
                :model-value="form[f.key] ?? ''"
                style="width: 100%"
                @update:model-value="(v: any) => (form![f.key] = v === '' ? null : v)"
              >
                <el-option label="默认模型" value="" />
                <el-option
                  v-for="m in schema.models"
                  :key="m.id"
                  :label="`${m.label}（#${m.id}）${m.enabled ? '' : ' · 已停用'}`"
                  :value="m.id"
                  :disabled="!m.enabled"
                />
              </el-select>
              <template v-else-if="f.kind === 'int'">
                <el-input-number v-model="form[f.key]" :min="f.min" :max="f.max" step-strictly />
                <span class="muted">{{ f.unit }}（{{ f.min }}～{{ f.max }}，默认 {{ f.default ?? schema.defaults?.[f.key] }}）</span>
              </template>
              <el-switch v-else-if="f.kind === 'bool'" v-model="form[f.key]" active-text="开启" inactive-text="关闭" />
              <el-input v-else-if="f.kind === 'text'" v-model="form[f.key]" type="textarea" :autosize="{ minRows: 2, maxRows: 8 }"
                :maxlength="f.max" show-word-limit />
              <el-select v-else-if="f.kind === 'skill'" v-model="form[f.key]" style="width: 100%">
                <el-option v-for="sk in schema.skills" :key="sk.name" :label="`${sk.label}（${sk.name}）`" :value="sk.name" />
              </el-select>
              <div v-if="f.help" class="help">{{ f.help }}</div>
            </el-form-item>
            </template>
          </el-form>
          <el-alert v-if="localErrors.length" type="warning" :closable="false" style="margin-bottom: 8px">
            <div v-for="e in localErrors" :key="e">· {{ e }}</div>
          </el-alert>
          <el-alert
            v-if="draft?.validation && !draft.validation.ok"
            type="error"
            :closable="false"
            title="服务端校验未通过"
            style="margin-bottom: 8px"
          >
            <div v-for="e in draft.validation.errors" :key="e">· {{ e }}</div>
          </el-alert>
          <div style="display: flex; gap: 8px">
            <template v-if="can('ops.config.edit')">
              <el-button :loading="busy" :disabled="!dirty" @click="saveDraft">保存草稿</el-button>
              <el-button :loading="busy" @click="validate">校验</el-button>
              <el-button :loading="busy" type="danger" plain @click="discard">丢弃草稿</el-button>
            </template>
            <el-tooltip
              v-if="can('ops.config.publish')"
              :disabled="publishable"
              content="需先保存并通过校验；校验后修改需重新校验"
            >
              <span><el-button type="primary" :loading="busy" :disabled="!publishable" @click="publish">发布</el-button></span>
            </el-tooltip>
          </div>
        </template>
      </el-card>

      <el-card v-if="diffRows" shadow="never" style="margin-top: 12px" :header="`配置差异 · ${diffTitle}`">
        <el-table :data="diffRows" size="small" empty-text="无差异">
          <el-table-column label="配置项" width="160">
            <template #default="{ row }">{{ fieldOf(row.key)?.label || row.key }}</template>
          </el-table-column>
          <el-table-column label="旧值" min-width="240">
            <template #default="{ row }">{{ displayValue(fieldOf(row.key), row.old, schema) }}</template>
          </el-table-column>
          <el-table-column label="新值" min-width="240">
            <template #default="{ row }">{{ displayValue(fieldOf(row.key), row.new, schema) }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never" style="margin-top: 12px" header="已发布版本（不可修改）">
        <el-table :data="detail.versions" size="small" empty-text="暂无数据">
          <el-table-column label="版本" width="90">
            <template #default="{ row }">
              v{{ row.version_no }}
              <el-tag v-if="row.version_no === detail.current_release?.version_no" type="success" size="small">生效</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="哈希" width="150">
            <template #default="{ row }">{{ row.content_hash.slice(0, 12) }}</template>
          </el-table-column>
          <el-table-column label="作者" prop="created_by" width="120" />
          <el-table-column label="发布时间" width="170">
            <template #default="{ row }">{{ formatTime(row.published_at) }}</template>
          </el-table-column>
          <el-table-column label="">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="showDiff(null, String(row.version_no))">与生效版本对比</el-button>
              <el-button
                v-if="can('ops.config.rollback') && row.version_no !== detail.current_release?.version_no"
                link
                type="warning"
                size="small"
                @click="rollback(row.version_no)"
              >
                回滚到此版本
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never" style="margin-top: 12px" header="发布记录">
        <el-table :data="detail.releases" size="small" empty-text="暂无数据">
          <el-table-column label="发布 ID" prop="release_id" min-width="200" />
          <el-table-column label="类型" width="80">
            <template #default="{ row }">{{ row.release_type === 'rollback' ? '回滚' : '发布' }}</template>
          </el-table-column>
          <el-table-column label="版本" width="80">
            <template #default="{ row }">v{{ row.version_no }}</template>
          </el-table-column>
          <el-table-column label="操作人" prop="released_by" width="120" />
          <el-table-column label="时间" width="170">
            <template #default="{ row }">{{ formatTime(row.released_at) }}</template>
          </el-table-column>
          <el-table-column label="原因" prop="reason" min-width="200" show-overflow-tooltip />
        </el-table>
      </el-card>
    </template>
    <el-skeleton v-else :rows="8" />
  </div>
</template>

<style scoped>
.muted {
  color: var(--tech-text-2);
  font-size: 12px;
  margin-left: 6px;
}
.help {
  width: 100%;
  margin-top: 4px;
  color: var(--tech-text-2);
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-line;
}
</style>
