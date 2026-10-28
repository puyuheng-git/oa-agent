<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ORBITS, orbitPoint, projectSimple, type NodeLayout, type Projected } from './orbits'
import type { Mood } from './telemetry'
import type { CoreMode, NeuralCore } from './NeuralCore'

const props = withDefaults(
  defineProps<{
    mood: Mood
    mode: CoreMode
    nodes?: NodeLayout[]
    paused?: boolean
    activity?: number
    lerpRate?: number
  }>(),
  {
    nodes: () => [],
    paused: false,
    activity: 0,
    lerpRate: 2.5,
  },
)

const FOLDS = [
  'M58 84 C74 72 88 92 106 80',
  'M92 52 C106 64 122 46 138 58',
  'M150 42 C160 62 178 56 190 72',
  'M66 108 C86 98 106 114 128 100',
  'M138 82 C154 94 170 86 186 100',
  'M116 32 C110 52 122 66 112 86',
  'M84 132 C100 124 118 134 136 124',
]

const root = ref<HTMLDivElement>()
const canvas = ref<HTMLCanvasElement>()
const webgl = ref(false)
const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

let core: NeuralCore | null = null
let raf = 0
let last = 0
let orbitT = 0
let timeScale = 1
let hovering = 0
let disposed = false
const nodeEls = new Map<string, HTMLElement>()
const positions = new Map<string, Projected>()

function setNodeEl(key: string, el: unknown) {
  if (el) nodeEls.set(key, el as HTMLElement)
  else nodeEls.delete(key)
}

function hoverIn() {
  hovering++
}
function hoverOut() {
  hovering = Math.max(0, hovering - 1)
}

function place(dt: number) {
  const el = root.value
  if (!el) return
  if (props.paused) timeScale = 0
  // 悬停时尽快刹停轨道，避免与指针视差叠成抖动
  const target = hovering > 0 || reduced || props.paused ? 0 : 1
  const brake = hovering > 0 ? 10 : 4
  timeScale += (target - timeScale) * Math.min(1, dt * brake)
  if (timeScale < 0.002) timeScale = 0
  orbitT += dt * timeScale
  const w = el.clientWidth
  const h = el.clientHeight
  for (const n of props.nodes) {
    const node = nodeEls.get(n.key)
    if (!node) continue
    const orbit = ORBITS[n.orbit]
    const p = orbitPoint(orbit, n.phase + orbitT * orbit.speed)
    const s = core ? core.project(p, w, h) : projectSimple(p, w, h)
    positions.set(n.key, s)
    const depth = Math.max(0.6, Math.min(1.25, s.scale))
    node.style.transform = `translate3d(${s.x.toFixed(1)}px, ${s.y.toFixed(1)}px, 0) translate(-50%, -50%) scale(${depth.toFixed(3)})`
    node.style.zIndex = String(Math.round(depth * 100))
    node.style.setProperty('--depth', ((depth - 0.6) / 0.65).toFixed(3))
    node.style.opacity = ''
  }
}

function fallbackLoop(now: number) {
  raf = requestAnimationFrame(fallbackLoop)
  const dt = last ? Math.min((now - last) / 1000, 0.05) : 0
  last = now
  if (!document.hidden) place(dt)
}

let pointerRaf = 0
let pendingPtr: PointerEvent | null = null
function onPointer(e: PointerEvent) {
  // 悬停卫星时冻结视差，否则相机跟着鼠标动、节点投影跟着抖
  if (props.paused || hovering > 0) return
  pendingPtr = e
  if (pointerRaf) return
  pointerRaf = requestAnimationFrame(() => {
    pointerRaf = 0
    const p = pendingPtr
    pendingPtr = null
    if (!p || props.paused || hovering > 0) return
    core?.setPointer((p.clientX / window.innerWidth) * 2 - 1, -((p.clientY / window.innerHeight) * 2 - 1))
  })
}

