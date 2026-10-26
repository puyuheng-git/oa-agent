import { describe, expect, it } from 'vitest'
import type { Component } from 'vue'
import { arcPositions, groupOf, groupTelemetry, visibleGroups, type MenuGroup, type MenuLeaf } from './menuGroups'

const icon = {} as Component
const groups: MenuGroup[] = [
  { id: 'monitor', title: '运行监控', code: 'MONITOR', icon, orbit: 'monitor' },
  { id: 'handoff', title: '介入中心', code: 'HANDOFF', icon, orbit: 'monitor' },
  { id: 'security', title: '权限与审计', code: 'SECURITY', icon, orbit: 'system' },
]
const leaves: MenuLeaf[] = [
  { path: '/runs', title: '运行记录', code: 'RUNS', perm: 'ops.run.view', icon, group: 'monitor' },
  { path: '/conversations', title: '对话记录', code: 'DIALOGS', perm: 'ops.run.view_sensitive', icon, group: 'monitor' },
  { path: '/interventions', title: '介入中心', code: 'HANDOFF', perm: 'ops.intervention.handle', icon, group: 'handoff' },
  { path: '/accounts', title: '账号', code: 'ACCOUNTS', perm: 'sys.account.manage', icon, group: 'security' },
  { path: '/audit', title: '审计日志', code: 'AUDIT', perm: 'ops.audit.view', icon, group: 'security' },
]

describe('visibleGroups', () => {
  it('按权限过滤子项，没有可见子项的组隐藏，保持定义顺序', () => {
    const perms = new Set(['ops.run.view', 'ops.audit.view'])
    const result = visibleGroups(groups, leaves, (p) => perms.has(p))
    expect(result.map((g) => g.id)).toEqual(['monitor', 'security'])
    expect(result[0].items.map((i) => i.path)).toEqual(['/runs'])
    expect(result[1].items.map((i) => i.path)).toEqual(['/audit'])
  })
})

describe('groupOf', () => {
  it('按子项路径找到所属组', () => {
    const all = visibleGroups(groups, leaves, () => true)
    expect(groupOf(all, '/conversations')?.id).toBe('monitor')
    expect(groupOf(all, '/status')).toBeUndefined()
  })
})

describe('groupTelemetry', () => {
  const all = visibleGroups(groups, leaves, () => true)
  const monitor = all[0]

  it('子项都没有遥测时返回 undefined', () => {
    expect(groupTelemetry(monitor, {})).toBeUndefined()
  })

  it('有告警时优先显示告警项', () => {
    const t = groupTelemetry(monitor, {
      '/runs': { text: '疑似卡住 1', tone: 'warn' },
      '/conversations': { text: 'x', tone: 'normal' },
    })
    expect(t).toEqual({ text: '疑似卡住 1', tone: 'warn' })
  })

  it('无告警时拼接子项遥测', () => {
    const t = groupTelemetry(monitor, {
      '/runs': { text: '运行中 2', tone: 'normal' },
      '/conversations': { text: '今日 5', tone: 'normal' },
    })
    expect(t).toEqual({ text: '运行中 2 · 今日 5', tone: 'normal' })
  })
})

describe('arcPositions', () => {
  it('子节点到原点距离等于半径，并朝向屏幕中心对称展开', () => {
    const origin = { x: 200, y: 300 }
    const center = { x: 800, y: 300 }
    const pts = arcPositions(origin, center, 3, 120, 0.8)
    expect(pts).toHaveLength(3)
    for (const p of pts) expect(Math.hypot(p.x - origin.x, p.y - origin.y)).toBeCloseTo(120, 6)
    expect(pts[1].x).toBeCloseTo(320, 6)
    expect(pts[1].y).toBeCloseTo(300, 6)
    expect(pts[0].y + pts[2].y).toBeCloseTo(600, 6)
  })

  it('原点与中心重合时向上展开', () => {
    const [p] = arcPositions({ x: 100, y: 100 }, { x: 100, y: 100 }, 1, 50, 0.8)
    expect(p.x).toBeCloseTo(100, 6)
    expect(p.y).toBeCloseTo(50, 6)
  })

  it('给定边界时把节点限制在视口内', () => {
    const pts = arcPositions({ x: 10, y: 10 }, { x: 10, y: 10 }, 1, 100, 0.8, { width: 500, height: 500, margin: 40 })
    expect(pts[0].y).toBe(40)
    expect(pts[0].x).toBe(40)
  })
})
