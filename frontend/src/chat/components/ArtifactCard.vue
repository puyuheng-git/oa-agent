<script setup lang="ts">
import { Document, Download, View } from '@element-plus/icons-vue'
import type { ArtifactFile } from '../types'

defineProps<{ file: ArtifactFile }>()
const emit = defineEmits<{
  preview: [file: ArtifactFile]
  download: [file: ArtifactFile]
}>()

const kindLabel: Record<string, string> = {
  pdf: 'PDF',
  docx: 'DOCX',
  xlsx: 'XLSX',
  csv: 'CSV',
  markdown: 'Markdown',
  image: '图片',
  generic: '文件',
}
</script>

<template>
  <div class="card">
    <div class="icon"><el-icon :size="20"><Document /></el-icon></div>
    <div class="meta">
      <div class="name" :title="file.name">{{ file.name }}</div>
      <div class="sub">
        {{ kindLabel[file.kind] || '文件' }} · {{ file.sizeLabel }} ·
        {{ file.status === 'ready' ? '已生成' : file.status === 'generating' ? '生成中' : '失败' }}
      </div>
    </div>
    <div class="acts">
      <button type="button" title="预览" :disabled="!file.previewable" @click="emit('preview', file)">
        <el-icon><View /></el-icon>
      </button>
      <button type="button" title="下载" :disabled="file.status !== 'ready'" @click="emit('download', file)">
        <el-icon><Download /></el-icon>
      </button>
    </div>
  </div>
</template>

<style scoped>
.card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--ds-line);
  border-radius: 12px;
  background: linear-gradient(180deg, #fff, #f8fbff);
  margin-bottom: 8px;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.card:hover {
  border-color: rgba(0, 138, 231, 0.35);
  box-shadow: 0 8px 18px rgba(0, 138, 231, 0.08);
}
.icon {
  width: 38px;
  height: 38px;
  border-radius: 11px;
  background: linear-gradient(145deg, #fff, var(--ds-brand-soft));
  color: var(--ds-brand);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 1px solid var(--ds-line);
}
.meta {
  min-width: 0;
  flex: 1;
}
.name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ds-title);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sub {
  font-size: 11px;
  color: var(--ds-muted);
  margin-top: 2px;
}
.acts {
  display: flex;
  gap: 2px;
}
.acts button {
  border: none;
  background: transparent;
  color: var(--ds-muted);
  width: 30px;
  height: 30px;
  border-radius: 6px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.acts button:hover:not(:disabled) {
  background: var(--ds-brand-soft);
  color: var(--ds-brand);
}
.acts button:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
</style>
