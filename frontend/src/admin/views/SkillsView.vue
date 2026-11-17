<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errorMessage, http } from '@/shared/http'
import { formatTime } from '@/shared/format'
import { syncTag, type SkillItem, type ToolItem } from '../ops'
import { emptySkillForm, skillPayload, type SkillForm } from '../catalogForm'
import AbilityHelpBanner from '../components/AbilityHelpBanner.vue'

interface PackItem {
  id: number
  name: string
  display_name: string
  description: string
  kind: string
  source: string
  source_url: string
  enabled: boolean
  invoke_count: number
  version_no: number
  updated_at?: string
}

interface MarketSubmission {
  listing_id: number
  id: number
  name: string
  display_name: string
  description: string
  publisher_oa: string
  market_status: string
  market_description?: string
  model_review_status?: string
  model_review_summary?: string
  model_review_recommend?: string
  admin_note?: string
  skill_md_preview?: string
  updated_at?: string
}

const mainTab = ref<'catalog' | 'packs' | 'market'>('catalog')

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

const packs = ref<PackItem[]>([])
const packsLoading = ref(false)
const importing = ref(false)
const importOpen = ref(false)
const importUrl = ref('https://github.com/anthropics/skills')
const importPaths = ref('skills/xlsx\nskills/pdf\nskills/docx\nskills/pptx')
const importReason = ref('导入官方 Office Skills')

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

