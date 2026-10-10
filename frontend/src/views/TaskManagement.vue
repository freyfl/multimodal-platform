<template>
  <div class="task-management-page">
    <PageHeader eyebrow="多模态工作台 / 任务" title="任务管理" subtitle="管理数据处理、标注、检索任务，点击行可展开数据预览">
      <template #extra>
        <a-button @click="handleRefresh" :loading="importStore.isLoading">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
      </template>
    </PageHeader>

    <!-- 筛选栏 -->
    <GlassCard class="filter-card" padding="12px 20px">
      <div class="filter-bar">
        <div class="filter-tabs">
          <button
            v-for="item in statusFilters"
            :key="item.value"
            class="filter-tab"
            :class="{ active: currentFilter === item.value }"
            @click="currentFilter = item.value"
          >
            {{ item.label }}
            <span v-if="item.count > 0" class="filter-count">{{ item.count }}</span>
          </button>
        </div>
        <div class="filter-right">
          <a-input
            v-model:value="searchKeyword"
            placeholder="搜索任务名称..."
            allow-clear
            class="search-input"
          >
            <template #prefix><SearchOutlined /></template>
          </a-input>
        </div>
      </div>
    </GlassCard>

    <!-- 任务表格 -->
    <GlassCard class="table-card" padding="0">
      <div class="table-responsive">
        <a-table
          :columns="columns"
          :data-source="filteredTasks"
          :row-key="(record: ImportTask) => record.task_id"
          :loading="importStore.isLoading"
          :pagination="false"
          :expand-column-width="48"
          :scroll="{ x: 1310 }"
          v-model:expandedRowKeys="expandedRowKeys"
          :custom-row="customRow"
          class="task-table"
        >
          <!-- 展开行 -->
          <template #expandedRowRender="{ record }">
            <div class="expand-panel">
              <div class="expand-grid">
                <!-- 任务进度 -->
                <div class="expand-section">
                  <div class="expand-section-title">任务进度</div>
                  <ProgressBar
                    :percent="getProgress(record)"
                    :color="getProgressColor(record)"
                    :animated="record.status === 'running'"
                  />
                  <div class="expand-stats">
                    <div class="expand-stat">
                      <span class="stat-label">已处理</span>
                      <span class="stat-value">{{ record.processed_files }}</span>
                    </div>
                    <div class="expand-stat">
                      <span class="stat-label">总文件</span>
                      <span class="stat-value">{{ record.total_files }}</span>
                    </div>
                    <div class="expand-stat">
                      <span class="stat-label">成功</span>
                      <span class="stat-value">{{ Math.max(0, record.processed_files - record.failed_files) }}</span>
                    </div>
                    <div class="expand-stat">
                      <span class="stat-label">失败</span>
                      <span class="stat-value" :class="{ 'stat-error': record.failed_files > 0 }">{{ record.failed_files }}</span>
                    </div>
                  </div>
                </div>

                <!-- 任务信息 -->
                <div class="expand-section">
                  <div class="expand-section-title">任务信息</div>
                  <div class="expand-info-list">
                    <div class="expand-info-row">
                      <span class="info-label">TOS目录</span>
                      <span class="info-value info-mono">{{ record.tos_directory }}</span>
                    </div>
                    <div class="expand-info-row">
                      <span class="info-label">状态</span>
                      <a-tag :color="statusColor(record.status)">{{ statusText(record.status) }}</a-tag>
                    </div>
                    <div class="expand-info-row">
                      <span class="info-label">标签模式</span>
                      <span class="info-value">{{ getTagModeLabel(record.tag_mode) }}</span>
                    </div>
                    <div v-if="record.current_stage" class="expand-info-row">
                      <span class="info-label">当前阶段</span>
                      <span class="info-value">{{ stageText(record.current_stage) }}</span>
                    </div>
                    <div v-if="record.vector_status" class="expand-info-row">
                      <span class="info-label">向量阶段</span>
                      <a-tag :color="statusColor(record.vector_status)">{{ statusText(record.vector_status) }}</a-tag>
                    </div>
                    <div v-if="record.tag_status" class="expand-info-row">
                      <span class="info-label">标签阶段</span>
                      <a-tag :color="statusColor(record.tag_status)">{{ statusText(record.tag_status) }}</a-tag>
                    </div>
                    <div class="expand-info-row">
                      <span class="info-label">创建时间</span>
                      <span class="info-value">{{ formatTime(record.created_at) }}</span>
                    </div>
                    <div v-if="record.started_at" class="expand-info-row">
                      <span class="info-label">开始时间</span>
                      <span class="info-value">{{ formatTime(record.started_at) }}</span>
                    </div>
                    <div v-if="record.completed_at" class="expand-info-row">
                      <span class="info-label">完成时间</span>
                      <span class="info-value">{{ formatTime(record.completed_at) }}</span>
                    </div>
                  </div>
                </div>

                <div class="expand-section annotation-section">
                  <div class="expand-section-title">独立标注阶段</div>
                  <a-tag :color="statusColor(annotationStatus(record))">{{ annotationStatusText(record) }}</a-tag>
                  <div v-if="record.annotation_mode" class="annotation-detail">
                    {{ record.annotation_mode === 'custom' ? '自定义标注' : '默认标注' }}
                    · {{ record.annotation_box_mode === '2d' ? '2D 框' : '2D + 3D 投影框（模型估计）' }}
                  </div>
                  <template v-if="record.annotation_progress">
                    <div class="annotation-detail">
                      文件：已处理 {{ record.annotation_progress.processed_files }} / {{ record.annotation_progress.total_files }}，
                      成功 {{ record.annotation_progress.completed_files }}，失败 {{ record.annotation_progress.failed_files }}
                    </div>
                    <div class="annotation-detail">
                      抽样帧：已处理 {{ record.annotation_progress.processed_frames }} / 计划 {{ record.annotation_progress.planned_frames }}，
                      成功 {{ record.annotation_progress.completed_frames }}，失败 {{ record.annotation_progress.failed_frames }}
                    </div>
                    <ProgressBar
                      :percent="annotationPercent(record)"
                      :color="annotationStatus(record) === 'completed' ? 'green' : 'blue'"
                      :animated="annotationStatus(record) === 'running'"
                    />
                    <div class="annotation-detail">
                      当前媒体：{{ record.annotation_progress.current_media_id ?? '-' }}；
                      当前帧：{{ record.annotation_progress.current_frame_index == null ? '-' : record.annotation_progress.current_frame_index + 1 }}；
                      标注已耗时：{{ formatElapsed(record.annotation_progress.elapsed_ms) }}
                    </div>
                  </template>
                  <div v-if="record.annotation_sample_interval_seconds" class="annotation-detail">
                    目标间隔 {{ record.annotation_sample_interval_seconds }} 秒，每视频最多 {{ record.annotation_max_frames }} 帧。抽样不代表覆盖每一帧。
                  </div>
                  <a-alert
                    v-if="['partial', 'failed', 'cancelled'].includes(annotationStatus(record))"
                    type="warning"
                    message="标注未全部完成；已成功的帧和原有标签、向量保留。重试仅处理失败或未完成帧，并使用原任务规则。"
                    show-icon
                  />
                </div>
              </div>
            </div>
          </template>

          <!-- 任务名称列 -->
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'name'">
              <div class="task-name" :title="record.tos_directory">
                <FolderOutlined class="name-icon" />
                <span class="name-text">{{ record.task_id }}</span>
              </div>
            </template>

            <template v-else-if="column.key === 'status'">
              <a-tag :color="statusColor(record.status)">{{ statusText(record.status) }}</a-tag>
            </template>

            <template v-else-if="column.key === 'tag_mode'">
              <span class="tag-mode-cell">{{ getTagModeLabel(record.tag_mode) }}</span>
            </template>

            <template v-else-if="column.key === 'annotation'">
              <a-tag :color="statusColor(annotationStatus(record))">{{ annotationStatusText(record) }}</a-tag>
              <div v-if="record.annotation_progress" class="annotation-detail">
                文件 {{ record.annotation_progress.processed_files }}/{{ record.annotation_progress.total_files }}；
                帧 {{ record.annotation_progress.processed_frames }}/{{ record.annotation_progress.planned_frames }}
              </div>
            </template>

            <template v-else-if="column.key === 'progress'">
              <div class="progress-cell">
                <ProgressBar
                  :percent="getProgress(record)"
                  :color="getProgressColor(record)"
                  :animated="record.status === 'running'"
                  :show-text="false"
                />
                <span class="progress-text">{{ getProgressText(record) }}</span>
              </div>
            </template>

            <template v-else-if="column.key === 'counts'">
              <div class="counts-cell">
                <span class="count-item">
                  <span class="count-label">总</span>{{ record.total_files }}
                </span>
                <span class="count-divider">/</span>
                <span class="count-item count-success">
                  <span class="count-label">成</span>{{ Math.max(0, record.processed_files - record.failed_files) }}
                </span>
                <span class="count-divider">/</span>
                <span class="count-item" :class="{ 'count-error': record.failed_files > 0 }">
                  <span class="count-label">败</span>{{ record.failed_files }}
                </span>
              </div>
            </template>

            <template v-else-if="column.key === 'created_at'">
              <span class="time-cell">{{ formatTime(record.created_at) }}</span>
            </template>

            <template v-else-if="column.key === 'actions'">
              <div class="action-cell" @click.stop>
                <a-tooltip title="展开详情">
                  <a-button
                    type="text"
                    size="small"
                    @click="toggleExpand(record.task_id)"
                  >
                    <template #icon>
                      <EyeOutlined v-if="!expandedRowKeys.includes(record.task_id)" />
                      <EyeInvisibleOutlined v-else />
                    </template>
                  </a-button>
                </a-tooltip>
                <a-tooltip v-if="record.status === 'running' || record.status === 'pending'" title="取消任务">
                  <a-popconfirm
                    title="确认取消该任务？"
                    ok-text="确认"
                    cancel-text="取消"
                    @confirm="handleCancel(record.task_id)"
                  >
                    <a-button type="text" size="small" danger>
                      <template #icon><StopOutlined /></template>
                    </a-button>
                  </a-popconfirm>
                </a-tooltip>
                <a-popconfirm
                  v-if="isAnnotationRetryable(record)"
                  title="按原规则重试失败 / 未完成帧？将增加模型调用费用，成功帧不会重做。"
                  ok-text="确认重试"
                  cancel-text="取消"
                  :disabled="!retryMediaIds(record).length || retrying.has(record.task_id) || retrySubmitted.has(record.task_id)"
                  @confirm="handleAnnotationRetry(record)"
                >
                  <a-button
                    type="link"
                    size="small"
                    :loading="retrying.has(record.task_id)"
                    :disabled="!retryMediaIds(record).length || retrySubmitted.has(record.task_id)"
                    :title="retryMediaIds(record).length ? '使用原任务快照，仅重试标注' : '任务未返回可重试媒体，请前往标注查询选择本人资源'"
                  >{{ retrySubmitted.has(record.task_id) ? '已提交重试' : '重试标注' }}</a-button>
                </a-popconfirm>
              </div>
            </template>
          </template>

          <!-- 空状态 -->
          <template #emptyText>
            <EmptyState
              title="暂无任务"
              description="前往「数据导入」页面创建导入任务"
              :icon="UnorderedListOutlined"
            />
          </template>
        </a-table>
      </div>
    </GlassCard>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { message } from 'ant-design-vue'
