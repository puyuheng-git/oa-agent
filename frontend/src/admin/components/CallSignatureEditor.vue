<script setup lang="ts">
/**
 * 调用形参：预设 + 槽位表 + method($oa, $params) 预览。
 * 向导与新建/编辑 Tool 共用。
 */
import { computed, watch } from 'vue'
import {
  CALL_PRESETS,
  findPresetId,
  previewCall,
  slotsFromPresetId,
  type CallSlot,
  type CallSlotRole,
} from '../callSignature'

const props = defineProps<{
  methodName: string
  slots: CallSlot[]
}>()

const emit = defineEmits<{
  (e: 'update:slots', v: CallSlot[]): void
}>()

const ROLE_OPTIONS: { value: CallSlotRole; label: string }[] = [
  { value: 'identity', label: '身份' },
  { value: 'bag', label: '参数袋' },
  { value: 'scalar', label: '标量' },
]

const presetId = computed({
  get: () => findPresetId(props.slots) || '',
  set: (id: string) => {
    if (!id) return
    emit('update:slots', slotsFromPresetId(id))
  },
})

const preview = computed(() => previewCall(props.methodName, props.slots))

function updateRow(index: number, patch: Partial<CallSlot>) {
  const next = props.slots.map((s, i) => (i === index ? { ...s, ...patch } : { ...s }))
  emit('update:slots', next)
}

function addSlot() {
  emit('update:slots', [...props.slots, { role: 'bag', name: 'params' }])
}

function removeSlot(index: number) {
  emit('update:slots', props.slots.filter((_, i) => i !== index))
}

function moveSlot(index: number, delta: number) {
  const j = index + delta
  if (j < 0 || j >= props.slots.length) return
  const next = [...props.slots]
  const tmp = next[index]
  next[index] = next[j]
  next[j] = tmp
  emit('update:slots', next)
}

// 无槽位时给一个默认袋，避免预览 method()
watch(
  () => props.slots.length,
  (n) => {
    if (n === 0) emit('update:slots', slotsFromPresetId('bag_only'))
  },
  { immediate: true },
)
</script>

<template>
  <div class="call-sig">
    <div class="preview-box">
      <div class="preview-label">调用预览</div>
      <code class="preview-code">{{ preview }}</code>
    </div>

    <el-form-item label="形参预设">
      <el-select v-model="presetId" clearable placeholder="选择常见签名或下方自定义" style="width: 100%">
        <el-option
          v-for="p in CALL_PRESETS"
          :key="p.id"
          :value="p.id"
          :label="`${p.label} → ${previewCall(p.sampleMethod, p.slots)}`"
        />
      </el-select>
    </el-form-item>

    <el-table :data="slots" size="small" border>
      <el-table-column label="角色" width="120">
        <template #default="{ row, $index }">
          <el-select
            :model-value="row.role"
            size="small"
            style="width: 100%"
            @update:model-value="(v: CallSlotRole) => updateRow($index, { role: v })"
          >
            <el-option v-for="o in ROLE_OPTIONS" :key="o.value" :value="o.value" :label="o.label" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="参数名" min-width="140">
        <template #default="{ row, $index }">
          <el-input
            :model-value="row.name"
            size="small"
            placeholder="如 oa、params、page"
            @update:model-value="(v: string) => updateRow($index, { name: v })"
          />
        </template>
      </el-table-column>
      <el-table-column label="顺序" width="100">
        <template #default="{ $index }">
          <el-button link size="small" :disabled="$index === 0" @click="moveSlot($index, -1)">上</el-button>
          <el-button link size="small" :disabled="$index >= slots.length - 1" @click="moveSlot($index, 1)">下</el-button>
        </template>
      </el-table-column>
      <el-table-column label="" width="64">
        <template #default="{ $index }">
          <el-button link type="danger" size="small" @click="removeSlot($index)">删</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-button size="small" style="margin-top: 6px" @click="addSlot">添加形参</el-button>
    <div class="hint">
      身份 = 服务端写入当前员工账号；参数袋 = 关联数组（如 $params）；标量 = page/limit 等独立参数。
    </div>
  </div>
</template>

<style scoped>
.call-sig { width: 100%; }
.preview-box {
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
}
.preview-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}
.preview-code {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-color-primary);
  word-break: break-all;
}
.hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
</style>
