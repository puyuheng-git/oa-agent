<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  Document,
  Plus,
  Setting,
  Stamp,
  Tools,
  OfficeBuilding,
  List,
  Fold,
  Expand,
  Collection,
  Notebook,
  Search,
  EditPen,
  Delete,
  ArrowDown,
} from '@element-plus/icons-vue'
import { formatRelativeTime, threadDisplayTitle } from '../api'
import type { LocalConversation, NavKey } from '../types'

const props = defineProps<{
  collapsed: boolean
  activeNav: NavKey
  conversations: LocalConversation[]
  activeConversationId: string
}>()

const emit = defineEmits<{
  'update:collapsed': [v: boolean]
  'update:activeNav': [k: NavKey]
  'new-chat': []
  select: [id: string]
  rename: [id: string, title: string]
  remove: [id: string]
  'open-memory': []
}>()

const query = ref('')
const renamingId = ref<string | null>(null)
const renameDraft = ref('')
/** 侧栏展开时，分区默认收起，给对话列表更多空间 */
const workspaceOpen = ref(false)
const manageOpen = ref(false)

const workspaceItems: { key: NavKey; label: string; icon: unknown }[] = [
  { key: 'workspace', label: '工作空间', icon: OfficeBuilding },
  { key: 'tasks', label: 'AI 任务', icon: List },
  { key: 'documents', label: '文档中心', icon: Document },
  { key: 'knowledge', label: '企业知识库', icon: Collection },
]

const manageItems: { key: NavKey; label: string; icon: unknown }[] = [
  { key: 'tools', label: '工具中心', icon: Tools },
  { key: 'approvals', label: '审批中心', icon: Stamp },
  { key: 'settings', label: '设置', icon: Setting },
]

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return props.conversations
  return props.conversations.filter((c) => threadDisplayTitle(c.title).toLowerCase().includes(q))
})

function channelLabel(ch: string | null | undefined) {
  if (!ch) return ''
  if (ch === 'oa_web') return '网页'
  if (ch === 'wecom') return '企微'
  return ch
}

function startRename(c: LocalConversation, e: Event) {
  e.stopPropagation()
  renamingId.value = c.id
  renameDraft.value = threadDisplayTitle(c.title)
}

function commitRename() {
  if (!renamingId.value) return
  const title = renameDraft.value.trim()
  if (title) emit('rename', renamingId.value, title)
  renamingId.value = null
}

function cancelRename() {
  renamingId.value = null
}

function onRemove(id: string, e: Event) {
  e.stopPropagation()
  emit('remove', id)
}
</script>

