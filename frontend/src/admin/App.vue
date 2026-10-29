<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import CoreStage from './console/CoreStage.vue'
import SatelliteNode from './console/SatelliteNode.vue'
import {
  brainStage,
  brainStageHandle,
  emitBrainNodeClick,
} from './console/brainStage'

const stage = ref<InstanceType<typeof CoreStage>>()

function syncHandle() {
  brainStageHandle.value = stage.value
    ? { nodePosition: (key) => stage.value?.nodePosition(key) ?? null }
    : null
}

onMounted(syncHandle)
watch(stage, syncHandle, { flush: 'post' })
onBeforeUnmount(() => {
  brainStageHandle.value = null
})
</script>

<template>
  <div class="shell">
    <CoreStage
      ref="stage"
      :mood="brainStage.mood"
      :mode="brainStage.mode"
      :nodes="brainStage.layouts"
      :paused="brainStage.paused"
      :activity="brainStage.activity"
    >
      <template #node="{ node }">
        <SatelliteNode
          v-if="brainStage.views[node.key]"
          :title="brainStage.views[node.key].title"
          :code="brainStage.views[node.key].code"
          :motif="brainStage.views[node.key].motif"
          :group="brainStage.views[node.key].group"
          :telemetry="brainStage.views[node.key].telemetry"
          :count="brainStage.views[node.key].count"
          :active="brainStage.views[node.key].active"
          :dimmed="brainStage.views[node.key].dimmed"
          @click="emitBrainNodeClick(node.key)"
        />
      </template>
    </CoreStage>
    <router-view />
  </div>
</template>

<style scoped>
.shell {
  position: relative;
  min-height: 100%;
}
</style>
