<script setup lang="ts">
import type { ChatMessage } from '../types'

defineProps<{ message: ChatMessage }>()
</script>

<template>
  <div class="row user">
    <div class="bubble">
      <div class="text">{{ message.text }}</div>
      <ul v-if="message.attachments?.length" class="atts">
        <li v-for="a in message.attachments" :key="a.id">{{ a.name }}</li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  margin-bottom: 16px;
}
.user {
  justify-content: flex-end;
}
.bubble {
  max-width: min(85%, 520px);
  padding: 10px 14px;
  border-radius: 12px 12px 4px 12px;
  background: var(--ds-brand);
  color: #fff;
}
.text {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 15px;
  line-height: 1.55;
}
.atts {
  margin: 8px 0 0;
  padding: 8px 0 0;
  list-style: none;
  font-size: 12px;
  opacity: 0.9;
  border-top: 1px solid rgba(255, 255, 255, 0.22);
}
.atts li {
  padding: 2px 0;
}
</style>
