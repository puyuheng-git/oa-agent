/** 大脑粒子几何与神经连线（纯函数，便于测试）。坐标：x 左右、y 上下、z 前后（+z 为额叶）。 */

export type Rand = () => number

export function mulberry32(seed: number): Rand {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function gaussian(rand: Rand): number {
  const u = Math.max(rand(), 1e-9)
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rand())
}

function direction(rand: Rand): [number, number, number] {
  const x = gaussian(rand)
  const y = gaussian(rand)
  const z = gaussian(rand)
  const l = Math.hypot(x, y, z) || 1
  return [x / l, y / l, z / l]
}

function hash3(x: number, y: number, z: number): number {
  let h = Math.imul(x, 374761393) ^ Math.imul(y, 668265263) ^ Math.imul(z, 1274126177)
  h = Math.imul(h ^ (h >>> 13), 1274126177)
  h ^= h >>> 16
  return ((h >>> 0) / 4294967295) * 2 - 1
}

const fade = (t: number) => t * t * (3 - 2 * t)

/** 平滑值噪声，取值约 -1..1 */
function noise3(x: number, y: number, z: number): number {
  const ix = Math.floor(x)
  const iy = Math.floor(y)
  const iz = Math.floor(z)
  const fx = fade(x - ix)
  const fy = fade(y - iy)
  const fz = fade(z - iz)
  const lerp = (a: number, b: number, t: number) => a + (b - a) * t
  const c = (dx: number, dy: number, dz: number) => hash3(ix + dx, iy + dy, iz + dz)
  return lerp(
    lerp(lerp(c(0, 0, 0), c(1, 0, 0), fx), lerp(c(0, 1, 0), c(1, 1, 0), fx), fy),
    lerp(lerp(c(0, 0, 1), c(1, 0, 1), fx), lerp(c(0, 1, 1), c(1, 1, 1), fx), fy),
    fz,
  )
}

/** 脑沟场：零值等值线即脑沟走向，在表面形成迷宫状沟回 */
export function sulcusField(x: number, y: number, z: number): number {
  return noise3(x * 2.4 + 11.3, y * 2.4 + 3.7, z * 2.4) + 0.45 * noise3(x * 4.8, y * 4.8 + 7.1, z * 4.8 + 2.9)
}

export const SULCUS_WIDTH = 0.13

/** 外侧裂（Sylvian）：侧面从前下斜向后上的一道深沟，分开颞叶与额顶叶；返回点到该线的距离 */
export function sylvianDistance(y: number, z: number): number {
  const [z0, y0, z1, y1] = [1.0, -0.25, -0.55, 0.38]
  const dz = z1 - z0
  const dy = y1 - y0
  const t = Math.max(0, Math.min(1, ((z - z0) * dz + (y - y0) * dy) / (dz * dz + dy * dy)))
  return Math.hypot(z - (z0 + t * dz), y - (y0 + t * dy))
}

export interface BrainGeometry {
  positions: Float32Array
  /** 每点的单位外法线，用于轮廓边缘提亮 */
  normals: Float32Array
  /** 前 cortexCount 个点属于大脑皮层，其余为小脑与脑干 */
  cortexCount: number
}

const SCALE = 1.12
const HEMI_X = 0.42

type Vec3 = [number, number, number]

function unit(x: number, y: number, z: number): Vec3 {
  const l = Math.hypot(x, y, z) || 1
  return [x / l, y / l, z / l]
}

/** 单侧半球表面点（未缩放）与近似外法线；hemi = ±1 */
function cortexPoint(hemi: number, rand: Rand): [Vec3, Vec3] | null {
  const raw = direction(rand)
  let [dx, dy, dz] = raw
  const lateral = dx * hemi
  if (lateral < 0) dx *= 0.32
  // 额叶高而圆，枕叶窄而低
  const width = 0.92 * (dz < 0 ? 1 + 0.18 * dz : 1)
  const height = 1.42 * (1 + 0.1 * dz)
  const temporal = lateral > 0.25 && dy < 0 && dz > -0.55 && dz < 0.8
  if (dy < 0) dy *= temporal ? 0.75 : 0.4
  let x = hemi * HEMI_X + dx * width
  let y = 0.22 + dy * height
  let z = dz * 1.72
  if (temporal) {
    y -= 0.12 * lateral
    x += hemi * 0.08 * lateral
  }
  // 额叶底面（眶面）压平
  if (z > 0.6 && y < -0.2) y = -0.2 + (y + 0.2) * 0.4

  const outer = Math.abs(x) > HEMI_X + 0.35
  if (outer && sylvianDistance(y, z) < 0.08) return null

  const s = sulcusField(x, y, z)
  if (Math.abs(s) < SULCUS_WIDTH) return null
  // 脑回隆起、脑沟两侧向内凹陷
  const k = 1 - 0.1 * Math.exp(-((s / 0.25) ** 2)) + (rand() - 0.5) * 0.01
  x = hemi * HEMI_X + (x - hemi * HEMI_X) * k
  y = 0.22 + (y - 0.22) * k
  z *= k
  if (Math.abs(x) < 0.06) x = hemi * 0.06
  return [
    [x, y, z],
    unit(raw[0] / width, raw[1] / height, raw[2] / 1.72),
  ]
}

