<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errorMessage } from '../shared/http'
import {
  clearTicket,
  createThread,
  deleteThread,
  getRun,
  getThreadMessages,
  hasTicket,
  listThreads,
  mapThreadMessages,
  openSession,
  patchThread,
  plainText,
  pollSettings,
  refreshDelayMs,
  refreshSession,
  sendMessageStream,
  StreamAbortedError,
  switchThread,
  takeLaunchCode,
  threadDisplayTitle,
  welcomeExamples,
  type ChatThreadItem,
  type SkillMenuItem,
  type SwitchThreadResult,
} from './api'
import { MockAgentAdapter } from './agent/adapter'
import { buildDelivery } from './delivery'
import AppLayout from './components/AppLayout.vue'
import type {
  AgentTask,
  ChatMessage,
  LocalConversation,
  NavKey,
  PendingAttachment,
} from './types'

const embedded = new URLSearchParams(window.location.search).get('embed') === '1'
const reopenHint = embedded ? '点窗口右上角 ↻ 重新连接。' : '请重新打开 OA 助手页。'

const state = ref<'loading' | 'ready' | 'expired' | 'no_launch'>('loading')
const loadError = ref('')
const displayName = ref('')
const threadId = ref('')
const skills = ref<SkillMenuItem[]>([])
const chatEnabled = ref(false)
const examples = ref<string[]>([])
const maxChars = ref(500)
let poll = pollSettings({})

const input = ref('')
const sending = ref(false)
const attachments = ref<PendingAttachment[]>([])

const sidebarCollapsed = ref(typeof window !== 'undefined' ? window.innerWidth <= 768 : false)
const inspectorOpen = ref(typeof window !== 'undefined' ? window.innerWidth > 1100 : true)
const memoryOpen = ref(false)
const activeNav = ref<NavKey>('conversations')

const conversations = ref<LocalConversation[]>([])
const activeConversationId = ref('')
const loadingMessages = ref(false)
const messages = computed({
  get: () => conversations.value.find((c) => c.id === activeConversationId.value)?.messages ?? [],
  set: (list: ChatMessage[]) => {
    const c = conversations.value.find((x) => x.id === activeConversationId.value)
    if (c) {
      c.messages = list
      c.updatedAt = Date.now()
      if (list.length && !(c.title ?? '').trim()) {
        const firstUser = list.find((m) => m.role === 'user')
        if (firstUser) c.title = firstUser.text.slice(0, 24) || null
      }
    }
  },
})

const currentTask = ref<AgentTask | null>(null)
let refreshTimer: number | undefined
let abortCtrl: AbortController | null = null
const pollTimers = new Set<number>()
let onResize: (() => void) | undefined

const mockAdapter = new MockAgentAdapter({
  onTask: (t) => {
    currentTask.value = t
  },
})

const skillNames = computed(() => skills.value.map((s) => s.display_name))
const placeholder = computed(() =>
  examples.value[0] ? `例如：${examples.value[0]}（Enter 发送，Shift+Enter 换行）` : undefined,
)
const sessionTitle = computed(() => {
  const c = conversations.value.find((x) => x.id === activeConversationId.value)
  return threadDisplayTitle(c?.title)
})

