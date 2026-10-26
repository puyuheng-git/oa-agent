<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import UserMessage from './UserMessage.vue'
import AssistantMessage from './AssistantMessage.vue'
import WelcomeScreen from './WelcomeScreen.vue'
import type { ChatMessage } from '../types'

const props = defineProps<{
  messages: ChatMessage[]
  sending: boolean
  displayName: string
  examples: string[]
  skillNames: string[]
  chatEnabled: boolean
}>()

const emit = defineEmits<{
  example: [text: string]
  regenerate: [msg: ChatMessage]
}>()

const listEl = ref<HTMLElement | null>(null)

async function scrollToBottom() {
  await nextTick()
  listEl.value?.scrollTo({ top: listEl.value.scrollHeight, behavior: 'smooth' })
}

watch(
  () => [props.messages.length, props.messages[props.messages.length - 1]?.text, props.sending],
  () => scrollToBottom(),
)

defineExpose({ scrollToBottom })
</script>

<template>
  <main ref="listEl" class="messages">
    <div class="column">
      <WelcomeScreen
        v-if="!messages.length"
        :display-name="displayName"
        :examples="examples"
        :skill-names="skillNames"
        :chat-enabled="chatEnabled"
        @example="emit('example', $event)"
      />

      <template v-else>
        <template v-for="m in messages" :key="m.id">
          <UserMessage v-if="m.role === 'user'" :message="m" />
          <AssistantMessage
            v-else
            :message="m"
            @regenerate="emit('regenerate', m)"
          />
        </template>

        <div v-if="sending && !messages[messages.length - 1]?.streaming" class="thinking">
          <div class="avatar">AI</div>
          <div class="dots" aria-label="正在理解"><span /><span /><span /></div>
          <span class="label">正在理解你的需求…</span>
        </div>
      </template>
    </div>
  </main>
</template>

<style scoped>
.messages {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px 20px 12px;
  scroll-behavior: smooth;
}
.column {
  max-width: var(--ds-chat-max);
  margin: 0 auto;
  width: 100%;
}
.thinking {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 4px 0 16px;
}
.avatar {
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
  flex-shrink: 0;
}
.label {
  color: var(--ds-muted);
  font-size: 13px;
}
.dots {
  display: flex;
  gap: 4px;
}
.dots span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ds-brand);
  animation: bounce 1.2s ease-in-out infinite;
}
.dots span:nth-child(2) {
  animation-delay: 0.15s;
}
.dots span:nth-child(3) {
  animation-delay: 0.3s;
}
@keyframes bounce {
  0%,
  80%,
  100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  40% {
    transform: translateY(-3px);
    opacity: 1;
  }
}
@media (prefers-reduced-motion: reduce) {
  .dots span {
    animation: none;
    opacity: 0.7;
  }
}
</style>
