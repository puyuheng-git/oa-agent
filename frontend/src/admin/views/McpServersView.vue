<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errorMessage, http } from '@/shared/http'
import { formatTime } from '@/shared/format'
import AbilityHelpBanner from '../components/AbilityHelpBanner.vue'
import { emptyMcpForm, mcpFormFromItem, mcpPayload, type McpServerForm, type McpServerItem } from '../mcpForm'

interface ProbeResult { ok: boolean; count: number; error: string | null; [k: string]: unknown }

const items = ref<McpServerItem[]>([])
const loading = ref(false)
const loadError = ref('')
const busy = ref<Record<string, 'test' | 'sync' | undefined>>({})
const lastProbe = ref<{ name: string; kind: 'test' | 'sync'; result: ProbeResult } | null>(null)

const TRANSPORT_LABEL: Record<string, string> = { stdio: 'stdio（本地进程）', sse: 'SSE（远程）', http: 'HTTP（远程）' }

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    items.value = (await http.get<{ items: McpServerItem[] }>('/v1/admin/mcp-servers')).items
  } catch (e) {
    loadError.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

function syncText(row: McpServerItem): { label: string; type: 'success' | 'danger' | 'info' } {
  if (row.last_sync_result === 'ok') return { label: '同步成功', type: 'success' }
  if (row.last_sync_result === 'error') return { label: '同步失败', type: 'danger' }
  return { label: row.last_sync_result || '未同步', type: 'info' }
}

function target(row: McpServerItem): string {
  return row.transport === 'stdio' ? [row.command, ...(row.args || [])].filter(Boolean).join(' ') : row.url || ''
}

// ---- 新建 / 编辑 ----
const editor = ref(false)
const editing = ref(false)
const saving = ref(false)
const form = ref<McpServerForm>(emptyMcpForm())
const current = ref<McpServerItem | null>(null)

function create() {
  editing.value = false
  current.value = null
  form.value = emptyMcpForm()
  editor.value = true
}

function edit(row: McpServerItem) {
  editing.value = true
  current.value = row
  form.value = mcpFormFromItem(row)
  editor.value = true
}

async function save() {
  let body: Record<string, unknown>
  try {
    body = mcpPayload(form.value)
  } catch (e) {
    ElMessage.warning((e as Error).message)
    return
  }
  saving.value = true
  try {
    if (editing.value) await http.put(`/v1/admin/mcp-servers/${form.value.name}`, body)
    else await http.post('/v1/admin/mcp-servers', body)
    ElMessage.success('已保存')
    editor.value = false
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    saving.value = false
  }
}

async function toggle(row: McpServerItem) {
  const enable = !row.enabled
  try {
    await ElMessageBox.confirm(
      enable ? `启用 ${row.name}？启用后同步得到的 Tool 才可被调用（Tool 仍需单独启用并绑定 Skill）。` : `停用 ${row.name}？其下 Tool 将立即不可调用。`,
      enable ? '启用 MCP 连接' : '停用 MCP 连接',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    // 不带 headers / env：沿用已有密钥
    await http.put(`/v1/admin/mcp-servers/${row.name}`, {
      ...mcpPayload({ ...mcpFormFromItem(row), enabled: enable }),
    })
    ElMessage.success(enable ? '已启用' : '已停用')
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
  await load()
}

async function probe(row: McpServerItem, kind: 'test' | 'sync') {
  busy.value = { ...busy.value, [row.name]: kind }
  try {
    const result = await http.post<ProbeResult>(`/v1/admin/mcp-servers/${row.name}/${kind}`)
    lastProbe.value = { name: row.name, kind, result }
    if (result.ok) ElMessage.success(kind === 'test' ? `连接成功，发现 ${result.count} 个 Tool` : `已同步 ${result.count} 个 Tool`)
    else ElMessage.error(result.error || (kind === 'test' ? '连接失败' : '同步失败'))
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    busy.value = { ...busy.value, [row.name]: undefined }
  }
  if (kind === 'sync') await load()
}

async function remove(row: McpServerItem) {
  try {
    await ElMessageBox.confirm(`删除 MCP 连接 ${row.name}？其密钥会一并删除；仍有 Tool 来自该连接时会被拒绝。`, '删除', { type: 'warning' })
  } catch {
    return
  }
  try {
    await http.del(`/v1/admin/mcp-servers/${row.name}`)
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
  await load()
}

function reportEntries(r: ProbeResult): [string, string][] {
  return Object.entries(r)
    .filter(([k, v]) => !['ok', 'count', 'error'].includes(k) && v !== null && v !== undefined)
    .map(([k, v]) => [k, Array.isArray(v) ? (v.length ? v.join('、') : '无') : String(v)])
}

onMounted(load)
</script>

<template>
  <div>
    <AbilityHelpBanner focus="mcp" />
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="MCP 连接只负责接入外部工具服务。「同步 Tools」把对方的工具列表写成 Tool（新增默认停用）；之后到 Tool 管理启用，并在 Skill 中绑定，员工才能在对话中使用。远程地址必须是 https 且命中「系统接入 → 连接配置」中的 MCP 地址白名单。"
      style="margin-bottom: 12px"
    />
    <div style="margin-bottom: 12px">
      <el-button type="primary" @click="create">新建 MCP 连接</el-button>
      <el-button @click="load">刷新</el-button>
    </div>

    <el-alert
      v-if="lastProbe"
      :type="lastProbe.result.ok ? 'success' : 'error'"
      closable
      style="margin-bottom: 12px"
      @close="lastProbe = null"
    >
      <template #title>
        {{ lastProbe.name }} · {{ lastProbe.kind === 'test' ? '测试连接' : '同步 Tools' }}：{{ lastProbe.result.ok ? '成功' : '失败' }}
      </template>
      <div v-if="lastProbe.result.ok">发现 {{ lastProbe.result.count }} 个 Tool</div>
      <div v-else>{{ lastProbe.result.error || '未知错误' }}</div>
      <div v-for="[k, v] in reportEntries(lastProbe.result)" :key="k">{{ k }}：{{ v }}</div>
    </el-alert>

    <el-result v-if="loadError" icon="error" :title="loadError" />
    <el-table v-else v-loading="loading" :data="items" empty-text="暂无数据">
      <el-table-column label="连接" min-width="260">
        <template #default="{ row }">
          <b>{{ row.name }}</b>
          <span v-if="row.display_name && row.display_name !== row.name" class="muted">{{ row.display_name }}</span>
          <div class="muted"><code>{{ target(row) || '—' }}</code></div>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="150">
        <template #default="{ row }">{{ TRANSPORT_LABEL[row.transport] || row.transport }}</template>
      </el-table-column>
      <el-table-column label="Tool 前缀" width="110">
        <template #default="{ row }">{{ row.tool_prefix || '—' }}</template>
      </el-table-column>
      <el-table-column label="密钥" min-width="170">
        <template #default="{ row }">
          <div v-if="row.transport !== 'stdio'" class="muted">请求头：{{ row.headers_set.display }}</div>
          <div v-else class="muted">环境变量：{{ row.env_set.display }}</div>
        </template>
      </el-table-column>
      <el-table-column label="启用" width="80">
        <template #default="{ row }">
          <el-switch :model-value="row.enabled" @click="toggle(row)" />
        </template>
      </el-table-column>
      <el-table-column label="最近同步" min-width="220">
        <template #default="{ row }">
          <el-tag size="small" :type="syncText(row).type">{{ syncText(row).label }}</el-tag>
          <span class="muted">{{ formatTime(row.last_sync_at) }}</span>
          <el-tooltip v-if="row.last_sync_error" :content="row.last_sync_error">
            <span class="err">查看错误</span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="290" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" :loading="busy[row.name] === 'test'" :disabled="!!busy[row.name]" @click="probe(row, 'test')">测试连接</el-button>
          <el-button link type="primary" :loading="busy[row.name] === 'sync'" :disabled="!!busy[row.name]" @click="probe(row, 'sync')">同步 Tools</el-button>
          <el-button link type="primary" @click="edit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="editor" :title="editing ? `编辑 MCP 连接：${form.name}` : '新建 MCP 连接'" width="720px" :close-on-click-modal="false">
      <el-form label-width="120px">
        <el-form-item label="连接名" required>
          <el-input v-model="form.name" :disabled="editing" placeholder="小写字母、数字、下划线、连字符，字母开头，创建后不可改" />
        </el-form-item>
        <el-form-item label="显示名称">
          <el-input v-model="form.display_name" maxlength="128" placeholder="留空则同连接名" />
        </el-form-item>
        <el-form-item label="连接类型" required>
          <el-radio-group v-model="form.transport">
            <el-radio-button value="http">HTTP（远程）</el-radio-button>
            <el-radio-button value="sse">SSE（远程）</el-radio-button>
            <el-radio-button value="stdio">stdio（本地进程）</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <template v-if="form.transport === 'stdio'">
          <el-form-item label="command" required>
            <el-input v-model="form.command" placeholder="可执行文件名或路径，如 npx（不能含空格与 shell 字符）" />
          </el-form-item>
          <el-form-item label="args">
            <el-input v-model="form.argsText" type="textarea" :rows="3" placeholder="每行一个参数，如：&#10;-y&#10;@modelcontextprotocol/server-everything" />
          </el-form-item>
          <el-form-item label="环境变量">
            <el-input
              v-model="form.envText"
              type="textarea"
              :rows="3"
              :disabled="form.clearEnv"
              :placeholder="editing && current?.env_set.is_set ? `${current.env_set.display}（留空 = 不修改；填写则整体替换）` : '每行 KEY=value，留空表示不设置'"
            />
            <el-checkbox v-if="editing && current?.env_set.is_set" v-model="form.clearEnv">清除已设置的环境变量</el-checkbox>
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="url" required>
            <el-input v-model="form.url" placeholder="https://mcp.example.com/mcp（须在 MCP 地址白名单内）" />
          </el-form-item>
          <el-form-item label="请求头">
            <el-input
              v-model="form.headersText"
              type="textarea"
              :rows="3"
              :disabled="form.clearHeaders"
              :placeholder="editing && current?.headers_set.is_set ? `${current.headers_set.display}（留空 = 不修改；填写则整体替换）` : '每行 Name: value，如 Authorization: Bearer xxx，留空表示不设置'"
            />
            <el-checkbox v-if="editing && current?.headers_set.is_set" v-model="form.clearHeaders">清除已设置的请求头</el-checkbox>
          </el-form-item>
        </template>

        <el-form-item label="Tool 前缀">
          <el-input v-model="form.tool_prefix" maxlength="32" style="width: 240px" placeholder="可选，小写字母/数字/下划线" />
          <span class="hint">同步出的 Tool 名会加此前缀，避免与其他连接重名。</span>
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="form.timeout_seconds" :min="1" :max="300" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
          <span class="hint">新建默认停用；测试、同步可在停用状态下进行。</span>
        </el-form-item>
        <div class="hint" style="margin-left: 120px">密钥只写不读：保存后只显示「已设置 · ****」，不会回显明文。</div>
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
  margin-left: 4px;
}
.err {
  color: var(--tech-danger);
  font-size: 12px;
  margin-left: 6px;
  cursor: help;
}
code {
  font-size: 12px;
  word-break: break-all;
}
.hint {
  color: var(--tech-text-2);
  font-size: 12px;
  margin-left: 8px;
  line-height: 1.6;
}
</style>
