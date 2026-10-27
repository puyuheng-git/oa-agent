import type { Component } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import {
  Aim,
  ChatDotRound,
  Connection,
  Cpu,
  DataLine,
  Document,
  Link,
  List,
  Lock,
  MagicStick,
  Monitor,
  Share,
  Tools,
  User,
  UserFilled,
} from '@element-plus/icons-vue'
import { auth, can, loadMe } from './auth'
import type { MenuGroup, MenuLeaf } from './console/menuGroups'

export interface MenuItem extends MenuLeaf {
  component: () => Promise<{ default: Component }>
}

/** 一级菜单（指挥舱卫星）；顺序即轨道上的分布顺序。 */
export const menuGroups: MenuGroup[] = [
  { id: 'monitor', title: '运行监控', code: 'MONITOR', icon: DataLine, orbit: 'monitor' },
  { id: 'handoff', title: '介入中心', code: 'HANDOFF', icon: Aim, orbit: 'monitor' },
  { id: 'ability', title: '能力编排', code: 'ABILITY', icon: MagicStick, orbit: 'config' },
  { id: 'access', title: '系统接入', code: 'ACCESS', icon: Connection, orbit: 'config' },
  { id: 'security', title: '权限与审计', code: 'SECURITY', icon: UserFilled, orbit: 'system' },
]

export const menu: MenuItem[] = [
  { path: '/runs', title: '运行记录', code: 'RUNS', perm: 'ops.run.view', group: 'monitor', icon: List, component: () => import('./views/RunsView.vue') },
  { path: '/conversations', title: '对话记录', code: 'DIALOGS', perm: 'ops.run.view_sensitive', group: 'monitor', icon: ChatDotRound, component: () => import('./views/ConversationsView.vue') },
  { path: '/employees', title: '员工治理', code: 'EMPLOYEES', perm: 'ops.employee.view', group: 'monitor', icon: User, component: () => import('./views/EmployeesView.vue') },
  { path: '/interventions', title: '介入中心', code: 'HANDOFF', perm: 'ops.intervention.handle', group: 'handoff', icon: Aim, component: () => import('./views/InterventionsView.vue') },
  { path: '/tools', title: 'Tool 管理', code: 'TOOLS', perm: 'ops.tool.manage', group: 'ability', icon: Tools, component: () => import('./views/ToolsView.vue') },
  { path: '/mcp-servers', title: 'MCP 连接', code: 'MCP', perm: 'ops.mcp.manage', group: 'ability', icon: Connection, component: () => import('./views/McpServersView.vue') },
  { path: '/skills', title: 'Skill 管理', code: 'SKILLS', perm: 'ops.skill.manage', group: 'ability', icon: MagicStick, component: () => import('./views/SkillsView.vue') },
  { path: '/workflows', title: '流程配置', code: 'FLOWS', perm: 'ops.config.edit', group: 'ability', icon: Share, component: () => import('./views/WorkflowsView.vue') },
  { path: '/settings', title: '连接配置', code: 'LINKS', perm: 'sys.setting.view', group: 'access', icon: Link, component: () => import('./views/SettingsView.vue') },
  { path: '/llm', title: 'LLM 配置', code: 'LLM', perm: 'sys.setting.view', group: 'access', icon: Cpu, component: () => import('./views/LlmView.vue') },
  { path: '/accounts', title: '账号', code: 'ACCOUNTS', perm: 'sys.account.manage', group: 'security', icon: User, component: () => import('./views/AccountsView.vue') },
  { path: '/roles', title: '角色与权限', code: 'ROLES', perm: 'sys.account.manage', group: 'security', icon: Lock, component: () => import('./views/RolesView.vue') },
  { path: '/audit', title: '审计日志', code: 'AUDIT', perm: 'ops.audit.view', group: 'security', icon: Document, component: () => import('./views/AuditView.vue') },
]

const CoreIdle = { name: 'CoreIdle', render: () => null }

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', component: () => import('./views/LoginView.vue'), meta: { public: true } },
    {
      path: '/',
      component: () => import('./views/LayoutView.vue'),
      children: [
        { path: '', component: CoreIdle },
        // 运行总览已并入指挥舱主页；必须排在 runs/:runId 之前
        { path: 'runs/overview', redirect: '/' },
        {
          path: 'status',
          component: () => import('./views/HomeView.vue'),
          meta: { title: '系统状态', code: 'STATUS', icon: Monitor },
        },
        ...menu.map((m) => ({
          path: m.path.slice(1),
          component: m.component,
          meta: { perm: m.perm, title: m.title, code: m.code, icon: m.icon, menuPath: m.path },
        })),
        {
          path: 'runs/:runId',
          component: () => import('./views/RunDetailView.vue'),
          meta: { perm: 'ops.run.view', title: '运行详情', code: 'RUN TRACE', icon: List, menuPath: '/runs' },
        },
        {
          path: 'employees/:oa',
          component: () => import('./views/EmployeeDetailView.vue'),
          meta: { perm: 'ops.employee.view', title: '员工详情', code: 'EMPLOYEE', icon: User, menuPath: '/employees' },
        },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  if (!auth.loaded) await loadMe()
  if (to.meta.public) return auth.me ? '/' : true
  if (!auth.me) return { path: '/login', query: { redirect: to.fullPath } }
  const perm = to.meta.perm as string | undefined
  if (perm && !can(perm)) return '/'
  return true
})
