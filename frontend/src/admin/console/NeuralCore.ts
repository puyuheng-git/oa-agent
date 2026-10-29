import * as THREE from 'three'
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js'
import { CAMERA, ORBITS, ORBIT_ORDER, orbitPoint, type OrbitId, type Projected, type Vec3 } from './orbits'
import { buildLinks, generateBrain, mulberry32 } from './brain'
import type { Mood } from './telemetry'

export type CoreMode = 'dormant' | 'active' | 'focus' | 'awaken'

const MOOD_COLOR: Record<Mood, string> = { ok: '#22d3ee', warn: '#fbbf24', bad: '#f43f5e', unknown: '#818cf8' }
const MOOD_PULSE: Record<Mood, number> = { ok: 1, warn: 1.6, bad: 2.6, unknown: 0.8 }
const RING_COLOR: Record<OrbitId, string> = { monitor: '#22d3ee', config: '#818cf8', system: '#3b82f6' }

interface ModeState {
  intensity: number
  spin: number
  camZ: number
  scale: number
  rings: number
}
/** 各模式同尺寸、同机位，只调亮度/转速，登录与主页不会因缩放产生割裂 */
const MODES: Record<CoreMode, ModeState> = {
  dormant: { intensity: 0.5, spin: 0.35, camZ: CAMERA.distance, scale: 1, rings: 0.35 },
  active: { intensity: 1, spin: 1, camZ: CAMERA.distance, scale: 1, rings: 1 },
  focus: { intensity: 0.55, spin: 0.5, camZ: CAMERA.distance, scale: 1, rings: 0.25 },
  awaken: { intensity: 1.15, spin: 1.15, camZ: CAMERA.distance, scale: 1, rings: 1 },
}

const PARTICLES = 8000
const LINK_SAMPLE = 500
const MAX_PULSES = 36
const TRAIL = 3
const FLASHES = 4
const FLOW_PER_RING = 24
const BRAIN_SCALE = 1.3
/** 主页常态帧间隔；面板打开暂停渲染后不占用 GPU */
const FRAME_MS = 1000 / 30

/** 脑电波方向（前→后略带斜向）与放电闪烁，粒子与连线共用。 */
const thinkingGlsl = /* glsl */ `
  uniform float uWave;
  uniform float uActivity;
  uniform vec4 uFlash[${FLASHES}];
  float thinking(vec3 p) {
    float w = sin(dot(p, normalize(vec3(0.25, 0.35, -1.0))) * 2.4 + uWave);
    float band = smoothstep(0.82 - uActivity * 0.12, 1.0, w);
    float flash = 0.0;
    for (int i = 0; i < ${FLASHES}; i++) {
      vec3 d = p - uFlash[i].xyz;
      flash += uFlash[i].w * exp(-dot(d, d) * 5.0);
    }
    return band * (0.7 + uActivity * 0.6) + flash;
  }
`

const particleVertex = /* glsl */ `
  uniform float uTime;
  uniform float uPixelRatio;
  attribute float aRand;
  attribute vec3 aNormal;
  varying float vAlpha;
  varying float vHot;
  varying float vRim;
  ${thinkingGlsl}
  void main() {
    vec3 p = position + aNormal * sin(uTime * 2.0 + aRand * 40.0) * 0.006;
    vHot = thinking(position);
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    float centerZ = (modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0)).z;
    float front = smoothstep(-2.6, 1.8, mv.z - centerZ);
    vec3 n = normalize(normalMatrix * aNormal);
    vRim = pow(1.0 - abs(dot(n, normalize(-mv.xyz))), 3.0);
    gl_PointSize = (0.6 + aRand * 0.9 + vHot * 0.9 + vRim * 1.6) * uPixelRatio * (14.0 / -mv.z) * (0.75 + 0.25 * front);
    vAlpha = (0.3 + 0.5 * aRand) * (0.22 + 0.78 * front) + vRim * 0.75;
  }
`
const particleFragment = /* glsl */ `
  uniform vec3 uColor;
  uniform float uIntensity;
  varying float vAlpha;
  varying float vHot;
  varying float vRim;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5) discard;
    float a = smoothstep(0.5, 0.0, d);
    vec3 c = mix(uColor, vec3(1.0), clamp(vHot * 0.45 + vRim * 0.35, 0.0, 0.75));
    gl_FragColor = vec4(c * uIntensity * (0.95 + vHot * 0.8), a * clamp(vAlpha * 1.15 + vHot * 0.35, 0.0, 1.0));
  }
`
const linkVertex = /* glsl */ `
  varying float vHot;
  ${thinkingGlsl}
  void main() {
    vHot = thinking(position);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const linkFragment = /* glsl */ `
  uniform vec3 uColor;
  uniform float uIntensity;
  varying float vHot;
  void main() {
    gl_FragColor = vec4(uColor * uIntensity, (0.04 + vHot * 0.4) * uIntensity);
  }
