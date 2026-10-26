<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, shallowRef, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Back, SwitchButton, Key } from '@element-plus/icons-vue'
import { auth, can, logout } from '../auth'
import { menu, menuGroups } from '../router'
import { errorMessage, http } from '@/shared/http'
import { rangeParams, type RunStats } from '../runs'
import CoreStage from '../console/CoreStage.vue'
import SatelliteNode from '../console/SatelliteNode.vue'
import SubMenu from '../console/SubMenu.vue'
import OverviewWings from '../console/OverviewWings.vue'
import { layoutNodes } from '../console/orbits'
import { activityLevel } from '../console/brain'
import { groupOf, groupTelemetry, visibleGroups, type Point, type VisibleGroup } from '../console/menuGroups'
import {
  buildBroadcast,
  buildTelemetry,
  buildTicker,
  coreMood,
  fetchReady,
  type ConsoleData,
} from '../console/telemetry'

const route = useRoute()
const router = useRouter()
const stage = ref<InstanceType<typeof CoreStage>>()

const groups = computed(() => visibleGroups(menuGroups, menu, can))
const groupById = computed<Record<string, VisibleGroup>>(() => Object.fromEntries(groups.value.map((g) => [g.id, g])))
const nodes = computed(() => layoutNodes(groups.value.map((g) => ({ key: g.id, group: g.orbit }))))
const showWings = computed(() => can('ops.run.view'))

const data = reactive<ConsoleData>({ ready: null, readyFailed: false, stats: null, pending: null })
const mood = computed(() => coreMood(data))
const activity = computed(() => activityLevel(data.stats?.in_progress))
const telemetry = computed(() => buildTelemetry(data))
const ticker = computed(() => buildTicker(data))

async function refresh() {
  if (document.hidden) return
  const tasks: Promise<void>[] = [
    fetchReady()
      .then((r) => {
        data.ready = r
        data.readyFailed = false
      })
      .catch(() => {
        data.ready = null
        data.readyFailed = true
      }),
  ]
  if (can('ops.run.view')) {
    tasks.push(
      http
        .get<RunStats>('/v1/admin/runs/stats', rangeParams('24h'))
        .then((s) => void (data.stats = s))
        .catch(() => void (data.stats = null)),
    )
  }
  if (can('ops.intervention.handle')) {
    tasks.push(
      http
        .get<{ pending_count: number }>('/v1/admin/interventions', { status: 'pending', page: 1, page_size: 1 })
        .then((r) => void (data.pending = r.pending_count ?? null))
        .catch(() => void (data.pending = null)),
    )
  }
  await Promise.all(tasks)
}

const panelOpen = computed(() => route.path !== '/')
const panelMeta = computed(() => ({
  title: (route.meta.title as string) || '',
  code: (route.meta.code as string) || '',
  icon: route.meta.icon as Component | undefined,
  tele: telemetry.value[(route.meta.menuPath as string) || route.path],
}))
const currentGroup = computed(() => groupOf(groups.value, (route.meta.menuPath as string) || route.path))
const activeTab = computed(() => (route.meta.menuPath as string) || route.path)
const origin = ref<Point>({ x: window.innerWidth / 2, y: window.innerHeight / 2 })
const screenCenter = (): Point => ({ x: window.innerWidth / 2, y: window.innerHeight / 2 })

const expanded = shallowRef<{ group: VisibleGroup; at: Point } | null>(null)
const subItems = computed(() =>
  (expanded.value?.group.items ?? []).map((i) => ({ ...i, telemetry: telemetry.value[i.path] })),
)

function openPath(path: string, at?: Point) {
  origin.value = at ?? screenCenter()
  expanded.value = null
  router.push(path)
}
function onGroupClick(group: VisibleGroup) {
  const p = stage.value?.nodePosition(group.id)
  const at = p ? { x: p.x, y: p.y } : screenCenter()
  if (group.items.length === 1) return openPath(group.items[0].path, at)
  expanded.value = expanded.value?.group.id === group.id ? null : { group, at }
}
function backToCore() {
  expanded.value = null
  router.push('/')
}
function onKey(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (expanded.value) {
    expanded.value = null
    return
  }
  if (!panelOpen.value) return
  const overlayOpen = [...document.querySelectorAll<HTMLElement>('.el-overlay')].some((el) => el.style.display !== 'none')
  if (!overlayOpen) backToCore()
}

