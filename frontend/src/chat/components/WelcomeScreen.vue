<script setup lang="ts">
import AIBrainVisual from './AIBrainVisual.vue'

defineProps<{
  displayName: string
  examples: string[]
  skillNames: string[]
  chatEnabled: boolean
}>()

const emit = defineEmits<{
  example: [text: string]
}>()
</script>

<template>
  <div class="welcome">
    <div class="hero">
      <AIBrainVisual class="brain" />
      <h1 class="title">你好，我是东审财税 AI 助手</h1>
      <p class="subtitle">从任务理解到文件交付，协助你完成财税工作每一步。</p>
      <p class="hello">
        <template v-if="displayName">{{ displayName }}，</template>
        <template v-if="chatEnabled">直接提问即可</template>
        <template v-if="skillNames.length">；也可查询<strong>本人</strong> OA 数据</template>
        <template v-else-if="!chatEnabled">暂无可用能力，请联系管理员</template>
        。
      </p>
      <div v-if="skillNames.length" class="skills">
        <span v-for="n in skillNames" :key="n" class="skill">{{ n }}</span>
      </div>
    </div>

    <div v-if="examples.length" class="examples">
      <button
        v-for="ex in examples.slice(0, 4)"
        :key="ex"
        type="button"
        class="chip"
        @click="emit('example', ex)"
      >
        {{ ex }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.welcome {
  max-width: var(--ds-chat-max);
  margin: 0 auto;
  padding: 28px 4px 8px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: min(52vh, 420px);
}
.hero {
  text-align: center;
  padding: 0 8px 4px;
}
.brain {
  width: 80px !important;
  margin: 0 auto 12px;
}
.title {
  margin: 0 0 8px;
  font-size: 20px;
  font-weight: 700;
  color: var(--ds-title);
  line-height: 1.35;
}
.subtitle {
  margin: 0 auto;
  max-width: 28em;
  font-size: 14px;
  line-height: 1.55;
  color: var(--ds-body);
}
.hello {
  margin: 10px 0 0;
  font-size: 13px;
  color: var(--ds-muted);
  line-height: 1.5;
}
.skills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: center;
  margin-top: 12px;
}
.skill {
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--ds-brand-soft);
  color: var(--ds-brand);
  font-size: 12px;
  font-weight: 600;
}
.examples {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 20px;
}
.chip {
  border: 1px solid var(--ds-line);
  background: #fff;
  color: var(--ds-title);
  padding: 12px 14px;
  border-radius: var(--ds-radius);
  font-size: 13px;
  cursor: pointer;
  line-height: 1.45;
  text-align: left;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}
.chip:hover {
  border-color: rgba(0, 138, 231, 0.4);
  background: var(--ds-brand-soft);
  color: var(--ds-brand);
}

@media (max-width: 560px) {
  .examples {
    grid-template-columns: 1fr;
  }
  .welcome {
    min-height: auto;
    padding-top: 16px;
  }
}
</style>