import { createAnnotationJob } from '@/api/annotations'
import {
  ReloadOutlined,
  SearchOutlined,
  FolderOutlined,
  EyeOutlined,
  EyeInvisibleOutlined,
  StopOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons-vue'
import PageHeader from '@/components/common/PageHeader/PageHeader.vue'
import GlassCard from '@/components/common/GlassCard/GlassCard.vue'
import ProgressBar from '@/components/common/ProgressBar/ProgressBar.vue'
import EmptyState from '@/components/common/EmptyState/EmptyState.vue'
import { useImportStore } from '@/stores/import'
import { useTaskPolling } from '@/composables/useTaskPolling'
import { getTagModeLabel } from '@/constants/tags'
import type { ImportTask } from '@/types'
import type { AnnotationJobRequest } from '@/types/annotation'

const importStore = useImportStore()

const currentFilter = ref('all')
const searchKeyword = ref('')
const expandedRowKeys = ref<string[]>([])
const retrying = ref(new Set<string>())
const retrySubmitted = ref(new Set<string>())
const submittedMediaIds = new Map<string, Set<string>>()

// Never turn successful file transfer into "all completed" when an enabled stage failed.
function taskStatus(task: ImportTask): ImportTask['status'] {
  if (task.status !== 'completed') return task.status
  const stages = [
    task.generate_vectors !== false ? task.vector_status : undefined,
    task.generate_tags !== false ? task.tag_status : undefined,
    task.generate_annotations !== false ? task.annotation_status : undefined,
  ]
  if (task.failed_files > 0 || stages.some(status => ['failed', 'partial', 'cancelled'].includes(status ?? ''))
    || (task.generate_annotations !== false && ((task.annotation_progress?.failed_frames ?? 0) > 0
      || (task.annotation_progress?.failed_files ?? 0) > 0))) return 'partial'
  if (stages.some(status => status === 'running' || status === 'processing')) return 'running'
  if (stages.includes('pending')) return 'pending'
  if (task.generate_annotations && (!task.annotation_status || task.annotation_status === 'not_started'
    || task.annotation_status === 'skipped')) return 'partial'
  return task.status
}

const displayTasks = computed(() => importStore.tasks.map(task => ({ ...task, status: taskStatus(task) })))

function annotationStatus(task: ImportTask) {
  return task.annotation_status ?? (task.generate_annotations === false ? 'skipped' : 'not_started')
}

function annotationStatusText(task: ImportTask) {
  if (!task.annotation_status && task.generate_annotations == null) return '历史未标注'
  return statusText(annotationStatus(task))
}

function statusText(status: string): string {
  const labels: Record<string, string> = {
    not_started: '未标注', pending: '等待中', running: '运行中', processing: '处理中',
    completed: '已完成', done: '已完成', partial: '部分失败', failed: '失败',
    skipped: '已跳过', cancelled: '已取消',
  }
  return labels[status] ?? status
}

function statusColor(status: string): string {
  if (['failed', 'partial'].includes(status)) return 'error'
  if (['running', 'processing'].includes(status)) return 'processing'
  if (status === 'pending') return 'warning'
  if (['completed', 'done'].includes(status)) return 'success'
  return 'default'
}

function stageText(stage: string): string {
  const labels: Record<string, string> = {
    import: '导入', vector: '向量', vectors: '向量', embedding: '向量',
    tag: '标签', tags: '标签', annotation: '标注', annotations: '标注',
  }
  return labels[stage] ?? stage
}

function annotationPercent(task: ImportTask): number {
  const progress = task.annotation_progress
  return progress?.planned_frames
    ? Math.min(100, Math.round(progress.processed_frames / progress.planned_frames * 100)) : 0
}

function formatElapsed(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))
  return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
}

