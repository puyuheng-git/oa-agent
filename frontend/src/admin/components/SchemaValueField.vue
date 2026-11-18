<script setup lang="ts">
// SchemaValueEditor 的节点级递归渲染：按 SchemaNode.type 渲染单个值的输入控件。
// 值约定见 schemaValue.ts：file 存 ref 字符串；boolean 为 boolean|undefined；其余见各分支。
// 不直接修改 props，所有变更通过 update:modelValue 发出新值。
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'
import { errorMessage, http } from '@/shared/http'
import { emptyValue } from '../schemaValue'
import type { SchemaNode } from '../schemaTree'

const props = defineProps<{
  node: SchemaNode
  modelValue: unknown
  /** 参数名；无显示名时作为标签 */
  name: string
  /** 数组元素等场景不显示标签 */
  hideLabel?: boolean
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: unknown): void }>()

const UPLOAD_URL = '/v1/admin/tools/export-wizard/upload-temp'

interface UploadResp {
  data: { ref: string; filename: string; sha256?: string; size?: number }
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

const labelText = computed(() => props.node.label || props.name)
const items = computed<SchemaNode>(() => props.node.items ?? { type: 'string' })
const objectValue = computed<Record<string, unknown>>(() => (isPlainObject(props.modelValue) ? props.modelValue : {}))
const arrayValue = computed<unknown[]>(() => (Array.isArray(props.modelValue) ? props.modelValue : []))
const textValue = computed(() => (props.modelValue === undefined || props.modelValue === null ? '' : String(props.modelValue)))
const enumOptions = computed(() =>
  (props.node.enum ?? []).map((e) => ({ value: e as string | number, label: props.node.enum_labels?.[String(e)] ?? String(e) })),
)
const acceptStr = computed(() => (props.node.accept ?? []).join(','))
const hasProps = computed(() => Object.keys(props.node.properties ?? {}).length > 0)

// ---------- object / array ----------

function setProp(key: string, v: unknown) {
  const next = { ...objectValue.value }
  if (v === undefined) delete next[key]
  else next[key] = v
  emit('update:modelValue', next)
}

// ---------- 粘贴 JSON（object / array；未声明子参数的自由对象只能走 JSON） ----------

const isContainer = computed(() => props.node.type === 'object' || props.node.type === 'array')
const freeObject = computed(() => props.node.type === 'object' && !hasProps.value)
const jsonMode = ref(false)
const showJson = computed(() => freeObject.value || jsonMode.value)
const jsonText = ref('')
const jsonError = ref('')
// 最近一次由本组件发出的值指纹，用于忽略父级回灌、只响应外部改值
let lastJson = ''

function valueToText(v: unknown): string {
  return v === undefined || v === null ? '' : JSON.stringify(v, null, 2)
}

jsonText.value = valueToText(props.modelValue)
lastJson = JSON.stringify(props.modelValue ?? null)

watch(
  () => props.modelValue,
  (v) => {
    if (JSON.stringify(v ?? null) === lastJson) return
    lastJson = JSON.stringify(v ?? null)
    jsonText.value = valueToText(v)
    jsonError.value = ''
  },
  { deep: true },
)

function toggleJson() {
  jsonMode.value = !jsonMode.value
  if (jsonMode.value) {
    jsonText.value = valueToText(props.modelValue)
    jsonError.value = ''
  }
}

/** 输入即解析：合法且类型匹配才外发；非法只提示，不动已有值。 */
function onJsonInput(text: string) {
  jsonText.value = text
  if (!text.trim()) {
    jsonError.value = ''
    lastJson = 'null'
    emit('update:modelValue', undefined)
    return
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch (e) {
    jsonError.value = `JSON 格式错误：${(e as Error).message}`
    return
  }
  const ok = props.node.type === 'array' ? Array.isArray(parsed) : isPlainObject(parsed)
  if (!ok) {
    jsonError.value = props.node.type === 'array' ? '必须是 JSON 数组' : '必须是 JSON 对象'
    return
  }
  jsonError.value = ''
  lastJson = JSON.stringify(parsed)
  emit('update:modelValue', parsed)
}

function addItem() {
  emit('update:modelValue', [...arrayValue.value, emptyValue(items.value)])
}

function setItem(i: number, v: unknown) {
  const next = [...arrayValue.value]
  next[i] = v
  emit('update:modelValue', next)
}

function removeItem(i: number) {
  emit('update:modelValue', arrayValue.value.filter((_, idx) => idx !== i))
}

// ---------- file ----------

const uploading = ref(false)
// 最近一次上传的 ref → 文件名，仅用于展示；手填路径时不显示
const uploaded = ref<{ ref: string; filename: string } | null>(null)
const shownFilename = computed(() =>
  uploaded.value && uploaded.value.ref === textValue.value ? uploaded.value.filename : '',
)

/** 自定义上传：POST multipart 到向导临时目录，成功后把 ref 写入值。 */
async function doUpload(opt: UploadRequestOptions) {
  // 上传前按 accept 扩展名拦截（el-upload 的 accept 仅是选择框提示，可被绕过）
  const exts = (props.node.accept ?? []).map((a) => a.trim().toLowerCase()).filter(Boolean)
  if (exts.length) {
    const fileName = String(opt.file?.name ?? '').toLowerCase()
    if (!exts.some((e) => fileName.endsWith(e.startsWith('.') ? e : `.${e}`))) {
      ElMessage.error(`文件类型不符，仅支持：${exts.join(', ')}`)
      return
    }
  }
  uploading.value = true
  try {
    const form = new FormData()
    form.append('file', opt.file)
    const r = await http.postForm<UploadResp>(UPLOAD_URL, form)
    uploaded.value = { ref: r.data.ref, filename: r.data.filename }
    emit('update:modelValue', r.data.ref)
  } catch (e) {
    ElMessage.error(`上传失败：${errorMessage(e)}`)
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <el-form-item :label="hideLabel ? '' : labelText" :label-width="hideLabel ? '0px' : undefined" :required="!!node.required">
    <div class="svf-control">
      <!-- 粘贴 JSON：object / array 可切换；自由对象（无子参数）始终使用 -->
      <template v-if="isContainer && showJson">
        <el-input
          type="textarea"
          :rows="freeObject ? 4 : 6"
          spellcheck="false"
          :model-value="jsonText"
          :placeholder="node.type === 'array' ? '粘贴 JSON 数组，如 [1, 2]' : '粘贴 JSON 对象，如 {&quot;key&quot;: &quot;value&quot;}'"
          @update:model-value="onJsonInput"
        />
        <div v-if="jsonError" class="svf-err">{{ jsonError }}</div>
        <el-button v-if="!freeObject" size="small" link type="primary" @click="toggleJson">返回表单填写</el-button>
      </template>

      <!-- 对象：递归渲染子属性 -->
      <div v-else-if="node.type === 'object'" class="svf-box">
        <SchemaValueField
          v-for="(child, key) in node.properties"
          :key="key"
          :node="child"
          :name="String(key)"
          :model-value="objectValue[key]"
          @update:model-value="(v: unknown) => setProp(String(key), v)"
        />
        <el-button size="small" link type="primary" class="svf-json-btn" @click="toggleJson">粘贴 JSON</el-button>
      </div>

      <!-- 数组：元素列表 + 增删 -->
      <div v-else-if="node.type === 'array'" class="svf-box">
        <div v-for="(item, i) in arrayValue" :key="i" class="svf-item">
          <span class="svf-idx">#{{ i + 1 }}</span>
          <div class="svf-item-body">
            <SchemaValueField
              :node="items"
              :name="`#${i + 1}`"
              hide-label
              :model-value="item"
              @update:model-value="(v: unknown) => setItem(i, v)"
            />
          </div>
          <el-button size="small" type="danger" plain @click="removeItem(i)">删除</el-button>
        </div>
        <el-button size="small" plain @click="addItem">添加一项</el-button>
        <el-button size="small" link type="primary" class="svf-json-btn" @click="toggleJson">粘贴 JSON</el-button>
      </div>

      <!-- 文件：上传 + 手填路径 -->
      <div v-else-if="node.type === 'file'" class="svf-file">
        <el-upload
          :show-file-list="false"
          :http-request="doUpload"
          :accept="acceptStr || undefined"
          :disabled="uploading"
        >
          <el-button size="small" :loading="uploading">选择文件上传</el-button>
        </el-upload>
        <el-input
          size="small"
          :model-value="textValue"
          placeholder="或手填服务器上的文件路径"
          clearable
          @update:model-value="(v: string) => emit('update:modelValue', v)"
        />
        <span v-if="shownFilename" class="svf-filename">已上传：{{ shownFilename }}</span>
      </div>

      <!-- 布尔：三态（未设置 / true / false） -->
      <el-select
        v-else-if="node.type === 'boolean'"
        size="small"
        clearable
        placeholder="不传"
        style="width: 160px"
        :model-value="typeof modelValue === 'boolean' ? modelValue : undefined"
        @update:model-value="(v: boolean | undefined) => emit('update:modelValue', v)"
      >
        <el-option label="true" :value="true" />
        <el-option label="false" :value="false" />
      </el-select>

      <!-- 枚举 -->
      <el-select
        v-else-if="enumOptions.length"
        size="small"
        clearable
        placeholder="请选择"
        style="width: 100%"
        :model-value="textValue === '' ? undefined : modelValue"
        @update:model-value="(v: string | number | undefined) => emit('update:modelValue', v ?? '')"
      >
        <el-option v-for="o in enumOptions" :key="String(o.value)" :label="o.label" :value="o.value" />
      </el-select>

      <!-- 字符串 / 整数 / 数字 -->
      <el-input
        v-else
        size="small"
        :model-value="textValue"
        :placeholder="node.type === 'string' ? (node.format || '') : node.type"
        clearable
        @update:model-value="(v: string) => emit('update:modelValue', v)"
      />

      <div v-if="node.description" class="svf-desc">{{ node.description }}</div>
    </div>
  </el-form-item>
</template>

<style scoped>
.svf-control {
  width: 100%;
}
.svf-box {
  width: 100%;
  border: 1px dashed var(--el-border-color);
  border-radius: 4px;
  padding: 8px 8px 0;
}
.svf-box :deep(.el-form-item) {
  margin-bottom: 8px;
}
.svf-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 8px;
}
.svf-idx {
  flex: 0 0 28px;
  line-height: 24px;
  color: var(--tech-text-2);
  font-size: 12px;
}
.svf-item-body {
  flex: 1;
  min-width: 0;
}
.svf-box > .el-button {
  margin-bottom: 8px;
}
.svf-file {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.svf-file .el-input {
  flex: 1;
  min-width: 200px;
}
.svf-filename {
  color: var(--tech-text-2);
  font-size: 12px;
}
.svf-err {
  margin-top: 2px;
  color: var(--el-color-danger);
  font-size: 12px;
}
.svf-json-btn {
  margin-bottom: 8px;
}
.svf-desc {
  margin-top: 2px;
  color: var(--tech-text-2);
  font-size: 12px;
  line-height: 1.4;
}
</style>