const resizer = new ResizeObserver(() => {
  if (root.value) core?.resize(root.value.clientWidth, root.value.clientHeight)
})

onMounted(async () => {
  resizer.observe(root.value!)
  window.addEventListener('pointermove', onPointer)
  if (!reduced) {
    const mod = await import('./NeuralCore')
    if (!disposed && mod.webglSupported()) {
      try {
        webgl.value = true
        core = new mod.NeuralCore(canvas.value!, place, props.mode)
        core.setMood(props.mood)
        core.setActivity(props.activity)
        core.setPaused(props.paused)
        core.setLerpRate(props.lerpRate)
        return
      } catch {
        webgl.value = false
        core = null
      }
    }
  }
  if (!disposed) raf = requestAnimationFrame(fallbackLoop)
})

watch(() => props.mood, (m) => core?.setMood(m))
watch(() => props.mode, (m) => core?.setMode(m))
watch(() => props.activity, (a) => core?.setActivity(a))
watch(() => props.paused, (p) => core?.setPaused(p))
watch(() => props.lerpRate, (r) => core?.setLerpRate(r))

onBeforeUnmount(() => {
  disposed = true
  cancelAnimationFrame(raf)
  cancelAnimationFrame(pointerRaf)
  resizer.disconnect()
  window.removeEventListener('pointermove', onPointer)
  core?.dispose()
  core = null
})

defineExpose({
  nodePosition: (key: string) => positions.get(key) ?? null,
})
</script>

<template>
  <div ref="root" class="stage" :class="[`mood-${mood}`, `mode-${mode}`, { webgl, paused }]">
    <canvas v-show="webgl" ref="canvas" class="gl" />
    <div v-if="!webgl" class="fallback" :style="{ '--think': String(1.8 - activity * 1.1) + 's' }">
      <svg class="brain-svg" viewBox="0 0 240 180" aria-hidden="true">
        <path
          class="outline"
          d="M60 120 C30 115 20 85 35 62 C45 35 80 20 112 24 C140 12 182 22 200 50 C222 60 226 95 210 112 C205 132 180 140 160 134 C150 150 120 152 108 140 C92 146 70 138 60 120 Z"
        />
        <path class="outline" d="M150 136 C160 152 186 152 198 136" />
        <path class="outline" d="M138 142 C137 156 135 166 131 178" />
        <path v-for="(d, i) in FOLDS" :key="i" class="fold" :d="d" :style="{ animationDelay: `${i * -0.37}s` }" />
      </svg>
      <div class="ring r1" />
      <div class="ring r2" />
      <div class="ring r3" />
    </div>
    <div class="floor" />
    <div class="vignette" />
    <div class="nodes">
      <div
        v-for="n in nodes"
        :key="n.key"
        :ref="(el) => setNodeEl(n.key, el)"
        class="node-wrap"
        @mouseenter="hoverIn"
        @mouseleave="hoverOut"
      >
        <slot name="node" :node="n" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.stage {
  position: fixed;
  inset: 0;
  overflow: hidden;
  --mood: #818cf8;
}
.stage.mood-ok {
  --mood: #22d3ee;
}
.stage.mood-warn {
  --mood: #fbbf24;
}
.stage.mood-bad {
  --mood: #f43f5e;
}
.gl {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
  mix-blend-mode: screen;
  contain: strict;
}
/* 面板打开时冻结画面并弱化混合，避免滚动时每帧重算 screen blend */
.stage.paused .gl {
  mix-blend-mode: normal;
  opacity: 0.35;
  pointer-events: none;
}
.stage.paused .floor,
.stage.paused .fallback {
  animation: none;
}

