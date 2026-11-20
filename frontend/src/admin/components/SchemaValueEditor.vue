<script setup lang="ts">
// Schema 驱动的试调参数表单：按 schema（参数名 → SchemaNode）递归渲染输入控件。
// modelValue 为编辑态值（约定见 schemaValue.ts），调用前用 buildArgsFromValues 转成 args。
// 不直接修改 props，变更通过 update:modelValue 发出新对象。
import SchemaValueField from './SchemaValueField.vue'
import type { SchemaNode } from '../schemaTree'

const props = defineProps<{
  schema: Record<string, SchemaNode>
  modelValue: Record<string, unknown>
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: Record<string, unknown>): void }>()

/** 更新单个参数；undefined 表示清除该键。 */
function setValue(key: string, v: unknown) {
  const next = { ...(props.modelValue ?? {}) }
  if (v === undefined) delete next[key]
  else next[key] = v
  emit('update:modelValue', next)
}
</script>

<template>
  <el-form class="schema-value-editor" label-width="120px" size="small" @submit.prevent>
    <SchemaValueField
      v-for="(node, key) in schema"
      :key="key"
      :node="node"
      :name="String(key)"
      :model-value="modelValue?.[key]"
      @update:model-value="(v: unknown) => setValue(String(key), v)"
    />
    <el-empty v-if="!Object.keys(schema).length" :image-size="48" description="暂无参数" />
  </el-form>
</template>
