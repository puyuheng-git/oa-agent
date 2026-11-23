// 测调后 LLM enrich 建议 → 智能 merge 进 ToolForm（空补全、非空保留、fields 并集）

import type { FieldRow, ToolForm } from './catalogForm'
import type { SchemaNode } from './schemaTree'
import { normalizeNode } from './schemaTree'

export interface EnrichSuggestion {
  name?: string
  summary?: string
  description?: string
  result_kind?: 'list' | 'object' | string
  fields?: { field: string; label: string }[]
  list_columns?: string[]
  params?: Record<string, { label?: string; description?: string }>
}

export interface EnrichSkillDraft {
  name: string
  display_name: string
  description: string
  instructions: string
  examples: string[]
  tools: string[]
}

/** 将 suggestion 智能 merge 进 form；返回补全的字段数等信息。 */
export function mergeEnrichSuggestion(form: ToolForm, suggestion: EnrichSuggestion): {
  filledName: boolean
  filledSummary: boolean
  filledDescription: boolean
  paramHints: number
  fieldCount: number
} {
  let filledName = false
  let filledSummary = false
  let filledDescription = false
  let paramHints = 0

  if (!form.name.trim() && suggestion.name?.trim()) {
    form.name = suggestion.name.trim()
    filledName = true
  }
  if (!form.summary.trim() && suggestion.summary?.trim()) {
    form.summary = suggestion.summary.trim()
    filledSummary = true
  }
  if (!form.description.trim() && suggestion.description?.trim()) {
    form.description = suggestion.description.trim()
    filledDescription = true
  }
  if (suggestion.result_kind === 'list' || suggestion.result_kind === 'object') {
    // 仅当尚无字段或仍是默认占位时才改 kind
    if (!form.fields.some((f) => f.key.trim() && f.key !== 'id')) {
      form.result_kind = suggestion.result_kind
    }
  }

  const params = suggestion.params || {}
  for (const [key, hint] of Object.entries(params)) {
    const node = form.modelParams[key]
    if (!node) continue
    const next: SchemaNode = { ...node }
    let changed = false
    if (!(next.label || '').trim() && hint.label?.trim()) {
      next.label = hint.label.trim()
      changed = true
    }
    if (!(next.description || '').trim() && hint.description?.trim()) {
      next.description = hint.description.trim()
      changed = true
    }
    if (changed) {
      form.modelParams[key] = normalizeNode(next)
      paramHints += 1
    }
  }

  const existingByKey = new Map<string, FieldRow>()
  for (const f of form.fields) {
    const k = f.key.trim()
    if (k) existingByKey.set(k, f)
  }
  const listCols = new Set((suggestion.list_columns || []).filter(Boolean))
  const merged: FieldRow[] = []
  const seen = new Set<string>()

  for (const f of form.fields) {
    const k = f.key.trim()
    if (!k) continue
    seen.add(k)
    const sug = (suggestion.fields || []).find((s) => s.field === k)
    merged.push({
      key: k,
      label: f.label.trim() || sug?.label || k,
      inList: form.result_kind === 'list' ? (f.inList || listCols.has(k)) : false,
    })
  }
  for (const s of suggestion.fields || []) {
    const k = (s.field || '').trim()
    if (!k || seen.has(k)) continue
    seen.add(k)
    merged.push({
      key: k,
      label: (s.label || '').trim() || k,
      inList: form.result_kind === 'list' ? (listCols.has(k) || listCols.size === 0) : false,
    })
  }
  if (merged.length) form.fields = merged

  return {
    filledName,
    filledSummary,
    filledDescription,
    paramHints,
    fieldCount: merged.length,
  }
}
