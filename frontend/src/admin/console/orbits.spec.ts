import { describe, expect, it } from 'vitest'
import { ORBITS, layoutNodes, orbitPoint, projectSimple } from './orbits'

describe('orbitPoint', () => {
  it('点到原点距离等于轨道半径', () => {
    for (const orbit of Object.values(ORBITS)) {
      for (const a of [0, 1, 2.5, 4]) {
        const [x, y, z] = orbitPoint(orbit, a)
        expect(Math.hypot(x, y, z)).toBeCloseTo(orbit.radius, 6)
      }
    }
  })

  it('无倾斜时位于水平面', () => {
    const [, y] = orbitPoint({ radius: 3, tiltX: 0, tiltZ: 0, speed: 0 }, 1.2)
    expect(y).toBeCloseTo(0, 9)
  })
})

describe('layoutNodes', () => {
  it('按分组分配轨道，并在同轨道内均匀分布相位', () => {
    const nodes = layoutNodes([
      { key: 'a', group: 'monitor' },
      { key: 'b', group: 'monitor' },
      { key: 'c', group: 'config' },
    ])
    expect(nodes.map((n) => n.orbit)).toEqual(['monitor', 'monitor', 'config'])
    const [a, b] = nodes
    expect(Math.abs(b.phase - a.phase)).toBeCloseTo(Math.PI, 6)
  })
})

describe('默认 5 组布局不拥挤', () => {
  const nodes = layoutNodes([
    { key: 'monitor', group: 'monitor' },
    { key: 'handoff', group: 'monitor' },
    { key: 'ability', group: 'config' },
    { key: 'access', group: 'config' },
    { key: 'security', group: 'system' },
  ])
  const at = (t: number, W: number, H: number) =>
    nodes.map((n) => projectSimple(orbitPoint(ORBITS[n.orbit], n.phase + t * ORBITS[n.orbit].speed), W, H))

  it('1600×900 下任意时刻节点间距 ≥ 150px，且不进入两翼区域', () => {
    for (let t = 0; t < 400; t += 0.5) {
      const ps = at(t, 1600, 900)
      for (let i = 0; i < ps.length; i++) {
        expect(Math.abs(ps[i].x - 800)).toBeLessThan(392)
        for (let j = i + 1; j < ps.length; j++) {
          expect(Math.hypot(ps[i].x - ps[j].x, ps[i].y - ps[j].y)).toBeGreaterThan(150)
        }
      }
    }
  })
})

describe('projectSimple', () => {
  it('原点投影到视口中心、缩放为 1', () => {
    const p = projectSimple([0, 0, 0], 800, 600)
    expect(p.x).toBeCloseTo(400)
    expect(p.y).toBeCloseTo(300)
    expect(p.scale).toBeCloseTo(1)
  })

  it('靠近相机的点更大，远离的点更小', () => {
    expect(projectSimple([0, 0, 3], 800, 600).scale).toBeGreaterThan(1)
    expect(projectSimple([0, 0, -3], 800, 600).scale).toBeLessThan(1)
  })
})
