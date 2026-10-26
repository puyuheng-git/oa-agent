<script setup lang="ts">
import type { ArtifactFile } from '../types'

defineProps<{
  open: boolean
  file: ArtifactFile | null
}>()
const emit = defineEmits<{ 'update:open': [v: boolean] }>()
</script>

<template>
  <el-drawer
    :model-value="open"
    title="文件预览"
    size="420px"
    append-to-body
    @update:model-value="emit('update:open', $event)"
  >
    <template v-if="file">
      <h3 class="name">{{ file.name }}</h3>
      <p class="meta">{{ file.kind.toUpperCase() }} · {{ file.sizeLabel }}</p>
      <div class="preview">
        <p v-if="file.previewNote">{{ file.previewNote }}</p>
        <p v-else class="limit">
          当前环境未接入文档转换服务，无法完整解析该文件内容。请下载后使用本地办公软件查看。
        </p>
        <pre v-if="file.kind === 'markdown'" class="md-sample"># {{ file.name }}

> 演示预览占位

本文档由 AI 工作台 Mock 适配层生成，**不是**真实业务系统产出。
接入真实 Agent 文件服务后，将在此展示服务端返回的可预览内容。</pre>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.name {
  margin: 0;
  font-size: 16px;
  color: var(--ds-title);
}
.meta {
  margin: 6px 0 16px;
  font-size: 12px;
  color: var(--ds-muted);
}
.preview {
  padding: 14px;
  border: 1px solid var(--ds-line);
  border-radius: var(--ds-radius-sm);
  background: var(--ds-page);
  font-size: 13px;
  line-height: 1.6;
  color: var(--ds-body);
}
.limit {
  margin: 0;
  color: var(--ds-muted);
}
.md-sample {
  margin: 12px 0 0;
  white-space: pre-wrap;
  font-family: inherit;
  font-size: 13px;
  color: var(--ds-title);
}
</style>
