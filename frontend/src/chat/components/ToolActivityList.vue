<script setup lang="ts">
import { toolStatusMeta, formatDuration } from '../agent/status'
import type { ToolCallEvent } from '../types'
import EmptyState from './EmptyState.vue'

defineProps<{ tools: ToolCallEvent[] }>()
</script>

<template>
  <EmptyState
    v-if="!tools.length"
    title="暂无工具调用"
    description="任务运行后将在此显示工具名称、状态与结果摘要。"
  />
  <ul v-else class="list">
    <li v-for="t in tools" :key="t.id" class="item">
      <div class="row">
        <span class="name">{{ t.name }}</span>
        <span class="badge" :style="{ color: toolStatusMeta(t.status).color, background: toolStatusMeta(t.status).bg }">
          {{ toolStatusMeta(t.status).label }}
        </span>
      </div>
      <div class="meta">
        <span v-if="t.durationMs != null">耗时 {{ formatDuration(t.durationMs) }}</span>
        <span v-if="t.summary">{{ t.summary }}</span>
      </div>
    </li>
  </ul>
</template>

<style scoped>
.list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.item {
  padding: 10px 0;
  border-bottom: 1px solid var(--ds-line);
}
.item:last-child {
  border-bottom: none;
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.name {
  font-size: 12px;
  font-weight: 600;
  color: var(--ds-title);
  font-family: ui-monospace, Consolas, monospace;
  word-break: break-all;
}
.badge {
  flex-shrink: 0;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 500;
}
.meta {
  margin-top: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 11px;
  color: var(--ds-muted);
  line-height: 1.45;
}
</style>
