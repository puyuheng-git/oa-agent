<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { http } from '@/shared/http'
import { formatTime } from '@/shared/format'
import {
  NO_DATA,
  RANGE_PRESETS,
  formatDuration,
  formatP95,
  rangeParams,
  type RangePreset,
  type RunStats,
  type TopError,
} from '../runs'
import { arcPath, gaugeTicks, statusRings, trendOption } from '../charts'
import TechChart from '../components/TechChart.vue'
import CountUp from '../components/CountUp.vue'

const router = useRouter()
const preset = ref<RangePreset>('24h')
const stats = ref<RunStats | null>(null)
const errors = ref<TopError[]>([])
const failed = ref(false)
const loading = ref(false)
let range = rangeParams(preset.value)

async function load() {
  if (document.hidden) return
  loading.value = true
  range = rangeParams(preset.value)
  try {
    const [s, e] = await Promise.all([
      http.get<RunStats>('/v1/admin/runs/stats', range),
      http.get<{ items: TopError[] }>('/v1/admin/runs/errors/top', { ...range, limit: 5 }),
    ])
    stats.value = s
    errors.value = e.items
    failed.value = false
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

function setPreset(p: RangePreset) {
  preset.value = p
  load()
}

function goList(query: Record<string, string>) {
  router.push({ path: '/runs', query: { ...range, ...query } })
}

const trend = computed(() => (stats.value ? trendOption(stats.value) : null))
const rings = computed(() => (stats.value ? statusRings(stats.value) : []))
const ticks = computed(() => gaugeTicks(stats.value?.success_rate ?? null, 48))
const rate = computed(() => {
  const r = stats.value?.success_rate
  return r === null || r === undefined ? null : Math.round(r * 1000) / 10
})
const obsDegraded = computed(() => stats.value && stats.value.observability?.status !== 'ok')

const ENERGY = 32
const energy = computed(() => {
  const t = stats.value?.tokens
  if (!t || !t.total_tokens) return null
  const prompt = Math.round((t.prompt_tokens / t.total_tokens) * ENERGY)
  return Array.from({ length: ENERGY }, (_, i) => (i < prompt ? 'in' : 'out'))
})

const RING_R0 = 70
const RING_STEP = 11
const ringR = (i: number) => RING_R0 - i * RING_STEP

const pad2 = (n: number) => String(n + 1).padStart(2, '0')
/** 刻度由靛蓝渐变到青色 */
const tickColor = (i: number, n: number) => `hsla(${Math.round(238 - (i / (n - 1)) * 50)}, 90%, 68%, 0.78)`

const root = ref<HTMLDivElement>()
const leftWing = ref<HTMLElement>()
const size = ref({ w: 0, h: 0, wing: 0, cy: 0 })
const resizer = new ResizeObserver(measure)
function measure() {
  const el = root.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  size.value = {
    w: el.clientWidth,
    h: el.clientHeight,
    wing: leftWing.value?.offsetWidth ?? 0,
    cy: window.innerHeight / 2 - rect.top,
  }
}

/** 两翼内侧到大脑边缘的数据流弧线 */
const streams = computed(() => {
  const { w, h, wing, cy } = size.value
  if (!w || !wing) return []
  const cx = w / 2
  const out: { d: string; side: 'l' | 'r'; dur: number }[] = []
  ;[0.2, 0.5, 0.8].forEach((f, i) => {
    const y0 = h * f
    const ty = cy + (y0 - cy) * 0.28
    const lx = 20 + wing + 10
    const ltx = cx - 150
    out.push({ d: `M ${lx} ${y0} C ${lx + 140} ${y0}, ${ltx - 160} ${ty}, ${ltx} ${ty}`, side: 'l', dur: 2.6 + i * 0.7 })
    const rx = w - 20 - wing - 10
    const rtx = cx + 150
    out.push({ d: `M ${rx} ${y0} C ${rx - 140} ${y0}, ${rtx + 160} ${ty}, ${rtx} ${ty}`, side: 'r', dur: 3.1 + i * 0.6 })
  })
  return out
})

let timer = 0
onMounted(() => {
  load()
  timer = window.setInterval(load, 30_000)
  resizer.observe(root.value!)
  window.addEventListener('resize', measure)
  measure()
})
onBeforeUnmount(() => {
  clearInterval(timer)
  resizer.disconnect()
  window.removeEventListener('resize', measure)
})
</script>

<template>
  <div ref="root" class="wings">
    <svg class="streams" aria-hidden="true">
      <defs>
        <linearGradient id="stream-l" x1="0" x2="1">
          <stop offset="0" stop-color="#22d3ee" stop-opacity="0.55" />
          <stop offset="1" stop-color="#22d3ee" stop-opacity="0" />
        </linearGradient>
        <linearGradient id="stream-r" x1="1" x2="0">
          <stop offset="0" stop-color="#818cf8" stop-opacity="0.55" />
          <stop offset="1" stop-color="#818cf8" stop-opacity="0" />
        </linearGradient>
      </defs>
      <g v-for="(s, i) in streams" :key="i">
        <path :d="s.d" class="stream" :stroke="`url(#stream-${s.side})`" />
        <path :d="s.d" class="stream-dash" :class="s.side" :style="{ animationDuration: `${s.dur}s` }" />
        <circle r="2.4" class="spark" :class="s.side">
          <animateMotion :dur="`${s.dur}s`" repeatCount="indefinite" :path="s.d" />
        </circle>
      </g>
    </svg>

    <aside ref="leftWing" class="wing left">
      <header class="hud-head" style="--i: 0">
        <span class="hud-title">运行态势<em>TELEMETRY</em></span>
        <span class="presets">
          <button
            v-for="p in RANGE_PRESETS"
            :key="p.value"
            type="button"
            :class="{ on: preset === p.value }"
            @click="setPreset(p.value)"
          >
            {{ p.value.toUpperCase() }}
          </button>
        </span>
      </header>

      <div v-if="failed && !stats" class="hud-empty">统计数据加载失败</div>
      <template v-else-if="stats">
        <div v-if="obsDegraded" class="obs-warn" style="--i: 1">▲ 运行监控写入降级，统计可能暂缺部分记录</div>

        <section class="gauge" style="--i: 1">
          <svg viewBox="0 0 200 200" class="gauge-svg">
            <defs>
              <radialGradient id="g-glass">
                <stop offset="0" stop-color="#22d3ee" stop-opacity="0.16" />
                <stop offset="0.75" stop-color="#6366f1" stop-opacity="0.05" />
                <stop offset="1" stop-color="#6366f1" stop-opacity="0" />
              </radialGradient>
            </defs>
            <circle cx="100" cy="100" r="80" fill="url(#g-glass)" />
            <circle cx="100" cy="100" r="95" class="g-dash spin" />
            <path :d="arcPath(100, 100, 87, 20, 70)" class="g-arc spin-rev" />
            <path :d="arcPath(100, 100, 87, 200, 50)" class="g-arc spin-rev" />
            <line
              v-for="(t, i) in ticks"
              :key="i"
              x1="100"
              y1="22"
              x2="100"
              y2="34"
              class="g-tick"
              :class="{ on: t.on }"
              :style="{ '--d': `${i * 18}ms`, stroke: t.on ? tickColor(i, ticks.length) : undefined }"
              :transform="`rotate(${t.angle} 100 100)`"
            />
            <circle cx="100" cy="100" r="58" class="g-inner" />
            <circle cx="100" cy="100" r="50" class="g-inner-dash spin" />
          </svg>
          <div class="gauge-center">
            <template v-if="rate !== null">
              <div class="gauge-val tech-num">{{ rate }}<small>%</small></div>
              <div class="gauge-sub">SUCCESS RATE</div>
            </template>
            <div v-else class="gauge-none">{{ NO_DATA }}</div>
          </div>
          <div class="gauge-note">分母 {{ stats.rate_denominator }} · 成功 + 失败 + 超时</div>
        </section>

        <div class="readouts">
          <div class="readout" style="--i: 2">
            <div class="ro-label"><em>RUNS</em>运行总数</div>
            <div class="ro-val"><CountUp :value="stats.total" /></div>
            <div class="ro-sub">进行中 {{ stats.in_progress }}</div>
          </div>
          <button
            type="button"
            class="readout clickable"
            :class="{ alert: stats.suspected_stuck > 0 }"
            style="--i: 3"
            title="查看疑似卡住的运行"
            @click="goList({ stuck_only: 'true' })"
          >
            <div class="ro-label"><em>STUCK</em>疑似卡住</div>
            <div class="ro-val">
              <svg v-if="stats.suspected_stuck > 0" class="warn-tri" viewBox="0 0 24 22" aria-hidden="true">
                <path d="M12 2 L22.5 20 H1.5 Z" />
                <path d="M12 8.5 V13.5 M12 16.2 V16.6" />
              </svg>
              <CountUp :value="stats.suspected_stuck" />
            </div>
            <div class="ro-sub">点击查看 ›</div>
          </button>
          <div class="readout" style="--i: 4">
            <div class="ro-label"><em>LATENCY</em>耗时 P50</div>
            <div class="ro-val small">{{ formatDuration(stats.duration_ms.p50) }}</div>
            <div class="ro-sub">P95 {{ formatP95(stats.duration_ms) }}</div>
          </div>
          <div class="readout" style="--i: 5">
            <div class="ro-label"><em>CALLS</em>Tool / 模型</div>
            <div class="ro-val small"><CountUp :value="stats.tool_calls" /> / <CountUp :value="stats.model_calls" /></div>
            <div class="ro-sub">规则解析不产生模型调用</div>
          </div>
        </div>

        <section class="token" style="--i: 6">
          <div class="hud-label"><i />Token<em>PROVIDER USAGE</em></div>
          <template v-if="stats.tokens && energy">
            <div class="token-val"><CountUp :value="stats.tokens.total_tokens" /></div>
            <div class="energy">
              <i v-for="(e, i) in energy" :key="i" :class="e" :style="{ '--d': `${i * 25}ms` }" />
            </div>
            <div class="token-legend tech-num">
              <span><b class="in" />输入 {{ stats.tokens.prompt_tokens.toLocaleString('en-US') }}</span>
              <span><b class="out" />输出 {{ stats.tokens.completion_tokens.toLocaleString('en-US') }}</span>
            </div>
          </template>
          <template v-else>
            <div class="token-val muted">{{ NO_DATA }}</div>
            <div class="ro-sub">范围内没有提供方返回的用量记录</div>
          </template>
        </section>
      </template>
      <div v-else class="hud-empty">{{ loading ? '正在接收遥测…' : NO_DATA }}</div>
    </aside>

    <aside class="wing right">
      <header class="hud-head" style="--i: 0">
        <span class="hud-title">态势分析<em>ANALYTICS</em></span>
        <span v-if="stats" class="stamp tech-num">SYNC {{ formatTime(stats.generated_at).slice(11) }}</span>
      </header>
      <template v-if="stats">
        <section class="framed" style="--i: 1">
          <div class="hud-label"><i />按天趋势<em>DAILY · UTC+8</em></div>
          <div class="bracket">
            <TechChart :option="trend" height="168px" />
            <div class="scanline" />
          </div>
        </section>

        <section style="--i: 2">
          <div class="hud-label"><i />状态分布<em>STATUS</em></div>
          <div v-if="!rings.length" class="hud-empty small">{{ NO_DATA }}</div>
          <div v-else class="rings">
            <svg viewBox="0 0 160 160" class="rings-svg">
              <circle cx="80" cy="80" r="74" fill="url(#g-glass)" />
              <circle cx="80" cy="80" r="78" class="g-dash spin" />
              <g v-for="(r, i) in rings" :key="r.id">
                <circle cx="80" cy="80" :r="ringR(i)" class="ring-track" />
                <path
                  :d="arcPath(80, 80, ringR(i), 0, r.ratio * 360)"
                  pathLength="1"
                  class="ring-arc"
                  :stroke="r.color"
                  :style="{ '--d': `${i * 120}ms`, color: r.color }"
                  @click="goList({ status: r.id })"
                >
                  <title>{{ r.label }}：{{ r.value }}</title>
                </path>
              </g>
              <text x="80" y="78" class="rings-total">{{ stats.total }}</text>
              <text x="80" y="92" class="rings-cap">TOTAL</text>
            </svg>
            <div class="ring-legend">
              <button v-for="r in rings" :key="r.id" type="button" @click="goList({ status: r.id })">
                <b :style="{ background: r.color, boxShadow: `0 0 6px ${r.color}` }" />
                <span class="rl-label">{{ r.label }}</span>
                <span class="rl-val tech-num">{{ r.value }}</span>
                <span class="rl-pct tech-num">{{ Math.round(r.ratio * 100) }}%</span>
              </button>
            </div>
          </div>
        </section>

        <section class="term" style="--i: 3">
          <div class="hud-label danger"><i />错误排行<em>ERR.LOG · TOP 5</em></div>
          <div v-if="!errors.length" class="term-line idle">&gt; {{ NO_DATA }}<span class="caret" /></div>
          <button
            v-for="(e, i) in errors"
            :key="`${e.error_code}-${e.failed_node}`"
            type="button"
            class="term-line"
            :style="{ '--r': i }"
            :title="`${e.error_code} · ${e.failed_node || '—'}`"
            @click="goList({ error_code: e.error_code, ...(e.failed_node ? { failed_node: e.failed_node } : {}) })"
          >
            <span class="t-prompt">&gt;</span>
            <span class="t-rank" :class="{ top: i < 3 }">[{{ pad2(i) }}]</span>
            <span class="t-code">{{ e.error_code }}</span>
            <span class="t-dots" />
            <span class="t-node">{{ e.failed_node || '—' }}</span>
            <span class="t-count">×{{ e.count }}</span>
          </button>
          <div v-if="errors.length" class="term-line idle caret-line">&gt;<span class="caret" /></div>
        </section>
      </template>
      <div v-else class="hud-empty">{{ loading ? '正在接收遥测…' : NO_DATA }}</div>
    </aside>
  </div>
</template>

<style scoped>
.wings {
  position: absolute;
  inset: 76px 0 46px;
  pointer-events: none;
  z-index: 10;
  --hud-cyan: #22d3ee;
  --hud-glow: 0 0 10px rgba(34, 211, 238, 0.65);
}
.wings::before,
.wings::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  width: 30%;
  pointer-events: none;
}
.wings::before {
  left: 0;
  background: linear-gradient(90deg, rgba(3, 7, 15, 0.55), transparent);
}
.wings::after {
  right: 0;
  background: linear-gradient(270deg, rgba(3, 7, 15, 0.55), transparent);
}

.streams {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
}
.stream {
  fill: none;
  stroke-width: 1;
}
.stream-dash {
  fill: none;
  stroke-width: 1.2;
  stroke-dasharray: 3 14;
  animation: dash-flow linear infinite;
}
.stream-dash.l {
  stroke: rgba(34, 211, 238, 0.4);
}
.stream-dash.r {
  stroke: rgba(129, 140, 248, 0.4);
}
.spark.l {
  fill: #cffafe;
  filter: drop-shadow(0 0 4px #22d3ee);
}
.spark.r {
  fill: #e0e7ff;
  filter: drop-shadow(0 0 4px #818cf8);
}

.wing {
  position: absolute;
  top: 0;
  bottom: 0;
  z-index: 1;
  width: clamp(280px, 22vw, 370px);
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
  overflow-x: hidden;
  pointer-events: auto;
  scrollbar-width: none;
  text-shadow: 0 0 6px rgba(0, 0, 0, 0.9);
}
.wing::-webkit-scrollbar {
  display: none;
}
.wing.left {
  left: 20px;
}
.wing.right {
  right: 20px;
}
.wing > *,
.readout {
  flex: none;
  opacity: 0;
  animation: holo-in 0.7s cubic-bezier(0.16, 1, 0.3, 1) forwards calc(var(--i, 0) * 100ms + 120ms);
}
.readouts {
  opacity: 1 !important;
  animation: none !important;
}

.hud-head {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 0 8px;
}
.hud-head::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 1px;
  background: linear-gradient(90deg, var(--hud-cyan), rgba(34, 211, 238, 0.15) 60%, transparent);
}
.wing.right .hud-head::after {
  background: linear-gradient(270deg, var(--hud-cyan), rgba(34, 211, 238, 0.15) 60%, transparent);
}
.hud-title {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 3px;
  color: #e0f7ff;
}
.hud-title em,
.hud-label em,
.ro-label em {
  font-style: normal;
  font-family: var(--tech-mono);
  font-size: 9px;
  letter-spacing: 2px;
  color: rgba(34, 211, 238, 0.6);
  margin-left: 6px;
}
.presets {
  display: flex;
  gap: 2px;
}
.presets button {
  font-family: var(--tech-mono);
  font-size: 10px;
  padding: 1px 6px;
  border: none;
  background: transparent;
  color: var(--tech-text-3);
  cursor: pointer;
  transition: color 0.2s, text-shadow 0.2s;
}
.presets button::before {
  content: '[';
  opacity: 0;
}
.presets button::after {
  content: ']';
  opacity: 0;
}
.presets button.on {
  color: var(--hud-cyan);
  text-shadow: var(--hud-glow);
}
.presets button.on::before,
.presets button.on::after {
  opacity: 1;
}
.stamp {
  font-size: 10px;
  letter-spacing: 1px;
  color: rgba(34, 211, 238, 0.6);
}

.hud-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--tech-text-2);
  margin-bottom: 6px;
}
.hud-label i {
  width: 3px;
  height: 11px;
  background: var(--hud-cyan);
  box-shadow: var(--hud-glow);
}
.hud-label em {
  margin-left: 0;
}
.hud-label::after {
  content: '';
  flex: 1;
  height: 1px;
  background: repeating-linear-gradient(90deg, rgba(34, 211, 238, 0.35) 0 2px, transparent 2px 6px);
}
.hud-label.danger i {
  background: rgba(244, 114, 182, 0.8);
  box-shadow: 0 0 10px rgba(244, 114, 182, 0.6);
}
.hud-label.danger em {
  color: rgba(244, 114, 182, 0.65);
}
.hud-label.danger::after {
  background: repeating-linear-gradient(90deg, rgba(244, 114, 182, 0.3) 0 2px, transparent 2px 6px);
}
.obs-warn {
  font-size: 11px;
  font-family: var(--tech-mono);
  color: var(--tech-warning);
  text-shadow: 0 0 8px rgba(251, 191, 36, 0.6);
  animation:
    holo-in 0.7s forwards 0.2s,
    blink 1.6s steps(2) infinite 1s;
}

