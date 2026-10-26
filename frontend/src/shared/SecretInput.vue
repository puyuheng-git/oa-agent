<script setup lang="ts">
// 密钥只写：展示后端掩码，留空表示不修改
defineProps<{ modelValue: string; display?: string; isSet?: boolean; clearable?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [string]; clear: [] }>()
</script>

<template>
  <div class="secret-input">
    <el-input
      :model-value="modelValue"
      type="password"
      show-password
      autocomplete="new-password"
      :placeholder="isSet ? `${display}（留空不修改）` : '未设置'"
      @update:model-value="(v: string) => emit('update:modelValue', v)"
    />
    <el-button v-if="clearable && isSet" link type="danger" @click="emit('clear')">清除</el-button>
  </div>
</template>

<style scoped>
.secret-input {
  display: flex;
  gap: 8px;
  width: 100%;
}
</style>
