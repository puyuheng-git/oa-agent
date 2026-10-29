<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { can } from '../auth'
import { errorMessage, http } from '@/shared/http'
import SecretInput from '@/shared/SecretInput.vue'
import TestResult from '@/shared/TestResult.vue'

interface FieldDef {
  key: string; label: string; kind: string; help: string; default?: any
  min?: number; max?: number; unit?: string; options?: { value: string; label: string }[]
}
interface Group {
  group: string; label: string; apply_mode: string; testable: boolean; description?: string
  fields: FieldDef[]; values: Record<string, any>
}

const groups = ref<Group[]>([])
const redisStatus = ref<Record<string, any>>({})
const wecomStatus = ref<Record<string, any>>({})

async function refreshWecom() {
  try {
    wecomStatus.value = (await http.get<{ wecom_status: any }>('/v1/admin/settings')).wecom_status ?? {}
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}
const forms = reactive<Record<string, Record<string, any>>>({})
const testResults = reactive<Record<string, any>>({})
const active = ref('redis')
const editable = can('sys.setting.edit')

const dbView = ref<Record<string, any> | null>(null)
const dbForm = reactive({ host: '', port: 3306, user: '', password: '', database: '' })
const dbTest = ref<Record<string, any> | null>(null)

function fillForm(g: Group) {
  forms[g.group] = Object.fromEntries(
    g.fields.map((f) => {
      const v = g.values[f.key]
      if (f.kind === 'secret') return [f.key, '']
      if (f.kind === 'list') return [f.key, (v ?? []).join(', ')]
      if (f.kind === 'upstreams') return [f.key, (v ?? []).map((u: Record<string, string>) => ({ ...u }))]
      return [f.key, v ?? '']
    }),
  )
}

async function load() {
  try {
    const data = await http.get<{ groups: Group[]; redis_status: any; wecom_status: any }>('/v1/admin/settings')
    groups.value = data.groups
    redisStatus.value = data.redis_status
    wecomStatus.value = data.wecom_status ?? {}
    data.groups.forEach(fillForm)
    const db = await http.get<any>('/v1/admin/settings/database')
    dbView.value = db
    Object.assign(dbForm, db.values, { password: '' })
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

function payload(g: Group, clear: string[] = []) {
  return { values: { ...forms[g.group] }, clear_secrets: clear }
}

async function save(g: Group, clear: string[] = []) {
  try {
    const r = await http.put<any>(`/v1/admin/settings/${g.group}`, payload(g, clear))
    const idx = groups.value.findIndex((x) => x.group === g.group)
    groups.value[idx] = r.group
    fillForm(r.group)
    redisStatus.value = r.redis_status
    ElMessage.success(r.changed.length ? `已保存：${r.changed.join('、')}` : '没有变更')
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function test(g: Group) {
  try {
    testResults[g.group] = await http.post(`/v1/admin/settings/${g.group}/test`, payload(g))
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function testDb() {
  try {
    dbTest.value = await http.post('/v1/admin/settings/database/test', dbForm)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function saveDb() {
  try {
    await http.put('/v1/admin/settings/database', dbForm)
    ElMessage.warning('已写入 bootstrap.json，重启服务后生效')
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

onMounted(load)
</script>

<template>
  <el-card>
    <el-tabs v-model="active">
      <el-tab-pane v-for="g in groups" :key="g.group" :label="g.label" :name="g.group">
        <el-alert :closable="false" type="info" :title="`生效方式：${g.apply_mode}`" style="margin-bottom: 16px">
          <div v-if="g.description">{{ g.description }}</div>
        </el-alert>
        <el-alert v-if="g.group === 'redis'" :closable="false" style="margin-bottom: 16px"
          :type="redisStatus.status === 'ok' ? 'success' : redisStatus.status === 'error' ? 'error' : 'warning'"
          :title="`当前状态：${redisStatus.status}（会话存储：${redisStatus.backend === 'redis' ? 'Redis' : '进程内存'}）${redisStatus.error ? '：' + redisStatus.error : ''}`" />
        <el-alert v-if="g.group === 'wecom'" :closable="false" style="margin-bottom: 16px"
          :type="wecomStatus.status === '已连接' ? 'success' : wecomStatus.status === '已断开' ? 'error' : 'warning'">
          <template #title>
            长连接状态：{{ wecomStatus.status || '未知' }}{{ wecomStatus.error ? '：' + wecomStatus.error : '' }}
            <el-button link type="primary" style="margin-left: 8px" @click="refreshWecom">刷新</el-button>
          </template>
          <div>只支持单聊；员工身份由 OA 按企业微信绑定关系解析（签发入口 mint 需支持 wework_user_id）。同一机器人只能有一个连接，请勿多实例部署。</div>
        </el-alert>
        <el-form v-if="forms[g.group]" label-width="260px" style="max-width: 900px" :disabled="!editable">
          <el-form-item v-for="f in g.fields" :key="f.key" :label="f.label">
            <SecretInput v-if="f.kind === 'secret'" v-model="forms[g.group][f.key]"
              :display="g.values[f.key].display" :is-set="g.values[f.key].is_set" clearable
              @clear="save(g, [f.key])" />
            <template v-else-if="f.kind === 'int'">
              <el-input-number v-model="forms[g.group][f.key]" :min="f.min ?? 0" :max="f.max" :step="1"
                step-strictly />
              <el-text type="info" size="small" style="margin-left: 8px">
                {{ f.unit }}<template v-if="f.min !== undefined && f.max !== undefined">（{{ f.min }}～{{ f.max }}，默认 {{ f.default }}）</template>
              </el-text>
            </template>
            <el-switch v-else-if="f.kind === 'bool'" v-model="forms[g.group][f.key]" />
            <el-select v-else-if="f.kind === 'enum'" v-model="forms[g.group][f.key]" style="width: 360px">
              <el-option v-for="o in f.options" :key="o.value" :label="o.label" :value="o.value" />
            </el-select>
            <div v-else-if="f.kind === 'text'" style="width: 100%">
              <el-input v-model="forms[g.group][f.key]" type="textarea" :autosize="{ minRows: 1, maxRows: 6 }"
                :maxlength="f.max" show-word-limit :placeholder="String(f.default ?? '')" />
              <el-button v-if="forms[g.group][f.key] !== f.default" link type="primary" size="small"
                @click="forms[g.group][f.key] = f.default">恢复默认</el-button>
            </div>
            <div v-else-if="f.kind === 'upstreams'" style="width: 100%">
              <el-table :data="forms[g.group][f.key]" size="small" border empty-text="未配置（请至少添加一个业务上游）">
                <el-table-column label="标识" width="150">
                  <template #default="{ row }"><el-input v-model="row.key" size="small" placeholder="如 office" /></template>
                </el-table-column>
                <el-table-column label="名称" width="150">
                  <template #default="{ row }"><el-input v-model="row.label" size="small" placeholder="如 办公接口" /></template>
                </el-table-column>
                <el-table-column label="地址" min-width="220">
                  <template #default="{ row }">
                    <el-input v-model="row.base_url" size="small" placeholder="https://api.example.com" />
                  </template>
                </el-table-column>
                <el-table-column label="" width="60">
                  <template #default="{ $index }">
                    <el-button link type="danger" size="small" @click="forms[g.group][f.key].splice($index, 1)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
              <el-button size="small" style="margin-top: 6px"
                @click="forms[g.group][f.key].push({ key: '', label: '', base_url: '' })">添加地址</el-button>
            </div>
            <el-input v-else v-model="forms[g.group][f.key]" />
            <div v-if="f.help || f.kind === 'list'" class="field-help">
              {{ f.help }}<template v-if="f.kind === 'list'">{{ f.help ? '；' : '' }}多个用英文逗号分隔</template>
            </div>
          </el-form-item>
          <el-form-item v-if="g.testable" label="连接测试"><TestResult :result="testResults[g.group] ?? null" /></el-form-item>
          <el-form-item>
            <el-button v-if="g.testable" @click="test(g)">测试连接</el-button>
            <el-button type="primary" @click="save(g)">保存</el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="数据库" name="database">
        <el-alert v-if="dbView?.values.driver === 'sqlite'" :closable="false" type="info" style="margin-bottom: 16px"
          title="当前实例使用 SQLite（仅测试用，数据目录内的本地文件），不能在线切换到 MySQL：数据与管理员账号不会迁移。">
          切换方法：停止服务 → 删除该实例 data 目录下的 bootstrap.json → 重新启动 → 在安装向导（/setup/）中填写 MySQL。
        </el-alert>
        <el-alert v-else :closable="false" type="warning" style="margin-bottom: 16px"
          title="生效方式：测试通过后写入 bootstrap.json，重启服务生效。目标库需已存在且已迁移。" />
        <el-form v-if="dbView" label-width="260px" style="max-width: 820px"
          :disabled="!editable || dbView.values.driver === 'sqlite'">
          <el-form-item label="主机"><el-input v-model="dbForm.host" /></el-form-item>
          <el-form-item label="端口"><el-input-number v-model="dbForm.port" :min="1" :max="65535" /></el-form-item>
          <el-form-item label="用户名"><el-input v-model="dbForm.user" /></el-form-item>
          <el-form-item label="密码">
            <SecretInput v-model="dbForm.password" :display="dbView.password.display" :is-set="dbView.password.is_set" />
          </el-form-item>
          <el-form-item label="数据库名"><el-input v-model="dbForm.database" /></el-form-item>
          <el-form-item label="连接测试"><TestResult :result="dbTest" /></el-form-item>
          <el-form-item>
            <el-button @click="testDb">测试连接</el-button>
            <el-button type="primary" @click="saveDb">保存（重启生效）</el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>
    </el-tabs>
  </el-card>
</template>

<style scoped>
.field-help {
  width: 100%;
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-line;
}
</style>