/* 仪表 */
.gauge {
  position: relative;
  width: 210px;
  align-self: center;
}
.gauge-svg {
  display: block;
  width: 210px;
  height: 210px;
  overflow: visible;
}
.g-dash {
  fill: none;
  stroke: rgba(34, 211, 238, 0.35);
  stroke-width: 1;
  stroke-dasharray: 1.5 5;
}
.g-arc {
  fill: none;
  stroke: var(--hud-cyan);
  stroke-width: 2;
  opacity: 0.7;
  filter: drop-shadow(0 0 3px #22d3ee);
}
.spin {
  transform-origin: center;
  transform-box: view-box;
  animation: spin 24s linear infinite;
}
.spin-rev {
  transform-origin: center;
  transform-box: view-box;
  animation: spin 14s linear infinite reverse;
}
.g-tick {
  stroke: rgba(34, 211, 238, 0.12);
  stroke-width: 2.6;
  stroke-linecap: round;
}
.g-tick.on {
  filter: drop-shadow(0 0 3px rgba(34, 211, 238, 0.7));
  animation: tick-on 0.4s ease-out backwards calc(var(--d) + 500ms);
}
.g-inner {
  fill: none;
  stroke: rgba(34, 211, 238, 0.25);
  stroke-width: 1;
}
.g-inner-dash {
  fill: none;
  stroke: rgba(129, 140, 248, 0.5);
  stroke-width: 3;
  stroke-dasharray: 1 7;
  animation-duration: 40s;
  animation-direction: reverse;
}
.gauge-center {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 210px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.gauge-val {
  font-size: 34px;
  font-weight: 700;
  line-height: 1;
  color: #ecfeff;
  text-shadow: 0 0 14px rgba(34, 211, 238, 0.9), 0 0 30px rgba(34, 211, 238, 0.4);
}
.gauge-val small {
  font-size: 15px;
  margin-left: 2px;
  color: var(--hud-cyan);
}
.gauge-sub {
  margin-top: 6px;
  font-family: var(--tech-mono);
  font-size: 9px;
  letter-spacing: 3px;
  color: rgba(34, 211, 238, 0.7);
}
.gauge-none {
  font-size: 13px;
  letter-spacing: 2px;
  color: var(--tech-text-3);
}
.gauge-note {
  margin-top: -6px;
  text-align: center;
  font-size: 10px;
  color: var(--tech-text-3);
}

/* 读数 */
.readouts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px 16px;
}
.readout {
  position: relative;
  padding: 0 0 8px 10px;
  border: none;
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
}
.readout::before {
  content: '';
  position: absolute;
  left: 0;
  top: 2px;
  bottom: 8px;
  width: 1px;
  background: linear-gradient(180deg, var(--hud-cyan), transparent);
}
.readout::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 1px;
  background: linear-gradient(90deg, rgba(34, 211, 238, 0.5), transparent);
  background-size: 200% 100%;
}
.ro-label {
  font-size: 11px;
  color: var(--tech-text-3);
}
.ro-label em {
  display: block;
  margin: 0 0 1px;
}
.ro-val {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: var(--tech-mono);
  font-size: 26px;
  font-weight: 700;
  line-height: 1.25;
  color: #ecfeff;
  text-shadow: 0 0 12px rgba(34, 211, 238, 0.75);
}
.ro-val.small {
  font-size: 17px;
  line-height: 1.7;
}
.ro-sub {
  font-size: 10px;
  color: var(--tech-text-3);
}
.clickable {
  cursor: pointer;
}
.readout.clickable:hover .ro-sub {
  color: var(--hud-cyan);
}
.readout.alert::before {
  background: linear-gradient(180deg, var(--tech-warning), transparent);
}
.readout.alert .ro-val {
  color: #fef3c7;
  text-shadow: 0 0 14px rgba(251, 191, 36, 0.9);
}
.warn-tri {
  width: 22px;
  height: 20px;
  flex: none;
  animation: blink 1.2s steps(2) infinite;
}
.warn-tri path {
  fill: none;
  stroke: var(--tech-warning);
  stroke-width: 1.8;
  stroke-linejoin: round;
  stroke-linecap: round;
  filter: drop-shadow(0 0 4px #fbbf24);
}

/* Token 能量条 */
.token-val {
  font-family: var(--tech-mono);
  font-size: 24px;
  font-weight: 700;
  color: #ecfeff;
  text-shadow: 0 0 12px rgba(34, 211, 238, 0.75);
}
.token-val.muted {
  font-size: 14px;
  color: var(--tech-text-3);
  text-shadow: none;
}
.energy {
  display: flex;
  gap: 2px;
  margin: 6px 0;
}
.energy i {
  flex: 1;
  height: 10px;
  transform: skewX(-20deg);
  animation: seg-on 0.3s ease-out backwards calc(var(--d) + 700ms);
}
.energy i.in,
.token-legend b.in {
  background: rgba(34, 211, 238, 0.4);
  box-shadow: inset 0 0 0 1px rgba(34, 211, 238, 0.85), 0 0 6px rgba(34, 211, 238, 0.45);
}
.energy i.out,
.token-legend b.out {
  background: rgba(129, 140, 248, 0.35);
  box-shadow: inset 0 0 0 1px rgba(129, 140, 248, 0.85), 0 0 6px rgba(129, 140, 248, 0.45);
}
.token-legend {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--tech-text-3);
}
.token-legend b {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 5px;
  transform: skewX(-20deg);
}