async function loadPacks() {
  packsLoading.value = true
  try {
    packs.value = (await http.get<{ items: PackItem[] }>('/v1/admin/skill-packs')).items
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    packsLoading.value = false
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

async function removeSkill(skill: SkillItem) {
  let reason = ''
  try {
    reason = (
      await ElMessageBox.prompt('请填写原因（写入审计）', `删除 Skill：${skill.name}`, {
        inputValidator: (v: string) => (v && v.trim().length >= 2) || '至少 2 个字',
      })
    ).value.trim()
  } catch {
    return
  }
  try {
    await ElMessageBox.confirm(`确定删除「${skill.display_name}」？此操作不可恢复。`, '删除 Skill', { type: 'warning' })
  } catch {
    return
  }
  try {
    await http.del(`/v1/admin/skills/${skill.name}`, { reason })
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

const packEditor = ref(false)
const packEditing = ref<PackItem | null>(null)
const packMd = ref('')
const packReason = ref('')
const packSaving = ref(false)

async function editPack(row: PackItem) {
  try {
    const r = await http.get<{ skill_md: string }>(`/v1/admin/skill-packs/${row.id}`)
    packEditing.value = row
    packMd.value = r.skill_md
    packReason.value = ''
    packEditor.value = true
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function savePack() {
  if (!packEditing.value) return
  if (packReason.value.trim().length < 2) {
    ElMessage.warning('请填写变更原因')
    return
  }
  if (packMd.value.trim().length < 10) {
    ElMessage.warning('请填写完整的 SKILL.md')
    return
  }
  packSaving.value = true
  try {
    await http.put(`/v1/admin/skill-packs/${packEditing.value.id}`, {
      skill_md: packMd.value,
      reason: packReason.value.trim(),
    })
    ElMessage.success('已保存')
    packEditor.value = false
    await loadPacks()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    packSaving.value = false
  }
}

async function removePack(row: PackItem) {
  let reason = ''
  try {
    reason = (
      await ElMessageBox.prompt('请填写原因（写入审计）', `删除 Skill 包：${row.name}`, {
        inputValidator: (v: string) => (v && v.trim().length >= 2) || '至少 2 个字',
      })
    ).value.trim()
  } catch {
    return
  }
  try {
    await ElMessageBox.confirm(`确定删除包「${row.display_name}」？`, '删除', { type: 'warning' })
  } catch {
    return
  }
  try {
    await http.del(`/v1/admin/skill-packs/${row.id}`, { reason })
    ElMessage.success('已删除')
    await loadPacks()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function doImport() {
  if (importReason.value.trim().length < 2) {
    ElMessage.warning('请填写变更原因')
    return
  }
  importing.value = true
  try {
    const paths = importPaths.value
      .split(/\n|,/)
      .map((s) => s.trim())
      .filter(Boolean)
    const r = await http.post<{
      ok_count: number
      fail_count: number
      files: { dir: string; ok: boolean; errors: string[]; name?: string }[]
    }>('/v1/admin/skill-packs/import/github', {
      url: importUrl.value.trim(),
      paths,
      reason: importReason.value.trim(),
    })
    if (r.fail_count) {
      ElMessage.warning(`成功 ${r.ok_count}，失败 ${r.fail_count}`)
    } else {
      ElMessage.success(`已导入 ${r.ok_count} 个 Skill 包`)
    }
    importOpen.value = false
    await loadPacks()
  } catch (e) {
    ElMessage.error(`GitHub 导入失败：${errorMessage(e)}（若因网络问题，请稍后重试或配置代理）`)
  } finally {
    importing.value = false
  }
}

async function toggleDefault(row: PackItem) {
  let reason = ''
  try {
    reason = (
      await ElMessageBox.prompt('请填写原因（写入审计）', row.enabled ? `默认停用 ${row.name}` : `默认启用 ${row.name}`, {
        inputValidator: (v: string) => (v && v.trim().length >= 2) || '至少 2 个字',
      })
    ).value.trim()
  } catch {
    return
  }
  try {
    await http.post(`/v1/admin/skill-packs/${row.id}/enable-default`, {
      enabled_default: !row.enabled,
      reason,
    })
    ElMessage.success('已更新')
    await loadPacks()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function viewMd(row: PackItem) {
  try {
    const r = await http.get<{ skill_md: string }>(`/v1/admin/skill-packs/${row.id}`)
    await ElMessageBox.alert(r.skill_md.slice(0, 4000) + (r.skill_md.length > 4000 ? '\n…' : ''), row.name, {
      customClass: 'skill-md-box',
    })
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

const marketItems = ref<MarketSubmission[]>([])
const marketLoading = ref(false)
const marketFilter = ref('pending_admin')

async function loadMarket() {
  marketLoading.value = true
  try {
    marketItems.value = (
      await http.get<{ items: MarketSubmission[] }>(
        `/v1/admin/skill-packs/market?status=${encodeURIComponent(marketFilter.value)}`,
      )
    ).items
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    marketLoading.value = false
  }
}

async function approveMarket(row: MarketSubmission) {
  let reason = '审核通过'
  try {
    reason = (
      await ElMessageBox.prompt('审核备注（可选，写入审计）', `通过：${row.display_name}`, {
        inputValue: '审核通过上架',
        inputValidator: (v: string) => (v && v.trim().length >= 2) || '至少 2 个字',
      })
    ).value.trim()
  } catch {
    return
  }
  try {
    await http.post(`/v1/admin/skill-packs/market/${row.listing_id}/approve`, {
      reason,
      note: reason,
    })
    ElMessage.success('已通过并上架到 Skill 市场')
    await loadMarket()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function rejectMarket(row: MarketSubmission) {
  let reason = ''
  try {
    reason = (
      await ElMessageBox.prompt('请填写驳回原因（将展示给推送者）', `驳回：${row.display_name}`, {
        inputValidator: (v: string) => (v && v.trim().length >= 2) || '至少 2 个字',
      })
    ).value.trim()
  } catch {
    return
  }
  try {
    await http.post(`/v1/admin/skill-packs/market/${row.listing_id}/reject`, {
      reason,
      note: reason,
    })
    ElMessage.success('已驳回')
    await loadMarket()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

function recommendType(v?: string) {
  if (v === 'approve') return 'success'
  if (v === 'reject') return 'danger'
  return 'warning'
}

watch(mainTab, (t) => {
  if (t === 'catalog') void load()
  else if (t === 'packs') void loadPacks()
  else void loadMarket()
})

onMounted(() => {
  void load()
})
</script>

<template>
  <div>
    <AbilityHelpBanner focus="skill" />
    <el-tabs v-model="mainTab">
      <el-tab-pane label="目录 Skill" name="catalog">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="目录 Skill = 说明 + 填参指引 + 示例问题 + 可用 Tool。对话时模型据此选 Tool 并填参；示例显示在员工欢迎页。"
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
          <el-table-column label="" width="140" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="edit(row)">编辑</el-button>
              <el-button link type="danger" @click="removeSkill(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="Skill 包" name="packs" lazy>
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="后台添加的 Skill 包为系统包：默认全员可用并注入系统提示词；不会出现在对话页「我的 Skill」。可从 GitHub 导入。"
          style="margin-bottom: 12px"
        />
        <div style="margin-bottom: 12px">
          <el-button type="primary" @click="importOpen = true">从 GitHub 导入</el-button>
          <el-button @click="loadPacks">刷新</el-button>
        </div>
        <el-table v-loading="packsLoading" :data="packs" empty-text="暂无 Skill 包">
          <el-table-column label="包" min-width="260">
            <template #default="{ row }">
              <b>{{ row.display_name }}</b>
              <div class="muted">{{ row.name }} · {{ row.kind }} · {{ row.source }} · v{{ row.version_no }}</div>
              <div class="muted">{{ row.description }}</div>
              <div v-if="row.source_url" class="muted">{{ row.source_url }}</div>
            </template>
          </el-table-column>
          <el-table-column label="调用" width="90" align="center" prop="invoke_count" />
          <el-table-column label="默认启用" width="100">
            <template #default="{ row }">
              <el-switch :model-value="row.enabled" @click="toggleDefault(row)" />
            </template>
          </el-table-column>
          <el-table-column label="更新" width="160">
            <template #default="{ row }">
              <span class="muted">{{ formatTime(row.updated_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="" width="180" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="editPack(row)">编辑</el-button>
              <el-button link @click="viewMd(row)">查看</el-button>
              <el-button link type="danger" @click="removePack(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="市场审核" name="market" lazy>
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="员工推送的 Skill 经模型审查后进入本列表；通过后才会出现在对话页 Skill 市场。"
          style="margin-bottom: 12px"
        />
        <div style="margin-bottom: 12px; display: flex; gap: 8px; align-items: center">
          <el-select v-model="marketFilter" style="width: 160px" @change="loadMarket">
            <el-option label="待审核" value="pending_admin" />
            <el-option label="已上架" value="published" />
            <el-option label="已驳回" value="rejected" />
            <el-option label="全部" value="all" />
          </el-select>
          <el-button @click="loadMarket">刷新</el-button>
        </div>
        <el-table v-loading="marketLoading" :data="marketItems" empty-text="暂无投稿">
          <el-table-column label="Skill" min-width="220">
            <template #default="{ row }">
              <b>{{ row.display_name }}</b>
              <div class="muted">{{ row.name }} · 推送者 {{ row.publisher_oa }}</div>
              <div class="muted">{{ row.market_description || row.description }}</div>
            </template>
          </el-table-column>
          <el-table-column label="模型审查" min-width="280">
            <template #default="{ row }">
              <el-tag size="small" :type="recommendType(row.model_review_recommend)">
                {{ row.model_review_recommend || row.model_review_status || '—' }}
              </el-tag>
              <div class="muted" style="white-space: pre-wrap; margin-top: 6px">
                {{ row.model_review_summary || '暂无审查意见' }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.market_status === 'published' ? 'success' : row.market_status === 'rejected' ? 'danger' : 'warning'"
              >
                {{ row.market_status }}
              </el-tag>
              <div v-if="row.admin_note" class="muted">{{ row.admin_note }}</div>
            </template>
          </el-table-column>
          <el-table-column label="" width="160" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.market_status === 'pending_admin' || row.market_status === 'rejected'"
                link
                type="success"
                @click="approveMarket(row)"
              >
                通过
              </el-button>
              <el-button
                v-if="row.market_status === 'pending_admin'"
                link
                type="danger"
                @click="rejectMarket(row)"
              >
                驳回
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="packEditor"
      :title="packEditing ? `编辑 Skill 包：${packEditing.name}` : '编辑 Skill 包'"
      width="760px"
      :close-on-click-modal="false"
      :teleported="true"
      append-to="body"
      align-center
    >
      <el-form label-width="90px">
        <el-form-item label="SKILL.md" required>
          <el-input v-model="packMd" type="textarea" :rows="16" />
        </el-form-item>
        <el-form-item label="变更原因" required>
          <el-input v-model="packReason" type="textarea" :rows="2" maxlength="200" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="packEditor = false">取消</el-button>
        <el-button type="primary" :loading="packSaving" @click="savePack">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editor" :title="editing ? `编辑 Skill：${editing}` : '新建 Skill'" width="760px" :close-on-click-modal="false" :teleported="true" append-to="body" align-center>
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

    <el-dialog v-model="importOpen" title="从 GitHub 导入 Skill 包" width="640px" :close-on-click-modal="false" :teleported="true" append-to="body">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="需服务器能访问 GitHub。失败时会自动重试数次；仍失败请检查网络/代理后重试。"
        style="margin-bottom: 12px"
      />
      <el-form label-width="100px">
        <el-form-item label="仓库 URL" required>
          <el-input v-model="importUrl" placeholder="https://github.com/anthropics/skills" />
        </el-form-item>
        <el-form-item label="子目录">
          <el-input
            v-model="importPaths"
            type="textarea"
            :rows="4"
            placeholder="每行一个，如 skills/xlsx；留空则扫描整个仓库"
          />
        </el-form-item>
        <el-form-item label="变更原因" required>
          <el-input v-model="importReason" maxlength="200" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="importOpen = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="doImport">导入</el-button>
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
