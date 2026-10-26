<script setup lang="ts">
// 只展示后端真实检测结果；未检测时如实显示
defineProps<{ result: Record<string, any> | null }>()
</script>

<template>
  <el-text v-if="!result" type="info">未检测</el-text>
  <el-alert v-else-if="result.ok" type="success" :closable="false" show-icon>
    <template #title>
      连接成功
      <span v-if="result.latency_ms !== undefined"> · {{ result.latency_ms }} ms</span>
      <span v-if="result.server_version"> · {{ result.server_version }}</span>
      <span v-if="result.model_count !== undefined"> · 可用模型 {{ result.model_count }} 个</span>
      <span v-if="result.usage"> · usage {{ JSON.stringify(result.usage) }}</span>
    </template>
  </el-alert>
  <el-alert v-else type="error" :closable="false" show-icon :title="`连接失败：${result.error}`" />
</template>
