<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errorMessage } from '@/shared/http'
import { disablePack, enablePack, listPacks, type PackItem } from '../packs'

const items = ref<PackItem[]>([])
const loading = ref(false)
const loadError = ref('')
const toggling = ref<string | null>(null)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    items.value = (await listPacks()).items
  } catch (e) {
    loadError.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

async function toggle(row: PackItem) {
  const enable = !row.enabled
  let reason = ''
  try {
    reason = (
      await ElMessageBox.prompt(
        '请填写原因（写入审计）',
        enable ? `启用 ${row.display_name}` : `禁用 ${row.display_name}`,
        { inputValidator: (v: string) => (v && v.trim().length >= 2) || '至少 2 个字' },
      )
    ).value.trim()
  } catch {
    return
  }
  toggling.value = row.id
  try {
    const updated = enable ? await enablePack(row.id, { reason }) : await disablePack(row.id, { reason })
    const idx = items.value.findIndex((p) => p.id === row.id)
    if (idx >= 0) items.value[idx] = updated
    ElMessage.success(enable ? '已启用' : '已禁用')
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    toggling.value = null
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
      title="领域包来自本机 packs 目录；启停写入配置并刷新运行时注册表，不上传 zip。"
      style="margin-bottom: 12px"
    />
    <div style="margin-bottom: 12px">
      <el-button @click="load">刷新</el-button>
    </div>
    <el-result v-if="loadError" icon="error" :title="loadError" />
    <el-table v-else v-loading="loading" :data="items" empty-text="暂无数据">
      <el-table-column prop="id" label="ID" min-width="140" />
      <el-table-column label="显示名" min-width="160">
        <template #default="{ row }">
          <b>{{ row.display_name }}</b>
          <div v-if="row.default_enabled" class="muted">默认启用</div>
        </template>
      </el-table-column>
      <el-table-column prop="version" label="版本" width="100" />
      <el-table-column label="启用" width="90">
        <template #default="{ row }">
          <el-switch
            :model-value="row.enabled"
            :loading="toggling === row.id"
            @click="toggle(row)"
          />
        </template>
      </el-table-column>
      <el-table-column label="Connectors" min-width="180">
        <template #default="{ row }">
          <template v-if="row.connectors?.length">
            <el-tag v-for="c in row.connectors" :key="c" size="small" style="margin: 0 4px 4px 0">{{ c }}</el-tag>
          </template>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="校验" min-width="160">
        <template #default="{ row }">
          <el-tooltip v-if="row.validation_errors.length" :content="row.validation_errors.join('；')">
            <el-tag type="danger">{{ row.validation_errors.length }} 项错误</el-tag>
          </el-tooltip>
          <el-tag v-else type="success">通过</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <el-button
            link
            type="primary"
            :disabled="toggling === row.id"
            @click="toggle(row)"
          >
            {{ row.enabled ? '禁用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
