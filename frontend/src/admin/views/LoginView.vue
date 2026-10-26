<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { login } from '../auth'
import { errorMessage } from '@/shared/http'
import CoreStage from '../console/CoreStage.vue'
import type { CoreMode } from '../console/NeuralCore'
import { coreMood, fetchReady, type Mood } from '../console/telemetry'

const form = reactive({ username: '', password: '' })
const busy = ref(false)
const mode = ref<CoreMode>('dormant')
const mood = ref<Mood>('unknown')
const route = useRoute()
const router = useRouter()

onMounted(async () => {
  try {
    mood.value = coreMood({ ready: await fetchReady(), readyFailed: false, stats: null, pending: null }).mood
  } catch {
    mood.value = 'bad'
  }
})

async function submit() {
  busy.value = true
  try {
    await login(form.username, form.password)
    mode.value = 'awaken'
    setTimeout(() => router.replace((route.query.redirect as string) || '/'), 900)
  } catch (e) {
    ElMessage.error(errorMessage(e))
    busy.value = false
  }
}
</script>

<template>
  <div class="login">
    <CoreStage :mood="mood" :mode="mode" />
    <div class="login-card tech-corners" :class="{ leaving: mode === 'awaken' }">
      <div class="scan" />
      <div class="head">
        <div class="eyebrow">OA·AGENT // NEURAL CONSOLE</div>
        <h1>管理控制台</h1>
        <p>身份验证后唤醒神经核心</p>
      </div>
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名">
          <el-input v-model="form.username" :prefix-icon="User" size="large" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            :prefix-icon="Lock"
            size="large"
            type="password"
            show-password
            autocomplete="current-password"
          />
        </el-form-item>
        <el-button type="primary" native-type="submit" size="large" :loading="busy" class="go">
          {{ busy ? '正在唤醒…' : '登录' }}
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.login {
  position: fixed;
  inset: 0;
}
.login-card {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 380px;
  transform: translate(-50%, -50%);
  padding: 30px 32px 28px;
  border-radius: 12px;
  border: 1px solid var(--tech-border-strong);
  background: linear-gradient(160deg, rgba(14, 26, 48, 0.72), rgba(6, 10, 20, 0.78));
  backdrop-filter: blur(18px) saturate(1.3);
  box-shadow: 0 0 60px rgba(34, 211, 238, 0.15), inset 0 0 40px rgba(34, 211, 238, 0.05);
  overflow: hidden;
  animation: card-in 0.9s cubic-bezier(0.16, 1, 0.3, 1);
  transition: opacity 0.6s, transform 0.8s cubic-bezier(0.7, 0, 0.84, 0), filter 0.6s;
}
.login-card.leaving {
  opacity: 0;
  transform: translate(-50%, -50%) scale(0.85);
  filter: blur(8px) brightness(2);
}
.scan {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 80px;
  pointer-events: none;
  background: linear-gradient(180deg, transparent, rgba(34, 211, 238, 0.12) 90%, rgba(34, 211, 238, 0.55));
  animation: scan 4.5s ease-in-out infinite;
}
.head {
  margin-bottom: 18px;
}
.eyebrow {
  font-family: var(--tech-mono);
  font-size: 10px;
  letter-spacing: 3px;
  color: var(--tech-cyan);
  text-shadow: 0 0 8px var(--tech-cyan);
}
h1 {
  margin: 8px 0 4px;
  font-size: 26px;
  letter-spacing: 4px;
  background: linear-gradient(90deg, #e2e8f0, #22d3ee 60%, #818cf8);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.head p {
  margin: 0;
  font-size: 12px;
  color: var(--tech-text-3);
  letter-spacing: 1px;
}
.go {
  width: 100%;
  margin-top: 8px;
  letter-spacing: 4px;
}
@media (min-width: 1100px) {
  .login-card {
    left: auto;
    right: 9vw;
    transform: translate(0, -50%);
  }
  .login-card.leaving {
    transform: translate(0, -50%) scale(0.85);
  }
}
@keyframes card-in {
  from {
    opacity: 0;
    filter: blur(6px);
  }
}
@keyframes scan {
  0% {
    transform: translateY(-80px);
  }
  70%,
  100% {
    transform: translateY(520px);
  }
}
@media (prefers-reduced-motion: reduce) {
  .scan {
    animation: none;
    display: none;
  }
}
</style>
