<script setup lang="ts">
// Schema 树编辑器：左树 + 右属性；顶栏「树编辑 / JSON」切换。
// - mode='params'：modelValue 为 {参数名 → SchemaNode}
// - mode='result-root'：modelValue 为可选根 SchemaNode | null
// 组件内部持有本地深拷贝，只通过 update:modelValue 向外发出新对象，不直接修改 props。
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { ElTree } from 'element-plus'
import {
  SCHEMA_MAX_DEPTH,
  SCHEMA_TYPES,
  emptyNode,
  enumToText,
  fileMultipleToArray,
  normalizeNode,
  parseEnumText,
  parseSchemaJson,
  stringifySchema,
} from '../schemaTree'
import type { SchemaNode, SchemaType } from '../schemaTree'

type SchemaMap = Record<string, SchemaNode>

const props = defineProps<{
  mode: 'params' | 'result-root'
  modelValue: SchemaMap | SchemaNode | null
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: SchemaMap | SchemaNode | null): void }>()

// result-root 模式下，根节点在内部 map 中的虚拟键
const ROOT = '$'
const isRootMode = computed(() => props.mode === 'result-root')

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T
}
function hasOwn(o: object, k: string): boolean {
  return Object.prototype.hasOwnProperty.call(o, k)
}

/** 把外部值转成内部统一的 map（result-root 用 ROOT 键包一层）。 */
function toLocal(v: SchemaMap | SchemaNode | null | undefined): SchemaMap {
  if (isRootMode.value) return v ? { [ROOT]: clone(v as SchemaNode) } : {}
  return v ? clone(v as SchemaMap) : {}
}
/** 把内部 map 还原成外部值。 */
function fromLocal(): SchemaMap | SchemaNode | null {
  if (isRootMode.value) return local.value[ROOT] ? clone(local.value[ROOT]) : null
  return clone(local.value)
}

const local = ref<SchemaMap>({})
let lastEmitted = ''
local.value = toLocal(props.modelValue)
lastEmitted = JSON.stringify(props.modelValue ?? null)

/** 本地变更后向外发出新值，并记录指纹以忽略父级回灌。 */
function emitChange() {
  const out = fromLocal()
  lastEmitted = JSON.stringify(out ?? null)
  emit('update:modelValue', out)
}

// ---------- 路径定位 ----------
// 路径规则：`a/b/c` 逐层取 properties；array 的 items 追加 `[]`（如 `tags[]`、`list[]/name`）。

interface Located {
  node: SchemaNode
  /** 所在 properties 容器；items 节点没有容器 */
  container: SchemaMap | null
  key: string
  isItems: boolean
}

function resolve(path: string): Located | null {
  if (!path) return null
  let container: SchemaMap = local.value
  let node: SchemaNode | undefined
  let key = ''
  let isItems = false
  const segs = path.split('/')
  for (let i = 0; i < segs.length; i++) {
    const m = /^(.*?)((?:\[\])*)$/.exec(segs[i])
    const name = m ? m[1] : segs[i]
    const arrays = m ? m[2].length / 2 : 0
    if (i > 0) {
      if (!node || node.type !== 'object' || !node.properties) return null
      container = node.properties
    }
    if (!hasOwn(container, name)) return null
    node = container[name]
    key = name
    isItems = false
    for (let a = 0; a < arrays; a++) {
      if (!node || node.type !== 'array' || !node.items) return null
      node = node.items
      isItems = true
    }
  }
  if (!node) return null
  return { node, container: isItems ? null : container, key, isItems }
}

