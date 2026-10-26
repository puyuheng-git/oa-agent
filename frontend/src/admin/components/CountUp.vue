<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(defineProps<{ value: number; duration?: number }>(), { duration: 1200 })
const shown = ref(0)
const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
let raf = 0

watch(
  () => props.value,
  (to, from) => {
    cancelAnimationFrame(raf)
    if (reduced) {
      shown.value = to
      return
    }
    const start = performance.now()
    const begin = from ?? 0
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / props.duration)
      shown.value = Math.round(begin + (to - begin) * (1 - Math.pow(1 - t, 3)))
      if (t < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
  },
  { immediate: true },
)
onBeforeUnmount(() => cancelAnimationFrame(raf))
</script>

<template>
  <span class="tech-num">{{ shown.toLocaleString('en-US') }}</span>
</template>
