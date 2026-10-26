<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, EffectScatterChart, LineChart, LinesChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'
import { NO_DATA } from '../runs'

echarts.use([
  BarChart,
  EffectScatterChart,
  LineChart,
  LinesChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
])

const props = withDefaults(defineProps<{ option: EChartsCoreOption | null; height?: string }>(), { height: '260px' })
const emit = defineEmits<{ (e: 'chart-click', params: any): void }>()

const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
const resizer = new ResizeObserver(() => chart?.resize())

function render() {
  if (!props.option) {
    chart?.dispose()
    chart = null
    return
  }
  if (!chart && el.value) {
    chart = echarts.init(el.value, undefined, { renderer: 'canvas' })
    chart.on('click', (p) => emit('chart-click', p))
    resizer.observe(el.value)
  }
  chart?.setOption({ backgroundColor: 'transparent', textStyle: { fontFamily: 'inherit' }, ...props.option }, true)
}

watch(() => props.option, () => nextTick(render), { immediate: true })

onBeforeUnmount(() => {
  resizer.disconnect()
  chart?.dispose()
})
</script>

<template>
  <div class="tech-chart" :style="{ height }">
    <div v-show="option" ref="el" class="canvas" />
    <div v-if="!option" class="empty">{{ NO_DATA }}</div>
  </div>
</template>

<style scoped>
.tech-chart {
  position: relative;
  width: 100%;
}
.canvas {
  width: 100%;
  height: 100%;
}
.empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--tech-text-3);
  font-size: 13px;
  letter-spacing: 2px;
}
</style>
