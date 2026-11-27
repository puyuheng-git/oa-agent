<script setup lang="ts">
/**
 * 参数表（主编辑器）：名 / 类型 / 必填 / 放置 / 编码 / 说明。
 * Export 仅 scalar|bag；HTTP 为 query|body|bag。嵌套走高级 Schema 树。
 */
import { computed, nextTick, ref, watch } from 'vue'
import {
  applyParamRows, emptyParamRow, paramRowsFromForm, type ParamRow, type ToolForm,
} from '../catalogForm'
import {
  ENCODINGS, PLACEMENTS_EXPORT, PLACEMENTS_HTTP, recommendEncoding, type ParamEncoding, type ParamPlacement,
} from '../paramWire'
import { SCHEMA_TYPES, type SchemaType } from '../schemaTree'

const props = withDefaults(defineProps<{
  form: ToolForm
  isExport: boolean
  /** 极简：隐藏放置/编码列 */
  simple?: boolean
}>(), {
  simple: false,
})

const emit = defineEmits<{ (e: 'change'): void }>()

const rows = ref<ParamRow[]>([])
/** 写回 form 期间抑制 watch，避免空名草稿行被立刻 reload 清掉 */
let syncing = false

function draftRows(list: ParamRow[]): ParamRow[] {
  return list.filter((r) => !r.name.trim())
}

function reload() {
  syncing = true
  // 外部回灌时保留未命名草稿，避免点「添加」后行闪没
  const drafts = draftRows(rows.value)
  rows.value = [...paramRowsFromForm(props.form), ...drafts]
  nextTick(() => { syncing = false })
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
  json: '多维数组 name[key]',
}

function flush() {
  // applyParamRows 会跳过空名；先留住草稿，写回后再拼回去
  syncing = true
  const drafts = draftRows(rows.value)
  applyParamRows(props.form, rows.value)
  rows.value = [...paramRowsFromForm(props.form), ...drafts]
  emit('change')
  nextTick(() => { syncing = false })
}

function onRowEdit() {
  flush()
}

function addRow() {
  const row = emptyParamRow()
  // 极简/HTTP：按方法默认 query|body；Export 独立形参（袋留给专家模式）
  if (props.isExport) row.placement = 'scalar'
  else row.placement = (props.form.method || 'GET').toUpperCase() === 'POST' ? 'body' : 'query'
  // 先入表，再 flush；空名不会进 modelParams，靠草稿保留
  rows.value = [...rows.value, row]
  flush()
}

function removeRow(i: number) {
  rows.value = rows.value.filter((_, idx) => idx !== i)
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
      <el-table-column :label="simple ? '模型必填' : '必填'" width="88" align="center">
        <template #default="{ row }">
          <el-checkbox v-model="row.required" @change="onRowEdit" />
        </template>
      </el-table-column>
      <el-table-column v-if="!simple" label="放置位置" width="130">
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
      <el-table-column v-if="!simple && !isExport" label="编码" width="150">
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
      <template v-if="simple">核对参数名、类型与说明即可；放置与编码由系统自动处理。需要细调请开「专家模式」。</template>
      <template v-else>对象/数组的嵌套字段请用下方「高级 Schema」编辑；表格管顶层名、类型、放置与编码。</template>
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
