import { http, request } from '@/shared/http'

export const EMPLOYEES_BASE = '/v1/admin/employees'

export const CHECKPOINT_RESTORE_WARNING =
  '仅恢复会话元数据（标题、状态），不保证 LangGraph Checkpoint 可续聊；员工在该线程继续提问时，图内 history/memory 可能无法承接。'

export interface EmployeeListItem {
  oa: string
  last_active_at: string | null
  thread_count: number
  memory_active_count: number
}

export interface Paged<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface EmployeeThread {
  thread_id: string
  title: string | null
  status: 'active' | 'archived' | 'deleted'
  created_channel: string
  last_channel: string
  pinned: boolean
  created_at: string
  updated_at: string
  last_message_at: string | null
}

export interface EmployeeMessage {
  message_id: string
  role: string
  content: string
  reply_type: string | null
  data: unknown
  error_code: string | null
  created_at: string
  run_id: string
}

export interface EmployeeMemory {
  memory_id: string
  kind: 'preference' | 'constraint' | 'note'
  status: 'active' | 'deleted'
  text: string | null
  created_at: string
  updated_at: string
}

export interface VisibilitySkill {
  name: string
  display_name?: string
  reason?: string
}

export interface EmployeeVisibility {
  visible: { name: string; display_name: string }[]
  hidden: { name: string; reason: string }[]
}

export const THREAD_STATUS: Record<
  EmployeeThread['status'],
  { label: string; type: 'success' | 'info' | 'danger' }
> = {
  active: { label: '进行中', type: 'success' },
  archived: { label: '已归档', type: 'info' },
  deleted: { label: '已删除', type: 'danger' },
}

export const HIDDEN_REASON: Record<string, string> = {
  deny: '显式拒绝',
  no_allow: '无 allow 规则',
}

export function encodeOa(oa: string): string {
  return encodeURIComponent(oa)
}

export function employeePath(oa: string): string {
  return `${EMPLOYEES_BASE}/${encodeOa(oa)}`
}

/** 列表 Query：`q` 前缀、`page`、`page_size`。 */
export function employeesListQuery(params: {
  q?: string
  page?: number
  page_size?: number
}): Record<string, string | number> {
  const out: Record<string, string | number> = {}
  if (params.q?.trim()) out.q = params.q.trim()
  if (params.page !== undefined) out.page = params.page
  if (params.page_size !== undefined) out.page_size = params.page_size
  return out
}

export function threadsPath(
  oa: string,
  params?: { status?: EmployeeThread['status']; page?: number; page_size?: number },
): string {
  const base = `${employeePath(oa)}/threads`
  if (!params) return base
  const qs = new URLSearchParams()
  if (params.status) qs.set('status', params.status)
  if (params.page !== undefined) qs.set('page', String(params.page))
  if (params.page_size !== undefined) qs.set('page_size', String(params.page_size))
  const s = qs.toString()
  return s ? `${base}?${s}` : base
}

export function threadMessagesPath(
  oa: string,
  threadId: string,
  params?: { page?: number; page_size?: number },
): string {
  const base = `${employeePath(oa)}/threads/${encodeURIComponent(threadId)}/messages`
  if (!params?.page && !params?.page_size) return base
  const qs = new URLSearchParams()
  if (params.page !== undefined) qs.set('page', String(params.page))
  if (params.page_size !== undefined) qs.set('page_size', String(params.page_size))
  return `${base}?${qs.toString()}`
}

export function memoryPath(
  oa: string,
  params?: { status?: 'active' | 'deleted'; include_text?: 0 | 1; page?: number; page_size?: number },
): string {
  const base = `${employeePath(oa)}/memory`
  if (!params) return base
  const qs = new URLSearchParams()
  if (params.status) qs.set('status', params.status)
  if (params.include_text !== undefined) qs.set('include_text', String(params.include_text))
  if (params.page !== undefined) qs.set('page', String(params.page))
  if (params.page_size !== undefined) qs.set('page_size', String(params.page_size))
  return `${base}?${qs.toString()}`
}

export function visibilityPath(oa: string): string {
  return `${employeePath(oa)}/visibility`
}

export function visibilityGrantsPath(oa: string): string {
  return `${employeePath(oa)}/visibility/grants`
}

export function visibilityGrantsBatchPath(oa: string): string {
  return `${employeePath(oa)}/visibility/grants/batch`
}

export interface ReasonBody {
  reason: string
}

export interface ThreadPatchBody extends ReasonBody {
  title?: string | null
  status?: 'active' | 'archived'
}

export interface ThreadRestoreBody extends ReasonBody {
  status?: 'active' | 'archived'
}

export interface ThreadBatchBody extends ReasonBody {
  action: 'archive' | 'soft_delete'
  thread_ids: string[]
}

export interface MemoryCreateBody extends ReasonBody {
  kind: EmployeeMemory['kind']
  text: string
}

export interface MemoryPatchBody extends ReasonBody {
  kind?: EmployeeMemory['kind']
  text?: string
}

