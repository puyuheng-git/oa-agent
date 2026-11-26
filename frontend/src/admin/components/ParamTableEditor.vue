<script setup lang="ts">
/**
 * 参数表（主编辑器）：名 / 类型 / 必填 / 放置 / 编码 / 说明。
 * Export 仅 scalar|bag；HTTP 为 query|body|bag。嵌套走高级 Schema 树。
 */
import { computed, ref, watch } from 'vue'
import {
  applyParamRows, emptyParamRow, paramRowsFromForm, type ParamRow, type ToolForm,
} from '../catalogForm'
import {
  ENCODINGS, PLACEMENTS_EXPORT, PLACEMENTS_HTTP, recommendEncoding, type ParamEncoding, type ParamPlacement,
} from '../paramWire'
import { SCHEMA_TYPES, type SchemaType } from '../schemaTree'

const props = defineProps<{
  form: ToolForm
  isExport: boolean
}>()

const emit = defineEmits<{ (e: 'change'): void }>()

const rows = ref<ParamRow[]>([])
let syncing = false

function reload() {
  syncing = true
  rows.value = paramRowsFromForm(props.form)
  if (!rows.value.length) rows.value = []
  syncing = false
}

watch(
  () => [props.form.modelParams, props.form.topLevelFields, props.form.method, props.isExport, props.form.query_params_field] as const,
  () => { if (!syncing) reload() },
  { deep: true, immediate: true },
)

const placements = computed(() => (props.isExport ? PLACEMENTS_EXPORT : PLACEMENTS_HTTP))

const placementLabel: Record<ParamPlacement, string> = {
  scalar: '独立形参',
  bag: '装入袋',
  query: 'query',
  body: 'body',
}

const encodingLabel: Record<ParamEncoding, string> = {
  auto: '自动',
  flat: '扁平',
  repeat: '数组 name[]',
  json: 'JSON 字符串',
}

function flush() {
  applyParamRows(props.form, rows.value)
  emit('change')
}

function onRowEdit() {
  flush()
}

function addRow() {
  const row = emptyParamRow()
  row.placement = props.isExport ? 'bag' : ((props.form.method || 'GET').toUpperCase() === 'POST' ? 'body' : 'query')
  rows.value.push(row)
  flush()
}

function removeRow(i: number) {
  rows.value.splice(i, 1)
  flush()
}

function onTypeChange(row: ParamRow) {
  if (row.encoding === 'auto') {
    // 仅提示；auto 仍按类型推荐
    void recommendEncoding({ type: row.type as SchemaType })
  }
  onRowEdit()
}

function encodingHint(row: ParamRow): string {
  if (row.encoding !== 'auto') return ''
  const rec = recommendEncoding({ type: row.type })
  return `→ ${encodingLabel[rec]}`
}

defineExpose({ reload, flush })
</script>

<template>
  <div class="param-table">
    <el-table :data="rows" size="small" border empty-text="暂无参数，点击下方添加">
      <el-table-column label="参数名" min-width="120">
        <template #default="{ row }">
          <el-input v-model="row.name" size="small" placeholder="如 page" @change="onRowEdit" />
        </template>
      </el-table-column>
      <el-table-column label="类型" width="120">
        <template #default="{ row }">
          <el-select v-model="row.type" size="small" @change="() => onTypeChange(row)">
            <el-option v-for="t in SCHEMA_TYPES" :key="t" :label="t" :value="t" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="必填" width="64" align="center">
        <template #default="{ row }">
          <el-checkbox v-model="row.required" @change="onRowEdit" />
        </template>
      </el-table-column>
      <el-table-column label="放置位置" width="130">
        <template #default="{ row }">
          <el-select v-model="row.placement" size="small" @change="onRowEdit">
            <el-option
              v-for="p in placements"
              :key="p"
              :label="placementLabel[p]"
              :value="p"
            />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column v-if="!isExport" label="编码" width="150">
        <template #default="{ row }">
          <el-select v-model="row.encoding" size="small" @change="onRowEdit">
            <el-option
              v-for="e in ENCODINGS"
              :key="e"
              :label="encodingLabel[e]"
              :value="e"
            />
          </el-select>
          <div v-if="encodingHint(row)" class="enc-hint">{{ encodingHint(row) }}</div>
        </template>
      </el-table-column>
      <el-table-column label="显示名" min-width="100">
        <template #default="{ row }">
          <el-input v-model="row.label" size="small" placeholder="给模型看" @change="onRowEdit" />
        </template>
      </el-table-column>
      <el-table-column label="说明" min-width="120">
        <template #default="{ row }">
          <el-input v-model="row.description" size="small" @change="onRowEdit" />
        </template>
      </el-table-column>
      <el-table-column label="" width="64">
        <template #default="{ $index }">
          <el-button link type="danger" size="small" @click="removeRow($index)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-button size="small" style="margin-top: 8px" @click="addRow">添加参数</el-button>
    <div class="hint">
      对象/数组的嵌套字段请用下方「高级 Schema」编辑；表格管顶层名、类型、放置与编码。
    </div>
  </div>
</template>

<style scoped>
.hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.enc-hint {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  line-height: 1.2;
  margin-top: 2px;
}
</style>
