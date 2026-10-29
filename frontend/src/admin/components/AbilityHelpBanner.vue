<script setup lang="ts">
withDefaults(defineProps<{ focus?: 'skill' | 'tool' | 'mcp' }>(), { focus: 'skill' })
</script>

<template>
  <el-alert
    class="ability-help-banner"
    type="info"
    :closable="false"
    show-icon
    style="margin-bottom: 12px"
  >
    <template #title>能力配置说明</template>
    <ul class="ability-help-list">
      <li :class="{ active: focus === 'skill' }">
        <b>Skill</b>：员工能力包。决定员工能用什么、示例问题与可用 Tool，授权在 Skill 上配置。
      </li>
      <li :class="{ active: focus === 'tool' }">
        <b>Tool</b>：原子能力，有三种来源——OA 接口（office）、平台内置（builtin）、外部 MCP（mcp）。
      </li>
      <li :class="{ active: focus === 'mcp' }">
        <b>MCP</b>：外部连接，只负责接入；谁能用、能用哪些，授权在 Skill，而不在 MCP 连接上。
        <template v-if="focus === 'mcp'">用法：新建连接 → 测试连接 → 同步 Tools → 到 Tool 管理启用 → 在 Skill 中绑定。</template>
      </li>
    </ul>
  </el-alert>
</template>

<style scoped>
.ability-help-list { margin: 4px 0 0; padding-left: 18px; line-height: 1.7; }
.ability-help-list li.active { color: var(--el-color-primary); }
</style>