function isAnnotationRetryable(task: ImportTask): boolean {
  return !['pending', 'running'].includes(task.status)
    && task.generate_annotations !== false
    && ['partial', 'failed', 'cancelled'].includes(annotationStatus(task))
}

function retryMediaIds(task: ImportTask): string[] {
  return [...new Set(task.annotation_retry_media_ids ?? [])]
}

async function handleAnnotationRetry(task: ImportTask) {
  const accepted = submittedMediaIds.get(task.task_id) ?? new Set<string>()
  const ids = retryMediaIds(task).filter(id => !accepted.has(id))
  if (!isAnnotationRetryable(task) || !ids.length || retrying.value.has(task.task_id)
    || retrySubmitted.value.has(task.task_id)) return
  retrying.value.add(task.task_id)
  let submitted = 0
  try {
    for (let offset = 0; offset < ids.length; offset += 100) {
      const request: AnnotationJobRequest = { media_ids: ids.slice(offset, offset + 100), action: 'retry' }
      const response = await createAnnotationJob(request)
      if (!response.data?.task_id || ['failed', 'partial', 'cancelled'].includes(response.data.status)) {
        throw new Error('Annotation retry was not accepted')
      }
      request.media_ids.forEach(id => accepted.add(id))
      submittedMediaIds.set(task.task_id, accepted)
      submitted += request.media_ids.length
    }
    retrySubmitted.value.add(task.task_id)
    message.success(`已提交 ${submitted} 个媒体的标注重试，未重做标签或向量`)
  } catch {
    if (submitted) message.warning(`已提交 ${submitted} 个媒体，其余提交失败；请刷新任务后重试未完成项`)
    else message.error('标注重试未成功提交，请检查任务状态后重试')
  } finally {
    retrying.value.delete(task.task_id)
    await importStore.fetchTasks()
  }
}

