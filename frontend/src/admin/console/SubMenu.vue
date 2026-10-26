<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, type Component } from 'vue'
import { arcPositions, type Point } from './menuGroups'
import type { Telemetry } from './telemetry'

const props = defineProps<{
  origin: Point
  items: { path: string; title: string; code: string; icon: Component; telemetry?: Telemetry }[]
}>()
const emit = defineEmits<{ (e: 'select', path: string, at: Point): void; (e: 'close'): void }>()

const vw = ref(window.innerWidth)
const vh = ref(window.innerHeight)
const onResize = () => {
  vw.value = window.innerWidth
  vh.value = window.innerHeight
}
onMounted(() => window.addEventListener('resize', onResize))
onBeforeUnmount(() => window.removeEventListener('resize', onResize))

const positions = computed(() =>
  arcPositions(
    props.origin,
    { x: vw.value / 2, y: vh.value / 2 },
    props.items.length,
    props.items.length > 2 ? 150 : 130,
    props.items.length > 2 ? 0.78 : 0.95,
    { width: vw.value, height: vh.value, margin: 90 },
  ),
)
</script>

<template>
  <div class="layer" @click.self="emit('close')">
    <svg class="beams" :viewBox="`0 0 ${vw} ${vh}`" :width="vw" :height="vh" aria-hidden="true">
      <line
        v-for="(p, i) in positions"
        :key="i"
        class="beam"
        :style="{ '--i': i }"
        :x1="origin.x"
        :y1="origin.y"
        :x2="p.x"
        :y2="p.y"
      />
    </svg>
    <div class="hub" :style="{ left: `${origin.x}px`, top: `${origin.y}px` }" />
    <button
      v-for="(it, i) in items"
      :key="it.path"
      type="button"
      class="sub"
      :class="{ alert: it.telemetry?.tone === 'warn' }"
      :style="{ left: `${positions[i].x}px`, top: `${positions[i].y}px`, '--i': i, '--fx': `${origin.x - positions[i].x}px`, '--fy': `${origin.y - positions[i].y}px` }"
      @click="emit('select', it.path, positions[i])"
    >
      <span class="mini-hex">
        <svg viewBox="0 0 100 100" aria-hidden="true">
          <polygon points="50,4 92,28 92,72 50,96 8,72 8,28" />
        </svg>
        <el-icon :size="17"><component :is="it.icon" /></el-icon>
      </span>
      <span class="sub-label">
        <b>{{ it.title }}</b>
        <small>{{ it.code }}</small>
        <em v-if="it.telemetry">{{ it.telemetry.text }}</em>
      </span>
    </button>
  </div>
</template>

<style scoped>
.layer {
  position: absolute;
  inset: 0;
  z-index: 12;
  background: radial-gradient(circle at var(--x, 50%) var(--y, 50%), transparent, rgba(3, 6, 14, 0.35));
}
.beams {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: visible;
}
.beam {
  stroke: var(--tech-cyan);
  stroke-width: 1.5;
  stroke-dasharray: 6 5;
  filter: drop-shadow(0 0 4px var(--tech-cyan));
  opacity: 0;
  animation:
    beam-in 0.35s ease-out forwards calc(var(--i) * 70ms),
    beam-flow 1s linear infinite;
}
.hub {
  position: absolute;
  width: 96px;
  height: 96px;
  margin: -48px 0 0 -48px;
  border-radius: 50%;
  border: 1px dashed rgba(34, 211, 238, 0.6);
  box-shadow: 0 0 24px rgba(34, 211, 238, 0.35), inset 0 0 18px rgba(34, 211, 238, 0.2);
  pointer-events: none;
  animation: hub-spin 8s linear infinite;
}
.sub {
  --c: var(--tech-cyan);
  position: absolute;
  display: flex;
  align-items: center;
  gap: 8px;
  transform: translate(-50%, -50%);
  padding: 6px 14px 6px 6px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--c) 55%, transparent);
  background: rgba(7, 13, 26, 0.88);
  backdrop-filter: blur(8px);
  color: var(--tech-text);
  font: inherit;
  cursor: pointer;
  white-space: nowrap;
  box-shadow: 0 0 18px color-mix(in srgb, var(--c) 25%, transparent);
  opacity: 0;
  animation: sub-in 0.45s cubic-bezier(0.2, 1.3, 0.4, 1) forwards calc(var(--i) * 70ms + 80ms);
  transition: box-shadow 0.2s, border-color 0.2s, background 0.2s;
}
.sub.alert {
  --c: var(--tech-warning);
}
.sub:hover,
.sub:focus-visible {
  outline: none;
  background: color-mix(in srgb, var(--c) 14%, rgba(7, 13, 26, 0.92));
  box-shadow: 0 0 28px color-mix(in srgb, var(--c) 50%, transparent);
}
.mini-hex {
  position: relative;
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  color: var(--c);
}
.mini-hex svg {
  position: absolute;
  inset: 0;
}
.mini-hex polygon {
  fill: color-mix(in srgb, var(--c) 16%, transparent);
  stroke: var(--c);
  stroke-width: 4;
}
.sub-label {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  line-height: 1.25;
}
.sub-label b {
  font-size: 13px;
  letter-spacing: 1px;
}
.sub-label small {
  font-family: var(--tech-mono);
  font-size: 9px;
  letter-spacing: 2px;
  color: var(--tech-text-3);
}
.sub-label em {
  font-style: normal;
  font-family: var(--tech-mono);
  font-size: 11px;
  color: var(--c);
}
@keyframes sub-in {
  from {
    opacity: 0;
    transform: translate(calc(-50% + var(--fx)), calc(-50% + var(--fy))) scale(0.3);
  }
  to {
    opacity: 1;
    transform: translate(-50%, -50%) scale(1);
  }
}
@keyframes beam-in {
  to {
    opacity: 0.85;
  }
}
@keyframes beam-flow {
  to {
    stroke-dashoffset: -22;
  }
}
@keyframes hub-spin {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .beam,
  .sub {
    animation: none;
    opacity: 1;
  }
  .hub {
    animation: none;
  }
}
</style>
