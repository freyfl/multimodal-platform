<template>
  <div class="data-import-page">
    <PageHeader eyebrow="MULTIMODAL / INGEST" title="数据导入" subtitle="从对象存储（TOS）导入多模态数据" />

    <!-- TOS 导入配置区 -->
    <GlassCard class="tos-config-section">
        <template #header>
          <div class="section-title">
            <CloudUploadOutlined class="title-icon" />
            <span>TOS 导入配置</span>
          </div>
        </template>

        <ImportForm :loading="importStore.isImporting" @submit="startImportAction" />
      </GlassCard>

    <!-- 导入历史 -->
    <GlassCard class="history-section">
      <template #header>
        <div class="section-header">
          <div class="section-title">
            <UnorderedListOutlined class="title-icon" />
            <span>导入历史</span>
            <span class="task-count" v-if="importStore.tasks.length > 0">{{ importStore.tasks.length }}</span>
          </div>
          <a-button type="link" @click="refreshTasks" :loading="importStore.isLoading" class="refresh-btn">
            <ReloadOutlined />
            刷新
          </a-button>
        </div>
      </template>

      <a-table
        v-if="importStore.tasks.length > 0"
        :dataSource="displayTasks"
        :columns="historyColumns"
        :pagination="false"
        :rowKey="(record: any) => record.task_id"
        size="middle"
        class="history-table"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.dataIndex === 'task_id'">
            <span class="table-task-id">{{ record.task_id }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'tos_directory'">
            <span class="table-tos-path">{{ record.tos_directory }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'total_files'">
            {{ record.total_files ?? '-' }}
          </template>
          <template v-else-if="column.dataIndex === 'tag_mode'">
            <span class="tag-mode-text">{{ getTagModeLabel(record.tag_mode) }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'status'">
            <a-tag v-if="record.status === 'partial'" color="error">部分失败</a-tag>
            <StatusBadge v-else :status="record.status" :text="getStatusText(record.status)" />
          </template>
          <template v-else-if="column.dataIndex === 'annotation_status'">
            <span>{{ getAnnotationStatusText(record) }}</span>
            <div v-if="record.annotation_progress" class="tag-mode-text">
              文件 {{ record.annotation_progress.processed_files }}/{{ record.annotation_progress.total_files }}；
              帧 {{ record.annotation_progress.processed_frames }}/{{ record.annotation_progress.planned_frames }}
            </div>
          </template>
          <template v-else-if="column.dataIndex === 'created_at'">
            {{ formatTime(record.created_at) }}
          </template>
          <template v-else-if="column.key === 'action'">
            <a-popconfirm
              v-if="record.status === 'running' || record.status === 'pending'"
              title="确定取消此任务?"
              @confirm="cancelTask(record.task_id)"
            >
              <a-button type="link" danger size="small">取消</a-button>
            </a-popconfirm>
            <a-button v-else type="link" size="small" disabled>
              <EyeOutlined />
            </a-button>
          </template>
        </template>
      </a-table>

      <EmptyState
        v-else
        title="暂无导入任务"
        description="配置TOS目录后开始导入"
        :icon="InboxOutlined"
      />
    </GlassCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  CloudUploadOutlined,
  UnorderedListOutlined,
  ReloadOutlined,
  InboxOutlined,
  EyeOutlined
} from '@ant-design/icons-vue'
import { useImportStore } from '@/stores'
import { useTaskPolling } from '@/composables'
import GlassCard from '@/components/common/GlassCard/GlassCard.vue'
import StatusBadge from '@/components/common/StatusBadge/StatusBadge.vue'
import EmptyState from '@/components/common/EmptyState/EmptyState.vue'
import PageHeader from '@/components/common/PageHeader/PageHeader.vue'
import ImportForm from '@/components/features/import/ImportForm.vue'
import { getTagModeLabel } from '@/constants/tags'
import type { ImportTask, StartImportParams } from '@/types'

// 导入历史表格列
const historyColumns = [
  { title: '任务名称', dataIndex: 'task_id', key: 'task_id', ellipsis: true },
  { title: '来源', dataIndex: 'tos_directory', key: 'tos_directory', ellipsis: true },
  { title: '文件数', dataIndex: 'total_files', key: 'total_files', width: 100, align: 'center' as const },
  { title: '标签模式', dataIndex: 'tag_mode', key: 'tag_mode', width: 100, align: 'center' as const },
  { title: '标注阶段 / 进度', dataIndex: 'annotation_status', key: 'annotation_status', width: 200 },
  { title: '状态', dataIndex: 'status', key: 'status', width: 120, align: 'center' as const },
  { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
  { title: '操作', key: 'action', width: 100, align: 'center' as const }
]

const importStore = useImportStore()

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

function getAnnotationStatusText(task: ImportTask): string {
  if (!task.annotation_status && task.generate_annotations == null) return '历史未标注'
  const status = task.annotation_status ?? (task.generate_annotations === false ? 'skipped' : 'not_started')
  return getStatusText(status)
}

const { startPolling } = useTaskPolling({
  interval: 3000,
  shouldPoll: () => displayTasks.value.some(t => t.status === 'running' || t.status === 'pending'),
  onPoll: async () => {
    for (const task of displayTasks.value.filter(t => t.status === 'running' || t.status === 'pending')) {
      await importStore.refreshTaskStatus(task.task_id)
    }
  }
})

const startImportAction = async (params: StartImportParams) => {
  try {
    const res = await importStore.startImportTask(params)
    if (res?.data?.task_id) {
      message.success('导入任务已启动')
      startPolling()
    }
  } catch (e) {
    // 错误已在拦截器中处理
  }
}

const refreshTasks = () => importStore.fetchTasks()

const cancelTask = async (taskId: string) => {
  if (await importStore.cancelTask(taskId)) message.success('任务已取消')
}

const getStatusText = (status: string): string => {
  const texts: Record<string, string> = {
    pending: '等待中',
    running: '运行中',
    completed: '已完成',
    partial: '部分失败',
    not_started: '未标注',
    skipped: '已跳过',
    failed: '失败',
    cancelled: '已取消'
  }
  return texts[status] || status
}

const formatTime = (time: string): string => {
  if (!time) return ''
  return new Date(time).toLocaleString('zh-CN')
}

onMounted(() => {
  refreshTasks()
  startPolling()
})
</script>

<style scoped>
.data-import-page {
  padding: 0;
}

/* ═══ TOS 配置区 ═══ */
.tos-config-section {
  margin-bottom: 24px;
}

/* ═══ 区块通用 ═══ */
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: var(--font-heading);
  font-size: var(--text-base, 14px);
  font-weight: 600;
  color: var(--color-text-bright, #0f172a);
}

.title-icon {
  color: var(--color-primary, #0064ff);
  font-size: 16px;
}

.task-count {
  background: var(--color-primary-bg, #e8f0ff);
  color: var(--color-primary, #0064ff);
  padding: 1px 8px;
  border-radius: var(--radius, 8px);
  font-size: var(--text-xs, 11px);
  font-weight: 500;
}

/* ═══ 表单样式 ═══ */
.import-form {
  margin-top: 0;
}

.form-item {
  margin-bottom: var(--spacing-lg, 24px);
}

.form-item :deep(.ant-form-item-label > label) {
  color: var(--gray-700, #334155);
  font-size: var(--text-sm, 12px);
  font-weight: 600;
}

.input-group {
  display: flex;
  align-items: stretch;
}

.tos-input {
  flex: 1;
  border-radius: var(--radius-sm, 6px) 0 0 var(--radius-sm, 6px) !important;
  height: 40px !important;
}

.tos-input :deep(.ant-input) {
  height: 38px !important;
  font-family: var(--font-mono);
  font-size: var(--text-caption, 13px);
  color: var(--gray-800, #1e293b);
  background: var(--white, #ffffff);
  border-color: var(--color-border, #e2e8f0);
}

.tos-input :deep(.ant-input:focus) {
  border-color: var(--color-primary, #0064ff);
  box-shadow: 0 0 0 3px rgba(0, 100, 255, 0.08);
}

.validate-btn {
  border-radius: 0 var(--radius-sm, 6px) var(--radius-sm, 6px) 0 !important;
  height: 40px !important;
  margin-left: -1px;
  color: var(--gray-700, #334155);
  border-color: var(--color-border, #e2e8f0);
}

.validate-btn:hover {
  color: var(--color-primary, #0064ff);
  border-color: var(--color-primary, #0064ff);
}

.form-tip {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--gray-500, #64748b);
  font-size: var(--text-sm, 12px);
}

/* 选项卡片 */
.options-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.option-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  background: var(--gray-50, #f8fafc);
  border: 1px solid var(--color-border, #e2e8f0);
  border-radius: var(--radius-lg, 12px);
  cursor: pointer;
  transition: all 0.2s ease;
  overflow: hidden;
}

.option-card:hover {
  border-color: var(--color-border-hover, #cbd5e1);
  box-shadow: var(--shadow-sm);
}

.option-card.active {
  background: var(--color-primary-bg, #e8f0ff);
  border-color: var(--color-primary, #0064ff);
  box-shadow: 0 0 0 3px rgba(0, 100, 255, 0.08);
}

.option-icon {
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-primary-bg, #e8f0ff);
  border-radius: var(--radius-md, 10px);
  color: var(--color-primary, #0064ff);
  font-size: 16px;
}

.option-icon.tag-icon {
  background: #d1fae5;
  color: #10b981;
}

.option-content {
  flex: 1;
}

.option-title {
  color: var(--gray-900, #0f172a);
  font-size: var(--text-caption, 13px);
  font-weight: 600;
}

.option-desc {
  color: var(--gray-500, #64748b);
  font-family: var(--font-mono);
  font-size: var(--text-xs, 11px);
  margin-top: 2px;
}

.option-check {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-primary, #0064ff);
  border-radius: 50%;
  color: #ffffff;
  font-size: 11px;
}

/* 模型配置 */
.model-config {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  background: var(--gray-50, #f8fafc);
  border: 1px solid var(--color-border, #e2e8f0);
  border-radius: var(--radius-lg, 12px);
}

.config-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.config-label {
  min-width: 70px;
  color: var(--gray-600, #475569);
  font-size: var(--text-sm, 12px);
  font-weight: 500;
}

.config-select {
  flex: 1;
}

.config-select :deep(.ant-select-selector) {
  background: var(--white, #ffffff) !important;
  border-color: var(--color-border, #e2e8f0) !important;
  border-radius: var(--radius-sm, 6px) !important;
}

.config-select :deep(.ant-select-selector:hover) {
  border-color: var(--color-primary, #0064ff) !important;
}

.config-select :deep(.ant-select-selection-item) {
  color: var(--gray-800, #1e293b) !important;
  font-family: var(--font-mono);
  font-size: var(--text-sm, 12px);
}

.config-select :deep(.ant-select-arrow) {
  color: var(--gray-400, #94a3b8) !important;
}

.tag-rule-config {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 14px;
}

.custom-prompt {
  width: 100%;
}

.custom-prompt :deep(textarea::placeholder) {
  color: var(--gray-400, #94a3b8);
  opacity: 1;
}

.custom-prompt :deep(.ant-input-data-count) {
  color: var(--gray-400, #94a3b8);
}

/* 操作按钮 */
.form-actions {
  display: flex;
  gap: 12px;
  margin-top: var(--spacing-lg, 24px);
}

.import-btn {
  flex: 2;
  height: 44px;
  font-size: var(--text-base, 14px);
  font-weight: 600;
  border-radius: var(--radius-sm, 6px);
  background: var(--color-primary, #0064ff);
  box-shadow: 0 1px 3px rgba(0, 100, 255, 0.3);
}

.import-btn:hover:not(:disabled) {
  background: var(--color-primary-dark, #0052d9);
  box-shadow: 0 2px 8px rgba(0, 100, 255, 0.4);
  transform: translateY(-1px);
}

.reset-btn {
  flex: 1;
  height: 44px;
  border-radius: var(--radius-sm, 6px);
  color: var(--gray-700, #334155);
  border-color: var(--color-border, #e2e8f0);
}

.reset-btn:hover {
  color: var(--color-primary, #0064ff);
  border-color: var(--color-primary, #0064ff);
}

/* ═══ 导入历史 ═══ */
.history-section {
  margin-bottom: 24px;
}

.refresh-btn {
  color: var(--gray-500, #64748b);
  font-size: var(--text-sm, 12px);
}

.refresh-btn:hover {
  color: var(--color-primary, #0064ff);
}

.history-table :deep(.ant-table) {
  background: transparent;
}

.history-table :deep(.ant-table-thead > tr > th) {
  background: var(--gray-50, #f8fafc);
  color: var(--gray-500, #64748b);
  font-size: var(--text-sm, 12px);
  font-weight: 600;
  border-bottom: 1px solid var(--color-border, #e2e8f0);
}

.history-table :deep(.ant-table-tbody > tr > td) {
  border-bottom: 1px solid var(--color-border-subtle, #f1f5f9);
  font-size: var(--text-caption, 13px);
  color: var(--gray-700, #334155);
}

.history-table :deep(.ant-table-tbody > tr:hover > td) {
  background: var(--gray-50, #f8fafc);
}

.table-task-id {
  color: var(--gray-800, #1e293b);
  font-weight: 600;
}

.table-tos-path {
  font-family: var(--font-mono);
  font-size: var(--text-sm, 12px);
  color: var(--gray-500, #64748b);
}

.tag-mode-text {
  color: var(--gray-600, #475569);
  font-size: var(--text-sm, 12px);
  white-space: nowrap;
}
</style>
