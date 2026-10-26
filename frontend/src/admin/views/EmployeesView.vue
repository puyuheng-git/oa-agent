<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { errorMessage } from '@/shared/http'
import { formatTime } from '@/shared/format'
import { NO_DATA } from '../runs'
import { listEmployees, type EmployeeListItem } from '../employees'

const router = useRouter()
const filters = reactive({ q: '', page: 1 })
const rows = ref<EmployeeListItem[]>([])
const total = ref(0)
const loading = ref(false)
const PAGE_SIZE = 20

async function load() {
  loading.value = true
  try {
    const data = await listEmployees({ q: filters.q, page: filters.page, page_size: PAGE_SIZE })
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

function openRow(row: EmployeeListItem) {
  router.push(`/employees/${encodeURIComponent(row.oa)}`)
}

onMounted(load)
</script>

<template>
  <el-card>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="按员工 OA 汇总本租户内的会话、长期记忆与 Skill 可见性；敏感原文需单独权限，访问会记入审计。"
      style="margin-bottom: 12px"
    />
    <el-form inline @submit.prevent="search">
      <el-form-item label="员工 OA">
        <el-input v-model="filters.q" clearable placeholder="前缀搜索" style="width: 160px" />
      </el-form-item>
      <el-button type="primary" native-type="submit">查询</el-button>
    </el-form>

    <el-table v-loading="loading" :data="rows" :empty-text="NO_DATA" row-class-name="clickable" @row-click="openRow">
      <el-table-column prop="oa" label="员工 OA" min-width="140" />
      <el-table-column label="最近活跃" width="180">
        <template #default="{ row }">{{ row.last_active_at ? formatTime(row.last_active_at) : NO_DATA }}</template>
      </el-table-column>
      <el-table-column prop="thread_count" label="会话数" width="90" />
      <el-table-column prop="memory_active_count" label="记忆（active）" width="120" />
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

<style scoped>
:deep(.clickable) {
  cursor: pointer;
}
</style>
