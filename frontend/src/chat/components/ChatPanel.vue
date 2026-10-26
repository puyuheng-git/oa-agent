<script setup lang="ts">
import MessageList from './MessageList.vue'
import Composer from './Composer.vue'
import type { ChatMessage, PendingAttachment } from '../types'

defineProps<{
  messages: ChatMessage[]
  sending: boolean
  displayName: string
  examples: string[]
  skillNames: string[]
  chatEnabled: boolean
  input: string
  maxChars: number
  attachments: PendingAttachment[]
  placeholder?: string
}>()

const emit = defineEmits<{
  'update:input': [v: string]
  'update:attachments': [items: PendingAttachment[]]
  send: []
  stop: []
  example: [text: string]
  regenerate: [msg: ChatMessage]
  'open-tools': []
}>()
</script>

<template>
  <section class="panel">
    <MessageList
      :messages="messages"
      :sending="sending"
      :display-name="displayName"
      :examples="examples"
      :skill-names="skillNames"
      :chat-enabled="chatEnabled"
      @example="emit('example', $event)"
      @regenerate="emit('regenerate', $event)"
    />
    <Composer
      :model-value="input"
      :max-chars="maxChars"
      :sending="sending"
      :attachments="attachments"
      :placeholder="placeholder"
      @update:model-value="emit('update:input', $event)"
      @update:attachments="emit('update:attachments', $event)"
      @send="emit('send')"
      @stop="emit('stop')"
      @open-tools="emit('open-tools')"
    />
  </section>
</template>

<style scoped>
.panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
  max-width: 100%;
  overflow: hidden;
  background: var(--ds-page);
}
</style>
