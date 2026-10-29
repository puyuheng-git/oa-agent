import { http } from '@/shared/http'

export const PACKS_BASE = '/v1/admin/packs'

export interface PackItem {
  id: string
  display_name: string
  version: string
  enabled: boolean
  default_enabled: boolean
  connectors: string[]
  validation_errors: string[]
}

export interface PackListResponse {
  items: PackItem[]
}

export interface PackReasonBody {
  reason?: string
}

export function packPath(packId: string): string {
  return `${PACKS_BASE}/${encodeURIComponent(packId)}`
}

export function packEnablePath(packId: string): string {
  return `${packPath(packId)}/enable`
}

export function packDisablePath(packId: string): string {
  return `${packPath(packId)}/disable`
}

export async function listPacks(): Promise<PackListResponse> {
  return http.get<PackListResponse>(PACKS_BASE)
}

export async function enablePack(packId: string, body: PackReasonBody = {}): Promise<PackItem> {
  return http.post<PackItem>(packEnablePath(packId), body)
}

export async function disablePack(packId: string, body: PackReasonBody = {}): Promise<PackItem> {
  return http.post<PackItem>(packDisablePath(packId), body)
}