export function generateBrain(count: number, rand: Rand): BrainGeometry {
  const positions = new Float32Array(count * 3)
  const normals = new Float32Array(count * 3)
  const cortexCount = Math.round(count * 0.82)
  const cerebellumCount = Math.round(count * 0.13)
  let i = 0
  const put = ([x, y, z]: Vec3, n: Vec3) => {
    positions.set([x * SCALE, y * SCALE, z * SCALE], i * 3)
    normals.set(n, i * 3)
    i++
  }

  while (i < cortexCount) {
    const p = cortexPoint(i % 2 === 0 ? 1 : -1, rand)
    if (p) put(...p)
  }

  const cerebellumEnd = cortexCount + cerebellumCount
  while (i < cerebellumEnd) {
    const [dx, dy, dz] = direction(rand)
    const y = -0.78 + dy * 0.42
    // 小脑叶片：水平细条纹
    if (Math.abs(Math.sin(y * 34)) < 0.35) continue
    const hemi = dx >= 0 ? 1 : -1
    put([hemi * 0.08 + dx * 0.98, y, -1.18 + dz * 0.56 + 0.15 * (1 - Math.abs(dx))], unit(dx / 0.98, dy / 0.42, dz / 0.56))
  }

  while (i < count) {
    const t = rand()
    const a = rand() * Math.PI * 2
    const r = 0.24 * (1 - t * 0.35)
    put([Math.cos(a) * r, -0.45 - t * 1.45, -0.42 - t * 0.28 + Math.sin(a) * r], [Math.cos(a), 0, Math.sin(a)])
  }

  return { positions, normals, cortexCount }
}

export interface Links {
  edges: [number, number][]
  adjacency: Map<number, number[]>
}

/** 在皮层随机取 sample 个点，各连最近 k 个邻居，形成突触网络。 */
export function buildLinks(positions: Float32Array, cortexCount: number, sample: number, k: number, rand: Rand): Links {
  const idx = new Set<number>()
  while (idx.size < Math.min(sample, cortexCount)) idx.add(Math.floor(rand() * cortexCount))
  const list = [...idx]
  const edges: [number, number][] = []
  const seen = new Set<string>()
  const adjacency = new Map<number, number[]>()
  const link = (a: number, b: number) => {
    const key = a < b ? `${a}-${b}` : `${b}-${a}`
    if (seen.has(key)) return
    seen.add(key)
    edges.push([a, b])
    adjacency.set(a, [...(adjacency.get(a) ?? []), b])
    adjacency.set(b, [...(adjacency.get(b) ?? []), a])
  }
  for (const a of list) {
    const ax = positions[a * 3]
    const ay = positions[a * 3 + 1]
    const az = positions[a * 3 + 2]
    const near = list
      .filter((b) => b !== a && Math.sign(positions[b * 3]) === Math.sign(ax))
      .map((b) => ({ b, d: (positions[b * 3] - ax) ** 2 + (positions[b * 3 + 1] - ay) ** 2 + (positions[b * 3 + 2] - az) ** 2 }))
      .sort((p, q) => p.d - q.d)
      .slice(0, k)
    for (const { b } of near) link(a, b)
  }
  return { edges, adjacency }
}

/** 思考强度：由真实“进行中运行数”映射到 0..1；无数据为 0（仅保留基础动画）。 */
export function activityLevel(inProgress: number | null | undefined): number {
  if (!inProgress || inProgress < 0) return 0
  return Math.min(1, inProgress / 8)
}