/* 趋势括号框 */
.bracket {
  position: relative;
  padding: 6px 4px 2px;
  overflow: hidden;
  background:
    linear-gradient(var(--hud-cyan), var(--hud-cyan)) top left / 12px 1px,
    linear-gradient(var(--hud-cyan), var(--hud-cyan)) top left / 1px 12px,
    linear-gradient(var(--hud-cyan), var(--hud-cyan)) top right / 12px 1px,
    linear-gradient(var(--hud-cyan), var(--hud-cyan)) top right / 1px 12px,
    linear-gradient(var(--hud-cyan), var(--hud-cyan)) bottom left / 12px 1px,
    linear-gradient(var(--hud-cyan), var(--hud-cyan)) bottom left / 1px 12px,
    linear-gradient(var(--hud-cyan), var(--hud-cyan)) bottom right / 12px 1px,
    linear-gradient(var(--hud-cyan), var(--hud-cyan)) bottom right / 1px 12px;
  background-repeat: no-repeat;
}
.scanline {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, rgba(34, 211, 238, 0.7), transparent);
  box-shadow: 0 0 10px rgba(34, 211, 238, 0.6);
  animation: scan 4.5s ease-in-out infinite;
  pointer-events: none;
}

/* 状态同心弧 */
.rings {
  display: flex;
  align-items: center;
  gap: 10px;
}
.rings-svg {
  flex: none;
  width: 150px;
  height: 150px;
  overflow: visible;
}
.ring-track {
  fill: none;
  stroke: rgba(34, 211, 238, 0.07);
  stroke-width: 6;
}
.ring-arc {
  fill: none;
  stroke-width: 6;
  stroke-opacity: 0.62;
  stroke-linecap: round;
  stroke-dasharray: 1;
  filter: drop-shadow(0 0 4px currentColor);
  cursor: pointer;
  animation: arc-draw 1.1s cubic-bezier(0.16, 1, 0.3, 1) backwards calc(var(--d) + 400ms);
  transition: stroke-width 0.2s;
}
.ring-arc:hover {
  stroke-width: 8;
  stroke-opacity: 0.95;
}
.rings-total {
  fill: #ecfeff;
  font-family: var(--tech-mono);
  font-size: 18px;
  font-weight: 700;
  text-anchor: middle;
  filter: drop-shadow(0 0 6px #22d3ee);
}
.rings-cap {
  fill: rgba(34, 211, 238, 0.7);
  font-family: var(--tech-mono);
  font-size: 7px;
  letter-spacing: 2px;
  text-anchor: middle;
}
.ring-legend {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ring-legend button {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0;
  border: none;
  background: none;
  color: var(--tech-text-2);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
  text-align: left;
}
.ring-legend button:hover {
  color: #ecfeff;
}
.ring-legend b {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.rl-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rl-val {
  color: #ecfeff;
}
.rl-pct {
  width: 32px;
  text-align: right;
  color: var(--tech-text-3);
}

/* 终端日志 */
.term-line {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 3px 0;
  border: none;
  background: none;
  font-family: var(--tech-mono);
  font-size: 11px;
  color: rgba(249, 168, 212, 0.85);
  text-align: left;
  text-shadow: 0 0 8px rgba(244, 114, 182, 0.45);
  cursor: pointer;
  clip-path: inset(0 100% 0 0);
  animation: type-in 0.7s steps(28) forwards calc(var(--r, 0) * 260ms + 700ms);
}
.term-line:hover {
  color: #fdf2f8;
  background: linear-gradient(90deg, rgba(244, 114, 182, 0.12), transparent);
}
.term-line.idle {
  cursor: default;
  color: var(--tech-text-3);
  text-shadow: none;
}
.caret-line {
  --r: 5;
}
.t-prompt {
  color: rgba(244, 114, 182, 0.8);
}
.t-rank {
  color: var(--tech-text-3);
}
.t-rank.top {
  color: rgba(196, 181, 253, 0.9);
}
.t-code {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.t-dots {
  flex: 1;
  min-width: 10px;
  height: 1px;
  background: repeating-linear-gradient(90deg, rgba(244, 114, 182, 0.35) 0 1px, transparent 1px 4px);
}
.t-node {
  flex: none;
  max-width: 90px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--tech-text-2);
  text-shadow: none;
}
.t-count {
  flex: none;
  color: #f472b6;
  font-weight: 700;
}
.caret {
  display: inline-block;
  width: 7px;
  height: 12px;
  margin-left: 4px;
  vertical-align: middle;
  background: rgba(244, 114, 182, 0.6);
  box-shadow: 0 0 6px rgba(244, 114, 182, 0.6);
  animation: blink 1s steps(2) infinite;
}

.hud-empty {
  padding: 30px 0;
  text-align: center;
  color: var(--tech-text-3);
  font-size: 13px;
  letter-spacing: 2px;
}
.hud-empty.small {
  padding: 12px 0;
}

@keyframes holo-in {
  0% {
    opacity: 0;
    filter: blur(6px) brightness(2);
    transform: scaleY(0.2);
  }
  50% {
    opacity: 0.6;
  }
  70% {
    opacity: 0.3;
  }
  100% {
    opacity: 1;
    filter: none;
    transform: none;
  }
}
@keyframes dash-flow {
  to {
    stroke-dashoffset: -34;
  }
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes tick-on {
  from {
    stroke: #fff;
    opacity: 0;
  }
}
@keyframes seg-on {
  from {
    opacity: 0;
    filter: brightness(3);
  }
}
@keyframes scan {
  0%,
  100% {
    top: 0;
    opacity: 0;
  }
  10%,
  90% {
    opacity: 1;
  }
  50% {
    top: calc(100% - 2px);
  }
}
@keyframes arc-draw {
  from {
    stroke-dashoffset: 1;
  }
}
@keyframes type-in {
  to {
    clip-path: inset(0 0 0 0);
  }
}
@keyframes blink {
  50% {
    opacity: 0.25;
  }
}
@media (max-width: 1100px) {
  .wings {
    display: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .wing > *,
  .readout,
  .term-line,
  .g-tick.on,
  .energy i,
  .ring-arc {
    animation: none;
    opacity: 1;
    clip-path: none;
  }
  .spin,
  .spin-rev,
  .scanline,
  .stream-dash,
  .warn-tri,
  .caret {
    animation: none;
  }
  .spark {
    display: none;
  }
}
</style>
