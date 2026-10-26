<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errorMessage, http } from '@/shared/http'
import { formatTime } from '@/shared/format'

const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const roles = ref<any[]>([])

const dialog = ref(false)
const editing = ref<any | null>(null)
const form = reactive({ username: '', display_name: '', password: '', status: 'active', role_ids: [] as number[] })

async function load() {
  try {
    const data = await http.get<any>('/v1/admin/accounts', { page: page.value, page_size: 20 })
    rows.value = data.items
    total.value = data.total
    roles.value = (await http.get<any>('/v1/admin/roles')).items
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

function open(u?: any) {
  editing.value = u ?? null
  Object.assign(form, u
    ? { username: u.username, display_name: u.display_name, password: '', status: u.status, role_ids: u.roles.map((r: any) => r.id) }
    : { username: '', display_name: '', password: '', status: 'active', role_ids: [] })
  dialog.value = true
}

async function save() {
  try {
    if (editing.value) {
      await http.put(`/v1/admin/accounts/${editing.value.id}`,
        { display_name: form.display_name, status: form.status, role_ids: form.role_ids })
    } else {
      await http.post('/v1/admin/accounts',
        { username: form.username, display_name: form.display_name, password: form.password, role_ids: form.role_ids })
    }
    dialog.value = false
    ElMessage.success('已保存')
    load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function resetPassword(u: any) {
  try {
    const { value } = await ElMessageBox.prompt(`为「${u.username}」设置新密码`, '重置密码', {
      inputType: 'password',
      inputPlaceholder: '至少 12 位，含 3 类字符',
    })
    await http.post(`/v1/admin/accounts/${u.id}/reset-password`, { password: value })
    ElMessage.success('密码已重置')
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(errorMessage(e))
  }
}

async function unlock(u: any) {
  try {
    await http.post(`/v1/admin/accounts/${u.id}/unlock`)
    ElMessage.success('已解锁')
    load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

onMounted(load)
</script>

<template>
  <el-card>
    <div class="page-toolbar">
      <el-text type="info">管理后台本地账号，与 OA 账号体系无关。登录失败 5 次锁定 15 分钟。</el-text>
      <el-button type="primary" @click="open()">新增账号</el-button>
    </div>
    <el-table :data="rows" empty-text="暂无数据">
      <el-table-column prop="username" label="用户名" width="140" />
      <el-table-column prop="display_name" label="显示名" width="140" />
      <el-table-column label="角色"><template #default="{ row }">{{ row.roles.map((r: any) => r.name).join('、') || '—' }}</template></el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'">{{ row.status === 'active' ? '启用' : '停用' }}</el-tag>
          <el-tag v-if="row.locked" type="danger" style="margin-left: 4px">锁定</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最近登录" width="180"><template #default="{ row }">{{ formatTime(row.last_login_at) }}</template></el-table-column>
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button link @click="open(row)">编辑</el-button>
          <el-button link @click="resetPassword(row)">重置密码</el-button>
          <el-button v-if="row.locked" link type="warning" @click="unlock(row)">解锁</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="total, prev, pager, next"
      style="margin-top: 12px" @current-change="load" />
  </el-card>

  <el-dialog v-model="dialog" :title="editing ? '编辑账号' : '新增账号'" width="520px">
    <el-form label-width="90px">
      <el-form-item label="用户名"><el-input v-model="form.username" :disabled="!!editing" /></el-form-item>
      <el-form-item label="显示名"><el-input v-model="form.display_name" /></el-form-item>
      <el-form-item v-if="!editing" label="初始密码">
        <el-input v-model="form.password" type="password" show-password autocomplete="new-password" />
      </el-form-item>
      <el-form-item v-if="editing" label="状态">
        <el-radio-group v-model="form.status">
          <el-radio value="active">启用</el-radio>
          <el-radio value="disabled">停用</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="角色">
        <el-checkbox-group v-model="form.role_ids">
          <el-checkbox v-for="r in roles" :key="r.id" :value="r.id">{{ r.name }}</el-checkbox>
        </el-checkbox-group>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialog = false">取消</el-button>
      <el-button type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>