const broadcast = computed(() => buildBroadcast(data))
const typed = ref('')
let msgIndex = 0
let typeTimer = 0
function playBroadcast() {
  const list = broadcast.value
  const msg = list[msgIndex % list.length]
  msgIndex++
  let i = 0
  clearInterval(typeTimer)
  typeTimer = window.setInterval(() => {
    i++
    typed.value = msg.slice(0, i)
    if (i >= msg.length) {
      clearInterval(typeTimer)
      typeTimer = window.setTimeout(playBroadcast, 4200)
    }
  }, 45)
}

const now = ref(new Date())
const clock = computed(() => now.value.toLocaleTimeString('zh-CN', { hour12: false }))
const today = computed(() => now.value.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }))

let pollTimer = 0
let clockTimer = 0
onMounted(() => {
  refresh().finally(playBroadcast)
  pollTimer = window.setInterval(refresh, 30_000)
  clockTimer = window.setInterval(() => (now.value = new Date()), 1000)
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  clearInterval(pollTimer)
  clearInterval(clockTimer)
  clearInterval(typeTimer)
  clearTimeout(typeTimer)
  window.removeEventListener('keydown', onKey)
})
const pwdOpen = ref(false)
const pwd = reactive({ old_password: '', new_password: '', confirm: '' })

async function doLogout() {
  await logout()
  router.replace('/login')
}