`
const pulseVertex = /* glsl */ `
  uniform float uPixelRatio;
  attribute float aAlpha;
  varying float vAlpha;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = (1.4 + aAlpha * 2.6) * uPixelRatio * (14.0 / -mv.z);
    vAlpha = aAlpha;
  }
`
const pulseFragment = /* glsl */ `
  uniform vec3 uColor;
  varying float vAlpha;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5 || vAlpha <= 0.0) discard;
    float a = smoothstep(0.5, 0.0, d) * vAlpha;
    gl_FragColor = vec4(mix(uColor, vec3(1.0), 0.6) * 1.8, a);
  }
`

interface Pulse {
  from: number
  to: number
  t: number
  speed: number
  hops: number
}

export function webglSupported(): boolean {
  try {
    const c = document.createElement('canvas')
    return !!(c.getContext('webgl2') || c.getContext('webgl'))
  } catch {
    return false
  }
}

export class NeuralCore {
  private renderer: THREE.WebGLRenderer
  private composer: EffectComposer
  private bloom: UnrealBloomPass
  private scene = new THREE.Scene()
  private camera: THREE.PerspectiveCamera
  private clock = new THREE.Clock()
  private raf = 0
  private t = 0
  private wave = 0

  private brain = new THREE.Group()
  private positions: Float32Array
  private cortexCount: number
  private adjacency: Map<number, number[]>
  private nodes: number[]
  private thinkingUniforms: { uWave: { value: number }; uActivity: { value: number }; uFlash: { value: THREE.Vector4[] } }
  private particleMat: THREE.ShaderMaterial
  private linkMat: THREE.ShaderMaterial
  private pulseMat: THREE.ShaderMaterial
  private pulseGeo: THREE.BufferGeometry
  private pulses: Pulse[] = []
  private nextFlash = 0
  private flashSlot = 0
  private scanners: THREE.Line[] = []
  private ringMats: THREE.LineBasicMaterial[] = []
  private flows: { orbit: OrbitId; geo: THREE.BufferGeometry; mat: THREE.PointsMaterial }[] = []
  private orbitRig = new THREE.Group()
  private stars: THREE.Points

  private mood: Mood = 'unknown'
  private mode: CoreMode = 'active'
  private activity = 0
  private curActivity = 0
  private color = new THREE.Color(MOOD_COLOR.unknown)
  private targetColor = new THREE.Color(MOOD_COLOR.unknown)
  private pulse = MOOD_PULSE.unknown
  private cur: ModeState = { ...MODES.active }
  private pointer = new THREE.Vector2()
  private tmp = new THREE.Vector3()
  private rand = mulberry32(20261014)
  private paused = false
  private lastFrame = 0
  private frameN = 0
  private useBloom = true
  private lerpRate = 2.5

  constructor(
    canvas: HTMLCanvasElement,
    private onFrame?: (dt: number) => void,
    initialMode: CoreMode = 'active',
  ) {
    this.mode = initialMode
    this.cur = { ...MODES[initialMode] }
    this.useBloom = initialMode === 'active' || initialMode === 'awaken'
    const w = canvas.clientWidth || window.innerWidth
    const h = canvas.clientHeight || window.innerHeight
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance' })
    // 核显上 dpr=2 + Bloom 代价很高；限制到 1.25
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25))
    this.renderer.setSize(w, h, false)
    // 纯黑清屏 + 画布 mix-blend-mode: screen，背景由页面 CSS 提供，只叠加发光部分
    this.renderer.setClearColor(0x000000, 1)

    this.camera = new THREE.PerspectiveCamera(CAMERA.fov, w / h, 0.1, 200)
    this.camera.position.set(0, 0, this.cur.camZ)
    const ratio = this.renderer.getPixelRatio()

    const geo = generateBrain(PARTICLES, mulberry32(7))
    this.positions = geo.positions
    this.cortexCount = geo.cortexCount
    const links = buildLinks(geo.positions, geo.cortexCount, LINK_SAMPLE, 2, mulberry32(11))
    this.adjacency = links.adjacency
    this.nodes = [...links.adjacency.keys()]

    this.thinkingUniforms = {
      uWave: { value: 0 },
      uActivity: { value: 0 },
      uFlash: { value: Array.from({ length: FLASHES }, () => new THREE.Vector4(0, 0, 0, 0)) },
    }

    const pGeo = new THREE.BufferGeometry()
    pGeo.setAttribute('position', new THREE.BufferAttribute(geo.positions, 3))
    pGeo.setAttribute('aNormal', new THREE.BufferAttribute(geo.normals, 3))
    pGeo.setAttribute('aRand', new THREE.BufferAttribute(Float32Array.from({ length: PARTICLES }, () => this.rand()), 1))
    this.particleMat = new THREE.ShaderMaterial({
      vertexShader: particleVertex,
      fragmentShader: particleFragment,
      uniforms: {
        ...this.thinkingUniforms,
        uTime: { value: 0 },
        uPixelRatio: { value: ratio },
        uColor: { value: this.color },
        uIntensity: { value: 1 },
      },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    this.brain.add(new THREE.Points(pGeo, this.particleMat))

    const seg = new Float32Array(links.edges.length * 6)
    links.edges.forEach(([a, b], i) => {
      seg.set(geo.positions.subarray(a * 3, a * 3 + 3), i * 6)
      seg.set(geo.positions.subarray(b * 3, b * 3 + 3), i * 6 + 3)
    })
    const lGeo = new THREE.BufferGeometry()
    lGeo.setAttribute('position', new THREE.BufferAttribute(seg, 3))
    this.linkMat = new THREE.ShaderMaterial({
      vertexShader: linkVertex,
      fragmentShader: linkFragment,
      uniforms: { ...this.thinkingUniforms, uColor: { value: this.color }, uIntensity: { value: 1 } },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    this.brain.add(new THREE.LineSegments(lGeo, this.linkMat))

    this.pulseGeo = new THREE.BufferGeometry()
    this.pulseGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(MAX_PULSES * TRAIL * 3), 3))
    this.pulseGeo.setAttribute('aAlpha', new THREE.BufferAttribute(new Float32Array(MAX_PULSES * TRAIL), 1))
    this.pulseMat = new THREE.ShaderMaterial({
      vertexShader: pulseVertex,
      fragmentShader: pulseFragment,
      uniforms: { uPixelRatio: { value: ratio }, uColor: { value: this.color } },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    const pulsePoints = new THREE.Points(this.pulseGeo, this.pulseMat)
    pulsePoints.frustumCulled = false
    this.brain.add(pulsePoints)

    this.brain.rotation.set(0.18, 0.9, 0)

    for (const [radius, span, tilt] of [
      [3.0, 1.6, 0.3],
      [3.3, 0.9, -0.7],
      [3.1, 2.3, 1.2],
    ] as const) {
      const pts: THREE.Vector3[] = []
      for (let i = 0; i <= 48; i++) {
        const a = (i / 48) * span
        pts.push(new THREE.Vector3(Math.cos(a) * radius, Math.sin(a) * radius, 0))
      }
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(pts),
        new THREE.LineBasicMaterial({ color: this.color, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending }),
      )
      line.rotation.x = tilt
      this.scanners.push(line)
      this.scene.add(line)
    }
    this.scene.add(this.brain)
    this.scene.add(this.orbitRig)

    for (const id of ORBIT_ORDER) {
      const orbit = ORBITS[id]
      const pts = Array.from({ length: 257 }, (_, i) => new THREE.Vector3(...orbitPoint(orbit, (i / 256) * Math.PI * 2)))
      const mat = new THREE.LineBasicMaterial({ color: RING_COLOR[id], transparent: true, opacity: 0.32, blending: THREE.AdditiveBlending })
      this.ringMats.push(mat)
      this.orbitRig.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), mat))

      const fgeo = new THREE.BufferGeometry()
      fgeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(FLOW_PER_RING * 3), 3))
      const fmat = new THREE.PointsMaterial({
        color: RING_COLOR[id],
        size: 0.09,
        transparent: true,
        opacity: 0.9,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
      this.flows.push({ orbit: id, geo: fgeo, mat: fmat })
      this.orbitRig.add(new THREE.Points(fgeo, fmat))
    }

    const starPos = new Float32Array(2000 * 3)
    for (let i = 0; i < 2000; i++) {
      const v = new THREE.Vector3().randomDirection().multiplyScalar(30 + Math.random() * 50)
      starPos.set([v.x, v.y, v.z], i * 3)
    }
    const sGeo = new THREE.BufferGeometry()
    sGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3))
    this.stars = new THREE.Points(
      sGeo,
      new THREE.PointsMaterial({ color: '#7aa2ff', size: 0.12, transparent: true, opacity: 0.55, depthWrite: false }),
    )
    this.scene.add(this.stars)

    this.composer = new EffectComposer(this.renderer)
    this.composer.addPass(new RenderPass(this.scene, this.camera))
    this.bloom = new UnrealBloomPass(new THREE.Vector2(w, h), 0.85, 0.5, 0.12)
    this.composer.addPass(this.bloom)
    this.composer.addPass(new OutputPass())
    this.composer.setSize(w, h)

    this.tick()
  }

  setMood(mood: Mood) {
    this.mood = mood
    this.targetColor.set(MOOD_COLOR[mood])
  }

  setMode(mode: CoreMode) {
    this.mode = mode
    // focus / dormant 用直接渲染，跳过 Bloom 后处理
    this.useBloom = mode === 'active' || mode === 'awaken'
  }

  /** 0..1，来自真实进行中运行数 */
  setActivity(level: number) {
    this.activity = Math.max(0, Math.min(1, level))
  }

  /** 面板打开或二级菜单展开时暂停 RAF 内重活，避免滚动/点击卡顿 */
  setPaused(paused: boolean) {
    if (this.paused === paused) return
    this.paused = paused
    if (!paused) {
      this.clock.getDelta()
      this.lastFrame = 0
    }
  }

  setLerpRate(rate: number) {
    this.lerpRate = Math.max(0.2, rate)
  }

  /** nx、ny ∈ [-1, 1] */
  setPointer(nx: number, ny: number) {
    if (this.paused) return
    this.pointer.set(nx, ny)
  }

  resize(w: number, h: number) {
    if (!w || !h) return
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
    this.renderer.setSize(w, h, false)
    this.composer.setSize(w, h)
    this.bloom.resolution.set(w, h)
  }

  project(p: Vec3, w: number, h: number): Projected {
    this.tmp.set(p[0], p[1], p[2])
    const dist = this.camera.position.distanceTo(this.tmp)
    this.tmp.project(this.camera)
    return {
      x: ((this.tmp.x + 1) / 2) * w,
      y: ((1 - this.tmp.y) / 2) * h,
      scale: this.camera.position.length() / dist,
    }
  }

  dispose() {
    cancelAnimationFrame(this.raf)
    this.scene.traverse((o) => {
      const m = o as THREE.Mesh
      m.geometry?.dispose()
      const mat = m.material as THREE.Material | THREE.Material[] | undefined
      if (Array.isArray(mat)) mat.forEach((x) => x.dispose())
      else mat?.dispose()
    })
    this.composer.dispose()
    this.renderer.dispose()
  }

  private spawnPulse(): Pulse | null {
    if (!this.nodes.length) return null
    const from = this.nodes[Math.floor(this.rand() * this.nodes.length)]
    const next = this.adjacency.get(from)
    if (!next?.length) return null
    return { from, to: next[Math.floor(this.rand() * next.length)], t: 0, speed: 1.6 + this.rand() * 1.8, hops: 4 + Math.floor(this.rand() * 10) }
  }

  private updatePulses(dt: number) {
    const target = Math.round(14 + this.curActivity * (MAX_PULSES - 14))
    while (this.pulses.length < target) {
      const p = this.spawnPulse()
      if (!p) break
      this.pulses.push(p)
    }
    if (this.pulses.length > target) this.pulses.length = target

    const pos = this.pulseGeo.attributes.position.array as Float32Array
    const alpha = this.pulseGeo.attributes.aAlpha.array as Float32Array
    alpha.fill(0)
    const P = this.positions
    this.pulses.forEach((p, i) => {
      p.t += dt * p.speed * (1 + this.curActivity)
      if (p.t >= 1) {
        p.hops--
        const options = (this.adjacency.get(p.to) ?? []).filter((n) => n !== p.from)
        if (p.hops <= 0 || !options.length) {
          const fresh = this.spawnPulse()
          if (fresh) this.pulses[i] = p = fresh
        } else {
          p.from = p.to
          p.to = options[Math.floor(this.rand() * options.length)]
          p.t = 0
        }
      }
      for (let k = 0; k < TRAIL; k++) {
        const tt = Math.max(0, p.t - k * 0.09)
        const j = (i * TRAIL + k) * 3
        pos[j] = P[p.from * 3] + (P[p.to * 3] - P[p.from * 3]) * tt
        pos[j + 1] = P[p.from * 3 + 1] + (P[p.to * 3 + 1] - P[p.from * 3 + 1]) * tt
        pos[j + 2] = P[p.from * 3 + 2] + (P[p.to * 3 + 2] - P[p.from * 3 + 2]) * tt
        alpha[i * TRAIL + k] = (1 - k / TRAIL) * Math.min(1, this.cur.intensity)
      }
    })
    this.pulseGeo.attributes.position.needsUpdate = true
    this.pulseGeo.attributes.aAlpha.needsUpdate = true
  }

  private updateFlashes(dt: number) {
    const flashes = this.thinkingUniforms.uFlash.value
    for (const f of flashes) f.w *= Math.exp(-dt * 3.2)
    this.nextFlash -= dt
    if (this.nextFlash <= 0) {
      const idx = Math.floor(this.rand() * this.cortexCount)
      const P = this.positions
      flashes[this.flashSlot].set(P[idx * 3], P[idx * 3 + 1], P[idx * 3 + 2], 0.9 + this.rand() * 0.6)
      this.flashSlot = (this.flashSlot + 1) % FLASHES
      this.nextFlash = (0.5 + this.rand() * 1.1) / (1 + this.curActivity * 2.5)
    }
  }

  private tick = (now = performance.now()) => {
    this.raf = requestAnimationFrame(this.tick)
    if (document.hidden || this.paused) return
    if (now - this.lastFrame < FRAME_MS) return
    const dt = Math.min(this.clock.getDelta(), 0.05)
    this.lastFrame = now
    this.frameN++
    this.t += dt
    const k = 1 - Math.exp(-dt * this.lerpRate)
    const target = MODES[this.mode]
    for (const key of Object.keys(target) as (keyof ModeState)[]) this.cur[key] += (target[key] - this.cur[key]) * k
    this.color.lerp(this.targetColor, k)
    this.pulse += (MOOD_PULSE[this.mood] - this.pulse) * k
    this.curActivity += (this.activity - this.curActivity) * k

    const c = this.cur
    this.wave += dt * (1.4 + this.curActivity * 2.4) * this.pulse
    this.thinkingUniforms.uWave.value = this.wave
    this.thinkingUniforms.uActivity.value = this.curActivity
    this.particleMat.uniforms.uTime.value = this.t
    this.particleMat.uniforms.uIntensity.value = c.intensity
    this.linkMat.uniforms.uIntensity.value = c.intensity
    this.updatePulses(dt)
    this.updateFlashes(dt)

    const breathe = 1 + 0.02 * Math.sin(this.t * 1.3 * this.pulse)
    this.brain.scale.setScalar(breathe * c.scale * BRAIN_SCALE)
    this.brain.rotation.y += dt * 0.14 * c.spin

    this.scanners.forEach((s, i) => {
      s.rotation.z += dt * (0.6 + i * 0.35) * c.spin * (i % 2 ? -1 : 1)
      s.scale.setScalar(c.scale)
      const m = s.material as THREE.LineBasicMaterial
      m.color.copy(this.color)
      m.opacity = 0.45 * Math.min(1, c.intensity)
    })

    this.ringMats.forEach((m) => (m.opacity = 0.32 * c.rings))
    if (this.frameN % 2 === 0) {
      for (const f of this.flows) {
        const orbit = ORBITS[f.orbit]
        const arr = f.geo.attributes.position.array as Float32Array
        for (let i = 0; i < FLOW_PER_RING; i++) {
          const a = (i / FLOW_PER_RING) * Math.PI * 2 + this.t * orbit.speed * 4 + Math.sin(i * 12.9898) * 0.08
          arr.set(orbitPoint(orbit, a), i * 3)
        }
        f.geo.attributes.position.needsUpdate = true
        f.mat.opacity = 0.9 * c.rings
        f.mat.size = 0.09
      }
    }

    this.stars.rotation.y += dt * 0.006
    this.bloom.strength = 0.4 + 0.3 * Math.min(1.5, c.intensity)

    this.camera.position.x += (this.pointer.x * 1.4 - this.camera.position.x) * k
    this.camera.position.y += (this.pointer.y * 0.9 - this.camera.position.y) * k
    this.camera.position.z += (c.camZ - this.camera.position.z) * k
    this.camera.lookAt(0, 0, 0)

    this.onFrame?.(dt)
    if (this.useBloom) this.composer.render()
    else this.renderer.render(this.scene, this.camera)
  }
}
