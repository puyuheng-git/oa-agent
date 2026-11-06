import { http } from '@/shared/http'

export const EXPORT_FILES_BASE = '/v1/admin/export-files'

export interface ExportFileItem {
  file_id: string
  oa: string
  thread_id: string | null
  run_id: string | null
  filename: string
  size_bytes: number
  storage: string
  created_at: string | null
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
  page?: number
  page_size?: number
}): Promise<ExportFileList> {
  return http.get<ExportFileList>(EXPORT_FILES_BASE, params)
}
