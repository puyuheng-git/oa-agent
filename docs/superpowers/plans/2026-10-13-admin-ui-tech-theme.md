# 管理后台「AI 神经核心指挥舱」Implementation Plan

> **For agentic workers:** 本计划在当前会话内联执行（executing-plans）。Steps 使用 `- [ ]` 跟踪。

**Goal：** 按 `docs/design/2026-10-13-admin-ui-tech-theme-design.md` 实现指挥舱式管理后台。

**Architecture：** 纯函数（轨道、遥测、图表 option）可单测；Three.js 场景类只负责渲染；Vue 组件组合舞台、HUD、全息面板；原业务页面作为面板内容不改逻辑。

**Tech Stack：** Vue 3、Element Plus 2.8、Three.js 0.169、ECharts 5、@element-plus/icons-vue、Vitest。

## Global Constraints

- 只改表现层；路由地址不变；遥测只来自真实接口，无数据显示「未检测 / 暂无数据」。
- 不引入外部字体 / CDN；Three.js 动态加载。

---

- [x] Task 1：依赖与全局深色主题（`theme.css`、`main.ts`、`admin/index.html`）
- [x] Task 2：`charts.ts` + `charts.spec.ts`（TDD）
- [x] Task 3：`console/orbits.ts` + spec（TDD）：`ORBITS`、`orbitPoint(orbit, angle)`、`layoutNodes(items)`、`projectSimple(p, w, h)`
- [x] Task 4：`console/telemetry.ts` + spec（TDD）：`coreMood(ready)`、`buildTelemetry(input)`、`buildBroadcast(input)`、`buildTicker(input)`、`fetchReady()`
- [x] Task 5：`console/NeuralCore.ts`、`console/CoreStage.vue`、`console/SatelliteNode.vue`
- [x] Task 6：`router.ts`（`group`、`icon`、`code`，新增 `/status`）、`LayoutView.vue`（指挥舱 + 全息面板）、`LoginView.vue`、`HomeView.vue`
- [x] Task 7：`components/TechChart.vue`、`RunsOverviewView.vue` 图表化
- [x] Task 8：其余页面硬编码颜色替换为主题变量
- [x] Task 9：`npm run test`（46 通过）、`npm run build`（通过）、浏览器截图（接口为 Playwright 模拟数据，真实后端未联调）