export interface MemoryClearBody extends ReasonBody {
  confirm: true
}

export interface VisibilityGrantBody extends ReasonBody {
  skill_name: string
  effect: 'allow' | 'deny'
}

export interface VisibilityGrantDeleteBody extends ReasonBody {
  skill_name: string
  effect?: 'allow' | 'deny'
}

export interface VisibilityGrantBatchBody extends ReasonBody {
  skill_names: string[]
  effect: 'allow' | 'deny'
}

export async function listEmployees(params: {
  q?: string
  page?: number
  page_size?: number
}): Promise<Paged<EmployeeListItem>> {
  return http.get<Paged<EmployeeListItem>>(EMPLOYEES_BASE, employeesListQuery(params))
}

export async function listEmployeeThreads(
  oa: string,
  params: { status?: EmployeeThread['status']; page?: number; page_size?: number },
): Promise<Paged<EmployeeThread>> {
  return http.get<Paged<EmployeeThread>>(`${employeePath(oa)}/threads`, {
    status: params.status,
    page: params.page,
    page_size: params.page_size,
  })
}

export async function listThreadMessages(
  oa: string,
  threadId: string,
  params?: { page?: number; page_size?: number },
): Promise<Paged<EmployeeMessage>> {
  return http.get<Paged<EmployeeMessage>>(
    `${employeePath(oa)}/threads/${encodeURIComponent(threadId)}/messages`,
    params,
  )
}

export async function patchEmployeeThread(oa: string, threadId: string, body: ThreadPatchBody): Promise<EmployeeThread> {
  return request<EmployeeThread>(
    'PATCH',
    `${employeePath(oa)}/threads/${encodeURIComponent(threadId)}`,
    body,
  )
}

export async function deleteEmployeeThread(oa: string, threadId: string, body: ReasonBody): Promise<{ ok: boolean }> {
  return request('DELETE', `${employeePath(oa)}/threads/${encodeURIComponent(threadId)}`, body)
}

export async function restoreEmployeeThread(
  oa: string,
  threadId: string,
  body: ThreadRestoreBody,
): Promise<EmployeeThread> {
  return request<EmployeeThread>(
    'POST',
    `${employeePath(oa)}/threads/${encodeURIComponent(threadId)}/restore`,
    body,
  )
}

export async function batchEmployeeThreads(oa: string, body: ThreadBatchBody): Promise<{ ok: boolean; count: number }> {
  return http.post(`${employeePath(oa)}/threads/batch`, body)
}

export async function listEmployeeMemory(
  oa: string,
  params: { status?: 'active' | 'deleted'; include_text?: 0 | 1; page?: number; page_size?: number },
): Promise<Paged<EmployeeMemory>> {
  return http.get<Paged<EmployeeMemory>>(`${employeePath(oa)}/memory`, {
    status: params.status,
    include_text: params.include_text,
    page: params.page,
    page_size: params.page_size,
  })
}

export async function createEmployeeMemory(oa: string, body: MemoryCreateBody): Promise<EmployeeMemory> {
  return http.post(`${employeePath(oa)}/memory`, body)
}

export async function patchEmployeeMemory(
  oa: string,
  memoryId: string,
  body: MemoryPatchBody,
): Promise<EmployeeMemory> {
  return request('PATCH', `${employeePath(oa)}/memory/${encodeURIComponent(memoryId)}`, body)
}

export async function deleteEmployeeMemory(oa: string, memoryId: string, body: ReasonBody): Promise<{ ok: boolean }> {
  return request('DELETE', `${employeePath(oa)}/memory/${encodeURIComponent(memoryId)}`, body)
}

export async function restoreEmployeeMemory(oa: string, memoryId: string, body: ReasonBody): Promise<EmployeeMemory> {
  return request('POST', `${employeePath(oa)}/memory/${encodeURIComponent(memoryId)}/restore`, body)
}

export async function clearEmployeeMemory(oa: string, body: MemoryClearBody): Promise<{ ok: boolean; deleted: number }> {
  return request('DELETE', `${employeePath(oa)}/memory`, body)
}

export async function getEmployeeVisibility(oa: string): Promise<EmployeeVisibility> {
  return http.get<EmployeeVisibility>(visibilityPath(oa))
}

export async function addVisibilityGrant(oa: string, body: VisibilityGrantBody): Promise<{ ok: boolean }> {
  return http.post(visibilityGrantsPath(oa), body)
}

export async function removeVisibilityGrant(oa: string, body: VisibilityGrantDeleteBody): Promise<{ ok: boolean }> {
  return request('DELETE', visibilityGrantsPath(oa), body)
}

export async function batchVisibilityGrants(
  oa: string,
  body: VisibilityGrantBatchBody,
): Promise<{ ok: boolean; created: number }> {
  return http.post(visibilityGrantsBatchPath(oa), body)
}

export function hiddenReasonLabel(code: string): string {
  return HIDDEN_REASON[code] ?? code
}
