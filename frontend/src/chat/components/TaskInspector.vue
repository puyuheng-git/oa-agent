<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, Close, Monitor } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { AgentTask, ArtifactFile, TaskStep } from '../types'
import TaskProgressCard from './TaskProgressCard.vue'
import StepTimeline from './StepTimeline.vue'
import ToolActivityList from './ToolActivityList.vue'
import ArtifactCard from './ArtifactCard.vue'
import ApprovalCard from './ApprovalCard.vue'
import EmptyState from './EmptyState.vue'
import DocumentPreviewDrawer from './DocumentPreviewDrawer.vue'

const props = defineProps<{
  task: AgentTask | null
  open: boolean
  threadId?: string
}>()

const emit = defineEmits<{
  'update:open': [v: boolean]
  approve: [id: string]
  reject: [id: string]
}>()

const stepsExpanded = ref(true)
const previewOpen = ref(false)
const previewFile = ref<ArtifactFile | null>(null)

/** 未实际调用工具 / 生成文件时，不展示对应步骤行。 */
function filterSteps(task: AgentTask): TaskStep[] {
  return task.steps.filter((s) => {
    if (s.id === 'tools') return task.tools.length > 0
    if (s.id === 'files' || s.id === 'deliver') return task.artifacts.length > 0
    return true
  })
}

const visibleSteps = computed(() => (props.task ? filterSteps(props.task) : []))

watch(
  () => props.task?.id,
  () => {
    stepsExpanded.value = true
  },
)

function onPreview(file: ArtifactFile) {
  previewFile.value = file
  previewOpen.value = true
}

function onDownload(file: ArtifactFile) {
  if (!file.downloadUrl) {
    ElMessage.info('该文件暂无真实下载地址（演示数据或后端未提供）')
    return
  }
  window.open(file.downloadUrl, '_blank', 'noopener')
}
</script>

<template>
  <aside :class="['inspector', { open }]">
    <div class="head">
      <div class="title">
        <el-icon><Monitor /></el-icon>
        <span>任务检查器</span>
      </div>
      <button type="button" class="close" aria-label="关闭" @click="emit('update:open', false)">
        <el-icon><Close /></el-icon>
      </button>
    </div>

    <div class="scroll">
      <section class="sec">
        <h3>当前任务</h3>
        <TaskProgressCard v-if="task" :task="task" :thread-id="threadId" />
        <EmptyState
          v-else
          title="暂无运行任务"
          description="发送消息后，将在此展示任务状态与进度。未接入细粒度 Agent 事件时可能仅有顶层状态。"
        />
      </section>

      <template v-if="task">
        <section v-if="visibleSteps.length" class="sec">
          <button type="button" class="sec-toggle" @click="stepsExpanded = !stepsExpanded">
            <h3>执行步骤</h3>
            <el-icon>
              <ArrowUp v-if="stepsExpanded" />
              <ArrowDown v-else />
            </el-icon>
          </button>
          <StepTimeline :steps="visibleSteps" :expanded="stepsExpanded" />
        </section>

        <section v-if="task.tools.length" class="sec">
          <h3>工具调用</h3>
          <ToolActivityList :tools="task.tools" />
        </section>

        <section v-if="task.artifacts.length" class="sec">
          <h3>生成文件</h3>
          <ArtifactCard
            v-for="f in task.artifacts"
            :key="f.id"
            :file="f"
            @preview="onPreview"
            @download="onDownload"
          />
        </section>

        <section v-if="task.approvals.length" class="sec">
          <h3>待审批事项</h3>
          <ApprovalCard
            v-for="a in task.approvals"
            :key="a.id"
            :item="a"
            @approve="emit('approve', $event)"
            @reject="emit('reject', $event)"
          />
        </section>
      </template>
    </div>

    <DocumentPreviewDrawer v-model:open="previewOpen" :file="previewFile" />
  </aside>
</template>

<style scoped>
.inspector {
  display: flex;
  flex-direction: column;
  width: var(--ds-inspector-w);
  background: #fafcfe;
  border-left: 1px solid var(--ds-line);
  height: 100%;
  min-height: 0;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--ds-header-h);
  padding: 0 12px 0 16px;
  border-bottom: 1px solid var(--ds-line);
  background: #fff;
  flex-shrink: 0;
}
.title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--ds-title);
}
.title :deep(.el-icon) {
  color: var(--ds-brand);
}
.close {
  border: none;
  background: transparent;
  color: var(--ds-muted);
  width: 32px;
  height: 32px;
  border-radius: 10px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.close:hover {
  background: var(--ds-brand-soft);
  color: var(--ds-brand);
}
.scroll {
  flex: 1;
  overflow-y: auto;
  padding: 16px 14px 28px;
}
.sec {
  margin-bottom: 12px;
  padding: 12px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid var(--ds-line);
}
.sec h3 {
  margin: 0 0 10px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--ds-muted);
}
.sec-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border: none;
  background: transparent;
  padding: 0;
  cursor: pointer;
  margin-bottom: 4px;
  color: var(--ds-muted);
}
.sec-toggle h3 {
  margin: 0;
}
</style>
