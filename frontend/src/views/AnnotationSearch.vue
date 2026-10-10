<template>
  <div class="annotation-search">
    <PageHeader eyebrow="多模态工作台 / 标注" title="标注查询" subtitle="按文件名检索图片与视频抽样标注；3D 投影为模型估计" />
    <section v-if="scopeId" class="scope-banner" data-testid="annotation-scope">
      <strong>标签结果集范围：{{ scope?.total ?? '未知' }} 条（创建时）</strong>
      <p v-if="scope">{{ scope.source.logic ?? 'AND' }}：
        {{ scope.source.tags.map(t => `${t.source === 'custom' ? '自定义' : '默认'}/${t.category}/${t.name}`).join('、') }}
      </p>
      <p v-else>已恢复快照 ID：{{ scopeId }}。本会话无来源摘要，范围仍由服务端快照限定。</p>
      <p v-if="scope">有效至 {{ formatDate(scope.expires_at) }}。删除或权限变更可能减少可见结果。</p>
      <a-button data-testid="annotation-clear-scope" @click="clearScope">清除结果集范围</a-button>
      <router-link to="/search/tags">返回标签检索重新转入</router-link>
    </section>
    <section class="panel">
      <label for="annotation-filenames">文件名（精确匹配含扩展名的 basename）</label>
      <a-textarea id="annotation-filenames" data-testid="annotation-filenames" v-model:value="filenames" :rows="2"
        placeholder='例如 road.jpg，clip.mp4 或 "road,night.jpg"；支持换行，最多 100 个' />
      <p class="hint">空输入查询全部可见媒体；同名不同路径均返回。结果集转入不上传文件，也不会自动生成标注。</p>
      <div class="filters">
        <label>媒体类型
          <select v-model="fileType" data-testid="annotation-file-type" @change="submitSearch">
            <option value="">全部类型</option><option value="image">图片</option><option value="video">视频</option>
          </select>
        </label>
        <label>标注状态
          <select v-model="status" data-testid="annotation-status" @change="submitSearch">
            <option value="">全部状态</option>
            <option v-for="(label, key) in annotationStatusLabels" :key="key" :value="key">{{ label }}</option>
          </select>
        </label>
        <a-button type="primary" data-testid="annotation-search" :loading="loading" @click="submitSearch">查询</a-button>
        <a-button data-testid="annotation-reset" @click="resetFilters">重置筛选</a-button>
      </div>
    </section>
    <a-alert v-if="error" :message="error" type="error" show-icon />
    <section class="panel">
      <div class="actions">
        <strong>检索结果 {{ total }} 条</strong>
        <span class="hint">视频目标数为各帧检测数累计，不等于去重物体数</span>
        <a-button data-testid="annotation-generate" :disabled="!selected.length || jobBusy" @click="submitJob('generate')">生成标注</a-button>
        <a-button data-testid="annotation-retry" :disabled="!selected.length || jobBusy" @click="submitJob('retry')">重试失败项</a-button>
        <a-button data-testid="annotation-regenerate" :disabled="!selected.length || jobBusy" @click="submitJob('regenerate')">重新生成</a-button>
      </div>
      <p class="hint">仅可选择本人资源。重试沿用原规则快照；生成/重新生成使用默认规则，重新生成保留旧发布版本。</p>
      <div class="table-scroll" :aria-busy="loading">
        <table>
          <thead><tr><th>选择</th><th>文件名 / 来源路径</th><th v-if="auth.isAdmin">归属用户</th><th>类型</th><th>状态</th><th>目标数</th><th>帧进度</th><th>规则</th><th>更新时间</th></tr></thead>
          <tbody>
            <tr v-for="item in results" :key="item.media_id" :data-testid="`annotation-media-${item.media_id}`">
              <td><input v-model="selected" type="checkbox" :value="item.media_id"
                :disabled="!canManage(item) || loading || jobBusy"
                :aria-label="`选择 ${item.file_name}`" /></td>
              <td><button class="detail-link" @click="openDetail(item)">{{ item.file_name }}</button><small class="source-path">{{ item.tos_url }}</small></td>
              <td v-if="auth.isAdmin">{{ item.user_id ?? '未知' }}</td>
              <td>{{ item.file_type === 'video' ? '视频（抽样）' : '图片' }}</td>
              <td>{{ annotationStatusLabels[item.status] }}</td>
              <td>{{ item.latest_run_id || item.published_run_id ? item.object_count : '未标注' }}</td>
              <td>{{ item.progress.completed_frames }}/{{ item.progress.planned_frames }} 成功<br />{{ item.progress.processed_frames }} 已处理 · {{ item.progress.failed_frames }} 失败</td>
              <td>{{ item.annotation_mode === 'custom' ? '自定义' : item.annotation_mode === 'default' ? '默认' : '无' }}</td>
              <td>{{ formatDate(item.updated_at) }}</td>
            </tr>
            <tr v-if="!results.length"><td :colspan="auth.isAdmin ? 9 : 8">{{ loading ? '加载中…' : error ? '查询未成功，未显示其他范围数据' : '无匹配媒体' }}</td></tr>
          </tbody>
        </table>
      </div>
      <a-pagination :current="page" :page-size="size" :total="total" :disabled="loading"
        :show-size-changer="true" :page-size-options="['20', '50', '100']" @change="changePage" />
    </section>
    <AnnotationDetailModal v-model:open="detailOpen" :media-id="detailMediaId" />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Modal, message } from 'ant-design-vue'
