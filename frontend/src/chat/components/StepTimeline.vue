<script setup lang="ts">
import { Check, Loading, Close, Clock } from '@element-plus/icons-vue'
import { stepStatusMeta } from '../agent/status'
import type { TaskStep } from '../types'

defineProps<{ steps: TaskStep[]; expanded: boolean }>()
</script>

<template>
  <ol v-show="expanded" class="steps">
    <li v-for="s in steps" :key="s.id" class="step">
      <span class="dot" :style="{ background: stepStatusMeta(s.status).bg, color: stepStatusMeta(s.status).color }">
        <el-icon v-if="s.status === 'completed'"><Check /></el-icon>
        <el-icon v-else-if="s.status === 'running'" class="spin"><Loading /></el-icon>
        <el-icon v-else-if="s.status === 'failed'"><Close /></el-icon>
        <el-icon v-else><Clock /></el-icon>
      </span>
      <div class="info">
        <div class="title">{{ s.title }}</div>
        <div class="status">{{ stepStatusMeta(s.status).label }}</div>
      </div>
    </li>
  </ol>
</template>

<style scoped>
.steps {
  list-style: none;
  margin: 0;
  padding: 0;
  position: relative;
}
.steps::before {
  content: '';
  position: absolute;
  left: 11px;
  top: 14px;
  bottom: 14px;
  width: 2px;
  background: linear-gradient(180deg, rgba(0, 138, 231, 0.35), rgba(230, 237, 245, 0.9));
  border-radius: 2px;
}
.step {
  display: flex;
  gap: 12px;
  padding: 8px 0;
  position: relative;
}
.dot {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 12px;
  border: 2px solid #fff;
  box-shadow: 0 0 0 1px rgba(0, 138, 231, 0.12);
  z-index: 1;
}
.info {
  min-width: 0;
}
.title {
  font-size: 13px;
  font-weight: 600;
  color: var(--ds-title);
}
.status {
  font-size: 11px;
  color: var(--ds-muted);
  margin-top: 2px;
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .spin {
    animation: none;
  }
}
</style>
