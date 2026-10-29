<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errorMessage, http } from '@/shared/http'
import { formatTime } from '@/shared/format'
import { syncTag, type SkillItem, type ToolItem } from '../ops'
import { emptySkillForm, skillPayload, type SkillForm } from '../catalogForm'
import AbilityHelpBanner from '../components/AbilityHelpBanner.vue'

const items = ref<SkillItem[]>([])
const loading = ref(false)
const loadError = ref('')
const syncing = ref(false)

const editor = ref(false)
const editing = ref<string | null>(null)
const form = ref<SkillForm>(emptySkillForm())
const editReason = ref('')
const saving = ref(false)
const toolOptions = ref<ToolItem[]>([])

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    items.value = (await http.get<{ items: SkillItem[] }>('/v1/admin/skills')).items
  } catch (e) {
    loadError.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

async function sync() {
  syncing.value = true
  try {
    const r = await http.post<{ files: { file: string; ok: boolean; errors: string[] }[] }>('/v1/admin/skills/sync')
    const failed = r.files.filter((f) => !f.ok)
    if (failed.length) ElMessage.warning(`有 ${failed.length} 个文件解析失败：${failed.map((f) => f.errors.join('；')).join(' / ')}`)
    else ElMessage.success('导入完成')
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    syncing.value = false
  }
}

async function loadTools() {
  try {
    toolOptions.value = (await http.get<{ items: ToolItem[] }>('/v1/admin/tools')).items
  } catch (e) {
    toolOptions.value = []
    ElMessage.warning(`读取 Tool 列表失败：${errorMessage(e)}`)
  }
}

async function create() {
  editing.value = null
  form.value = emptySkillForm()
  editReason.value = ''
  editor.value = true
  await loadTools()
}

async function edit(skill: SkillItem) {
  editing.value = skill.name
  form.value = {
    name: skill.name,
    display_name: skill.display_name,
    description: skill.description || '',
    instructions: skill.instructions || '',
    examplesText: (skill.examples || []).join('\n'),
    tools: skill.tools.map((t) => t.name),
  }
  editReason.value = ''
  editor.value = true
  await loadTools()
}

async function save() {
  if (editReason.value.trim().length < 2) {
    ElMessage.warning('请填写变更原因（至少 2 个字，写入审计）')
    return
  }
  saving.value = true
  try {
    const body = { ...skillPayload(form.value), reason: editReason.value.trim() }
    const r = editing.value
      ? await http.put<SkillItem>(`/v1/admin/skills/${editing.value}`, body)
      : await http.post<SkillItem>('/v1/admin/skills', body)
    if (r.validation_errors.length) ElMessage.warning(`已保存，但暂不可用：${r.validation_errors.join('；')}`)
    else ElMessage.success(`已保存 · v${r.current_version_no}`)
    editor.value = false
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    saving.value = false
  }
}

async function toggle(skill: SkillItem) {
  const enable = !skill.enabled
  let reason = ''
  try {
    reason = (
      await ElMessageBox.prompt('请填写原因（写入审计）', enable ? `启用 ${skill.name}` : `停用 ${skill.name}（对话将不再使用它）`, {
        inputValidator: (v: string) => (v && v.trim().length >= 2) || '至少 2 个字',
      })
    ).value.trim()
  } catch {
    return
  }
  try {
    await http.post(`/v1/admin/skills/${skill.name}/${enable ? 'enable' : 'disable'}`, { reason })
    ElMessage.success(enable ? '已启用' : '已停用')
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
  await load()
}

onMounted(load)
</script>

<template>
  <div>
    <AbilityHelpBanner focus="skill" />
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="Skill = 一组面向员工的能力（说明 + 填参指引 + 示例问题 + 可用 Tool）。对话时模型根据所有可用 Skill 的说明选择 Tool 并填参；示例问题显示在员工欢迎页。依赖 Tool 未注册或 Skill 被停用时，对话不会使用它。"
      style="margin-bottom: 12px"
    />
    <div style="margin-bottom: 12px">
      <el-button type="primary" @click="create">新建 Skill</el-button>
      <el-tooltip content="批量导入仓库 skills/*.yaml（同名 Skill 会被文件内容覆盖为新版本）">
        <el-button :loading="syncing" @click="sync">从文件导入</el-button>
      </el-tooltip>
      <el-button @click="load">刷新</el-button>
    </div>
    <el-result v-if="loadError" icon="error" :title="loadError" />
    <el-table v-else v-loading="loading" :data="items" empty-text="暂无数据">
      <el-table-column label="Skill" min-width="240">
        <template #default="{ row }">
          <b>{{ row.display_name }}</b>
          <div class="muted">{{ row.name }} · v{{ row.current_version_no ?? '—' }} · {{ row.source_file === 'admin' ? '管理后台' : row.source_file }}</div>
          <div class="muted">{{ row.description }}</div>
          <div v-if="row.examples?.length" class="muted">示例：{{ row.examples.join('；') }}</div>
        </template>
      </el-table-column>
      <el-table-column label="校验" width="120">
        <template #default="{ row }">
          <el-tooltip v-if="row.validation_errors.length" :content="row.validation_errors.join('；')">
            <el-tag type="danger">不可用</el-tag>
          </el-tooltip>
          <el-tag v-else :type="row.validation_status === 'valid' ? 'success' : 'info'">
            {{ row.validation_status === 'valid' ? '通过' : '未校验' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="启用" width="90">
        <template #default="{ row }">
          <el-switch :model-value="row.enabled" @click="toggle(row)" />
        </template>
      </el-table-column>
      <el-table-column label="可用 Tool" min-width="300">
        <template #default="{ row }">
          <div v-for="t in row.tools" :key="t.name">
            <el-tag size="small" :type="t.registered ? 'success' : 'danger'">{{ t.registered ? '已注册' : '未注册' }}</el-tag>
            {{ t.name }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="最近变更" width="220">
        <template #default="{ row }">
          <el-tag size="small" :type="syncTag(row.last_sync_result).type">{{ syncTag(row.last_sync_result).label }}</el-tag>
          <span class="muted">{{ formatTime(row.last_sync_at) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="" width="80" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="edit(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="editor" :title="editing ? `编辑 Skill：${editing}` : '新建 Skill'" width="760px" :close-on-click-modal="false">
      <el-form label-width="110px">
        <el-form-item label="Skill 名" required>
          <el-input v-model="form.name" :disabled="!!editing" placeholder="如 leave_query（小写字母、数字、下划线，创建后不可改）" />
        </el-form-item>
        <el-form-item label="显示名称" required>
          <el-input v-model="form.display_name" maxlength="128" placeholder="员工看到的功能名，如：请假查询" />
        </el-form-item>
        <el-form-item label="说明" required>
          <el-input v-model="form.description" type="textarea" :rows="2" maxlength="2000" show-word-limit
            placeholder="这个能力解决什么问题；模型据此判断何时使用" />
        </el-form-item>
        <el-form-item label="填参指引">
          <el-input v-model="form.instructions" type="textarea" :rows="4" maxlength="2000" show-word-limit
            placeholder="告诉模型如何把员工的话转换成参数，如：「上个月」换算为具体日期；年假对应 leave_type=1" />
        </el-form-item>
        <el-form-item label="示例问题">
          <el-input v-model="form.examplesText" type="textarea" :rows="3" placeholder="每行一条，最多 10 条；显示在员工欢迎页" />
        </el-form-item>
        <el-form-item label="可用 Tool" required>
          <el-select v-model="form.tools" multiple filterable style="width: 100%" placeholder="选择该 Skill 可调用的 Tool">
            <el-option v-for="t in toolOptions" :key="t.name" :value="t.name" :label="`${t.name}（${t.summary}）`">
              <span>{{ t.name }}</span>
              <span class="muted"> {{ t.summary }}<template v-if="!t.registered"> · 未注册</template></span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="变更原因" required>
          <el-input v-model="editReason" maxlength="200" placeholder="写入审计，至少 2 个字" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editor = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.muted {
  color: var(--tech-text-2);
  font-size: 12px;
}
</style>