<template>
  <aside :class="['sidebar', { collapsed }]">
    <div class="sidebar-bg" aria-hidden="true" />
    <div class="brand">
      <div class="logo" aria-hidden="true"><span>东</span></div>
      <div v-if="!collapsed" class="brand-text">
        <strong>东审财税</strong>
        <span>AI 智能工作台</span>
      </div>
    </div>

    <!-- 对话区 -->
    <section class="group">
      <div v-if="!collapsed" class="group-title">对话</div>
      <button type="button" class="new-chat" @click="emit('new-chat')">
        <el-icon :size="16"><Plus /></el-icon>
        <span v-if="!collapsed">新对话</span>
      </button>

      <div v-if="!collapsed" class="search">
        <el-icon class="search-ico"><Search /></el-icon>
        <input v-model="query" type="search" placeholder="搜索历史会话" aria-label="搜索历史会话" />
      </div>

      <ul v-if="!collapsed" class="conv-list">
        <li v-for="c in filtered" :key="c.id">
          <div
            :class="['conv', { active: c.id === activeConversationId }]"
            @click="emit('select', c.id)"
          >
            <template v-if="renamingId === c.id">
              <input
                v-model="renameDraft"
                class="rename-input"
                maxlength="40"
                @click.stop
                @keydown.enter.prevent="commitRename"
                @keydown.esc.prevent="cancelRename"
                @blur="commitRename"
              />
            </template>
            <template v-else>
              <div class="conv-main">
                <el-tooltip :content="threadDisplayTitle(c.title)" placement="right" :show-after="400">
                  <span class="conv-title">{{ threadDisplayTitle(c.title) }}</span>
                </el-tooltip>
                <span v-if="c.lastChannel || c.updatedAt" class="conv-meta">
                  <span v-if="channelLabel(c.lastChannel)">{{ channelLabel(c.lastChannel) }}</span>
                  <span v-if="formatRelativeTime(new Date(c.updatedAt).toISOString())">
                    {{ formatRelativeTime(new Date(c.updatedAt).toISOString()) }}
                  </span>
                </span>
              </div>
              <div class="conv-acts">
                <button type="button" title="重命名" @click="startRename(c, $event)">
                  <el-icon :size="14"><EditPen /></el-icon>
                </button>
                <button type="button" title="删除" @click="onRemove(c.id, $event)">
                  <el-icon :size="14"><Delete /></el-icon>
                </button>
              </div>
            </template>
          </div>
        </li>
        <li v-if="!filtered.length" class="empty-hint">
          {{ query.trim() ? '无匹配会话' : '暂无对话记录' }}
        </li>
      </ul>
    </section>

    <!-- 工作空间 -->
    <nav class="group">
      <button
        v-if="!collapsed"
        type="button"
        class="group-toggle"
        :aria-expanded="workspaceOpen"
        @click="workspaceOpen = !workspaceOpen"
      >
        <span>工作空间</span>
        <el-icon :size="14" :class="['chevron', { open: workspaceOpen }]"><ArrowDown /></el-icon>
      </button>
      <div v-show="collapsed || workspaceOpen" class="group-body">
        <button
          v-for="item in workspaceItems"
          :key="item.key"
          type="button"
          :class="['nav-item', { active: activeNav === item.key }]"
          :title="item.label"
          @click="emit('update:activeNav', item.key)"
        >
          <el-icon :size="18"><component :is="item.icon" /></el-icon>
          <span v-if="!collapsed">{{ item.label }}</span>
        </button>
      </div>
    </nav>

    <!-- 管理中心 -->
    <nav class="group grow">
      <button
        v-if="!collapsed"
        type="button"
        class="group-toggle"
        :aria-expanded="manageOpen"
        @click="manageOpen = !manageOpen"
      >
        <span>管理中心</span>
        <el-icon :size="14" :class="['chevron', { open: manageOpen }]"><ArrowDown /></el-icon>
      </button>
      <div v-show="collapsed || manageOpen" class="group-body">
        <button type="button" class="nav-item" title="我的记忆" @click="emit('open-memory')">
          <el-icon :size="18"><Notebook /></el-icon>
          <span v-if="!collapsed">我的记忆</span>
        </button>
        <button
          v-for="item in manageItems"
          :key="item.key"
          type="button"
          :class="['nav-item', { active: activeNav === item.key }]"
          :title="item.label"
          @click="emit('update:activeNav', item.key)"
        >
          <el-icon :size="18"><component :is="item.icon" /></el-icon>
          <span v-if="!collapsed">{{ item.label }}</span>
        </button>
      </div>
    </nav>

    <button
      type="button"
      class="collapse-btn"
      :title="collapsed ? '展开导航' : '收起导航'"
      @click="emit('update:collapsed', !collapsed)"
    >
      <el-icon :size="16">
        <Expand v-if="collapsed" />
        <Fold v-else />
      </el-icon>
      <span v-if="!collapsed">收起导航</span>
    </button>
  </aside>
</template>

