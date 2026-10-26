<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Coin, Connection, Cpu, DataLine } from '@element-plus/icons-vue'
import { fetchReady, type ReadyInfo } from '../console/telemetry'

const ready = ref<ReadyInfo | null>(null)
const failed = ref(false)
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    ready.value = await fetchReady()
    failed.value = false
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}
onMounted(load)

type Level = 'ok' | 'warn' | 'bad' | 'none'
function level(status: unknown, okValues: string[] = ['ok'], warnValues: string[] = []): Level {
  if (status === undefined || status === null) return 'none'
  if (okValues.includes(String(status))) return 'ok'
  if (warnValues.includes(String(status))) return 'warn'
  return 'bad'
}

const r = computed(() => ready.value as Record<string, any> | null)
const cards = computed(() => {
  const x = r.value
  return [
    { key: 'db', title: '数据库', code: 'DATABASE', icon: Coin, status: x?.database?.status, level: level(x?.database?.status, ['ok'], ['migration_pending']) },
    { key: 'redis', title: 'Redis', code: 'CACHE', icon: Connection, status: x?.redis?.status, level: level(x?.redis?.status) },
    { key: 'llm', title: 'LLM', code: 'MODEL', icon: Cpu, status: x?.llm?.status, level: level(x?.llm?.status, ['已配置（未检测）'], ['未配置', '未检测']) },
    { key: 'obs', title: '运行监控写入', code: 'OBSERVABILITY', icon: DataLine, status: x?.observability?.status, level: level(x?.observability?.status, ['ok'], ['degraded']) },
  ]
})
</script>

<template>
  <div v-loading="loading">
    <div class="page-toolbar">
      <span class="tech-muted">/readyz 实时检测</span>
      <el-button @click="load">重新检测</el-button>
    </div>
    <el-alert v-if="failed" type="error" :closable="false" show-icon title="状态检测失败：无法访问 /readyz" />
    <div v-else class="grid">
      <div v-for="c in cards" :key="c.key" class="cell tech-corners" :class="c.level">
        <div class="cell-head">
          <span class="cell-icon"><el-icon :size="20"><component :is="c.icon" /></el-icon></span>
          <span>
            <b>{{ c.title }}</b>
            <small>{{ c.code }}</small>
          </span>
          <span class="tech-dot" :class="{ ok: c.level === 'ok', warn: c.level === 'warn', bad: c.level === 'bad' }" />
        </div>
        <div class="cell-status tech-num">{{ c.status ?? '未检测' }}</div>
        <div class="cell-detail">
          <template v-if="c.key === 'db'">
            <div v-if="r?.database?.migration">迁移 {{ r.database.migration.current }} / 最新 {{ r.database.migration.head }}</div>
            <div v-if="r?.database?.error" class="err">{{ r.database.error }}</div>
          </template>
          <template v-else-if="c.key === 'redis'">
            <div v-if="r?.redis">当前存储：{{ r.redis.backend === 'redis' ? 'Redis' : '进程内存' }}</div>
            <div v-if="r?.redis?.error" class="err">{{ r.redis.error }}</div>
          </template>
          <template v-else-if="c.key === 'llm'">
            <div v-if="r?.llm?.enabled_providers !== undefined">
              启用提供方 {{ r.llm.enabled_providers }}，启用模型 {{ r.llm.enabled_models }}
            </div>
          </template>
          <template v-else-if="c.key === 'obs'">
            <div v-if="r?.observability?.status === 'degraded'" class="warn-text">
              待补写 {{ r.observability.spool_pending }} 条，写库失败 {{ r.observability.write_failures }} 次，丢弃
              {{ r.observability.dropped }} 条
            </div>
            <div v-if="r?.observability?.last_error" class="err">{{ r.observability.last_error }}</div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}
.cell {
  --c: var(--tech-text-3);
  padding: 18px;
  border-radius: 8px;
  border: 1px solid var(--tech-border);
  background: var(--tech-panel);
  transition: box-shadow 0.25s, border-color 0.25s;
}
.cell.ok {
  --c: var(--tech-success);
}
.cell.warn {
  --c: var(--tech-warning);
}
.cell.bad {
  --c: var(--tech-danger);
}
.cell:hover {
  border-color: color-mix(in srgb, var(--c) 60%, transparent);
  box-shadow: 0 0 24px color-mix(in srgb, var(--c) 25%, transparent);
}
.cell-head {
  display: flex;
  align-items: center;
  gap: 12px;
}
.cell-head > span:nth-child(2) {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.cell-head small {
  font-family: var(--tech-mono);
  font-size: 10px;
  letter-spacing: 2px;
  color: var(--tech-text-3);
}
.cell-icon {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: var(--c);
  background: color-mix(in srgb, var(--c) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--c) 40%, transparent);
}
.cell-status {
  margin: 16px 0 8px;
  font-size: 22px;
  font-weight: 600;
  color: var(--c);
  text-shadow: 0 0 12px color-mix(in srgb, var(--c) 50%, transparent);
}
.cell-detail {
  font-size: 12px;
  color: var(--tech-text-2);
  line-height: 1.7;
}
.err {
  color: var(--tech-danger);
  word-break: break-all;
}
.warn-text {
  color: var(--tech-warning);
}
</style>