// 状态筛选项
const statusFilters = computed(() => {
  const tasks = displayTasks.value
  return [
    { label: '全部', value: 'all', count: tasks.length },
    { label: '运行中', value: 'running', count: tasks.filter(t => t.status === 'running').length },
    { label: '等待中', value: 'pending', count: tasks.filter(t => t.status === 'pending').length },
    { label: '已完成', value: 'completed', count: tasks.filter(t => t.status === 'completed').length },
    { label: '部分失败', value: 'partial', count: tasks.filter(t => t.status === 'partial').length },
    { label: '失败', value: 'failed', count: tasks.filter(t => t.status === 'failed').length },
    { label: '已取消', value: 'cancelled', count: tasks.filter(t => t.status === 'cancelled').length },
  ]
})

// 筛选后的任务列表
const filteredTasks = computed(() => {
  let tasks = displayTasks.value
  if (currentFilter.value !== 'all') {
    tasks = tasks.filter(t => t.status === currentFilter.value)
  }
  if (searchKeyword.value.trim()) {
    const kw = searchKeyword.value.toLowerCase()
    tasks = tasks.filter(t => t.tos_directory.toLowerCase().includes(kw) || t.task_id.toLowerCase().includes(kw))
  }
  // 按创建时间倒序
  return [...tasks].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
})