<style scoped>
.sidebar {
  position: relative;
  width: var(--ds-sidebar-w);
  color: #fff;
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  transition: width 0.28s var(--ds-ease);
  flex-shrink: 0;
  overflow: hidden;
  z-index: 2;
}
.sidebar-bg {
  position: absolute;
  inset: 0;
  background: linear-gradient(165deg, #1296eb 0%, #008ae7 48%, #0070c0 100%);
  z-index: -1;
}
.sidebar.collapsed {
  width: var(--ds-sidebar-collapsed);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 14px 10px;
}
.logo {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.28);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-weight: 800;
  font-size: 15px;
}
.brand-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  line-height: 1.25;
}
.brand-text strong {
  font-size: 14px;
  font-weight: 700;
}
.brand-text span {
  font-size: 12px;
  opacity: 0.85;
}
.group {
  padding: 0 10px 6px;
  min-height: 0;
}
.group.grow {
  flex: 1;
  overflow-y: auto;
}
.group-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin: 4px 0 2px;
  padding: 8px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: rgba(255, 255, 255, 0.88);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  cursor: pointer;
}
.group-toggle:hover {
  background: rgba(255, 255, 255, 0.1);
}
.chevron {
  transition: transform 0.2s var(--ds-ease);
  opacity: 0.85;
}
.chevron.open {
  transform: rotate(180deg);
}
.group-body {
  padding-bottom: 2px;
}
.new-chat {
  width: 100%;
  height: 38px;
  margin-bottom: 8px;
  border: none;
  border-radius: 10px;
  background: #fff;
  color: var(--ds-brand);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}
.new-chat:hover {
  filter: brightness(0.98);
}
.sidebar.collapsed .new-chat {
  width: 44px;
  margin-inline: auto;
  padding: 0;
}
.search {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  margin-bottom: 6px;
  padding: 0 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.16);
}
.search-ico {
  opacity: 0.8;
  flex-shrink: 0;
}
.search input {
  flex: 1;
  min-width: 0;
  border: none;
  background: transparent;
  color: #fff;
  font-size: 13px;
  outline: none;
}
.search input::placeholder {
  color: rgba(255, 255, 255, 0.65);
}
.conv-list {
  list-style: none;
  margin: 0 0 4px;
  padding: 0;
  max-height: min(52vh, 420px);
  overflow-y: auto;
}
.conv {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  min-height: 36px;
  padding: 6px 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}
.conv:hover {
  background: rgba(255, 255, 255, 0.12);
}
.conv.active {
  background: rgba(255, 255, 255, 0.24);
  box-shadow: inset 3px 0 0 #fff;
}
.conv-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.conv-title {
  font-size: 13px;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.conv-meta {
  display: flex;
  gap: 6px;
  font-size: 11px;
  line-height: 1.2;
  opacity: 0.72;
}
.conv-meta span + span::before {
  content: '·';
  margin-right: 6px;
  opacity: 0.85;
}
.conv-acts {
  display: none;
  gap: 2px;
  flex-shrink: 0;
}
.conv:hover .conv-acts,
.conv.active .conv-acts {
  display: inline-flex;
}
.conv-acts button {
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: rgba(255, 255, 255, 0.85);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.conv-acts button:hover {
  background: rgba(255, 255, 255, 0.2);
}
.rename-input {
  flex: 1;
  min-width: 0;
  height: 28px;
  border: none;
  border-radius: 6px;
  padding: 0 8px;
  font-size: 13px;
  color: var(--ds-title);
}
.empty-hint {
  padding: 8px 10px;
  font-size: 12px;
  opacity: 0.75;
}
.nav-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  border: none;
  background: transparent;
  color: #fff;
  text-align: left;
  padding: 9px 10px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
}
.nav-item:hover {
  background: rgba(255, 255, 255, 0.12);
}
.nav-item.active {
  background: rgba(255, 255, 255, 0.2);
  font-weight: 650;
}
.sidebar.collapsed .nav-item {
  justify-content: center;
  padding-inline: 0;
}
.collapse-btn {
  margin: 4px 10px 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.95);
  padding: 9px 10px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
}
.collapse-btn:hover {
  background: rgba(255, 255, 255, 0.14);
}
.sidebar.collapsed .collapse-btn {
  justify-content: center;
}

@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    z-index: 50;
    width: min(288px, 86vw) !important;
    transform: translateX(-105%);
    box-shadow: 12px 0 40px rgba(23, 43, 77, 0.28);
    transition: transform 0.28s var(--ds-ease);
  }
  .sidebar:not(.collapsed) {
    transform: translateX(0);
  }
}
</style>
