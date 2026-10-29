<script setup lang="ts">
import type { OrbitId } from './orbits'
import type { Telemetry } from './telemetry'

defineProps<{
  title: string
  code: string
  /** 分子造型：monitor=DNA 双螺旋，handoff=苯环，ability=四面体分子，access=多肽链，security=染色体 */
  motif: string
  group: OrbitId
  telemetry?: Telemetry
  active?: boolean
  dimmed?: boolean
  count?: number
}>()

const HEX = Array.from({ length: 6 }, (_, i) => {
  const a = (Math.PI / 3) * i - Math.PI / 2
  return { x: 50 + Math.cos(a) * 24, y: 50 + Math.sin(a) * 24, hx: 50 + Math.cos(a) * 40, hy: 50 + Math.sin(a) * 40 }
})
const DOUBLE = [0, 2, 4].map((i) => {
  const a = HEX[i]
  const b = HEX[(i + 1) % 6]
  const k = 0.78
  return { x1: 50 + (a.x - 50) * k, y1: 50 + (a.y - 50) * k, x2: 50 + (b.x - 50) * k, y2: 50 + (b.y - 50) * k }
})
const CHAIN = [
  [10, 60],
  [28, 42],
  [46, 60],
  [64, 42],
  [82, 60],
] as const
const CHAIN_PATH = `M ${CHAIN.map(([x, y]) => `${x} ${y}`).join(' L ')}`
const SIDE = CHAIN.map(([x, y], i) => ({ x, y, sx: x, sy: i % 2 ? y - 18 : y + 18 }))
const BANDS = [-30, -22, -12, 12, 20, 30]
</script>

<template>
  <button type="button" class="sat" :class="[group, { alert: telemetry?.tone === 'warn', active, dimmed }]">
    <span class="glyph">
      <span class="halo" />

      <span v-if="motif === 'monitor'" class="dna" aria-hidden="true">
        <i v-for="k in 9" :key="k" :style="{ '--k': k }"><b /><b /></i>
      </span>

      <svg v-else viewBox="0 0 100 100" class="mol" aria-hidden="true">
        <g v-if="motif === 'handoff'" class="spin-slow">
          <polygon :points="HEX.map((p) => `${p.x},${p.y}`).join(' ')" class="bond-fill" />
          <line v-for="(p, i) in HEX" :key="`h${i}`" :x1="p.x" :y1="p.y" :x2="p.hx" :y2="p.hy" class="bond thin" />
          <line v-for="(d, i) in DOUBLE" :key="`d${i}`" v-bind="d" class="bond" />
          <polygon :points="HEX.map((p) => `${p.x},${p.y}`).join(' ')" class="bond ring" />
          <circle v-for="(p, i) in HEX" :key="`a${i}`" :cx="p.x" :cy="p.y" r="5.2" class="atom" />
          <circle v-for="(p, i) in HEX" :key="`s${i}`" :cx="p.hx" :cy="p.hy" r="3" class="atom small" />
        </g>

        <g v-else-if="motif === 'ability'">
          <ellipse cx="50" cy="50" rx="42" ry="14" class="orbit spin-mid" />
          <ellipse cx="50" cy="50" rx="42" ry="14" class="orbit spin-mid rev" transform="rotate(60 50 50)" />
          <line x1="50" y1="50" x2="50" y2="16" class="bond" />
          <line x1="50" y1="50" x2="80" y2="66" class="bond" />
          <line x1="50" y1="50" x2="22" y2="68" class="bond" />
          <line x1="50" y1="50" x2="64" y2="40" class="bond back" />
          <circle cx="64" cy="40" r="4.5" class="atom back" />
          <circle cx="50" cy="16" r="6" class="atom" />
          <circle cx="80" cy="66" r="7" class="atom alt" />
          <circle cx="22" cy="68" r="5.5" class="atom" />
          <circle cx="50" cy="50" r="10" class="atom core pulse" />
        </g>

        <g v-else-if="motif === 'access'">
          <line v-for="(s, i) in SIDE" :key="`b${i}`" :x1="s.x" :y1="s.y" :x2="s.sx" :y2="s.sy" class="bond thin" />
          <path :d="CHAIN_PATH" class="bond chain" />
          <circle v-for="(s, i) in SIDE" :key="`s${i}`" :cx="s.sx" :cy="s.sy" r="3.6" class="atom small" :class="{ alt: i % 2 }" />
          <circle v-for="([x, y], i) in CHAIN" :key="`a${i}`" :cx="x" :cy="y" r="5.5" class="atom" />
          <circle r="3.4" class="spark">
            <animateMotion dur="2.4s" repeatCount="indefinite" :path="CHAIN_PATH" />
          </circle>
        </g>

        <g v-else class="sway">
          <g v-for="rot in [-28, 28]" :key="rot" :transform="`rotate(${rot} 50 50)`">
            <rect x="42" y="12" width="16" height="76" rx="8" class="chromo" />
            <line v-for="b in BANDS" :key="b" x1="43" :y1="50 + b" x2="57" :y2="50 + b" class="band" />
          </g>
          <circle cx="50" cy="50" r="5" class="atom core pulse" />
        </g>
      </svg>

      <span v-if="telemetry?.tone === 'warn' || active" class="ping" />
      <span v-if="count && count > 1" class="badge tech-num">{{ count }}</span>
    </span>
    <span class="label">
      <span class="title">{{ title }}</span>
      <span class="code">{{ code }}</span>
      <span v-if="telemetry" class="tele">{{ telemetry.text }}</span>
    </span>
  </button>