async function changePassword() {
  if (pwd.new_password !== pwd.confirm) return ElMessage.error('两次输入的新密码不一致')
  try {
    await http.post('/v1/admin/auth/password', { old_password: pwd.old_password, new_password: pwd.new_password })
    ElMessage.success('密码已修改')
    pwdOpen.value = false
    Object.assign(pwd, { old_password: '', new_password: '', confirm: '' })
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}
</script>

<template>
  <div class="deck">
    <CoreStage ref="stage" :mood="mood.mood" :mode="panelOpen ? 'focus' : 'active'" :nodes="nodes" :paused="!!expanded" :activity="activity">
      <template #node="{ node }">
        <SatelliteNode
          v-if="groupById[node.key]"
          :title="groupById[node.key].title"
          :code="groupById[node.key].code"
          :motif="node.key"
          :group="groupById[node.key].orbit"
          :telemetry="groupTelemetry(groupById[node.key], telemetry)"
          :count="groupById[node.key].items.length"
          :active="expanded?.group.id === node.key"
          :dimmed="!!expanded && expanded.group.id !== node.key"
          @click="onGroupClick(groupById[node.key])"
        />
      </template>
    </CoreStage>

    <transition name="wings">
      <OverviewWings v-if="showWings && !panelOpen" />
    </transition>

    <SubMenu
      v-if="expanded && !panelOpen"
      :key="expanded.group.id"
      :origin="expanded.at"
      :items="subItems"
      @select="openPath"
      @close="expanded = null"
    />

    <header class="hud">
      <div class="brand" @click="backToCore">
        <span class="logo"><i /><i /><i /></span>
        <span class="brand-text">
          <b>OA·AGENT</b>
          <small>NEURAL CONSOLE</small>
        </span>
      </div>
      <div class="broadcast">
        <span class="bc-tag">AI·LINK</span>
        <span class="bc-text">{{ typed }}<i class="caret" /></span>
      </div>
      <div class="hud-right">
        <button class="status-chip" :class="mood.mood" title="查看系统状态" @click="openPath('/status')">
          <span class="tech-dot" :class="{ ok: mood.mood === 'ok', warn: mood.mood === 'warn', bad: mood.mood === 'bad' }" />
          {{ mood.text }}
        </button>
        <div class="clock">
          <b class="tech-num">{{ clock }}</b>
          <small class="tech-num">{{ today }}</small>
        </div>
        <el-dropdown trigger="click">
          <span class="operator">
            <span class="avatar">{{ (auth.me?.user.display_name || auth.me?.user.username || '?').slice(0, 1) }}</span>
            <span class="op-name">{{ auth.me?.user.display_name || auth.me?.user.username }}</span>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item :icon="Key" @click="pwdOpen = true">修改密码</el-dropdown-item>
              <el-dropdown-item divided :icon="SwitchButton" @click="doLogout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <div v-if="!panelOpen" class="hint">
      <template v-if="expanded">
        <span>选择二级模块</span>
        <span class="hint-sep">·</span>
        <span>点击空白处或 ESC 收起</span>
      </template>
      <template v-else>
        <span>点击卫星展开模块</span>
        <span class="hint-sep">·</span>
        <span>悬停可暂停轨道</span>
      </template>
    </div>

    <transition name="holo">
      <section
        v-if="panelOpen"
        class="holo"
        :style="{ '--ox': `${origin.x}px`, '--oy': `${origin.y}px` }"
      >
        <div class="holo-frame tech-corners">
          <header class="holo-head">
            <span class="holo-icon"><el-icon v-if="panelMeta.icon" :size="18"><component :is="panelMeta.icon" /></el-icon></span>
            <span class="holo-title">{{ panelMeta.title }}</span>
            <span class="holo-code">// {{ panelMeta.code }}</span>
            <span v-if="panelMeta.tele" class="holo-tele" :class="panelMeta.tele.tone">{{ panelMeta.tele.text }}</span>
            <nav v-if="currentGroup && currentGroup.items.length > 1" class="holo-tabs">
              <span class="tabs-group">{{ currentGroup.title }}</span>
              <router-link
                v-for="it in currentGroup.items"
                :key="it.path"
                :to="it.path"
                class="tab"
                :class="{ on: activeTab === it.path }"
              >
                <el-icon :size="13"><component :is="it.icon" /></el-icon>
                {{ it.title }}
              </router-link>
            </nav>
            <span class="holo-spacer" />
            <button class="holo-back" @click="backToCore">
              <el-icon><Back /></el-icon>
              返回核心
              <kbd>ESC</kbd>
            </button>
          </header>
          <div class="holo-scan" />
          <div class="holo-body">
            <router-view />
          </div>
        </div>
      </section>
    </transition>

    <footer class="ticker">
      <span class="ticker-tag">TELEMETRY</span>
      <div class="ticker-track">
        <div v-if="ticker.length" class="ticker-move">
          <span v-for="(t, i) in [...ticker, ...ticker]" :key="i" class="ticker-item">{{ t }}</span>
        </div>
        <span v-else class="ticker-item muted">暂无遥测数据</span>
      </div>
    </footer>
  </div>

  <el-dialog v-model="pwdOpen" title="修改密码" width="420px">
    <el-form label-width="90px">
      <el-form-item label="原密码"><el-input v-model="pwd.old_password" type="password" show-password /></el-form-item>
      <el-form-item label="新密码"><el-input v-model="pwd.new_password" type="password" show-password /></el-form-item>
      <el-form-item label="确认新密码"><el-input v-model="pwd.confirm" type="password" show-password /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="pwdOpen = false">取消</el-button>
      <el-button type="primary" @click="changePassword">确定</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.deck {
  position: fixed;
  inset: 0;
  overflow: hidden;
  color: var(--tech-text);
}

/* ---------- HUD ---------- */
.hud {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 64px;
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 0 24px;
  z-index: 20;
  background: linear-gradient(180deg, rgba(7, 11, 20, 0.92), rgba(7, 11, 20, 0.35) 80%, transparent);
}
.hud::after {
  content: '';
  position: absolute;
  left: 24px;
  right: 24px;
  bottom: 6px;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(34, 211, 238, 0.6) 20%, rgba(99, 102, 241, 0.6) 80%, transparent);
  box-shadow: 0 0 8px rgba(34, 211, 238, 0.5);
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  flex: none;
}
.logo {
  position: relative;
  width: 34px;
  height: 34px;
}
.logo i {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 1.5px solid var(--tech-cyan);
  box-shadow: 0 0 10px var(--tech-cyan);
}
.logo i:nth-child(1) {
  transform: rotateX(65deg);
  animation: logo-spin 4s linear infinite;
}
.logo i:nth-child(2) {
  transform: rotateY(65deg);
  border-color: var(--tech-violet);
  box-shadow: 0 0 10px var(--tech-violet);
  animation: logo-spin 6s linear infinite reverse;
}
.logo i:nth-child(3) {
  inset: 11px;
  background: radial-gradient(circle, #fff, var(--tech-cyan) 60%);
  border: none;
  box-shadow: 0 0 14px var(--tech-cyan);
}
.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.15;
}
.brand-text b {
  font-family: var(--tech-mono);
  font-size: 17px;
  letter-spacing: 3px;
  background: var(--tech-gradient);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.brand-text small {
  font-family: var(--tech-mono);
  font-size: 9px;
  letter-spacing: 4px;
  color: var(--tech-text-2);
}
.broadcast {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}
.bc-tag {
  flex: none;
  font-family: var(--tech-mono);
  font-size: 10px;
  letter-spacing: 2px;
  padding: 2px 8px;
  border: 1px solid var(--tech-border-strong);
  color: var(--tech-cyan);
  border-radius: 3px;
  box-shadow: inset 0 0 8px rgba(34, 211, 238, 0.2);
}
.bc-text {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  color: #cbe9f0;
  text-shadow: 0 0 8px rgba(34, 211, 238, 0.4);
}
.caret {
  display: inline-block;
  width: 7px;
  height: 14px;
  margin-left: 3px;
  vertical-align: -2px;
  background: var(--tech-cyan);
  box-shadow: 0 0 6px var(--tech-cyan);
  animation: blink 1s steps(1) infinite;
}
.hud-right {
  display: flex;
  align-items: center;
  gap: 18px;
  flex: none;
}
.status-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--tech-border-strong);
  background: rgba(7, 11, 20, 0.6);
  color: var(--tech-text);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  transition: box-shadow 0.25s;
}
.status-chip:hover {
  box-shadow: var(--tech-glow);
}
.status-chip.warn {
  border-color: rgba(251, 191, 36, 0.55);
}
.status-chip.bad {
  border-color: rgba(244, 63, 94, 0.6);
}
.clock {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  line-height: 1.2;
}
.clock b {
  font-size: 16px;
  letter-spacing: 1px;
  color: var(--tech-cyan);
  text-shadow: 0 0 8px rgba(34, 211, 238, 0.6);
}
.clock small {
  font-size: 10px;
  color: var(--tech-text-3);
}
.operator {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: var(--tech-text);
  outline: none;
}
.avatar {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--tech-gradient);
  color: #04121a;
  font-weight: 700;
  box-shadow: 0 0 12px rgba(34, 211, 238, 0.5);
}
.op-name {
  font-size: 13px;
}

