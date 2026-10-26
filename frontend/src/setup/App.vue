<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { errorMessage, http } from '@/shared/http'
import TestResult from '@/shared/TestResult.vue'

const step = ref(0)
const busy = ref(false)
const token = ref('')
const db = reactive({ host: '127.0.0.1', port: 3306, user: 'root', password: '', database: 'agent_ops' })
const admin = reactive({ username: 'admin', display_name: '超级管理员', password: '', confirm: '' })
const dbResult = ref<Record<string, any> | null>(null)

async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
  busy.value = true
  try {
    return await fn()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    busy.value = false
  }
}

async function verifyToken() {
  const ok = await run(() => http.post('/v1/setup/verify-token', { token: token.value }))
  if (ok) step.value = 1
}

async function testDb() {
  dbResult.value = (await run(() => http.post<Record<string, any>>('/v1/setup/test-db', { token: token.value, db }))) ?? null
}

async function install() {
  if (admin.password !== admin.confirm) {
    ElMessage.error('两次输入的密码不一致')
    return
  }
  const { confirm: _c, ...adminBody } = admin
  const ok = await run(() => http.post('/v1/setup/install', { token: token.value, db, admin: adminBody }))
  if (ok) step.value = 3
}
</script>

<template>
  <div class="wrap">
    <el-card class="card">
      <template #header><b>OA Agent 安装向导</b></template>
      <el-steps :active="step" finish-status="success" align-center style="margin-bottom: 24px">
        <el-step title="安装令牌" />
        <el-step title="数据库" />
        <el-step title="超级管理员" />
        <el-step title="完成" />
      </el-steps>

      <el-form v-if="step === 0" label-width="110px" @submit.prevent="verifyToken">
        <el-alert type="info" :closable="false" style="margin-bottom: 16px"
          title="安装令牌打印在服务启动日志中，也保存在服务器 data/setup.token。" />
        <el-form-item label="安装令牌">
          <el-input v-model="token" autocomplete="off" />
        </el-form-item>
        <el-button type="primary" :loading="busy" :disabled="!token" @click="verifyToken">下一步</el-button>
      </el-form>

      <el-form v-else-if="step === 1" label-width="110px">
        <el-alert type="info" :closable="false" style="margin-bottom: 16px"
          title="运营库 agent_ops（独立 MySQL 库）。库不存在时安装过程会自动创建（需账号有建库权限）。" />
        <el-form-item label="主机"><el-input v-model="db.host" /></el-form-item>
        <el-form-item label="端口"><el-input-number v-model="db.port" :min="1" :max="65535" /></el-form-item>
        <el-form-item label="用户名"><el-input v-model="db.user" /></el-form-item>
        <el-form-item label="密码">
          <el-input v-model="db.password" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-form-item label="数据库名"><el-input v-model="db.database" /></el-form-item>
        <el-form-item label="连接测试">
          <TestResult :result="dbResult" />
          <div v-if="dbResult?.ok" style="width: 100%">
            <el-text>目标库{{ dbResult.database_exists ? '已存在，将执行迁移' : '不存在，将自动创建' }}</el-text>
          </div>
        </el-form-item>
        <el-button :loading="busy" @click="testDb">测试连接</el-button>
        <el-button type="primary" :disabled="!dbResult?.ok" @click="step = 2">下一步</el-button>
      </el-form>

      <el-form v-else-if="step === 2" label-width="110px">
        <el-form-item label="用户名"><el-input v-model="admin.username" /></el-form-item>
        <el-form-item label="显示名"><el-input v-model="admin.display_name" /></el-form-item>
        <el-form-item label="密码">
          <el-input v-model="admin.password" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input v-model="admin.confirm" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-text type="info" size="small">至少 12 位，含大写、小写、数字、符号中的至少 3 类，且不包含用户名。</el-text>
        <div style="margin-top: 16px">
          <el-button @click="step = 1">上一步</el-button>
          <el-button type="primary" :loading="busy" @click="install">建库并安装</el-button>
        </div>
      </el-form>

      <el-result v-else icon="success" title="安装完成" sub-title="安装向导已永久关闭。请备份服务器上的 data/master.key。">
        <template #extra>
          <el-button type="primary" tag="a" href="/admin/">进入管理后台</el-button>
        </template>
      </el-result>
    </el-card>
  </div>
</template>

<style>
body {
  margin: 0;
  background: #f3f5f8;
}
.wrap {
  display: flex;
  justify-content: center;
  padding: 48px 16px;
}
.card {
  width: 640px;
}
</style>
