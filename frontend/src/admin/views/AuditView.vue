<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { errorMessage, http } from '@/shared/http'
import { formatTime } from '@/shared/format'

const rows = ref<any[]>([])
const total = ref(0)
const filters = reactive({ action: '', actor_id: '', result: '', page: 1 })

async function load() {
  try {
    const data = await http.get<any>('/v1/admin/audit', { ...filters, page_size: 20 })
    rows.value = data.items
    total.value = data.total
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

function search() {
  filters.page = 1
  load()
}

onMounted(load)
</script>

<template>
  <el-card>
    <el-form inline @submit.prevent="search">
      <el-form-item label="操作"><el-input v-model="filters.action" placeholder="前缀，如 setting." clearable /></el-form-item>
      <el-form-item label="操作人"><el-input v-model="filters.actor_id" clearable /></el-form-item>
      <el-form-item label="结果">
        <el-select v-model="filters.result" clearable style="width: 120px">
          <el-option label="成功" value="success" />
          <el-option label="失败" value="failure" />
          <el-option label="拒绝" value="denied" />
        </el-select>
      </el-form-item>
      <el-button type="primary" native-type="submit">查询</el-button>
    </el-form>
    <el-table :data="rows" empty-text="暂无数据">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div style="padding: 0 24px; white-space: pre-wrap; word-break: break-all">
            <p><b>变更前：</b>{{ row.before_summary || '—' }}</p>
            <p><b>变更后：</b>{{ row.after_summary || '—' }}</p>
            <p><b>原因：</b>{{ row.reason || '—' }}</p>
            <p><b>请求：</b>{{ row.request_id }} · {{ row.source_ip }}</p>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="时间" width="180"><template #default="{ row }">{{ formatTime(row.occurred_at) }}</template></el-table-column>
      <el-table-column label="操作人" width="160"><template #default="{ row }">{{ row.actor_type }} / {{ row.actor_id }}</template></el-table-column>
      <el-table-column prop="action" label="操作" width="200" />
      <el-table-column label="对象"><template #default="{ row }">{{ row.resource_type }} {{ row.resource_id }}</template></el-table-column>
      <el-table-column label="结果" width="90">
        <template #default="{ row }">
          <el-tag :type="row.result === 'success' ? 'success' : 'danger'">{{ row.result }}</el-tag>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination v-model:current-page="filters.page" :total="total" :page-size="20" layout="total, prev, pager, next"
      style="margin-top: 12px" @current-change="load" />
  </el-card>
</template>