.hint {
  position: absolute;
  left: 50%;
  bottom: 52px;
  transform: translateX(-50%);
  z-index: 5;
  font-size: 12px;
  letter-spacing: 2px;
  color: var(--tech-text-3);
  pointer-events: none;
}
.hint-sep {
  margin: 0 8px;
}

/* ---------- 全息面板 ---------- */
.holo {
  position: absolute;
  top: 74px;
  left: 3vw;
  right: 3vw;
  bottom: 44px;
  z-index: 15;
  transform-origin: calc(var(--ox) - 3vw) calc(var(--oy) - 74px);
}
.holo-frame {
  position: relative;
  height: 100%;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--tech-border-strong);
  border-radius: 10px;
  background:
    linear-gradient(180deg, rgba(34, 211, 238, 0.06), transparent 120px),
    rgba(6, 12, 24, 0.82);
  backdrop-filter: blur(16px) saturate(1.2);
  box-shadow:
    0 0 0 1px rgba(34, 211, 238, 0.08),
    0 0 60px rgba(34, 211, 238, 0.12),
    inset 0 0 80px rgba(34, 211, 238, 0.04);
  overflow: hidden;
}
.holo-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--tech-border);
  flex: none;
}
.holo-icon {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: var(--tech-cyan);
  background: rgba(34, 211, 238, 0.1);
  border: 1px solid var(--tech-border-strong);
  box-shadow: 0 0 12px rgba(34, 211, 238, 0.3);
}
.holo-title {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: 2px;
}
.holo-code {
  font-family: var(--tech-mono);
  font-size: 11px;
  letter-spacing: 2px;
  color: var(--tech-text-3);
}
.holo-tele {
  font-family: var(--tech-mono);
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 999px;
  color: var(--tech-cyan);
  background: rgba(34, 211, 238, 0.08);
  border: 1px solid var(--tech-border);
}
.holo-tele.warn {
  color: var(--tech-warning);
  background: rgba(251, 191, 36, 0.08);
  border-color: rgba(251, 191, 36, 0.35);
}
.holo-spacer {
  flex: 1;
}
.holo-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: 12px;
  padding: 3px;
  border-radius: 8px;
  border: 1px solid var(--tech-border);
  background: rgba(2, 6, 16, 0.5);
}
.tabs-group {
  padding: 0 8px 0 6px;
  font-size: 11px;
  letter-spacing: 1px;
  color: var(--tech-text-3);
  border-right: 1px solid var(--tech-border);
  margin-right: 2px;
}
.tab {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 13px;
  color: var(--tech-text-2);
  text-decoration: none;
  transition: color 0.2s, background 0.2s, box-shadow 0.2s;
}
.tab:hover {
  color: var(--tech-text);
  background: rgba(34, 211, 238, 0.08);
}
.tab.on {
  color: #04121a;
  font-weight: 600;
  background: var(--tech-gradient);
  box-shadow: 0 0 12px rgba(34, 211, 238, 0.45);
}
.wings-leave-active {
  transition: opacity 0.3s, filter 0.3s;
}
.wings-leave-to {
  opacity: 0;
  filter: blur(6px);
}
.holo-back {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 6px;
  border: 1px solid var(--tech-border-strong);
  background: rgba(34, 211, 238, 0.06);
  color: var(--tech-text);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  transition: box-shadow 0.2s, background 0.2s;
}
.holo-back:hover {
  background: rgba(34, 211, 238, 0.14);
  box-shadow: var(--tech-glow);
}
.holo-back kbd {
  font-family: var(--tech-mono);
  font-size: 10px;
  padding: 0 5px;
  border-radius: 3px;
  border: 1px solid var(--tech-border);
  color: var(--tech-text-3);
}
.holo-scan {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 140px;
  pointer-events: none;
  background: linear-gradient(180deg, transparent, rgba(34, 211, 238, 0.035) 85%, rgba(34, 211, 238, 0.16) 99%, transparent);
  animation: scan 9s ease-in-out infinite;
  z-index: 2;
}
.holo-body {
  flex: 1;
  overflow: auto;
  padding: 18px 20px 24px;
}

