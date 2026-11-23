<script setup lang="ts">
/**
 * 调用形参：动态槽位（增删排序）+ method($…) 预览。
 * 不写死签名菜单；可选示例仅作参考。
 */
import { computed, ref, watch } from 'vue'
import {
  CALL_PRESETS,
  previewCall,
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

const showExamples = ref(false)
const preview = computed(() => previewCall(props.methodName, props.slots))

function updateRow(index: number, patch: Partial<CallSlot>) {
  const next = props.slots.map((s, i) => (i === index ? { ...s, ...patch } : { ...s }))
  emit('update:slots', next)
}

function addSlot(role: CallSlotRole = 'scalar', name = '') {
  const defaults: Record<CallSlotRole, string> = { identity: 'oa', bag: 'params', scalar: 'page' }
  emit('update:slots', [...props.slots, { role, name: name || defaults[role] }])
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

function applyExample(slots: CallSlot[]) {
  emit('update:slots', slots.map((s) => ({ ...s })))
  showExamples.value = false
}

// 无槽位时给一个空袋，避免预览 method()
watch(
  () => props.slots.length,
  (n) => {
    if (n === 0) emit('update:slots', [{ role: 'bag', name: 'params' }])
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
    <div class="actions">
      <el-button size="small" @click="addSlot('identity')">加身份</el-button>
      <el-button size="small" @click="addSlot('bag')">加参数袋</el-button>
      <el-button size="small" @click="addSlot('scalar')">加标量</el-button>
      <el-button size="small" link type="primary" @click="showExamples = !showExamples">
        {{ showExamples ? '收起示例' : '参考示例' }}
      </el-button>
    </div>
    <div v-if="showExamples" class="examples">
      <div class="hint">仅作参考，点选后仍可继续增删改：</div>
      <el-button
        v-for="p in CALL_PRESETS"
        :key="p.id"
        size="small"
        style="margin: 4px 6px 0 0"
        @click="applyExample(p.slots)"
      >
        {{ previewCall(p.sampleMethod, p.slots) }}
      </el-button>
    </div>
    <div class="hint">
      身份 = 服务端写入当前员工账号；参数袋 = 关联数组（如 $params）；标量 = page/limit 等独立参数。自由组合即可覆盖多种 PHP 方法签名。
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
.actions {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}
.examples {
  margin-top: 8px;
  padding: 8px;
  border-radius: 6px;
  background: var(--el-fill-color-blank);
  border: 1px dashed var(--el-border-color);
}
.hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
</style>