.fallback {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 0;
  height: 0;
  perspective: 900px;
  transition: transform 0.8s ease, opacity 0.8s;
}
.brain-svg {
  position: absolute;
  width: 320px;
  height: 240px;
  left: -160px;
  top: -130px;
  overflow: visible;
  filter: drop-shadow(0 0 8px var(--mood)) drop-shadow(0 0 28px color-mix(in srgb, var(--mood) 50%, transparent));
  animation: orb-breathe 3.2s ease-in-out infinite;
}
.brain-svg path {
  fill: none;
  stroke: var(--mood);
  stroke-linecap: round;
}
.brain-svg .outline {
  stroke-width: 1.6;
  opacity: 0.85;
}
.brain-svg .fold {
  stroke-width: 1.4;
  stroke-dasharray: 10 70;
  animation: fold-flow var(--think, 1.8s) linear infinite;
}
@keyframes fold-flow {
  to {
    stroke-dashoffset: -80;
  }
}
.ring {
  position: absolute;
  border: 1px solid color-mix(in srgb, var(--mood) 55%, transparent);
  border-radius: 50%;
  box-shadow: 0 0 12px color-mix(in srgb, var(--mood) 40%, transparent);
  transform-style: preserve-3d;
}
.r1 {
  width: 520px;
  height: 520px;
  left: -260px;
  top: -260px;
  transform: rotateX(70deg) rotateZ(-10deg);
  animation: spin 40s linear infinite;
}
.r2 {
  width: 700px;
  height: 700px;
  left: -350px;
  top: -350px;
  transform: rotateX(74deg) rotateZ(12deg);
  border-style: dashed;
}
.r3 {
  width: 880px;
  height: 880px;
  left: -440px;
  top: -440px;
  transform: rotateX(68deg) rotateZ(4deg);
  opacity: 0.6;
}
.mode-dormant .fallback {
  opacity: 0.55;
}
.mode-focus .fallback {
  opacity: 0.35;
}

.floor {
  position: absolute;
  left: -50%;
  right: -50%;
  bottom: -10%;
  height: 55%;
  background-image:
    linear-gradient(color-mix(in srgb, var(--mood) 22%, transparent) 1px, transparent 1px),
    linear-gradient(90deg, color-mix(in srgb, var(--mood) 22%, transparent) 1px, transparent 1px);
  background-size: 60px 60px;
  transform: perspective(500px) rotateX(72deg);
  transform-origin: center top;
  mask-image: linear-gradient(to bottom, transparent, #000 30%, #000 60%, transparent);
  -webkit-mask-image: linear-gradient(to bottom, transparent, #000 30%, #000 60%, transparent);
  opacity: 0.35;
  pointer-events: none;
  animation: floor-move 6s linear infinite;
  transition: opacity 0.8s;
}
.mode-focus .floor,
.mode-dormant .floor {
  opacity: 0.15;
}
.vignette {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(ellipse 75% 70% at 50% 50%, transparent 55%, rgba(3, 6, 14, 0.85) 100%),
    repeating-linear-gradient(0deg, rgba(255, 255, 255, 0.018) 0 1px, transparent 1px 3px);
}

.nodes {
  position: absolute;
  inset: 0;
  transition: opacity 0.5s, filter 0.5s;
}
.mode-focus .nodes,
.mode-dormant .nodes,
.mode-awaken .nodes {
  opacity: 0;
  pointer-events: none;
  filter: blur(6px);
}
.node-wrap {
  position: absolute;
  left: 0;
  top: 0;
  will-change: transform;
  opacity: calc(0.45 + var(--depth, 1) * 0.55);
}
.node-wrap:hover {
  opacity: 1;
  z-index: 1000 !important;
}

@keyframes orb-breathe {
  0%,
  100% {
    transform: scale(1);
    filter: brightness(1);
  }
  50% {
    transform: scale(1.06);
    filter: brightness(1.25);
  }
}
@keyframes spin {
  to {
    transform: rotateX(70deg) rotateZ(350deg);
  }
}
@keyframes floor-move {
  to {
    background-position: 0 60px, 0 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .brain-svg,
  .brain-svg .fold,
  .r1,
  .floor {
    animation: none;
  }
  .brain-svg .fold {
    stroke-dasharray: none;
    opacity: 0.6;
  }
}
</style>
