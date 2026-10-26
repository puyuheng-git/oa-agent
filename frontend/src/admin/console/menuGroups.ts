import type { Component } from 'vue'
import type { OrbitId } from './orbits'
import type { Telemetry } from './telemetry'

export interface MenuLeaf {
  path: string
  title: string
  code: string
  perm: string
  icon: Component
  group: string
}

export interface MenuGroup {
  id: string
  title: string
  code: string
  icon: Component
  orbit: OrbitId
}

export interface VisibleGroup extends MenuGroup {
  items: MenuLeaf[]
}

/** 子项按权限过滤；没有可见子项的组整体隐藏。 */
export function visibleGroups(groups: MenuGroup[], leaves: MenuLeaf[], can: (perm: string) => boolean): VisibleGroup[] {
  return groups
    .map((g) => ({ ...g, items: leaves.filter((l) => l.group === g.id && can(l.perm)) }))
    .filter((g) => g.items.length > 0)
}

export function groupOf(groups: VisibleGroup[], path: string): VisibleGroup | undefined {
  return groups.find((g) => g.items.some((i) => i.path === path))
}

/** 组卫星的遥测：有告警优先显示告警，否则拼接子项遥测。 */
export function groupTelemetry(group: VisibleGroup, tele: Record<string, Telemetry>): Telemetry | undefined {
  const list = group.items.map((i) => tele[i.path]).filter((t): t is Telemetry => !!t)
  if (!list.length) return undefined
  const warn = list.find((t) => t.tone === 'warn')
  if (warn) return warn
  return { text: list.map((t) => t.text).join(' · '), tone: 'normal' }
}

export interface Point {
  x: number
  y: number
}

/** 二级菜单节点：以 origin 为圆心、朝向 center 方向呈弧形展开；spread 为相邻节点夹角（弧度）。 */
export function arcPositions(
  origin: Point,
  center: Point,
  count: number,
  radius: number,
  spread: number,
  bounds?: { width: number; height: number; margin: number },
): Point[] {
  const dx = center.x - origin.x
  const dy = center.y - origin.y
  const base = Math.hypot(dx, dy) < 1e-6 ? -Math.PI / 2 : Math.atan2(dy, dx)
  return Array.from({ length: count }, (_, i) => {
    const a = base + (i - (count - 1) / 2) * spread
    let x = origin.x + radius * Math.cos(a)
    let y = origin.y + radius * Math.sin(a)
    if (bounds) {
      x = Math.min(bounds.width - bounds.margin, Math.max(bounds.margin, x))
      y = Math.min(bounds.height - bounds.margin, Math.max(bounds.margin, y))
    }
    return { x, y }
  })
}
