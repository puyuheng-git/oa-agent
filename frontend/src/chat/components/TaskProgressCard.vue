<script setup lang="ts">
import { DocumentCopy } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { copyText } from '../../shared/clipboard'
import { agentStatusMeta, formatTime } from '../agent/status'
import type { AgentTask } from '../types'

const props = defineProps<{ task: AgentTask; threadId?: string }>()

async function copyThreadId() {
  const id = props.threadId?.trim()
  if (!id) {
    ElMessage.info('暂无会话 ID')
    return
  }
  const ok = await copyText(id)
  if (ok) ElMessage.success('会话 ID 已复制')
  else ElMessage.error('复制失败，请手动选中复制')
}
</script>

<template>
  <div class="card">
    <div class="top">
      <h4 class="name" :title="task.name">{{ task.name }}</h4>
      <span
        class="badge"
        :style="{ color: agentStatusMeta(task.status).color, background: agentStatusMeta(task.status).bg }"
      >
        {{ agentStatusMeta(task.status).label }}
      </span>
    </div>
    <div v-if="task.mock" class="mock-tag">演示数据 · 非真实 Agent 执行结果</div>
    <div class="progress-wrap">
      <div class="bar"><div class="fill" :style="{ width: `${task.progress}%` }" /></div>
      <span class="pct">{{ task.progress }}%</span>
    </div>
    <dl class="meta">
      <div class="created">
        <dt>创建</dt>
        <dd>{{ formatTime(task.createdAt) }}</dd>
      </div>
      <div class="session">
        <div class="session-head">
          <dt>会话 ID</dt>
          <button v-if="threadId" type="button" class="copy-btn" @click="copyThreadId">
            <el-icon :size="14"><DocumentCopy /></el-icon>
            复制
          </button>
        </div>
        <dd v-if="threadId" class="id-value" :title="threadId">{{ threadId }}</dd>
        <dd v-else class="empty">暂无</dd>
      </div>
    </dl>
  </div>
</template>

<style scoped>
.card {
  padding: 0;
  border: none;
  background: transparent;
}
.top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.name {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--ds-title);
  line-height: 1.4;
  word-break: break-word;
}
.badge {
  flex-shrink: 0;
  font-size: 11px;
  padding: 3px 9px;
  border-radius: 999px;
  font-weight: 700;
}
.mock-tag {
  margin-top: 10px;
  font-size: 11px;
  color: #b54708;
  background: var(--ds-warning-bg);
  padding: 6px 10px;
  border-radius: 8px;
  border: 1px solid #f9dbaf;
}
.progress-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
}
.bar {
  flex: 1;
  height: 8px;
  border-radius: 999px;
  background: var(--ds-brand-soft);
  overflow: hidden;
}
.fill {
  height: 100%;
  background: linear-gradient(90deg, #0075c7, #008ae7, #4aaef0);
  border-radius: 999px;
  transition: width 0.35s var(--ds-ease);
  box-shadow: 0 0 12px rgba(0, 138, 231, 0.35);
}
.pct {
  font-size: 12px;
  font-weight: 700;
  color: var(--ds-brand);
  min-width: 36px;
  text-align: right;
}
.meta {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 14px 0 0;
}
.meta > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  border-radius: 10px;
  background: var(--ds-page);
  min-width: 0;
}
dt {
  font-size: 11px;
  color: var(--ds-muted);
}
dd {
  margin: 0;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ds-title);
}
.session-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  margin: 0;
  padding: 2px 8px;
  border: 1px solid rgba(0, 138, 231, 0.35);
  border-radius: 6px;
  background: #fff;
  color: var(--ds-brand);
  cursor: pointer;
  font-size: 12px;
  line-height: 1.4;
}
.copy-btn:hover {
  background: var(--ds-brand-soft);
}
.id-value {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.45;
  word-break: break-all;
  overflow-wrap: anywhere;
  user-select: text;
  color: var(--ds-title);
}
.empty {
  color: var(--ds-muted);
  font-weight: 500;
}
</style>
