import { describe, expect, it } from 'vitest'
import { SULCUS_WIDTH, activityLevel, buildLinks, generateBrain, mulberry32, sulcusField, sylvianDistance } from './brain'

describe('generateBrain', () => {
  const brain = generateBrain(3000, mulberry32(42))

  it('生成指定数量的点，且皮层点与总数一致', () => {
    expect(brain.positions.length).toBe(3000 * 3)
    expect(brain.cortexCount).toBeGreaterThan(2000)
    expect(brain.cortexCount).toBeLessThan(3000)
  })

  it('左右两个半球之间留有纵裂沟', () => {
    for (let i = 0; i < brain.cortexCount; i++) {
      expect(Math.abs(brain.positions[i * 3])).toBeGreaterThan(0.05)
    }
  })

  it('左右半球点数大致对称', () => {
    let left = 0
    for (let i = 0; i < brain.cortexCount; i++) if (brain.positions[i * 3] < 0) left++
    expect(left / brain.cortexCount).toBeGreaterThan(0.4)
    expect(left / brain.cortexCount).toBeLessThan(0.6)
  })

  it('所有点都在包围盒内', () => {
    for (let i = 0; i < 3000; i++) {
      const [x, y, z] = [brain.positions[i * 3], brain.positions[i * 3 + 1], brain.positions[i * 3 + 2]]
      expect(Math.abs(x)).toBeLessThan(2.6)
      expect(Math.abs(y)).toBeLessThan(2.8)
      expect(Math.abs(z)).toBeLessThan(2.6)
    }
  })

  it('皮层表面留出脑沟：几乎没有点落在脑沟场零值附近', () => {
    let inSulcus = 0
    for (let i = 0; i < brain.cortexCount; i++) {
      const [x, y, z] = [0, 1, 2].map((k) => brain.positions[i * 3 + k] / 1.12)
      if (Math.abs(sulcusField(x, y, z)) < SULCUS_WIDTH * 0.4) inSulcus++
    }
    expect(inSulcus / brain.cortexCount).toBeLessThan(0.03)
  })

  it('外侧裂处留空', () => {
    let near = 0
    for (let i = 0; i < brain.cortexCount; i++) {
      const [x, y, z] = [0, 1, 2].map((k) => brain.positions[i * 3 + k] / 1.12)
      if (Math.abs(x) > 0.9 && sylvianDistance(y, z) < 0.03) near++
    }
    expect(near / brain.cortexCount).toBeLessThan(0.002)
  })

  it('每个点都有单位法线，皮层法线朝外', () => {
    expect(brain.normals.length).toBe(brain.positions.length)
    for (let i = 0; i < 3000; i++) {
      const n = [0, 1, 2].map((k) => brain.normals[i * 3 + k])
      expect(Math.hypot(...n)).toBeCloseTo(1, 4)
    }
    let outward = 0
    for (let i = 0; i < brain.cortexCount; i++) {
      const [x, y, z] = [0, 1, 2].map((k) => brain.positions[i * 3 + k])
      const cx = Math.sign(x) * 0.42 * 1.12
      const dot = (x - cx) * brain.normals[i * 3] + (y - 0.22 * 1.12) * brain.normals[i * 3 + 1] + z * brain.normals[i * 3 + 2]
      if (dot > 0) outward++
    }
    expect(outward / brain.cortexCount).toBeGreaterThan(0.95)
  })

  it('同一种子结果确定', () => {
    const again = generateBrain(3000, mulberry32(42))
    expect(Array.from(again.positions.slice(0, 30))).toEqual(Array.from(brain.positions.slice(0, 30)))
  })
})

describe('buildLinks', () => {
  it('每条边连接两个不同的点，邻接表双向', () => {
    const brain = generateBrain(800, mulberry32(7))
    const { edges, adjacency } = buildLinks(brain.positions, brain.cortexCount, 200, 2, mulberry32(1))
    expect(edges.length).toBeGreaterThan(0)
    for (const [a, b] of edges) {
      expect(a).not.toBe(b)
      expect(adjacency.get(a)).toContain(b)
      expect(adjacency.get(b)).toContain(a)
    }
  })
})

describe('activityLevel', () => {
  it('无数据或无进行中运行为 0，上限为 1', () => {
    expect(activityLevel(null)).toBe(0)
    expect(activityLevel(0)).toBe(0)
    expect(activityLevel(4)).toBeCloseTo(0.5)
    expect(activityLevel(100)).toBe(1)
  })
})
