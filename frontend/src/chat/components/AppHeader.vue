<script setup lang="ts">
import { Menu, Monitor, Fold, Notebook } from '@element-plus/icons-vue'

defineProps<{
  displayName: string
  sessionTitle?: string
  embedded?: boolean
  inspectorOpen: boolean
  sidebarCollapsed?: boolean
}>()

const emit = defineEmits<{
  'toggle-sidebar': []
  'toggle-inspector': []
  'open-memory': []
}>()
</script>

<template>
  <header v-if="!embedded" class="header">
    <div class="left">
      <button type="button" class="icon-btn mobile-only" aria-label="菜单" @click="emit('toggle-sidebar')">
        <el-icon :size="20"><Menu /></el-icon>
      </button>
      <div class="titles">
        <strong class="session" :title="sessionTitle || '新会话'">{{ sessionTitle || '新会话' }}</strong>
        <span class="sub">对话工作区</span>
      </div>
    </div>
    <div class="right">
      <button type="button" class="ghost-btn" title="我的记忆" @click="emit('open-memory')">
        <el-icon :size="16"><Notebook /></el-icon>
        <span>我的记忆</span>
      </button>
      <button
        type="button"
        class="ghost-btn"
        :title="inspectorOpen ? '收起任务面板' : '打开任务面板'"
        @click="emit('toggle-inspector')"
      >
        <el-icon :size="16">
          <Fold v-if="inspectorOpen" />
          <Monitor v-else />
        </el-icon>
        <span>{{ inspectorOpen ? '收起任务' : '任务面板' }}</span>
      </button>
      <div class="user" :title="displayName">
        <span class="avatar">{{ (displayName || '用').slice(0, 1) }}</span>
        <span class="name">{{ displayName || '员工' }}</span>
      </div>
    </div>
  </header>
</template>

<style scoped>
.header {
  height: var(--ds-header-h);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  background: #fff;
  border-bottom: 1px solid var(--ds-line);
  flex-shrink: 0;
  z-index: 5;
}
.left,
.right {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.titles {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
  min-width: 0;
  gap: 2px;
}
.session {
  font-size: 14px;
  font-weight: 650;
  color: var(--ds-title);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: min(42vw, 360px);
}
.sub {
  font-size: 12px;
  color: var(--ds-muted);
}
.icon-btn,
.ghost-btn {
  border: none;
  background: transparent;
  color: var(--ds-body);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
}
.icon-btn {
  width: 34px;
  height: 34px;
  border-radius: 8px;
}
.ghost-btn {
  gap: 5px;
  height: 32px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid var(--ds-line);
  background: #fff;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ds-title);
}
.icon-btn:hover,
.ghost-btn:hover {
  background: var(--ds-brand-soft);
  color: var(--ds-brand);
  border-color: transparent;
}
.user {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 8px 3px 3px;
  border-radius: 999px;
  background: var(--ds-page);
  border: 1px solid var(--ds-line);
}
.avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--ds-brand);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.name {
  font-size: 13px;
  color: var(--ds-title);
  max-width: 100px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding-right: 2px;
  font-weight: 550;
}
.mobile-only {
  display: none;
}
@media (max-width: 768px) {
  .mobile-only {
    display: inline-flex;
  }
  .ghost-btn span {
    display: none;
  }
  .ghost-btn {
    width: 32px;
    padding: 0;
  }
  .session {
    max-width: 40vw;
  }
}
</style>