// 是否有运行中任务
const hasRunningTasks = computed(() =>
  displayTasks.value.some(t => t.status === 'running' || t.status === 'pending')
)

// 表格列定义
const columns = [
  { title: '任务名称', key: 'name', ellipsis: true, width: 220 },
  { title: '状态', key: 'status', width: 110 },
  { title: '标签模式', key: 'tag_mode', width: 100 },
  { title: '标注阶段', key: 'annotation', width: 220 },
  { title: '进度', key: 'progress', width: 160 },
  { title: '文件统计', key: 'counts', width: 160 },
  { title: '创建时间', key: 'created_at', width: 160 },
  { title: '操作', key: 'actions', width: 180, fixed: 'right' as const },
]

// 行点击展开
const customRow = (record: ImportTask) => ({
  onClick: () => toggleExpand(record.task_id),
  style: { cursor: 'pointer' },
})

function toggleExpand(taskId: string) {
  const idx = expandedRowKeys.value.indexOf(taskId)
  if (idx >= 0) {
    expandedRowKeys.value = expandedRowKeys.value.filter(k => k !== taskId)
  } else {
    expandedRowKeys.value = [taskId]
  }
}

function getProgress(task: ImportTask): number {
  if (task.total_files === 0) return 0
  return Math.min(100, Math.round((task.processed_files / task.total_files) * 100))
}

