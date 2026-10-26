<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errorMessage } from '@/shared/http'
import { formatTime } from '@/shared/format'
import { memoryKindLabel } from '@/chat/api'
import { can } from '../auth'
import { NO_DATA } from '../runs'
import {
  CHECKPOINT_RESTORE_WARNING,
  THREAD_STATUS,
  addVisibilityGrant,
  batchEmployeeThreads,
  clearEmployeeMemory,
  createEmployeeMemory,
  deleteEmployeeMemory,
  deleteEmployeeThread,
  getEmployeeVisibility,
  hiddenReasonLabel,
  listEmployeeMemory,
  listEmployeeThreads,
  listThreadMessages,
  patchEmployeeMemory,
  patchEmployeeThread,
  removeVisibilityGrant,
  restoreEmployeeMemory,
  restoreEmployeeThread,
  type EmployeeMemory,
  type EmployeeMessage,
  type EmployeeThread,
  type EmployeeVisibility,
} from '../employees'

const route = useRoute()
const router = useRouter()

const oa = computed(() => decodeURIComponent(String(route.params.oa ?? '')))
const tab = ref('threads')

const canSensitive = computed(() => can('ops.employee.sensitive'))
const canManage = computed(() => can('ops.employee.manage'))

async function askReason(title: string, extra?: string): Promise<string | null> {
  try {
    const { value } = await ElMessageBox.prompt(extra ?? '请填写原因（写入审计，至少 2 个字）', title, {
      inputValidator: (v: string) => (v && v.trim().length >= 2) || '至少 2 个字',
      confirmButtonText: '确定',
      cancelButtonText: '取消',
    })
    return value.trim()
  } catch {
    return null
  }
}

// ---------- 会话 Tab ----------
const threadStatus = ref<EmployeeThread['status']>('active')
const threads = ref<EmployeeThread[]>([])
const threadsTotal = ref(0)
const threadsPage = ref(1)
const threadsLoading = ref(false)
const selectedThreadIds = ref<string[]>([])

const msgDrawer = ref(false)
const msgThread = ref<EmployeeThread | null>(null)
const messages = ref<EmployeeMessage[]>([])
const messagesLoading = ref(false)

async function loadThreads() {
  threadsLoading.value = true
  try {
    const data = await listEmployeeThreads(oa.value, {
      status: threadStatus.value,
      page: threadsPage.value,
      page_size: 20,
    })
    threads.value = data.items
    threadsTotal.value = data.total
    selectedThreadIds.value = []
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    threadsLoading.value = false
  }
}

async function openMessages(row: EmployeeThread) {
  if (!canSensitive.value) {
    ElMessage.warning('无权限：查看会话原文需要 ops.employee.sensitive')
    return
  }
  msgDrawer.value = true
  msgThread.value = row
  messages.value = []
  messagesLoading.value = true
  try {
    const data = await listThreadMessages(oa.value, row.thread_id, { page: 1, page_size: 100 })
    messages.value = data.items
  } catch (e) {
    ElMessage.error(errorMessage(e))
    msgDrawer.value = false
  } finally {
    messagesLoading.value = false
  }
}

