import { reactive, shallowRef } from 'vue'
import type { CoreMode } from './NeuralCore'
import type { NodeLayout, OrbitId, Projected } from './orbits'
import type { Mood, Telemetry } from './telemetry'

/** 卫星节点展示数据（由 Layout 写入，App 渲染） */
export interface BrainNodeView {
  key: string
  title: string
  code: string
  motif: string
  group: OrbitId
  telemetry?: Telemetry
  count?: number
  active?: boolean
  dimmed?: boolean
}

export const brainStage = reactive({
  mood: 'unknown' as Mood,
  mode: 'dormant' as CoreMode,
  activity: 0,
  paused: false,
  layouts: [] as NodeLayout[],
  views: {} as Record<string, BrainNodeView>,
})

type StageHandle = { nodePosition: (key: string) => Projected | null }
export const brainStageHandle = shallowRef<StageHandle | null>(null)

type NodeClick = (key: string) => void
let nodeClick: NodeClick | null = null

export function setBrainNodeClick(fn: NodeClick | null) {
  nodeClick = fn
}

export function emitBrainNodeClick(key: string) {
  nodeClick?.(key)
}

/** 回到登录态：清卫星、待命模式（大脑实例不销毁） */
export function resetBrainForLogin() {
  brainStage.mode = 'dormant'
  brainStage.paused = false
  brainStage.activity = 0
  brainStage.layouts = []
  brainStage.views = {}
  setBrainNodeClick(null)
}
