<script setup lang="ts">
import { computed, ref } from 'vue'
import { CopyDocument, RefreshRight } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { cellText, plainText } from '../api'
import type { ArtifactFile, ChatMessage } from '../types'
import DeliveryResultCard from './DeliveryResultCard.vue'
import DocumentPreviewDrawer from './DocumentPreviewDrawer.vue'

const props = defineProps<{ message: ChatMessage }>()
const emit = defineEmits<{ regenerate: [] }>()

const isError = computed(() => props.message.reply?.type === 'error')
const isWaiting = computed(() => props.message.reply?.type === 'pending')
const showData = ref(false)
const previewOpen = ref(false)
const previewFile = ref<ArtifactFile | null>(null)

function textLines(m: ChatMessage): string {
  // 流式与终态统一剥 HTML，避免回复过程中露出标签、完成后才变纯文字
  const raw = plainText(m.text)
  if (!m.reply?.data) return raw
  return raw
    .split('\n')
    .filter((l) => l.trim() && !['|', '- ', '>'].some((p) => l.trim().startsWith(p)))
    .join('\n')
}

async function copy() {
  try {
    await navigator.clipboard.writeText(plainText(props.message.text))
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

function onPreview(file: ArtifactFile) {
  previewFile.value = file
  previewOpen.value = true
}

function onDownload(file: ArtifactFile) {
  if (!file.downloadUrl) {
    ElMessage.info(file.previewNote || '该文件暂无真实下载地址（演示数据或后端未提供）')
    return
  }
  window.open(file.downloadUrl, '_blank', 'noopener')
}
</script>

<template>
  <div class="row assistant">
    <div class="avatar" aria-hidden="true">AI</div>
    <div class="body">
      <div :class="['content', { error: isError, waiting: isWaiting }]">
        <div class="text">
          {{ textLines(message) }}<span v-if="message.streaming" class="cursor">▍</span>
        </div>

        <DeliveryResultCard
          v-if="message.delivery && !message.streaming"
          :delivery="message.delivery"
          @view-data="showData = !showData"
          @preview="onPreview"
          @download="onDownload"
        />

        <div v-if="showData && message.reply?.data" class="data-wrap">
          <el-table
            v-if="message.reply.data.kind === 'table'"
            :data="message.reply.data.items"
            size="small"
            border
            class="data-table"
          >
            <el-table-column
              v-for="c in message.reply.data.columns"
              :key="c.key"
              :label="c.label"
              min-width="90"
              show-overflow-tooltip
            >
              <template #default="{ row }">{{ cellText(row[c.key]) }}</template>
            </el-table-column>
          </el-table>

          <el-descriptions
            v-else-if="message.reply.data.kind === 'record'"
            :column="1"
            size="small"
            border
            class="data-table"
          >
            <el-descriptions-item
              v-for="f in message.reply.data.fields"
              :key="f.key"
              :label="f.label"
            >
              {{ cellText(message.reply.data.item[f.key]) }}
            </el-descriptions-item>
          </el-descriptions>
        </div>

        <!-- 无交付卡片时仍直接展示结构化数据（兼容） -->
        <div v-else-if="!message.delivery && message.reply?.data" class="data-wrap">
          <el-table
            v-if="message.reply.data.kind === 'table'"
            :data="message.reply.data.items"
            size="small"
            border
            class="data-table"
          >
            <el-table-column
              v-for="c in message.reply.data.columns"
              :key="c.key"
              :label="c.label"
              min-width="90"
              show-overflow-tooltip
            >
              <template #default="{ row }">{{ cellText(row[c.key]) }}</template>
            </el-table-column>
          </el-table>
          <el-descriptions
            v-else-if="message.reply.data.kind === 'record'"
            :column="1"
            size="small"
            border
            class="data-table"
          >
            <el-descriptions-item
              v-for="f in message.reply.data.fields"
              :key="f.key"
              :label="f.label"
            >
              {{ cellText(message.reply.data.item[f.key]) }}
            </el-descriptions-item>
          </el-descriptions>
        </div>

        <div v-if="message.reply?.data && message.reply.notice" class="notice">
          业务系统提示：{{ message.reply.notice }}
        </div>
      </div>

      <div v-if="!message.streaming" class="actions">
        <button type="button" title="复制" @click="copy">
          <el-icon><CopyDocument /></el-icon>
          <span>复制</span>
        </button>
        <button type="button" title="基于此重新提问" @click="emit('regenerate')">
          <el-icon><RefreshRight /></el-icon>
          <span>重新提问</span>
        </button>
      </div>
    </div>

    <DocumentPreviewDrawer v-model:open="previewOpen" :file="previewFile" />
  </div>
</template>

<style scoped>
.row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
  align-items: flex-start;
}
.avatar {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: var(--ds-brand);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 2px;
}
.body {
  min-width: 0;
  flex: 1;
  max-width: min(100%, 620px);
}
.content {
  color: var(--ds-title);
}
.content.error {
  color: var(--ds-danger);
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--ds-danger-bg);
  border: 1px solid #fecdca;
}
.content.waiting {
  color: #b54708;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--ds-warning-bg);
  border: 1px solid #f9dbaf;
}
.text {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 15px;
  line-height: 1.65;
  color: inherit;
}
.cursor {
  color: var(--ds-brand);
  animation: blink 1s steps(2) infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
.data-wrap {
  margin-top: 10px;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--ds-line);
  background: #fff;
}
.data-table {
  margin: 0;
  max-width: 100%;
}
.notice {
  margin-top: 10px;
  padding: 8px 12px;
  border-left: 3px solid var(--ds-warning);
  background: var(--ds-warning-bg);
  color: #8a5a00;
  font-size: 13px;
  white-space: pre-wrap;
  border-radius: 0 8px 8px 0;
}
.actions {
  display: flex;
  gap: 4px;
  margin-top: 6px;
  opacity: 0.55;
  transition: opacity 0.15s;
}
.row:hover .actions {
  opacity: 1;
}
.actions button {
  border: none;
  background: transparent;
  color: var(--ds-muted);
  height: 28px;
  padding: 0 8px;
  border-radius: 6px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
}
.actions button:hover {
  background: var(--ds-brand-soft);
  color: var(--ds-brand);
}
@media (hover: none) {
  .actions {
    opacity: 1;
  }
}
</style>