</template>

<style scoped>
.sat {
  --c: #22d3ee;
  --c2: #818cf8;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  background: none;
  border: 0;
  padding: 0;
  cursor: pointer;
  color: var(--tech-text);
  font: inherit;
  transition: opacity 0.35s, filter 0.35s;
}
.sat.config {
  --c: #a5b4fc;
  --c2: #22d3ee;
}
.sat.system {
  --c: #60a5fa;
  --c2: #c4b5fd;
}
.sat.alert {
  --c: #fbbf24;
  --c2: #f472b6;
}
.glyph {
  position: relative;
  width: 64px;
  height: 64px;
  display: grid;
  place-items: center;
  /* 无过冲：过冲缩放容易在悬停时看起来像链条在抖 */
  transition: transform 0.25s ease, filter 0.25s ease;
  filter: drop-shadow(0 0 5px color-mix(in srgb, var(--c) 70%, transparent));
}
.halo {
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  background: radial-gradient(circle, color-mix(in srgb, var(--c) 18%, transparent), transparent 70%);
}
.mol {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: visible;
}

.bond {
  stroke: color-mix(in srgb, var(--c) 75%, transparent);
  stroke-width: 2.4;
  stroke-linecap: round;
  fill: none;
}
.bond.thin {
  stroke-width: 1.4;
  stroke: color-mix(in srgb, var(--c) 50%, transparent);
}
.bond.ring {
  stroke-width: 2.6;
}
.bond.back {
  stroke-dasharray: 2 3;
  opacity: 0.6;
}
.bond.chain {
  stroke-width: 2.6;
  stroke-linejoin: round;
}
.bond-fill {
  fill: color-mix(in srgb, var(--c) 10%, transparent);
}
.atom {
  fill: color-mix(in srgb, var(--c) 35%, rgba(7, 11, 20, 0.6));
  stroke: var(--c);
  stroke-width: 1.6;
}
.atom.small {
  stroke-width: 1.2;
  fill: color-mix(in srgb, var(--c2) 30%, transparent);
  stroke: var(--c2);
}
.atom.alt {
  stroke: var(--c2);
  fill: color-mix(in srgb, var(--c2) 35%, rgba(7, 11, 20, 0.6));
}
.atom.back {
  opacity: 0.55;
}
.atom.core {
  fill: color-mix(in srgb, var(--c) 55%, #fff 10%);
  stroke-width: 2;
}
.orbit {
  fill: none;
  stroke: color-mix(in srgb, var(--c2) 55%, transparent);
  stroke-width: 1;
  stroke-dasharray: 3 4;
}
.spark {
  fill: #fff;
  filter: drop-shadow(0 0 4px var(--c));
}
.chromo {
  fill: color-mix(in srgb, var(--c) 16%, transparent);
  stroke: var(--c);
  stroke-width: 1.8;
}
.band {
  stroke: var(--c2);
  stroke-width: 2.2;
  opacity: 0.75;
}

/* DNA 双螺旋：每条碱基对横杆沿 X 轴翻转，错开相位形成螺旋 */
.dna {
  position: relative;
  width: 38px;
  height: 62px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  transform: rotate(-18deg);
}
.dna i {
  position: relative;
  display: block;
  height: 2px;
  background: linear-gradient(90deg, color-mix(in srgb, var(--c) 65%, transparent), color-mix(in srgb, var(--c2) 65%, transparent));
  animation: helix 2.6s ease-in-out infinite;
  animation-delay: calc(var(--k) * -0.29s);
}
.dna b {
  position: absolute;
  top: -2.5px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.dna b:first-child {
  left: -3px;
  background: var(--c);
  box-shadow: 0 0 6px var(--c);
}
.dna b:last-child {
  right: -3px;
  background: var(--c2);
  box-shadow: 0 0 6px var(--c2);
}

.spin-slow,
.spin-mid,
.sway,
.pulse {
  transform-box: view-box;
  transform-origin: 50px 50px;
}
.spin-slow {
  animation: spin 18s linear infinite;
}
.spin-mid {
  animation: spin 7s linear infinite;
}
.spin-mid.rev {
  animation-direction: reverse;
}
.sway {
  animation: sway 5s ease-in-out infinite;
}
.pulse {
  animation: pulse 1.8s ease-in-out infinite;
}

.ping {
  position: absolute;
  inset: -6px;
  border-radius: 50%;
  border: 2px solid var(--c);
  animation: ping 1.6s ease-out infinite;
}
.label {
  display: flex;
  flex-direction: column;
  align-items: center;
  line-height: 1.3;
  white-space: nowrap;
  padding: 3px 10px 4px;
  border-radius: 6px;
  background: linear-gradient(180deg, rgba(7, 11, 20, 0.15), rgba(7, 11, 20, 0.6));
  border: 1px solid transparent;
  transition: border-color 0.3s, background 0.3s;
}
.title {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 1px;
  text-shadow: 0 0 8px rgba(0, 0, 0, 0.9);
}
.code {
  font-family: var(--tech-mono);
  font-size: 9px;
  letter-spacing: 2px;
  color: color-mix(in srgb, var(--c) 75%, transparent);
}
.tele {
  margin-top: 2px;
  font-family: var(--tech-mono);
  font-size: 11px;
  color: var(--c);
  text-shadow: 0 0 6px var(--c);
}
.sat:hover .glyph,
.sat:focus-visible .glyph {
  transform: scale(1.1);
  filter: drop-shadow(0 0 10px var(--c));
}
.sat:hover .label,
.sat:focus-visible .label {
  border-color: color-mix(in srgb, var(--c) 45%, transparent);
  background: rgba(7, 11, 20, 0.8);
}
.sat:focus-visible {
  outline: none;
}
.sat.dimmed {
  opacity: 0.25;
  filter: blur(1px) grayscale(0.6);
}
.sat.active .glyph {
  transform: scale(1.22);
  filter: drop-shadow(0 0 14px var(--c));
}
.badge {
  position: absolute;
  top: -2px;
  right: -6px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  font-size: 10px;
  line-height: 16px;
  text-align: center;
  color: #04121a;
  background: var(--c);
  box-shadow: 0 0 8px var(--c);
}

@keyframes helix {
  0%,
  100% {
    transform: scaleX(1);
    opacity: 1;
  }
  25%,
  75% {
    opacity: 0.45;
  }
  50% {
    transform: scaleX(-1);
    opacity: 1;
  }
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes sway {
  0%,
  100% {
    transform: rotate(-8deg);
  }
  50% {
    transform: rotate(8deg);
  }
}
@keyframes pulse {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.18);
  }
}
@keyframes ping {
  from {
    transform: scale(0.8);
    opacity: 0.9;
  }
  to {
    transform: scale(1.6);
    opacity: 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .dna i,
  .spin-slow,
  .spin-mid,
  .sway,
  .pulse,
  .ping {
    animation: none;
  }
  .spark {
    display: none;
  }
}
</style>