function getProgressText(task: ImportTask): string {
  if (task.status === 'running' && task.processed_files === 0) return '处理中'
  return `${getProgress(task)}%`
}

function getProgressColor(task: ImportTask): 'blue' | 'green' | 'orange' {
  if (task.status === 'completed') return 'green'
  if (['failed', 'partial', 'cancelled'].includes(task.status)) return 'orange'
  return 'blue'
}

function formatTime(timeStr: string | undefined): string {
  if (!timeStr) return '-'
  try {
    const d = new Date(timeStr)
    return d.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return timeStr
  }
}

async function handleRefresh() {
  await importStore.fetchTasks()
}

async function handleCancel(taskId: string) {
  await importStore.cancelTask(taskId)
}

// 自动轮询
const { startPolling, stopPolling } = useTaskPolling({
  interval: 5000,
  shouldPoll: () => hasRunningTasks.value,
  onPoll: () => importStore.fetchTasks(),
})

// 监听运行中任务，自动开始/停止轮询
watch(hasRunningTasks, (val) => {
  if (val) {
    startPolling()
  } else {
    stopPolling()
  }
}, { immediate: true })

onMounted(async () => {
  await importStore.fetchTasks()
  if (hasRunningTasks.value) {
    startPolling()
  }
})
</script>

<style scoped>
.task-management-page {
  animation: fadeInUp 0.4s ease both;
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ── 筛选栏 ── */
.filter-card {
  margin-bottom: 16px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 16px;
}

.filter-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  background: var(--gray-100, #f1f5f9);
  padding: 3px;
  border-radius: var(--radius-md, 10px);
}

.filter-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: none;
  border-radius: var(--radius-sm, 6px);
  background: transparent;
  color: var(--gray-500, #64748b);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  font-family: var(--font-body);
  white-space: nowrap;
}

.filter-tab:hover {
  color: var(--gray-700, #334155);
}

.filter-tab.active {
  background: var(--white, #ffffff);
  color: var(--gray-900, #0f172a);
  box-shadow: var(--shadow-sm, 0 1px 2px rgba(0,0,0,0.05));
}

.filter-count {
  font-size: 10px;
  min-width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 9px;
  background: var(--gray-200, #e2e8f0);
  color: var(--gray-600, #475569);
  font-weight: 600;
  padding: 0 5px;
}

.filter-tab.active .filter-count {
  background: var(--color-primary, #0064ff);
  color: #fff;
}

.filter-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}

.search-input {
  width: 220px;
}

/* ── 表格卡片 ── */
.table-card {
  margin-bottom: 24px;
}

.table-responsive {
  overflow-x: auto;
}

/* ── 表格样式覆盖 ── */
.task-table :deep(.ant-table) {
  background: transparent;
}

.task-table :deep(.ant-table-thead > tr > th) {
  background: var(--gray-50);
  border-bottom: 1px solid var(--color-border);
  padding: 12px 16px;
}

.task-table :deep(.ant-table-tbody > tr > td) {
  border-bottom: 1px solid var(--color-border-subtle, #f1f5f9);
  padding: 12px 16px;
  font-size: 13px;
  color: var(--gray-700, #334155);
  transition: background 0.15s ease;
}

.task-table :deep(.ant-table-tbody > tr:hover > td) {
  background: var(--gray-50, #f8fafc) !important;
}

.task-table :deep(.ant-table-tbody > tr.ant-table-expanded-row > td) {
  background: transparent !important;
  padding: 0;
}

.task-table :deep(.ant-table-tbody > tr.ant-table-expanded-row:hover > td) {
  background: transparent !important;
}

.task-table :deep(.ant-table-expand-icon-col) {
  width: 48px;
}

.task-table :deep(.ant-table-row-expand-icon) {
  color: var(--gray-400, #94a3b8);
  border-color: var(--gray-300, #cbd5e1);
}

/* 移除固定列产生的多余阴影和边框 */
.task-table :deep(.ant-table-cell-fix-right-first::after),
.task-table :deep(.ant-table-cell-fix-right::after) {
  box-shadow: none !important;
  border: none !important;
}

.task-table :deep(.ant-table-cell-fix-right) {
  background: inherit;
}

/* ── 任务名称 ── */
.task-name {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 200px;
}

.name-icon {
  color: var(--mint-deep);
  font-size: 14px;
  flex-shrink: 0;
}

.name-text {
  font-weight: 600;
  color: var(--gray-800, #1e293b);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── 进度列 ── */
.progress-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.progress-cell .progress-text {
  font-family: var(--font-mono, monospace);
  font-size: var(--text-xs, 11px);
  color: var(--gray-500, #64748b);
  font-weight: 500;
  min-width: 32px;
  text-align: right;
}

/* ── 文件统计 ── */
.counts-cell {
  display: flex;
  align-items: center;
  gap: 2px;
  font-family: var(--font-mono, monospace);
  font-size: var(--text-xs, 11px);
}

.count-item {
  color: var(--gray-600, #475569);
  font-weight: 500;
}

.count-label {
  color: var(--gray-400, #94a3b8);
  font-size: 10px;
  margin-right: 2px;
}

.count-success {
  color: var(--color-success, #10b981);
}

.count-error {
  color: var(--color-error, #ef4444);
}

.count-divider {
  color: var(--gray-300, #cbd5e1);
  margin: 0 2px;
}

/* ── 时间列 ── */
.time-cell {
  color: var(--gray-400, #94a3b8);
  font-size: var(--text-xs, 11px);
  white-space: nowrap;
}

.tag-mode-cell {
  color: var(--gray-600, #475569);
  font-size: var(--text-sm, 12px);
  white-space: nowrap;
}

/* ── 操作列 ── */
.action-cell {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* ── 展开面板 ── */
.expand-panel {
  background: var(--gray-50, #f8fafc);
  border-left: 3px solid var(--color-primary, #0064ff);
  padding: 16px 20px;
  animation: slideDown 0.2s ease;
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

.expand-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.expand-section {
  background: var(--white, #ffffff);
  border-radius: var(--radius-md, 10px);
  padding: 14px 18px;
  border: 1px solid var(--color-border, #e2e8f0);
}

.expand-section-title {
  font-size: var(--text-xs, 11px);
  color: var(--gray-400, #94a3b8);
  font-weight: 600;
  letter-spacing: 0.5px;
  margin-bottom: 10px;
}

.annotation-section {
  grid-column: 1 / -1;
}

.annotation-detail {
  margin: 8px 0;
  font-size: var(--text-sm, 12px);
  color: var(--gray-600, #475569);
  overflow-wrap: anywhere;
}

.expand-stats {
  display: flex;
  gap: 20px;
  margin-top: 12px;
}

.expand-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-label {
  font-size: 10px;
  color: var(--gray-400, #94a3b8);
}

.stat-value {
  font-size: var(--text-caption, 13px);
  font-weight: 600;
  color: var(--gray-800, #1e293b);
  font-family: var(--font-mono, monospace);
}

.stat-success {
  color: var(--color-success, #10b981);
}

.stat-error {
  color: var(--color-error, #ef4444);
}

/* ── 展开信息列表 ── */
.expand-info-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.expand-info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.info-label {
  font-size: var(--text-sm, 12px);
  color: var(--gray-400, #94a3b8);
}

.info-value {
  font-size: var(--text-sm, 12px);
  color: var(--gray-600, #475569);
}

.info-mono {
  font-family: var(--font-mono, monospace);
  font-size: var(--text-xs, 11px);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── 响应式 ── */
@media (max-width: 768px) {
  .filter-bar {
    flex-wrap: wrap;
  }
  .filter-right {
    margin-left: 0;
    width: 100%;
  }
  .search-input {
    width: 100%;
  }
  .expand-grid {
    grid-template-columns: 1fr;
  }
}
</style>