.holo-enter-active {
  animation: holo-in 0.6s cubic-bezier(0.16, 1, 0.3, 1);
}
.holo-leave-active {
  animation: holo-in 0.35s cubic-bezier(0.7, 0, 0.84, 0) reverse;
}
@keyframes holo-in {
  0% {
    opacity: 0;
    transform: scale(0.06);
    filter: brightness(3) blur(6px);
  }
  55% {
    opacity: 1;
    filter: brightness(1.6) blur(0);
  }
  100% {
    opacity: 1;
    transform: scale(1);
    filter: none;
  }
}

/* ---------- 底部遥测带 ---------- */
.ticker {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 34px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 24px;
  z-index: 20;
  background: linear-gradient(0deg, rgba(7, 11, 20, 0.95), rgba(7, 11, 20, 0.4));
  border-top: 1px solid rgba(34, 211, 238, 0.15);
  font-family: var(--tech-mono);
  font-size: 11px;
}
.ticker-tag {
  flex: none;
  color: var(--tech-violet);
  letter-spacing: 3px;
  text-shadow: 0 0 8px var(--tech-violet);
}
.ticker-track {
  flex: 1;
  overflow: hidden;
  mask-image: linear-gradient(90deg, transparent, #000 5%, #000 95%, transparent);
  -webkit-mask-image: linear-gradient(90deg, transparent, #000 5%, #000 95%, transparent);
}
.ticker-move {
  display: inline-flex;
  white-space: nowrap;
  animation: marquee 40s linear infinite;
}
.ticker-item {
  padding-right: 36px;
  color: var(--tech-text-2);
  letter-spacing: 1.5px;
}
.ticker-item::before {
  content: '▸ ';
  color: var(--tech-cyan);
}
.ticker-item.muted::before {
  content: '';
}

@keyframes logo-spin {
  to {
    transform: rotateX(65deg) rotateZ(360deg);
  }
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
@keyframes scan {
  0% {
    transform: translateY(-140px);
  }
  60%,
  100% {
    transform: translateY(calc(100vh));
  }
}
@keyframes marquee {
  to {
    transform: translateX(-50%);
  }
}
@media (prefers-reduced-motion: reduce) {
  .ticker-move,
  .holo-scan,
  .logo i,
  .caret {
    animation: none;
  }
}
@media (max-width: 900px) {
  .broadcast,
  .clock {
    display: none;
  }
}
</style>
