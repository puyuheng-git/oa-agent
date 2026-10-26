<script setup lang="ts">
import { ref, watch } from 'vue'
import { WarningFilled } from '@element-plus/icons-vue'
import type { ApprovalItem } from '../types'

const props = defineProps<{ item: ApprovalItem }>()
const emit = defineEmits<{
  approve: [id: string]
  reject: [id: string]
}>()

const loading = ref<'approve' | 'reject' | null>(null)

watch(
  () => props.item.status,
  (s) => {
    if (s !== 'pending') loading.value = null
  },
)

function act(kind: 'approve' | 'reject') {
  if (props.item.status !== 'pending' || loading.value) return
  loading.value = kind
  if (kind === 'approve') emit('approve', props.item.id)
  else emit('reject', props.item.id)
}
</script>

<template>
  <div class="card">
    <div class="head">
      <el-icon color="#F79009"><WarningFilled /></el-icon>
      <strong>{{ item.title }}</strong>
    </div>
    <p class="desc">{{ item.description }}</p>
    <p class="risk">{{ item.risk }}</p>
    <div v-if="item.status === 'pending'" class="acts">
      <button type="button" class="reject" :disabled="!!loading" @click="act('reject')">
        {{ loading === 'reject' ? '处理中…' : '拒绝' }}
      </button>
      <button type="button" class="approve" :disabled="!!loading" @click="act('approve')">
        {{ loading === 'approve' ? '处理中…' : '批准' }}
      </button>
    </div>
    <div v-else class="result">
      {{ item.status === 'approved' ? '已批准' : item.status === 'rejected' ? '已拒绝' : '处理失败' }}
    </div>
  </div>
</template>

<style scoped>
.card {
  padding: 12px;
  border-radius: var(--ds-radius-sm);
  border: 1px solid #f9dbaf;
  background: var(--ds-warning-bg);
  margin-bottom: 8px;
}
.head {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ds-title);
  font-size: 13px;
}
.desc,
.risk {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ds-body);
}
.risk {
  color: #b54708;
  background: rgba(255, 255, 255, 0.55);
  padding: 6px 8px;
  border-radius: 6px;
}
.acts {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  justify-content: flex-end;
}
.acts button {
  height: 32px;
  padding: 0 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.reject {
  border: 1px solid var(--ds-line);
  background: #fff;
  color: var(--ds-body);
}
.approve {
  border: none;
  background: var(--ds-brand);
  color: #fff;
}
.approve:hover:not(:disabled) {
  background: var(--ds-brand-hover);
}
.acts button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.result {
  margin-top: 10px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ds-title);
}
</style>