function uid(prefix: string) {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

function convFromThread(t: ChatThreadItem): LocalConversation {
  const raw = (t.title ?? '').trim()
  return {
    id: t.thread_id,
    title: raw || null,
    updatedAt: Date.parse(t.last_message_at || t.updated_at) || Date.now(),
    messages: [],
    lastChannel: t.last_channel,
  }
}

function mergeThreadList(items: ChatThreadItem[]) {
  const byId = new Map(conversations.value.map((c) => [c.id, c]))
  conversations.value = items.map((t) => {
    const prev = byId.get(t.thread_id)
    return prev
      ? {
          ...convFromThread(t),
          messages: prev.messages,
        }
      : convFromThread(t)
  })
}

function applySessionExtras(extras: SwitchThreadResult) {
  if (extras.skills) {
    skills.value = extras.skills
    examples.value = welcomeExamples(skills.value)
  }
  if (extras.chat !== undefined) chatEnabled.value = !!extras.chat
  if (extras.message_max_chars) maxChars.value = extras.message_max_chars
  if (extras.poll_interval_seconds !== undefined || extras.poll_max_minutes !== undefined) {
    poll = pollSettings({
      poll_interval_seconds: extras.poll_interval_seconds,
      poll_max_minutes: extras.poll_max_minutes,
    })
  }
}

async function loadThreads() {
  try {
    const res = await listThreads(1, 50)
    mergeThreadList(res.items)
    if (threadId.value && !conversations.value.some((c) => c.id === threadId.value)) {
      conversations.value = [
        convFromThread({
          thread_id: threadId.value,
          title: null,
          status: 'active',
          created_channel: 'oa_web',
          last_channel: null,
          pinned: false,
          created_at: '',
          updated_at: '',
          last_message_at: null,
        }),
        ...conversations.value,
      ]
    }
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function loadMessagesForThread(id: string) {
  loadingMessages.value = true
  try {
    const items = await getThreadMessages(id)
    const mapped = mapThreadMessages(items).map((m) => ({
      ...m,
      delivery: buildDelivery(m.reply, null) ?? undefined,
    }))
    const c = conversations.value.find((x) => x.id === id)
    if (c) c.messages = mapped
  } catch (e) {
    const status = (e as { status?: number }).status
    if (status === 401) {
      expire()
      return
    }
    ElMessage.error(errorMessage(e))
  } finally {
    loadingMessages.value = false
  }
}

function ensureActiveThread() {
  if (!activeConversationId.value && threadId.value) activeConversationId.value = threadId.value
}

function scheduleRefresh(expiresIn: number) {
  window.clearTimeout(refreshTimer)
  refreshTimer = window.setTimeout(async () => {
    try {
      const r = await refreshSession()
      scheduleRefresh(r.expires_in)
    } catch {
      expire()
    }
  }, refreshDelayMs(expiresIn))
}

function expire() {
  clearTicket()
  window.clearTimeout(refreshTimer)
  abortCtrl?.abort()
  state.value = 'expired'
}

onMounted(async () => {
  onResize = () => {
    if (window.innerWidth <= 768) sidebarCollapsed.value = true
  }
  window.addEventListener('resize', onResize)

  const code = takeLaunchCode()
  if (!code) {
    state.value = 'no_launch'
    return
  }
  try {
    const s = await openSession(code)
    displayName.value = s.display_name
    threadId.value = s.thread_id || ''
    skills.value = s.skills ?? []
    chatEnabled.value = !!s.chat
    maxChars.value = s.message_max_chars ?? 500
    poll = pollSettings(s)
    examples.value = welcomeExamples(skills.value)
    scheduleRefresh(s.expires_in)
    activeConversationId.value = threadId.value
    await loadThreads()
    ensureActiveThread()
    await loadMessagesForThread(activeConversationId.value)
    state.value = 'ready'
  } catch (e) {
    loadError.value = errorMessage(e)
    state.value = 'expired'
  }
})

onBeforeUnmount(() => {
  if (onResize) window.removeEventListener('resize', onResize)
  window.clearTimeout(refreshTimer)
  pollTimers.forEach((t) => window.clearTimeout(t))
  abortCtrl?.abort()
  mockAdapter.dispose()
})

function pollRun(msg: ChatMessage, startedAt = Date.now()) {
  if (!msg.runId || Date.now() - startedAt > poll.maxMs) return
  const timer = window.setTimeout(async () => {
    pollTimers.delete(timer)
    if (!hasTicket()) return
    try {
      const r = await getRun(msg.runId!)
      if (r.done && r.reply) {
        msg.reply = r.reply
        msg.text = plainText(r.reply.content)
        msg.delivery = buildDelivery(r.reply, currentTask.value) ?? undefined
        mockAdapter.syncLiveStatus('completed')
        return
      }
      if (r.run_status) mockAdapter.syncLiveStatus('waiting_approval')
    } catch (e) {
      if ((e as { status?: number }).status === 401) {
        expire()
        return
      }
    }
    pollRun(msg, startedAt)
  }, poll.intervalMs)
  pollTimers.add(timer)
}

function patchMessages(mutator: (list: ChatMessage[]) => void) {
  const list = [...messages.value]
  mutator(list)
  messages.value = list
}

async function send(text?: string) {
  const message = (text ?? input.value).trim()
  if (!message || sending.value || !hasTicket()) return
  ensureActiveThread()

  if (attachments.value.length) {
    ElMessage.warning('附件上传接口尚未接入，本次仅发送文本；附件列表已保留在消息气泡中供演示。')
  }

  const atts = attachments.value.map(({ id, name, size, mime }) => ({ id, name, size, mime }))
  patchMessages((list) => {
    list.push({
      id: uid('msg'),
      role: 'user',
      text: message,
      createdAt: Date.now(),
      attachments: atts.length ? atts : undefined,
    })
  })
  input.value = ''
  attachments.value.forEach((a) => a.previewUrl && URL.revokeObjectURL(a.previewUrl))
  attachments.value = []
  sending.value = true
  mockAdapter.syncLiveStatus('running', message.slice(0, 28))

  abortCtrl = new AbortController()
  let liveId: string | null = null
  let streamRaw = ''
  try {
    const r = await sendMessageStream(
      message,
      (piece) => {
        if (!liveId) {
          liveId = uid('msg')
          streamRaw = ''
          patchMessages((list) => {
            list.push({ id: liveId!, role: 'assistant', text: '', streaming: true, createdAt: Date.now() })
          })
        }
        streamRaw += piece
        const shown = plainText(streamRaw)
        patchMessages((list) => {
          const m = list.find((x) => x.id === liveId)
          if (m) m.text = shown
        })
      },
      abortCtrl.signal,
    )
    const delivery = buildDelivery(r.reply, currentTask.value)
    const done: ChatMessage = {
      id: liveId ?? uid('msg'),
      role: 'assistant',
      text: plainText(r.reply.content),
      reply: r.reply,
      runId: r.run_id,
      streaming: false,
      createdAt: Date.now(),
      delivery: delivery ?? undefined,
    }
    patchMessages((list) => {
      if (liveId) {
        const m = list.find((x) => x.id === liveId)
        if (m) Object.assign(m, done)
        else list.push(done)
      } else list.push(done)
    })
    if (r.reply.type === 'pending') {
      mockAdapter.syncLiveStatus('waiting_approval')
      const last = messages.value[messages.value.length - 1]
      if (last) pollRun(last)
    } else {
      mockAdapter.syncLiveStatus(r.reply.type === 'error' ? 'failed' : 'completed')
    }
    void loadThreads()
  } catch (e) {
    if (e instanceof StreamAbortedError) {
      patchMessages((list) => {
        if (liveId) {
          const m = list.find((x) => x.id === liveId)
          if (m) {
            m.streaming = false
            if (!m.text) m.text = '已停止生成'
            m.reply = { type: 'text', content: m.text, data: null }
          }
        }
      })
      mockAdapter.stop()
      return
    }
    const status = (e as { status?: number }).status
    if (status === 401) {
      expire()
      return
    }
    const failed: ChatMessage = {
      id: liveId ?? uid('msg'),
      role: 'assistant',
      text: errorMessage(e),
      reply: { type: 'error', content: errorMessage(e), data: null },
      streaming: false,
      createdAt: Date.now(),
    }
    patchMessages((list) => {
      if (liveId) {
        const m = list.find((x) => x.id === liveId)
        if (m) Object.assign(m, failed)
        else list.push(failed)
      } else list.push(failed)
    })
    mockAdapter.syncLiveStatus('failed')
  } finally {
    sending.value = false
    abortCtrl = null
  }
}

function stop() {
  abortCtrl?.abort()
  mockAdapter.stop()
  sending.value = false
}

async function newChat() {
  if (sending.value || loadingMessages.value) return
  try {
    const t = await createThread()
    threadId.value = t.thread_id
    const c = convFromThread(t)
    conversations.value = [c, ...conversations.value.filter((x) => x.id !== t.thread_id)]
    activeConversationId.value = t.thread_id
    input.value = ''
    currentTask.value = null
    mockAdapter.dispose()
    activeNav.value = 'conversations'
    ElMessage.success('已新建对话')
  } catch (e) {
    const status = (e as { status?: number }).status
    if (status === 401) {
      expire()
      return
    }
    ElMessage.error(errorMessage(e))
  }
}

async function selectConversation(id: string) {
  if (id === activeConversationId.value || sending.value || loadingMessages.value) return
  activeNav.value = 'conversations'
  try {
    const sw = await switchThread(id)
    threadId.value = sw.thread_id
    applySessionExtras(sw)
    activeConversationId.value = id
    currentTask.value = null
    mockAdapter.dispose()
    await loadMessagesForThread(id)
  } catch (e) {
    const status = (e as { status?: number }).status
    if (status === 401) {
      expire()
      return
    }
    ElMessage.error(errorMessage(e))
  }
}

async function renameConversation(id: string, title: string) {
  const c = conversations.value.find((x) => x.id === id)
  if (!c) return
  const next = title.trim().slice(0, 40)
  if (!next) return
  try {
    const t = await patchThread(id, { title: next })
    c.title = (t.title ?? '').trim() || null
    c.updatedAt = Date.parse(t.updated_at) || Date.now()
  } catch (e) {
    const status = (e as { status?: number }).status
    if (status === 401) {
      expire()
      return
    }
    ElMessage.error(errorMessage(e))
  }
}

async function removeConversation(id: string) {
  const c = conversations.value.find((x) => x.id === id)
  if (!c) return
  try {
    await ElMessageBox.confirm(`确定删除「${threadDisplayTitle(c.title)}」？`, '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteThread(id)
  } catch (e) {
    const status = (e as { status?: number }).status
    if (status === 401) {
      expire()
      return
    }
    ElMessage.error(errorMessage(e))
    return
  }
  conversations.value = conversations.value.filter((x) => x.id !== id)
  if (activeConversationId.value === id) {
    currentTask.value = null
    mockAdapter.dispose()
    if (conversations.value.length) await selectConversation(conversations.value[0].id)
    else await newChat()
    return
  }
  ElMessage.success('已删除')
}

function onNav(key: NavKey) {
  activeNav.value = key
  if (key === 'tasks') {
    inspectorOpen.value = true
    ElMessage.info('AI 任务详情见右侧任务检查器')
  } else if (key === 'approvals') {
    inspectorOpen.value = true
    ElMessage.info(currentTask.value?.approvals.length ? '请在右侧处理待审批事项' : '暂无待审批事项')
  } else if (key !== 'conversations') {
    ElMessage.info('该模块接口尚未接入，当前为导航占位')
  }
}

async function onApprove(id: string) {
  try {
    await mockAdapter.approve(id)
    ElMessage.success('已批准（演示适配层，未调用真实审批 API）')
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function onReject(id: string) {
  try {
    await mockAdapter.reject(id)
    ElMessage.success('已拒绝（演示适配层）')
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

function onOpenTools() {
  activeNav.value = 'tools'
  ElMessage.info(`可用能力：${skillNames.value.join('、') || '暂无'}。工具中心完整目录待后端开放。`)
}

function onRegenerate(msg: ChatMessage) {
  const idx = messages.value.findIndex((m) => m.id === msg.id)
  if (idx <= 0) return
  const prev = messages.value[idx - 1]
  if (prev?.role === 'user') send(prev.text)
}

watch(activeNav, (k) => {
  if (k === 'conversations') ensureActiveThread()
})
</script>

<template>
  <div class="chat-root">
    <div v-if="state === 'loading'" class="center">
      <el-skeleton :rows="4" animated style="width: 360px" />
    </div>

    <el-result
      v-else-if="state === 'no_launch'"
      icon="info"
      title="请从 OA 进入"
      sub-title="东审财税 AI 智能工作台需要在 OA 系统内打开，以确认你的身份。"
    />

    <el-result
      v-else-if="state === 'expired'"
      icon="warning"
      title="会话已失效"
      :sub-title="loadError ? `${loadError}，${reopenHint}` : reopenHint"
    />

    <AppLayout
      v-else
      :embedded="embedded"
      :display-name="displayName"
      :session-title="sessionTitle"
      :sidebar-collapsed="sidebarCollapsed"
      :inspector-open="inspectorOpen"
      :active-nav="activeNav"
      :conversations="conversations"
      :active-conversation-id="activeConversationId"
      :messages="messages"
      :sending="sending"
      :examples="examples"
      :skill-names="skillNames"
      :chat-enabled="chatEnabled"
      :input="input"
      :max-chars="maxChars"
      :attachments="attachments"
      :task="currentTask"
      :thread-id="threadId"
      :placeholder="placeholder"
      :memory-open="memoryOpen"
      @update:sidebar-collapsed="sidebarCollapsed = $event"
      @update:memory-open="memoryOpen = $event"
      @open-memory="memoryOpen = true"
      @update:inspector-open="inspectorOpen = $event"
      @update:active-nav="onNav"
      @update:input="input = $event"
      @update:attachments="attachments = $event"
      @new-chat="newChat"
      @select="selectConversation"
      @rename="renameConversation"
      @remove="removeConversation"
      @send="send()"
      @stop="stop"
      @example="send"
      @regenerate="onRegenerate"
      @open-tools="onOpenTools"
      @approve="onApprove"
      @reject="onReject"
    />
  </div>
</template>

<style scoped>
.chat-root {
  height: 100%;
  min-height: 100vh;
  background: var(--ds-page);
}
.center {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}
.chat-root :deep(.el-result) {
  padding-top: 12vh;
}
</style>
