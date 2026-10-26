export type OrbitId = 'monitor' | 'config' | 'system'

export interface Orbit {
  radius: number
  /** 绕 X 轴倾斜（弧度） */
  tiltX: number
  /** 绕 Z 轴倾斜（弧度） */
  tiltZ: number
  /** 角速度（弧度 / 秒），负数为逆向 */
  speed: number
}

/** 三条轨道同向同速：节点之间不会相互追越，始终保持错开（相位见 layoutNodes）。
 *  最外圈半径受两翼限制：1600×900 下节点中心距屏幕中线不超过约 390px。 */
const ORBIT_SPEED = 0.035
export const ORBITS: Record<OrbitId, Orbit> = {
  monitor: { radius: 4.4, tiltX: 0.66, tiltZ: -0.22, speed: ORBIT_SPEED },
  config: { radius: 5.15, tiltX: 0.46, tiltZ: 0.24, speed: ORBIT_SPEED },
  system: { radius: 5.7, tiltX: 0.6, tiltZ: -0.04, speed: ORBIT_SPEED },
}

export const ORBIT_ORDER: OrbitId[] = ['monitor', 'config', 'system']

/** 相机参数：NeuralCore 与 projectSimple 共用，保证两种渲染方式下卫星位置一致。 */
export const CAMERA = { distance: 17, fov: 45 }

export type Vec3 = [number, number, number]

/** 轨道上角度 angle 处的世界坐标：先在水平面取圆周点，再绕 X、绕 Z 倾斜。 */
export function orbitPoint(orbit: Orbit, angle: number): Vec3 {
  const x0 = orbit.radius * Math.cos(angle)
  const z0 = orbit.radius * Math.sin(angle)
  const cx = Math.cos(orbit.tiltX)
  const sx = Math.sin(orbit.tiltX)
  const y1 = -z0 * sx
  const z1 = z0 * cx
  const cz = Math.cos(orbit.tiltZ)
  const sz = Math.sin(orbit.tiltZ)
  return [x0 * cz - y1 * sz, x0 * sz + y1 * cz, z1]
}

export interface NodeLayout {
  key: string
  orbit: OrbitId
  phase: number
}

/** 同一轨道内的节点均匀分布；不同轨道错开起始相位，避免节点排成一列。 */
export function layoutNodes(items: { key: string; group: OrbitId }[]): NodeLayout[] {
  const counts: Record<string, number> = {}
  const seen: Record<string, number> = {}
  for (const it of items) counts[it.group] = (counts[it.group] ?? 0) + 1
  return items.map((it) => {
    const i = (seen[it.group] = (seen[it.group] ?? -1) + 1)
    const offset = [0, 1.8, 2.4][ORBIT_ORDER.indexOf(it.group)]
    return { key: it.key, orbit: it.group, phase: offset + (i / counts[it.group]) * Math.PI * 2 }
  })
}

export interface Projected {
  x: number
  y: number
  /** 相对原点深度的缩放：>1 更靠近相机 */
  scale: number
}

/** 无 WebGL 时使用的透视投影，与 CAMERA 参数一致。 */
export function projectSimple(p: Vec3, width: number, height: number): Projected {
  const f = height / 2 / Math.tan(((CAMERA.fov / 2) * Math.PI) / 180)
  const depth = CAMERA.distance - p[2]
  return {
    x: width / 2 + (p[0] * f) / depth,
    y: height / 2 - (p[1] * f) / depth,
    scale: CAMERA.distance / depth,
  }
}
