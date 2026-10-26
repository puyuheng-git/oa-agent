<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errorMessage, http } from '@/shared/http'
import { formatTime } from '@/shared/format'
import { TASK_KIND, TASK_STATUS, type InterventionDetail, type InterventionTask } from '../ops'
import { statusLabel, statusType } from '../runs'

const router = useRouter()
const filters = reactive({ status: 'pending', kind: '' })
const page = ref(1)
const items = ref<InterventionTask[]>([])
const total = ref(0)
const pendingCount = ref(0)
const loading = ref(false)
const loadError = ref('')

const drawer = ref(false)
const detail = ref<InterventionDetail | null>(null)
const acting = ref(false)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await http.get<{ items: InterventionTask[]; total: number; pending_count: number }>(
      '/v1/admin/interventions',
      { ...filters, page: page.value, page_size: 20 },
    )
    items.value = data.items
    total.value = data.total
    pendingCount.value = data.pending_count
  } catch (e) {
    loadError.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

async function open(task: InterventionTask) {
  drawer.value = true
  detail.value = null
  try {
    detail.value = await http.get<InterventionDetail>(`/v1/admin/interventions/${task.task_id}`)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function askReason(title: string): Promise<string | null> {
  try {
    const { value } = await ElMessageBox.prompt('请填写处理原因（写入审计）', title, {
      inputValidator: (v: string) => (v && v.trim().length >= 2) || '至少 2 个字',
      confirmButtonText: '确定',
      cancelButtonText: '取消',
    })
    return value.trim()
  } catch {
    return null
  }
}

async function act(action: 'resume' | 'terminate') {
  if (!detail.value) return
  const reason = await askReason(action === 'resume' ? '恢复执行（以员工身份重新调用业务系统）' : '终止运行')
  if (!reason) return
  acting.value = true
  try {
    const r = await http.post<{ run_status: string }>(
      `/v1/admin/interventions/${detail.value.task_id}/${action}`,
      { reason, version: detail.value.version },
    )
    ElMessage.success(`已处理，运行状态：${statusLabel(r.run_status)}`)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    acting.value = false
    await load()
    if (detail.value) await open(detail.value)
  }
}

onMounted(load)
</script>

<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="上游业务系统暂时故障且发布配置为「转人工」时，运行会挂起在这里。恢复前会重新校验员工会话、运行状态、流程版本与检查点；员工业务确认只能由员工本人完成。"
      style="margin-bottom: 12px"
    />
    <el-form inline>
      <el-form-item label="状态">
        <el-select v-model="filters.status" clearable placeholder="全部" style="width: 140px" @change="load">
          <el-option v-for="(v, k) in TASK_STATUS" :key="k" :label="v.label" :value="k" />
        </el-select>
      </el-form-item>
      <el-form-item label="类型">
        <el-select v-model="filters.kind" clearable placeholder="全部" style="width: 200px" @change="load">
          <el-option v-for="(v, k) in TASK_KIND" :key="k" :label="v" :value="k" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button @click="load">刷新</el-button>
        <el-tag type="warning" style="margin-left: 12px">待处理 {{ pendingCount }}</el-tag>
      </el-form-item>
    </el-form>

    <el-result v-if="loadError" icon="error" :title="loadError" />
    <el-table v-else v-loading="loading" :data="items" empty-text="暂无数据" @row-click="open" style="cursor: pointer">
      <el-table-column label="任务" prop="task_id" min-width="200" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="TASK_STATUS[row.status]?.type">{{ TASK_STATUS[row.status]?.label || row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="120">
        <template #default="{ row }">{{ row.kind === 'admin' ? '管理员介入' : '员工确认' }}</template>
      </el-table-column>
      <el-table-column label="员工" width="110">
        <template #default="{ row }">{{ row.run?.oa || '—' }}</template>
      </el-table-column>
      <el-table-column label="原因" prop="reason" min-width="240" show-overflow-tooltip />
      <el-table-column label="创建" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="过期" width="170">
        <template #default="{ row }">{{ formatTime(row.expire_at) }}</template>
      </el-table-column>
      <el-table-column label="处理人 / 结果" width="160">
        <template #default="{ row }">{{ row.handled_by || '—' }}<template v-if="row.result"> · {{ row.result }}</template></template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-if="total > 20"
      v-model:current-page="page"
      layout="total, prev, pager, next"
      :total="total"
      :page-size="20"
      style="margin-top: 12px"
      @current-change="load"
    />

    <el-drawer v-model="drawer" title="介入任务" size="560px">
      <el-skeleton v-if="!detail" :rows="6" />
      <template v-else>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="任务">{{ detail.task_id }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ TASK_KIND[detail.kind] }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="TASK_STATUS[detail.status]?.type">{{ TASK_STATUS[detail.status]?.label }}</el-tag>
            <span class="muted">（版本 {{ detail.version }}）</span>
          </el-descriptions-item>
          <el-descriptions-item label="原因">{{ detail.reason }}</el-descriptions-item>
          <el-descriptions-item label="挂起节点">{{ detail.node_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="过期时间">{{ formatTime(detail.expire_at) }}</el-descriptions-item>
          <el-descriptions-item label="运行">
            <template v-if="detail.run">
              <el-link type="primary" @click="router.push(`/runs/${detail.run.run_id}`)">{{ detail.run.run_id }}</el-link>
              <el-tag size="small" :type="statusType(detail.run.run_status)" style="margin-left: 6px">
                {{ statusLabel(detail.run.run_status) }}
              </el-tag>
              <div class="muted">员工 {{ detail.run.oa }} · {{ detail.run.workflow_id }} v{{ detail.run.workflow_version }}</div>
            </template>
            <span v-else>—</span>
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.handled_by" label="处理">
            {{ detail.handled_by }} · {{ formatTime(detail.handled_at) }} · {{ detail.result || '—' }}
            <div v-if="detail.handle_note" class="muted">{{ detail.handle_note }}</div>
          </el-descriptions-item>
        </el-descriptions>

        <el-alert
          v-if="detail.resumable.ok"
          type="success"
          :closable="false"
          show-icon
          title="可恢复：员工会话有效、运行在等待人工、流程版本一致、检查点中有中断点"
          style="margin-top: 12px"
        />
        <el-alert v-else type="warning" :closable="false" show-icon title="不可恢复" style="margin-top: 12px">
          <div v-for="r in detail.resumable.reasons" :key="r">· {{ r }}</div>
        </el-alert>

        <div style="margin-top: 16px; display: flex; gap: 8px">
          <el-button type="primary" :disabled="!detail.resumable.ok" :loading="acting" @click="act('resume')">
            恢复执行
          </el-button>
          <el-button type="danger" plain :disabled="!detail.terminable.ok" :loading="acting" @click="act('terminate')">
            终止运行
          </el-button>
        </div>
        <p class="muted" style="margin-top: 8px">
          恢复 = 以员工本人的身份重新调用一次业务系统；终止 = 运行标记为失败（HUMAN_TERMINATED），员工页面显示“请稍后重新提问”。
        </p>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.muted {
  color: var(--tech-text-2);
  font-size: 12px;
  margin-left: 4px;
}
</style>
