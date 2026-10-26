<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <div class="empty">
    <div class="ring" aria-hidden="true">
      <div class="empty-icon"><slot name="icon">◇</slot></div>
    </div>
    <p class="empty-title">{{ title }}</p>
    <p v-if="description" class="empty-desc">{{ description }}</p>
    <slot />
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 18px 12px 8px;
  color: var(--ds-muted);
}
.ring {
  width: 48px;
  height: 48px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
  background: linear-gradient(145deg, #fff, var(--ds-brand-soft));
  border: 1px solid var(--ds-line);
  box-shadow: 0 6px 16px rgba(0, 138, 231, 0.08);
}
.empty-icon {
  color: var(--ds-brand);
  font-size: 16px;
  opacity: 0.85;
}
.empty-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 700;
  color: var(--ds-title);
}
.empty-desc {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.55;
  max-width: 220px;
}
</style>