import { useAuthStore } from '@/stores/auth'
import { createAnnotationJob, getAnnotationResultSet, searchAnnotations } from '@/api/annotations'
import type { AnnotationJobAction, AnnotationMediaItem, AnnotationMediaType, AnnotationResultSetResponse, AnnotationStatus } from '@/types/annotation'
import {
  annotationHttpStatus, annotationStatusLabels, isAnnotationScopeExpired,
  normalizeAnnotationFilenames, ownsAnnotationMedia, readAnnotationScope, saveAnnotationScope,
} from '@/utils/annotations'
import PageHeader from '@/components/common/PageHeader/PageHeader.vue'
import AnnotationDetailModal from '@/components/AnnotationDetailModal.vue'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const scopeId = computed(() => typeof route.query.scope === 'string' ? route.query.scope : '')
const restoredScope = ref<AnnotationResultSetResponse | null>(null)
const scope = computed(() => restoredScope.value?.result_set_id === scopeId.value ? restoredScope.value
  : scopeId.value && auth.user?.id ? readAnnotationScope(auth.user.id, scopeId.value) : null)
const filenames = ref('')
const fileType = ref<AnnotationMediaType | ''>('')
const status = ref<AnnotationStatus | ''>('')
const submittedFilenames = ref('')
const results = ref<AnnotationMediaItem[]>([])
const selected = ref<string[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)
const error = ref('')
const jobBusy = ref(false)
const detailOpen = ref(false)
const detailMediaId = ref<string | null>(null)
let requestVersion = 0
let controller: AbortController | null = null
let jobController: AbortController | null = null
let disposed = false
let confirmation: ReturnType<typeof Modal.confirm> | null = null

function formatDate(value: string | null) { return value ? new Date(value).toLocaleString() : '无' }
function canManage(item: AnnotationMediaItem) { return ownsAnnotationMedia(item, auth.user?.id, !auth.isAdmin) }

