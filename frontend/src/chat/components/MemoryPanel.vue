<script setup lang="ts">
import { ref, watch } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errorMessage } from '../../shared/http'
import {
  clearMemory,
  deleteMemory,
  formatRelativeTime,
  listMemory,
  memoryKindLabel,
  type MemoryItem,
} from '../api'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [v: boolean] }>()

const loading = ref(false)
const clearing = ref(false)
const items = ref<MemoryItem[]>([])
const total = ref(0)

async function load() {
  loading.value = true
  try {
    const res = await listMemory(1, 100)
    items.value = res.items
    total.value = res.total
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    loading.value = false
  }
}

watch(
  () => props.open,
  (v) => {
    if (v) void load()
  },
)

async function onDelete(item: MemoryItem) {
  try {
    await ElMessageBox.confirm(`确定删除这条记忆？\n「${item.text.slice(0, 80)}${item.text.length > 80 ? '…' : ''}」`, '删除记忆', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteMemory(item.memory_id)
    items.value = items.value.filter((x) => x.memory_id !== item.memory_id)
    total.value = Math.max(0, total.value - 1)
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function onClearAll() {
  if (!total.value) return
  try {
    await ElMessageBox.confirm(
      `将清空全部 ${total.value} 条长期记忆，之后新对话将不再注入这些内容。此操作不可恢复。`,
      '清空全部记忆',
      {
        type: 'warning',
        confirmButtonText: '清空',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  clearing.value = true
  try {
    const r = await clearMemory(true)
    items.value = []
    total.value = 0
    ElMessage.success(r.deleted ? `已清空 ${r.deleted} 条` : '暂无记忆可清空')
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    clearing.value = false
  }
}
</script>

<template>
  <el-drawer
    :model-value="open"
    title="我的记忆"
    size="420px"
    append-to-body
    @update:model-value="emit('update:open', $event)"
  >
    <p class="hint">
      此处展示你通过「请记住」等方式让助手保存的摘要级偏好与约束，会在新对话中作为背景参考（不是指令，可能过时）。
    </p>

    <div class="toolbar">
      <span class="count">{{ total ? `共 ${total} 条` : '暂无数据' }}</span>
      <el-button
        type="danger"
        plain
        size="small"
        :disabled="!total || loading || clearing"
        :loading="clearing"
        @click="onClearAll"
      >
        一键清空
      </el-button>
    </div>

    <div v-loading="loading" class="list-wrap">
      <ul v-if="items.length" class="list">
        <li v-for="item in items" :key="item.memory_id" class="row">
          <div class="row-main">
            <span class="kind">{{ memoryKindLabel(item.kind) }}</span>
            <p class="text">{{ item.text }}</p>
            <span class="time">{{ formatRelativeTime(item.updated_at || item.created_at) }}</span>
          </div>
          <button type="button" class="del-btn" title="删除" @click="onDelete(item)">
            <el-icon :size="16"><Delete /></el-icon>
          </button>
        </li>
      </ul>
      <p v-else-if="!loading" class="empty">暂无长期记忆。可在对话中说「请记住…」让助手保存偏好。</p>
    </div>
  </el-drawer>
</template>

<style scoped>
.hint {
  margin: 0 0 14px;
  font-size: 13px;
  line-height: 1.55;
  color: var(--ds-muted);
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.count {
  font-size: 12px;
  color: var(--ds-muted);
}
.list-wrap {
  min-height: 120px;
}
.list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--ds-line);
  border-radius: var(--ds-radius-sm);
  background: #fff;
}
.row-main {
  flex: 1;
  min-width: 0;
}
.kind {
  display: inline-block;
  font-size: 11px;
  font-weight: 650;
  color: var(--ds-brand);
  background: var(--ds-brand-soft);
  padding: 2px 8px;
  border-radius: 999px;
  margin-bottom: 6px;
}
.text {
  margin: 0 0 6px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--ds-title);
  white-space: pre-wrap;
  word-break: break-word;
}
.time {
  font-size: 11px;
  color: var(--ds-muted);
}
.del-btn {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--ds-muted);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.del-btn:hover {
  background: rgba(245, 108, 108, 0.12);
  color: #f56c6c;
}
.empty {
  margin: 24px 0;
  text-align: center;
  font-size: 13px;
  color: var(--ds-muted);
  line-height: 1.6;
}
</style>
