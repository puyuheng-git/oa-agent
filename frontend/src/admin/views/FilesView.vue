<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ApiError, errorMessage } from '@/shared/http'
import { formatTime } from '@/shared/format'
import { NO_DATA } from '../runs'
import {
  conversationLink,
  downloadPath,
  exportOriginLabel,
  listExportFiles,
  type ExportFileItem,
  type ExportFileOrigin,
} from '../files'

const router = useRouter()
const filters = reactive<{ oa: string; thread_id: string; filename: string; origin: ExportFileOrigin | ''; page: number }>({
  oa: '',
  thread_id: '',
  filename: '',
  origin: '',
  page: 1,
})
const rows = ref<ExportFileItem[]>([])
const total = ref(0)
const loading = ref(false)
const PAGE_SIZE = 20

async function load() {
  loading.value = true
  try {
    const data = await listExportFiles({
      oa: filters.oa,
      thread_id: filters.thread_id,
      filename: filters.filename,
      origin: filters.origin || undefined,
      page: filters.page,
      page_size: PAGE_SIZE,
    })
    rows.value = data.items
    total.value = data.total
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    loading.value = false
  }
}

function search() {
  filters.page = 1
  load()
}

function openConversation(row: ExportFileItem) {
  const link = conversationLink(row.thread_id)
  if (link) router.push(link)
}

async function downloadFile(row: ExportFileItem) {
  try {
    const resp = await fetch(downloadPath(row.file_id), { credentials: 'same-origin' })
    if (!resp.ok) {
      const body = await resp.json().catch(() => null)
      const err = body?.error
      throw new ApiError(resp.status, err?.code ?? 'HTTP_ERROR', err?.message ?? `下载失败（HTTP ${resp.status}）`)
    }
    const blob = await resp.blob()
    const name =
      /filename\*=UTF-8''([^;]+)/.exec(resp.headers.get('Content-Disposition') ?? '')?.[1] ??
      /filename="([^"]+)"/.exec(resp.headers.get('Content-Disposition') ?? '')?.[1] ??
      row.filename
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = decodeURIComponent(name)
    a.click()
    URL.revokeObjectURL(a.href)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="查看列表与下载均记入审计；无权限会提示「无权限」。"
      style="margin-bottom: 12px"
    />
    <el-form inline @submit.prevent="search">
      <el-form-item label="员工 OA">
        <el-input v-model="filters.oa" clearable style="width: 140px" />
      </el-form-item>
      <el-form-item label="thread_id">
        <el-input v-model="filters.thread_id" clearable style="width: 220px" />
      </el-form-item>
      <el-form-item label="文件名">
        <el-input v-model="filters.filename" clearable placeholder="包含" style="width: 180px" />
      </el-form-item>
      <el-form-item label="来源">
        <el-select v-model="filters.origin" clearable placeholder="全部" style="width: 140px">
          <el-option label="全部" value="" />
          <el-option label="用户上传" value="upload" />
          <el-option label="助手导出" value="export" />
        </el-select>
      </el-form-item>
      <el-button type="primary" native-type="submit">查询</el-button>
    </el-form>

    <el-table v-loading="loading" :data="rows" :empty-text="NO_DATA">
      <el-table-column label="创建时间" width="180">
        <template #default="{ row }">{{ row.created_at ? formatTime(row.created_at) : NO_DATA }}</template>
      </el-table-column>
      <el-table-column prop="filename" label="文件名" min-width="220" show-overflow-tooltip />
      <el-table-column label="来源" width="110">
        <template #default="{ row }">{{ exportOriginLabel(row.origin) }}</template>
      </el-table-column>
      <el-table-column prop="oa" label="员工 OA" width="120" />
      <el-table-column label="thread_id" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <span :title="row.thread_id ? undefined : '暂无关联会话'">{{ row.thread_id || '暂无关联会话' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="大小" width="110">
        <template #default="{ row }">{{ row.size_bytes != null ? `${row.size_bytes} B` : NO_DATA }}</template>
      </el-table-column>
      <el-table-column label="存储" width="90">
        <template #default="{ row }">
          {{ row.storage === 'oss' ? 'OSS' : row.storage === 'local' ? '本地' : row.storage || NO_DATA }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link @click="downloadFile(row)">下载</el-button>
          <el-button type="primary" link :disabled="!conversationLink(row.thread_id)" @click="openConversation(row)">
            查看对话
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="filters.page"
      :total="total"
      :page-size="PAGE_SIZE"
      layout="total, prev, pager, next"
      style="margin-top: 12px"
      @current-change="load"
    />
  </el-card>
</template>