/** 路径深度（顶层为 0）：每个 `/` 与 `[]` 各算一层。 */
function depthOf(path: string): number {
  return (path.match(/\[\]|\//g) || []).length
}

/** array<file> 在 UI 上视为「多文件」的 file。 */
function isMultipleFile(n: SchemaNode): boolean {
  return n.type === 'array' && n.items?.type === 'file'
}

function viewTypeOf(n: SchemaNode): SchemaType {
  return isMultipleFile(n) ? 'file' : n.type
}

function typeLabel(n: SchemaNode): string {
  if (isMultipleFile(n)) return 'file[]'
  if (n.type === 'array') return `array<${n.items?.type ?? 'string'}>`
  return n.type
}

// ---------- 树数据 ----------

interface TreeItem {
  path: string
  name: string
  node: SchemaNode
  isItems: boolean
  children: TreeItem[]
}

function buildItem(path: string, name: string, node: SchemaNode, isItems: boolean): TreeItem {
  const children: TreeItem[] = []
  if (node.type === 'object' && node.properties) {
    for (const [k, v] of Object.entries(node.properties)) children.push(buildItem(`${path}/${k}`, k, v, false))
  } else if (node.type === 'array' && node.items && !isMultipleFile(node)) {
    children.push(buildItem(`${path}[]`, '[] 元素', node.items, true))
  }
  return { path, name, node, isItems, children }
}

const treeData = computed<TreeItem[]>(() => {
  if (isRootMode.value) {
    const root = local.value[ROOT]
    return root ? [buildItem(ROOT, '根节点', root, false)] : []
  }
  return Object.entries(local.value).map(([k, v]) => buildItem(k, k, v, false))
})

const treeRef = ref<InstanceType<typeof ElTree>>()
const selectedPath = ref('')
const selected = computed(() => resolve(selectedPath.value))
const selectedDepth = computed(() => depthOf(selectedPath.value))

// 展开状态：默认全展开，仅记录被用户折叠的节点
const collapsed = ref<Set<string>>(new Set())
const expandedKeys = computed<string[]>(() => {
  const keys: string[] = []
  const walk = (items: TreeItem[]) => {
    for (const it of items) {
      if (it.children.length) {
        if (!collapsed.value.has(it.path)) keys.push(it.path)
        walk(it.children)
      }
    }
  }
  walk(treeData.value)
  return keys
})

function onNodeClick(data: TreeItem) {
  selectedPath.value = data.path
}
function onNodeCollapse(data: TreeItem) {
  collapsed.value = new Set(collapsed.value).add(data.path)
}
function onNodeExpand(data: TreeItem) {
  const next = new Set(collapsed.value)
  next.delete(data.path)
  collapsed.value = next
}

// 树数据重建后恢复高亮
watch(treeData, () => {
  nextTick(() => treeRef.value?.setCurrentKey(selectedPath.value || undefined))
})
watch(selectedPath, (p) => {
  nextTick(() => treeRef.value?.setCurrentKey(p || undefined))
})

// ---------- 右侧属性：缓冲输入（需要整体解析/校验的字段，失焦提交） ----------

const nameBuf = ref('')
const enumBuf = ref('')
const acceptBuf = ref('')

/** accept / enum 存放的节点：多文件时在 items 上。 */
const acceptHost = computed<SchemaNode | null>(() => {
  const n = selected.value?.node
  if (!n) return null
  return isMultipleFile(n) ? (n.items as SchemaNode) : n
})
const viewType = computed<SchemaType | ''>(() => (selected.value ? viewTypeOf(selected.value.node) : ''))
const multipleFile = computed(() => !!selected.value && isMultipleFile(selected.value.node))
const canHaveChildren = computed(
  () => selected.value?.node.type === 'object' && selectedDepth.value < SCHEMA_MAX_DEPTH,
)
const canDelete = computed(() => !!selected.value && !selected.value.isItems)

function syncBuffers() {
  const sel = selected.value
  nameBuf.value = sel && !sel.isItems ? sel.key : ''
  const host = acceptHost.value
  enumBuf.value = host ? enumToText(host) : ''
  acceptBuf.value = host?.accept ? host.accept.join(', ') : ''
}
watch([() => selected.value?.node, viewType], syncBuffers, { immediate: true })

/** 写入/清除普通字段；空值一律清除，保持节点干净。 */
function setField(key: keyof SchemaNode, val: unknown) {
  const sel = selected.value
  if (!sel) return
  const bag = sel.node as unknown as Record<string, unknown>
  const empty = val === undefined || val === null || val === '' || val === false
  if (empty) delete bag[key]
  else bag[key] = val
  emitChange()
}

function setHostField(key: keyof SchemaNode, val: unknown) {
  const host = acceptHost.value
  if (!host) return
  const bag = host as unknown as Record<string, unknown>
  if (val === undefined || val === null || (Array.isArray(val) && val.length === 0)) delete bag[key]
  else bag[key] = val
  emitChange()
}

function commitEnum() {
  const host = acceptHost.value
  if (!host) return
  // 支持 `值=显示名`；同时写 enum 与 enum_labels，清空时一并删除（剔除过期 labels）
  const parsed = parseEnumText(enumBuf.value, host.type)
  const bag = host as unknown as Record<string, unknown>
  if (parsed.enum) bag.enum = parsed.enum
  else delete bag.enum
  if (parsed.enum_labels) bag.enum_labels = parsed.enum_labels
  else delete bag.enum_labels
  emitChange()
  enumBuf.value = enumToText(host)
}

function commitAccept() {
  const list = acceptBuf.value.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean)
  setHostField('accept', list)
  acceptBuf.value = list.join(', ')
}

/** 默认值：boolean 用下拉，数字用数字框，字符串用文本框。 */
const defaultBool = computed(() => {
  const d = selected.value?.node.default
  return d === true ? 'true' : d === false ? 'false' : ''
})
function setDefaultBool(v: string) {
  const sel = selected.value
  if (!sel) return
  if (v === '') delete sel.node.default
  else sel.node.default = v === 'true'
  emitChange()
}

// 数字框清空时返回 null/undefined，统一当作删除
function setNumField(key: 'minimum' | 'maximum' | 'default', v: number | null | undefined) {
  const sel = selected.value
  if (!sel) return
  const bag = sel.node as unknown as Record<string, unknown>
  if (v === null || v === undefined) delete bag[key]
  else bag[key] = v
  emitChange()
}

/** 原地替换节点内容，保持对象引用，选中态不丢。 */
function replaceNode(target: SchemaNode, src: SchemaNode) {
  const bag = target as unknown as Record<string, unknown>
  for (const k of Object.keys(bag)) delete bag[k]
  Object.assign(target, src)
}

/** 是否带有会因类型变更而丢失的子树。 */
function hasSubtree(n: SchemaNode): boolean {
  if (n.type === 'object') return !!n.properties && Object.keys(n.properties).length > 0
  if (n.type === 'array' && n.items && !isMultipleFile(n)) {
    return JSON.stringify(n.items) !== '{"type":"string"}'
  }
  return false
}

async function onTypeChange(newType: SchemaType) {
  const sel = selected.value
  if (!sel || newType === viewTypeOf(sel.node)) return
  const node = sel.node
  // 带子树时需用户确认，否则丢弃子树
  if (hasSubtree(node)) {
    try {
      await ElMessageBox.confirm('切换类型会清空当前节点下的子参数 / 元素定义，是否继续？', '切换类型', {
        type: 'warning',
        confirmButtonText: '继续',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
  }
  // 仅保留通用字段，类型相关字段（enum/accept/范围等）随类型重置
  const next = emptyNode(newType)
  if (node.label) next.label = node.label
  if (node.description) next.description = node.description
  if (node.required) next.required = true
  replaceNode(node, next)
  emitChange()
}

/** 「多文件」开关：UI 态 file+multiple 与持久态 array<file> 互转。 */
function onMultipleChange(v: boolean | string | number) {
  const sel = selected.value
  if (!sel) return
  const node = sel.node
  if (v) {
    if (node.type !== 'file') return
    replaceNode(node, fileMultipleToArray({ ...node, multiple: true }))
  } else {
    if (!isMultipleFile(node)) return
    const plain: SchemaNode = { type: 'file' }
    if (node.label) plain.label = node.label
    if (node.description) plain.description = node.description
    if (node.required) plain.required = true
    if (node.items?.accept?.length) plain.accept = node.items.accept
    replaceNode(node, plain)
  }
  emitChange()
}

// ---------- 增删改名 ----------

function checkName(container: SchemaMap, name: string, selfKey = ''): string {
  if (!name) return '名称不能为空'
  if (/[/[\]]/.test(name)) return '名称不能包含 / [ ]'
  if (name !== selfKey && hasOwn(container, name)) return '名称已存在'
  return ''
}

async function addChild(toRoot: boolean) {
  // 确定目标容器：顶层 map 或选中 object 节点的 properties
  let container: SchemaMap
  let base = ''
  if (toRoot) {
    container = local.value
  } else {
    const sel = selected.value
    if (!sel || sel.node.type !== 'object') return
    if (!sel.node.properties) sel.node.properties = {}
    container = sel.node.properties
    base = `${selectedPath.value}/`
  }
  let name = ''
  try {
    const r = await ElMessageBox.prompt('请输入参数名', '新增参数', {
      confirmButtonText: '添加',
      cancelButtonText: '取消',
      inputValidator: (v: string) => checkName(container, (v || '').trim()) || true,
    })
    name = (r.value || '').trim()
  } catch {
    return
  }
  container[name] = emptyNode('string')
  if (!toRoot) onNodeExpand({ path: selectedPath.value } as TreeItem)
  selectedPath.value = `${base}${name}`
  emitChange()
}

function addRoot() {
  local.value[ROOT] = emptyNode('object')
  selectedPath.value = ROOT
  emitChange()
}

async function removeSelected() {
  const sel = selected.value
  if (!sel || !sel.container) return
  const label = isRootMode.value && sel.key === ROOT ? '根节点' : sel.key
  try {
    await ElMessageBox.confirm(`确定删除「${label}」及其子节点？`, '删除', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  delete sel.container[sel.key]
  selectedPath.value = ''
  emitChange()
}

/** 重命名：保持键顺序，并更新选中路径。 */
function commitRename() {
  const sel = selected.value
  if (!sel || !sel.container || sel.isItems) return
  const next = nameBuf.value.trim()
  if (next === sel.key) {
    nameBuf.value = sel.key
    return
  }
  const err = checkName(sel.container, next, sel.key)
  if (err) {
    ElMessage.error(err)
    nameBuf.value = sel.key
    return
  }
  const entries = Object.entries(sel.container).map(([k, v]) => [k === sel.key ? next : k, v] as const)
  const oldKey = sel.key
  for (const k of Object.keys(sel.container)) delete sel.container[k]
  for (const [k, v] of entries) sel.container[k] = v
  selectedPath.value = selectedPath.value.slice(0, selectedPath.value.length - oldKey.length) + next
  emitChange()
}

// ---------- JSON 页签 ----------

const view = ref<'tree' | 'json'>('tree')
const jsonText = ref('')
const jsonError = ref('')

function serialize(): string {
  if (isRootMode.value) {
    const root = local.value[ROOT]
    return root ? JSON.stringify(root, null, 2) : 'null'
  }
  return stringifySchema(local.value)
}

/** 解析 JSON 文本为内部 map；result-root 允许空 / null 表示无根。 */
function parseJson(text: string): { ok: true; value: SchemaMap } | { ok: false; error: string } {
  if (!isRootMode.value) return parseSchemaJson(text)
  const t = text.trim()
  // 空文本视为错误；仅显式 JSON null 表示无根
  if (!t) return { ok: false, error: 'JSON 不能为空；如不设置根节点请输入 null' }
  if (t === 'null') return { ok: true, value: {} }
  let raw: unknown
  try {
    raw = JSON.parse(t)
  } catch (e) {
    return { ok: false, error: `JSON 解析失败：${(e as Error).message}` }
  }
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    return { ok: false, error: '根节点必须是对象（Schema 节点）' }
  }
  return { ok: true, value: { [ROOT]: normalizeNode(raw) } }
}

// 进入 JSON 页签时的本地模型快照（JSON 字符串），「丢弃 JSON」据此还原
let jsonSnapshot = ''

function onViewChange(v: string | number | boolean | undefined) {
  if (v === 'json') {
    if (view.value !== 'json') jsonSnapshot = JSON.stringify(local.value)
    jsonText.value = serialize()
    jsonError.value = ''
    view.value = 'json'
  } else if (v === 'tree') {
    if (jsonError.value) return
    if (selectedPath.value && !resolve(selectedPath.value)) selectedPath.value = ''
    view.value = 'tree'
  }
}

/** 输入即解析：合法则立即生效并外发；非法只显示错误，不动数据。 */
function onJsonInput(text: string) {
  jsonText.value = text
  const r = parseJson(text)
  if (!r.ok) {
    jsonError.value = r.error
    return
  }
  jsonError.value = ''
  local.value = r.value
  emitChange()
}

/** 丢弃 JSON：还原为进入 JSON 页签时的快照（含撤销期间已实时生效的修改）。 */
function discardJson() {
  local.value = JSON.parse(jsonSnapshot) as SchemaMap
  emitChange()
  jsonText.value = serialize()
  jsonError.value = ''
  if (selectedPath.value && !resolve(selectedPath.value)) selectedPath.value = ''
}

// 父级主动改值（非本组件回灌）时重置本地状态
watch(
  () => props.modelValue,
  (v) => {
    if (JSON.stringify(v ?? null) === lastEmitted) return
    lastEmitted = JSON.stringify(v ?? null)
    local.value = toLocal(v)
    if (selectedPath.value && !resolve(selectedPath.value)) selectedPath.value = ''
    if (view.value === 'json') {
      // 父级重置后以新值为准，快照同步更新
      jsonSnapshot = JSON.stringify(local.value)
      jsonText.value = serialize()
      jsonError.value = ''
    }
  },
  { deep: true },
)

const typeOptions = SCHEMA_TYPES
</script>

<template>
  <div class="schema-tree-editor">
    <div class="ste-head">
      <el-radio-group :model-value="view" size="small" @update:model-value="onViewChange">
        <el-radio-button value="tree" :disabled="!!jsonError">树编辑</el-radio-button>
        <el-radio-button value="json">JSON</el-radio-button>
      </el-radio-group>
      <span class="ste-hint">{{ isRootMode ? '返回结果根节点（可不设置）' : '参数列表' }}</span>
    </div>

    <!-- 树编辑 -->
    <div v-show="view === 'tree'" class="ste-body">
      <div class="ste-left">
        <div class="ste-toolbar">
          <el-button
            v-if="!isRootMode"
            size="small"
            type="primary"
            plain
            @click="addChild(true)"
          >新增参数</el-button>
          <el-button
            v-else-if="!treeData.length"
            size="small"
            type="primary"
            plain
            @click="addRoot"
          >添加根节点</el-button>
          <el-button
            size="small"
            plain
            :disabled="!canHaveChildren"
            @click="addChild(false)"
          >新增子参数</el-button>
          <el-button
            size="small"
            plain
            type="danger"
            :disabled="!canDelete"
            @click="removeSelected"
          >删除</el-button>
        </div>
        <el-tree
          v-if="treeData.length"
          ref="treeRef"
          :data="treeData"
          node-key="path"
          :props="{ label: 'name', children: 'children' }"
          :expand-on-click-node="false"
          :default-expanded-keys="expandedKeys"
          :current-node-key="selectedPath || undefined"
          highlight-current
          @node-click="onNodeClick"
          @node-collapse="onNodeCollapse"
          @node-expand="onNodeExpand"
        >
          <template #default="{ data }">
            <span class="ste-node">
              <span class="ste-node-name">{{ data.name }}</span>
              <el-tag size="small" effect="plain" class="ste-node-type">{{ typeLabel(data.node) }}</el-tag>
              <span v-if="data.node.required" class="ste-req" title="必填">*</span>
            </span>
          </template>
        </el-tree>
        <el-empty v-else :image-size="48" :description="isRootMode ? '未设置根节点' : '暂无参数'" />
      </div>

      <div class="ste-right">
        <el-empty v-if="!selected" :image-size="48" description="在左侧选择一个节点" />
        <el-form v-else label-width="86px" size="small" @submit.prevent>
          <el-form-item v-if="!selected.isItems && !(isRootMode && selected.key === ROOT)" label="名称">
            <el-input v-model="nameBuf" @change="commitRename" />
          </el-form-item>
          <el-form-item label="类型">
            <el-select :model-value="viewType" style="width: 100%" @change="onTypeChange">
              <el-option v-for="t in typeOptions" :key="t" :label="t" :value="t" />
            </el-select>
          </el-form-item>
          <el-form-item label="显示名">
            <el-input
              :model-value="selected.node.label ?? ''"
              @update:model-value="(v: string) => setField('label', v)"
            />
          </el-form-item>
          <el-form-item label="说明">
            <el-input
              type="textarea"
              :rows="2"
              :model-value="selected.node.description ?? ''"
              @update:model-value="(v: string) => setField('description', v)"
            />
          </el-form-item>
          <el-form-item v-if="!selected.isItems" label="必填">
            <el-switch
              :model-value="!!selected.node.required"
              @update:model-value="(v: boolean | string | number) => setField('required', !!v)"
            />
          </el-form-item>

          <!-- 字符串 -->
          <el-form-item v-if="viewType === 'string'" label="格式">
            <el-input
              :model-value="selected.node.format ?? ''"
              placeholder="如 date / date-time"
              @update:model-value="(v: string) => setField('format', v)"
            />
          </el-form-item>

          <!-- 枚举：字符串 / 整数 / 数字 -->
          <el-form-item v-if="viewType === 'string' || viewType === 'integer' || viewType === 'number'" label="枚举值">
            <el-input
              v-model="enumBuf"
              type="textarea"
              :rows="3"
              placeholder="每行一个，可写 值=显示名（如 0=未报销），留空表示不限制"
              @change="commitEnum"
            />
          </el-form-item>

          <!-- 数值范围 -->
          <template v-if="viewType === 'integer' || viewType === 'number'">
            <el-form-item label="最小值">
              <el-input-number
                :model-value="selected.node.minimum"
                controls-position="right"
                style="width: 100%"
                @update:model-value="(v: number | undefined) => setNumField('minimum', v)"
              />
            </el-form-item>
            <el-form-item label="最大值">
              <el-input-number
                :model-value="selected.node.maximum"
                controls-position="right"
                style="width: 100%"
                @update:model-value="(v: number | undefined) => setNumField('maximum', v)"
              />
            </el-form-item>
          </template>

          <!-- 默认值 -->
          <el-form-item v-if="viewType === 'string'" label="默认值">
            <el-input
              :model-value="typeof selected.node.default === 'string' ? selected.node.default : ''"
              @update:model-value="(v: string) => setField('default', v)"
            />
          </el-form-item>
          <el-form-item v-else-if="viewType === 'integer' || viewType === 'number'" label="默认值">
            <el-input-number
              :model-value="typeof selected.node.default === 'number' ? selected.node.default : undefined"
              controls-position="right"
              style="width: 100%"
              @update:model-value="(v: number | undefined) => setNumField('default', v)"
            />
          </el-form-item>
          <el-form-item v-else-if="viewType === 'boolean'" label="默认值">
            <el-select
              :model-value="defaultBool"
              clearable
              placeholder="无"
              style="width: 100%"
              @update:model-value="(v: string) => setDefaultBool(v || '')"
            >
              <el-option label="true" value="true" />
              <el-option label="false" value="false" />
            </el-select>
          </el-form-item>

          <!-- 文件 -->
          <template v-if="viewType === 'file'">
            <el-form-item label="允许类型">
              <el-input
                v-model="acceptBuf"
                placeholder="逗号分隔，如 .pdf, .docx"
                @change="commitAccept"
              />
            </el-form-item>
            <el-form-item label="多文件">
              <el-switch :model-value="multipleFile" @update:model-value="onMultipleChange" />
            </el-form-item>
          </template>

          <el-alert
            v-if="viewType === 'object' && selectedDepth >= SCHEMA_MAX_DEPTH"
            type="warning"
            :closable="false"
            show-icon
            :title="`嵌套已达上限（${SCHEMA_MAX_DEPTH} 层），不能再添加子参数`"
          />
        </el-form>
      </div>
    </div>

    <!-- JSON 页签 -->
    <div v-if="view === 'json'" class="ste-json">
      <el-alert
        v-if="jsonError"
        type="error"
        :closable="false"
        show-icon
        class="ste-json-err"
      >
        <template #title>{{ jsonError }}</template>
        <div>修复后才能返回「树编辑」；也可丢弃 JSON，恢复为进入 JSON 页签时的内容（期间已生效的修改也会撤销）。</div>
        <el-button size="small" type="danger" plain style="margin-top: 6px" @click="discardJson">丢弃 JSON</el-button>
      </el-alert>
      <el-input
        :model-value="jsonText"
        type="textarea"
        :rows="16"
        class="ste-json-input"
        spellcheck="false"
        @update:model-value="onJsonInput"
      />
    </div>
  </div>
</template>

<style scoped>
.schema-tree-editor {
  width: 100%;
}
.ste-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.ste-hint {
  color: var(--tech-text-2);
  font-size: 12px;
}
.ste-body {
  display: flex;
  gap: 12px;
  min-height: 320px;
}
.ste-left {
  flex: 0 0 300px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  padding: 8px;
  overflow: auto;
  max-height: 480px;
}
.ste-right {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  padding: 12px 12px 4px;
  overflow: auto;
  max-height: 480px;
}
.ste-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 8px;
}
.ste-toolbar .el-button + .el-button {
  margin-left: 0;
}
.ste-node {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.ste-node-type {
  transform: scale(0.9);
}
.ste-req {
  color: var(--tech-danger, var(--el-color-danger));
}
.ste-json-err {
  margin-bottom: 8px;
}
.ste-json-input :deep(textarea) {
  font-family: Consolas, Menlo, monospace;
  font-size: 12px;
}
</style>