async function patchThread(row: EmployeeThread, patch: { title?: string; status?: 'active' | 'archived' }) {
  const reason = await askReason('修改会话')
  if (!reason) return
  try {
    await patchEmployeeThread(oa.value, row.thread_id, { ...patch, reason })
    ElMessage.success('已更新')
    await loadThreads()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function softDeleteThread(row: EmployeeThread) {
  const reason = await askReason('软删会话')
  if (!reason) return
  try {
    await deleteEmployeeThread(oa.value, row.thread_id, { reason })
    ElMessage.success('已软删')
    await loadThreads()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function restoreThread(row: EmployeeThread) {
  try {
    await ElMessageBox.confirm(CHECKPOINT_RESTORE_WARNING, '恢复会话', {
      type: 'warning',
      confirmButtonText: '继续恢复',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const reason = await askReason('恢复会话', CHECKPOINT_RESTORE_WARNING)
  if (!reason) return
  try {
    await restoreEmployeeThread(oa.value, row.thread_id, { reason, status: 'active' })
    ElMessage.success('已恢复（仅元数据）')
    await loadThreads()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function batchThreads(action: 'archive' | 'soft_delete') {
  if (!selectedThreadIds.value.length) return
  const reason = await askReason(action === 'archive' ? '批量归档' : '批量软删')
  if (!reason) return
  try {
    await batchEmployeeThreads(oa.value, { action, thread_ids: selectedThreadIds.value, reason })
    ElMessage.success('批量操作完成')
    await loadThreads()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

// ---------- 记忆 Tab ----------
const memoryStatus = ref<'active' | 'deleted'>('active')
const memories = ref<EmployeeMemory[]>([])
const memoryTotal = ref(0)
const memoryPage = ref(1)
const memoryLoading = ref(false)
const memoryTextLoaded = ref(false)

async function loadMemory(includeText: 0 | 1 = 0) {
  memoryLoading.value = true
  try {
    const data = await listEmployeeMemory(oa.value, {
      status: memoryStatus.value,
      include_text: includeText,
      page: memoryPage.value,
      page_size: 20,
    })
    memories.value = data.items
    memoryTotal.value = data.total
    memoryTextLoaded.value = includeText === 1
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    memoryLoading.value = false
  }
}

async function loadMemoryText() {
  if (!canSensitive.value) {
    ElMessage.warning('无权限')
    return
  }
  await loadMemory(1)
}

async function addMemory() {
  try {
    const { value: kind } = await ElMessageBox.prompt('种类：preference / constraint / note', '代写记忆', {
      inputValue: 'note',
      inputValidator: (v) => ['preference', 'constraint', 'note'].includes(v.trim()) || '无效 kind',
    })
    const { value: text } = await ElMessageBox.prompt('记忆正文（≤200 字）', '代写记忆', {
      inputValidator: (v) => (v && v.trim().length >= 1) || '不能为空',
    })
    const reason = await askReason('代写记忆')
    if (!reason) return
    await createEmployeeMemory(oa.value, { kind: kind.trim() as EmployeeMemory['kind'], text: text.trim(), reason })
    ElMessage.success('已添加')
    await loadMemory(memoryTextLoaded.value ? 1 : 0)
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(errorMessage(e))
  }
}

async function editMemory(row: EmployeeMemory) {
  if (!canSensitive.value || !row.text) {
    ElMessage.warning('请先加载正文且无 sensitive 权限时不可编辑')
    return
  }
  const { value: text } = await ElMessageBox.prompt('新正文', '编辑记忆', {
    inputValue: row.text,
    inputValidator: (v) => (v && v.trim().length >= 1) || '不能为空',
  })
  const reason = await askReason('编辑记忆')
  if (!reason) return
  try {
    await patchEmployeeMemory(oa.value, row.memory_id, { text: text.trim(), reason })
    ElMessage.success('已更新')
    await loadMemory(1)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function delMemory(row: EmployeeMemory) {
  const reason = await askReason('删除记忆')
  if (!reason) return
  try {
    await deleteEmployeeMemory(oa.value, row.memory_id, { reason })
    ElMessage.success('已软删')
    await loadMemory(memoryTextLoaded.value ? 1 : 0)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function restoreMemory(row: EmployeeMemory) {
  const reason = await askReason('恢复记忆')
  if (!reason) return
  try {
    await restoreEmployeeMemory(oa.value, row.memory_id, { reason })
    ElMessage.success('已恢复')
    await loadMemory(memoryTextLoaded.value ? 1 : 0)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function clearMemory() {
  try {
    await ElMessageBox.confirm('将软删该员工全部 active 记忆，不可恢复。', '清空记忆', { type: 'warning' })
  } catch {
    return
  }
  const reason = await askReason('清空记忆')
  if (!reason) return
  try {
    const r = await clearEmployeeMemory(oa.value, { reason, confirm: true })
    ElMessage.success(r.deleted ? `已清空 ${r.deleted} 条` : '暂无 active 记忆')
    await loadMemory(0)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

// ---------- 可见性 Tab ----------
const visibility = ref<EmployeeVisibility | null>(null)
const visLoading = ref(false)

async function loadVisibility() {
  visLoading.value = true
  try {
    visibility.value = await getEmployeeVisibility(oa.value)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    visLoading.value = false
  }
}

async function grantSkill(skillName: string, effect: 'allow' | 'deny') {
  const reason = await askReason(effect === 'allow' ? '允许 Skill' : '拒绝 Skill')
  if (!reason) return
  try {
    await addVisibilityGrant(oa.value, { skill_name: skillName, effect, reason })
    ElMessage.success('规则已追加')
    await loadVisibility()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function revokeGrant(skillName: string, effect?: 'allow' | 'deny') {
  const reason = await askReason('移除可见性规则')
  if (!reason) return
  try {
    await removeVisibilityGrant(oa.value, { skill_name: skillName, effect, reason })
    ElMessage.success('已移除')
    await loadVisibility()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

function reloadTab() {
  if (tab.value === 'threads') loadThreads()
  else if (tab.value === 'memory') loadMemory(memoryTextLoaded.value ? 1 : 0)
  else loadVisibility()
}

function threadStatusMeta(status: EmployeeThread['status']) {
  return THREAD_STATUS[status]
}

watch(tab, () => reloadTab())
watch(threadStatus, () => {
  threadsPage.value = 1
  loadThreads()
})
watch(memoryStatus, () => {
  memoryPage.value = 1
  memoryTextLoaded.value = false
  loadMemory(0)
})

onMounted(reloadTab)
</script>

<template>
  <el-card>
    <div class="head">
      <el-button link type="primary" @click="router.push('/employees')">← 员工目录</el-button>
      <h2>{{ oa }}</h2>
    </div>

    <el-tabs v-model="tab">
      <el-tab-pane label="会话" name="threads">
        <el-form inline style="margin-bottom: 8px">
          <el-form-item label="状态">
            <el-select v-model="threadStatus" style="width: 120px">
              <el-option label="进行中" value="active" />
              <el-option label="已归档" value="archived" />
              <el-option label="已删除" value="deleted" />
            </el-select>
          </el-form-item>
          <el-button v-if="canManage && threadStatus !== 'deleted'" :disabled="!selectedThreadIds.length" @click="batchThreads('archive')">
            批量归档
          </el-button>
          <el-button
            v-if="canManage && threadStatus !== 'deleted'"
            type="danger"
            :disabled="!selectedThreadIds.length"
            @click="batchThreads('soft_delete')"
          >
            批量软删
          </el-button>
        </el-form>
        <el-table
          v-loading="threadsLoading"
          :data="threads"
          :empty-text="NO_DATA"
          @selection-change="(s: EmployeeThread[]) => (selectedThreadIds = s.map((x) => x.thread_id))"
        >
          <el-table-column v-if="canManage && threadStatus !== 'deleted'" type="selection" width="48" />
          <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="threadStatusMeta(row.status).type" size="small">{{ threadStatusMeta(row.status).label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最近消息" width="170">
            <template #default="{ row }">{{ row.last_message_at ? formatTime(row.last_message_at) : NO_DATA }}</template>
          </el-table-column>
          <el-table-column prop="thread_id" label="thread_id" min-width="200" show-overflow-tooltip />
          <el-table-column label="操作" width="280" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openMessages(row)">
                {{ canSensitive ? '消息' : '消息（无权限）' }}
              </el-button>
              <template v-if="canManage">
                <el-button v-if="row.status === 'active'" link @click="patchThread(row, { status: 'archived' })">归档</el-button>
                <el-button v-if="row.status === 'archived'" link @click="patchThread(row, { status: 'active' })">启封</el-button>
                <el-button v-if="row.status !== 'deleted'" link type="danger" @click="softDeleteThread(row)">软删</el-button>
                <el-button v-if="row.status === 'deleted'" link type="warning" @click="restoreThread(row)">恢复</el-button>
              </template>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="threadsPage"
          :total="threadsTotal"
          :page-size="20"
          layout="total, prev, pager, next"
          style="margin-top: 12px"
          @current-change="loadThreads"
        />
      </el-tab-pane>

      <el-tab-pane label="记忆" name="memory">
        <el-form inline style="margin-bottom: 8px">
          <el-form-item label="状态">
            <el-select v-model="memoryStatus" style="width: 120px">
              <el-option label="active" value="active" />
              <el-option label="deleted" value="deleted" />
            </el-select>
          </el-form-item>
          <el-button v-if="canSensitive && !memoryTextLoaded" @click="loadMemoryText">加载正文（审计）</el-button>
          <el-button v-if="canManage && memoryStatus === 'active'" type="primary" @click="addMemory">代写</el-button>
          <el-button v-if="canManage && memoryStatus === 'active'" type="danger" @click="clearMemory">清空 active</el-button>
        </el-form>
        <el-table v-loading="memoryLoading" :data="memories" :empty-text="NO_DATA">
          <el-table-column label="种类" width="90">
            <template #default="{ row }">{{ memoryKindLabel(row.kind) }}</template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column label="正文" min-width="240">
            <template #default="{ row }">
              <span v-if="memoryTextLoaded && row.text">{{ row.text }}</span>
              <span v-else-if="canSensitive" class="muted">未加载</span>
              <span v-else class="muted">无权限</span>
            </template>
          </el-table-column>
          <el-table-column label="更新" width="170">
            <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
          </el-table-column>
          <el-table-column v-if="canManage" label="操作" width="160">
            <template #default="{ row }">
              <el-button v-if="row.status === 'active'" link @click="editMemory(row)">编辑</el-button>
              <el-button v-if="row.status === 'active'" link type="danger" @click="delMemory(row)">删除</el-button>
              <el-button v-if="row.status === 'deleted'" link @click="restoreMemory(row)">恢复</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="memoryPage"
          :total="memoryTotal"
          :page-size="20"
          layout="total, prev, pager, next"
          style="margin-top: 12px"
          @current-change="() => loadMemory(memoryTextLoaded ? 1 : 0)"
        />
      </el-tab-pane>

      <el-tab-pane label="可见性" name="visibility">
        <el-skeleton v-if="visLoading && !visibility" :rows="6" />
        <template v-else-if="visibility">
          <el-row :gutter="16">
            <el-col :span="12">
              <h4>可见 Skill</h4>
              <el-table :data="visibility.visible" :empty-text="NO_DATA" size="small">
                <el-table-column prop="display_name" label="名称" />
                <el-table-column prop="name" label="标识" />
                <el-table-column v-if="canManage" label="快捷" width="100">
                  <template #default="{ row }">
                    <el-button link type="danger" size="small" @click="revokeGrant(row.name, 'allow')">撤 allow</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-col>
            <el-col :span="12">
              <h4>不可见 Skill</h4>
              <el-table :data="visibility.hidden" :empty-text="NO_DATA" size="small">
                <el-table-column prop="name" label="标识" />
                <el-table-column label="原因" width="120">
                  <template #default="{ row }">{{ hiddenReasonLabel(row.reason) }}</template>
                </el-table-column>
                <el-table-column v-if="canManage" label="快捷" width="140">
                  <template #default="{ row }">
                    <el-button link type="primary" size="small" @click="grantSkill(row.name, 'allow')">allow</el-button>
                    <el-button link type="danger" size="small" @click="grantSkill(row.name, 'deny')">deny</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-col>
          </el-row>
        </template>
      </el-tab-pane>
    </el-tabs>
  </el-card>

  <el-drawer v-model="msgDrawer" size="55%" :title="msgThread ? `消息 · ${msgThread.title ?? msgThread.thread_id}` : '消息'">
    <el-skeleton v-if="messagesLoading" :rows="8" />
    <div v-else class="msgs">
      <div v-for="m in messages" :key="m.message_id" :class="['msg', m.role]">
        <div class="msg-head">
          <b>{{ m.role === 'user' ? '员工' : '助手' }}</b>
          <span class="meta">{{ formatTime(m.created_at) }}</span>
          <el-link type="primary" class="meta" @click="router.push(`/runs/${m.run_id}`)">{{ m.run_id }}</el-link>
        </div>
        <div class="msg-body">{{ m.content || '（空）' }}</div>
      </div>
      <p v-if="!messages.length && !messagesLoading">{{ NO_DATA }}</p>
    </div>
  </el-drawer>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.head h2 {
  margin: 0;
  font-size: 1.25rem;
}
.muted {
  color: var(--el-text-color-secondary);
}
.msgs {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.msg-head {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  font-size: 13px;
}
.meta {
  color: var(--el-text-color-secondary);
}
.msg-body {
  white-space: pre-wrap;
  margin-top: 4px;
}
.msg.user .msg-body {
  background: var(--el-fill-color-light);
  padding: 8px;
  border-radius: 6px;
}
</style>
