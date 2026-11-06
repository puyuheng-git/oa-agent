import { http } from '@/shared/http'
import { NO_DATA } from './runs'

export const EXPORT_FILES_BASE = '/v1/admin/export-files'

export type ExportFileOrigin = 'upload' | 'export'

export interface ExportFileItem {
  file_id: string
  oa: string
  thread_id: string | null
  run_id: string | null
  filename: string
  size_bytes: number
  storage: string
  origin: ExportFileOrigin | null
  media_kind: string | null
  created_at: string | null
}

export function exportOriginLabel(origin: ExportFileOrigin | null | undefined): string {
  if (origin === 'upload') return '用户上传'
  if (origin === 'export') return '助手导出'
  return NO_DATA
}

export interface ExportFileList {
  items: ExportFileItem[]
  total: number
  page: number
  page_size: number
}

export function conversationLink(
  threadId: string | null | undefined,
): { path: '/conversations'; query: { thread: string } } | null {
  if (!threadId) return null
  return { path: '/conversations', query: { thread: threadId } }
}

export function downloadPath(fileId: string): string {
  return `${EXPORT_FILES_BASE}/${encodeURIComponent(fileId)}/download`
}

export function listExportFiles(params: {
  oa?: string
  thread_id?: string
  filename?: string
  origin?: ExportFileOrigin
  page?: number
  page_size?: number
}): Promise<ExportFileList> {
  return http.get<ExportFileList>(EXPORT_FILES_BASE, params)
}
