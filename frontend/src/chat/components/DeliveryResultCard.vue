<script setup lang="ts">
import { Download, View, DataAnalysis } from '@element-plus/icons-vue'
import type { ArtifactFile, DeliverySummary } from '../types'

defineProps<{
  delivery: DeliverySummary
}>()

const emit = defineEmits<{
  'view-data': []
  preview: [file: ArtifactFile]
  download: [file: ArtifactFile]
}>()
</script>

<template>
  <div :class="['delivery', { mock: delivery.mock }]">
    <div class="head">
      <div class="icon"><el-icon :size="18"><DataAnalysis /></el-icon></div>
      <div class="titles">
        <strong>{{ delivery.title }}</strong>
        <span v-if="delivery.mock" class="mock-badge">演示数据</span>
        <span v-else class="live-badge">真实结果</span>
      </div>
    </div>
    <ul class="highlights">
      <li v-for="(h, i) in delivery.highlights" :key="i">
        <span class="k">{{ h.label }}</span>
        <span class="v">{{ h.value }}</span>
      </li>
    </ul>
    <div class="acts">
      <button
        v-if="delivery.hasStructuredData"
        type="button"
        class="act primary"
        @click="emit('view-data')"
      >
        <el-icon><View /></el-icon>
        查看结果
      </button>
      <template v-for="f in delivery.artifacts || []" :key="f.id">
        <button type="button" class="act" :disabled="!f.previewable" @click="emit('preview', f)">
          <el-icon><View /></el-icon>
          预览 {{ f.name.length > 12 ? f.name.slice(0, 12) + '…' : f.name }}
        </button>
        <button type="button" class="act" @click="emit('download', f)">
          <el-icon><Download /></el-icon>
          下载
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.delivery {
  margin-top: 10px;
  padding: 12px;
  border-radius: 10px;
  border: 1px solid var(--ds-line);
  background: #fff;
}
.delivery.mock {
  border-color: #f9dbaf;
  background: #fffdf8;
}
.head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.icon {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: var(--ds-brand-soft);
  color: var(--ds-brand);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.titles {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.titles strong {
  font-size: 14px;
  color: var(--ds-title);
  font-weight: 700;
  line-height: 1.4;
}
.mock-badge,
.live-badge {
  font-size: 12px;
  font-weight: 650;
  padding: 2px 8px;
  border-radius: 999px;
}
.mock-badge {
  color: #b54708;
  background: var(--ds-warning-bg);
}
.live-badge {
  color: var(--ds-success);
  background: var(--ds-success-bg);
}
.highlights {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.highlights li {
  display: flex;
  gap: 10px;
  align-items: baseline;
  font-size: 13px;
  line-height: 1.45;
}
.k {
  flex-shrink: 0;
  min-width: 42px;
  color: var(--ds-muted);
  font-size: 12px;
}
.v {
  color: var(--ds-title);
  font-weight: 600;
}
.acts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.act {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 32px;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid var(--ds-line);
  background: #fff;
  color: var(--ds-body);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}
.act:hover:not(:disabled) {
  border-color: rgba(0, 138, 231, 0.4);
  color: var(--ds-brand);
  background: var(--ds-brand-soft);
}
.act.primary {
  background: var(--ds-brand);
  border-color: var(--ds-brand);
  color: #fff;
}
.act.primary:hover:not(:disabled) {
  background: var(--ds-brand-hover);
  color: #fff;
}
.act:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
