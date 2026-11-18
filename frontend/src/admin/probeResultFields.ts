// 从向导 probe 成功返回的 data 推断 result.fields / labels（顶层 + 一层点路径）。

const FIELD_RE = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$/

export interface ProbeFieldRow {
  field: string
  label: string
}

/** 从一条对象行提取字段：顶层键 + 一层 object 的 a.b；数组整段只保留顶层键。 */
export function fieldsFromRow(row: Record<string, unknown>, max = 40): ProbeFieldRow[] {
  const out: ProbeFieldRow[] = []
  const seen = new Set<string>()
  const add = (field: string, label: string) => {
    if (!FIELD_RE.test(field) || seen.has(field) || out.length >= max) return
    seen.add(field)
    out.push({ field, label })
  }
  for (const [k, v] of Object.entries(row)) {
    add(k, k)
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      for (const sk of Object.keys(v as Record<string, unknown>)) {
        add(`${k}.${sk}`, sk)
      }
    }
  }
  return out
}

/**
 * 解析 probe 的 data：list 形态取首行；object 形态用自身；info 包一层则剥开。
 * 与现有行合并：已有 field 保留（含手改 label），只追加缺失字段。
 */
export function mergeProbeResultFields(
  data: unknown,
  existing: ProbeFieldRow[],
  resultKind: 'list' | 'object',
): ProbeFieldRow[] {
  let row: Record<string, unknown> | null = null
  let kind = resultKind
  if (Array.isArray(data) && data.length && typeof data[0] === 'object' && data[0]) {
    row = data[0] as Record<string, unknown>
    kind = 'list'
  } else if (data && typeof data === 'object' && !Array.isArray(data)) {
    const obj = data as Record<string, unknown>
    if (Array.isArray(obj.list) && obj.list.length && typeof obj.list[0] === 'object') {
      row = obj.list[0] as Record<string, unknown>
      kind = 'list'
    } else if (obj.info && typeof obj.info === 'object' && !Array.isArray(obj.info)) {
      row = obj.info as Record<string, unknown>
    } else {
      row = obj
    }
  }
  void kind
  if (!row) return existing.length ? existing : []
  const inferred = fieldsFromRow(row)
  const byField = new Map(existing.filter((r) => r.field.trim()).map((r) => [r.field.trim(), r]))
  for (const r of inferred) {
    if (!byField.has(r.field)) byField.set(r.field, r)
  }
  // 稳定顺序：原有在前，新推断按 inferred 顺序追加
  const ordered: ProbeFieldRow[] = []
  const used = new Set<string>()
  for (const r of existing) {
    const f = r.field.trim()
    if (!f || used.has(f)) continue
    ordered.push(byField.get(f) || r)
    used.add(f)
  }
  for (const r of inferred) {
    if (used.has(r.field)) continue
    ordered.push(r)
    used.add(r.field)
  }
  return ordered
}
