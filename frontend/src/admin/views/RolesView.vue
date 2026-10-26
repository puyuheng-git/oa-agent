<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errorMessage, http } from '@/shared/http'

const roles = ref<any[]>([])
const perms = ref<{ code: string; label: string }[]>([])
const dialog = ref(false)
const editing = ref<any | null>(null)
const form = reactive({ code: '', name: '', description: '', perm_codes: [] as string[] })

async function load() {
  try {
    roles.value = (await http.get<any>('/v1/admin/roles')).items
    perms.value = (await http.get<any>('/v1/admin/perms')).items
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

function open(r?: any) {
  editing.value = r ?? null
  Object.assign(form, r
    ? { code: r.code, name: r.name, description: r.description, perm_codes: [...r.perm_codes] }
    : { code: '', name: '', description: '', perm_codes: [] })
  dialog.value = true
}

async function save() {
  try {
    if (editing.value) await http.put(`/v1/admin/roles/${editing.value.id}`, form)
    else await http.post('/v1/admin/roles', form)
    dialog.value = false
    ElMessage.success('已保存')
    load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function remove(r: any) {
  await ElMessageBox.confirm(`删除角色「${r.name}」？`, '确认', { type: 'warning' })
  try {
    await http.del(`/v1/admin/roles/${r.id}`)
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
      <el-text type="info">权限变更立即生效。内置「超级管理员」拥有全部权限点，不可修改。</el-text>
      <el-button type="primary" @click="open()">新增角色</el-button>
    </div>
    <el-table :data="roles" empty-text="暂无数据">
      <el-table-column prop="code" label="编码" width="160" />
      <el-table-column prop="name" label="名称" width="140" />
      <el-table-column label="权限点"><template #default="{ row }">{{ row.perm_codes.join('，') || '—' }}</template></el-table-column>
      <el-table-column prop="user_count" label="账号数" width="80" />
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <template v-if="!row.is_builtin">
            <el-button link @click="open(row)">编辑</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
          <el-tag v-else type="info">内置</el-tag>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-dialog v-model="dialog" :title="editing ? '编辑角色' : '新增角色'" width="620px">
    <el-form label-width="80px">
      <el-form-item label="编码"><el-input v-model="form.code" :disabled="!!editing" placeholder="小写字母开头，如 ops_viewer" /></el-form-item>
      <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
      <el-form-item label="说明"><el-input v-model="form.description" /></el-form-item>
      <el-form-item label="权限点">
        <el-checkbox-group v-model="form.perm_codes">
          <div v-for="p in perms" :key="p.code">
            <el-checkbox :value="p.code">{{ p.label }} <el-text type="info" size="small">{{ p.code }}</el-text></el-checkbox>
          </div>
        </el-checkbox-group>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialog = false">取消</el-button>
      <el-button type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>