async function fetchResults(nextPage = 1) {
  const version = ++requestVersion
  controller?.abort()
  controller = new AbortController()
  selected.value = []
  results.value = []
  total.value = 0
  error.value = ''
  page.value = nextPage
  if ('scope' in route.query && !scopeId.value) {
    loading.value = false
    error.value = '结果集范围参数无效，请清除 URL 中的 scope 参数或返回标签检索重新转入。'
    return
  }
  if (isAnnotationScopeExpired(scope.value)) {
    loading.value = false
    error.value = '结果集快照已过期，请返回标签检索重新转入，或明确清除范围后查询。'
    return
  }
  loading.value = true
  try {
    if (scopeId.value && restoredScope.value?.result_set_id !== scopeId.value) {
      const metadata = await getAnnotationResultSet(scopeId.value, controller.signal)
      if (version !== requestVersion) return
      restoredScope.value = metadata.data
      if (auth.user?.id) saveAnnotationScope(auth.user.id, metadata.data)
      if (isAnnotationScopeExpired(metadata.data)) {
        error.value = '结果集快照已过期，请返回标签检索重新转入。'
        return
      }
    }
    const response = await searchAnnotations({
      filenames: submittedFilenames.value, file_type: fileType.value || null,
      status: status.value || null, result_set_id: scopeId.value || null, page: nextPage, size: size.value,
    }, controller.signal)
    if (version !== requestVersion) return
    results.value = response.data.results
    total.value = response.data.total
    page.value = response.data.page
    const lastPage = Math.max(1, Math.ceil(total.value / size.value))
    if (nextPage > lastPage) await fetchResults(lastPage)
  } catch (cause) {
    if (version !== requestVersion) return
    error.value = scopeId.value && [404, 410].includes(annotationHttpStatus(cause) ?? 0)
      ? '结果集快照已过期或不可访问，请返回标签检索重新转入。不会自动查询全部媒体。'
      : '标注查询失败，请检查权限和服务状态后重试。'
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function submitSearch() {
  try { submittedFilenames.value = normalizeAnnotationFilenames(filenames.value) }
  catch (cause) {
    requestVersion++
    controller?.abort()
    loading.value = false
    results.value = []
    total.value = 0
    selected.value = []
    error.value = (cause as Error).message
    return
  }
  return fetchResults(1)
}

function resetFilters() {
  filenames.value = ''
  fileType.value = ''
  status.value = ''
  return submitSearch()
}

function changePage(nextPage: number, nextSize: number) {
  const resized = size.value !== nextSize
  size.value = nextSize
  return fetchResults(resized ? 1 : nextPage)
}

async function clearScope() {
  const hadScopeId = !!scopeId.value
  const query = { ...route.query }
  delete query.scope
  restoredScope.value = null
  await router.replace({ query })
  // Removing an empty/invalid scope does not change scopeId, so its watcher
  // cannot restart the unscoped query.
  if (!hadScopeId) return submitSearch()
}

function openDetail(item: AnnotationMediaItem) {
  detailMediaId.value = item.media_id
  detailOpen.value = true
}

function submitJob(action: AnnotationJobAction) {
  if (jobBusy.value) return
  const items = results.value.filter(item => selected.value.includes(item.media_id))
  if (!items.length || items.some(item => !canManage(item))) return
  const retryable = ['partial', 'failed', 'cancelled']
  if (action === 'retry' && items.some(item => !retryable.includes(item.status))) {
    message.warning('重试仅支持部分失败、失败或已取消的本人资源')
    return
  }
  confirmation = Modal.confirm({
    title: action === 'retry' ? '重试失败/未完成帧？' : action === 'regenerate' ? '创建新的标注版本？' : '为选中媒体生成标注？',
    content: `${items.length} 个本人资源。将增加模型调用和处理时间，可能产生费用；不重新生成标签或向量。`,
    async onOk() {
      if (disposed || jobBusy.value || items.some(item => !canManage(item))) return
      jobBusy.value = true
      jobController = new AbortController()
      try {
        const response = await createAnnotationJob({ media_ids: items.map(item => item.media_id), action }, jobController.signal)
        if (disposed) return
        message.success(`标注任务已提交：${response.data.task_id}，可在任务管理查看进度`)
        await fetchResults(page.value)
      } catch {
        if (!disposed) message.error('任务提交未确认，请先在任务管理检查，避免重复提交')
      } finally { jobBusy.value = false }
    },
  })
}

watch(scopeId, () => { void submitSearch() }, { immediate: true })
onBeforeUnmount(() => {
  disposed = true
  requestVersion++
  controller?.abort()
  jobController?.abort()
  confirmation?.destroy()
})
</script>

<style scoped>
.annotation-search { display: flex; flex-direction: column; gap: 20px; }
.panel, .scope-banner {
  background: var(--white);
  border: 1px solid var(--color-border);
  padding: 24px;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
}
.scope-banner {
  background: var(--mint-soft);
  border-color: transparent;
  overflow-wrap: anywhere;
  color: var(--mint-ink);
  box-shadow: none;
}
.scope-banner strong { color: var(--mint-ink); }
.scope-banner p { margin: 8px 0; font-size: 13px; line-height: 1.7; }
.scope-banner a { margin-left: 16px; }
.filters, .actions { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin: 14px 0 0; }
.actions { margin: 0 0 4px; }
.actions strong { font-size: 14px; color: var(--gray-900); margin-right: 4px; }
.actions .hint { margin: 0; flex-basis: 100%; order: 5; }
.actions .hint + * { margin-left: 0; }
.panel > label {
  display: block;
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 500;
  color: var(--gray-700);
}
.filters label {
  display: inline-flex;
  align-items: center;
  margin: 0;
  color: var(--gray-500);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.14em;
}
select {
  margin-left: 10px;
  padding: 0 32px 0 12px;
  height: 36px;
  border: 1px solid var(--gray-200);
  border-radius: var(--radius);
  background: var(--white) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%237f8e92' stroke-width='1.4' stroke-linecap='round'/%3E%3C/svg%3E") no-repeat right 12px center;
  color: var(--gray-800);
  font: 13px var(--font-body);
  letter-spacing: 0;
  text-transform: none;
  appearance: none;
  -webkit-appearance: none;
  cursor: pointer;
  transition: border-color var(--transition-default), box-shadow var(--duration-normal) var(--ease-default);
}
select:hover { border-color: var(--gray-400); }
select:focus { outline: none; border-color: var(--color-primary); box-shadow: 0 0 0 4px var(--color-primary-ring); }
.hint { color: var(--gray-500); font-size: 12px; margin: 10px 0 0; line-height: 1.7; }
.table-scroll { overflow-x: auto; margin: 18px 0 16px; border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); }
table { width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; }
th, td { padding: 12px 14px; border-bottom: 1px solid var(--color-border-subtle); min-width: 70px; vertical-align: top; }
th {
  background: var(--gray-50);
  color: var(--gray-500);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.14em;
  white-space: nowrap;
}
tbody tr { transition: background var(--transition-default); }
tbody tr:hover { background: var(--gray-50); }
tbody tr:last-child td { border-bottom: 0; }
td[colspan] { text-align: center; padding: 36px 14px; color: var(--gray-500); }
td { color: var(--gray-700); line-height: 1.6; }
input[type="checkbox"] { width: 15px; height: 15px; accent-color: var(--ink); cursor: pointer; }
input[type="checkbox"]:disabled { cursor: not-allowed; }
.source-path { display: block; color: var(--gray-400); font: 11px var(--font-mono); overflow-wrap: anywhere; max-width: 360px; margin-top: 3px; }
.detail-link {
  padding: 0; background: none; border: 0;
  color: var(--color-primary); font-weight: 500;
  text-align: left; cursor: pointer; overflow-wrap: anywhere;
  transition: color var(--transition-default);
}
.detail-link:hover { color: var(--color-primary-dark); text-decoration: underline; text-underline-offset: 3px; }
@media (max-width: 600px) {
  .panel, .scope-banner { padding: 18px; }
  .filters label { width: 100%; justify-content: space-between; }
  select { flex: 1; }
}
</style>
