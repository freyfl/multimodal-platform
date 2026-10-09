<template>
  <div class="task-card">
    <div class="task-header">
      <div class="task-id">{{ task.task_id }}</div>
      <StatusBadge :status="task.status" :text="getStatusText(task.status)" />
    </div>

    <div class="task-path">{{ task.tos_directory }}</div>

    <ProgressBar
      :percent="progressPercent"
      :show-text="!(task.status === 'running' && task.processed_files === 0)"
    />
    <span v-if="task.status === 'running' && task.processed_files === 0" class="processing-text">
      处理中
    </span>

    <div class="task-stats">
      <div class="stat">
        <span class="stat-label">总数</span>
        <span class="stat-value">{{ task.total_files }}</span>
      </div>
      <div class="stat">
        <span class="stat-label">已处理</span>
        <span class="stat-value success">{{ task.processed_files }}</span>
      </div>
      <div class="stat">
        <span class="stat-label">失败</span>
        <span class="stat-value error">{{ task.failed_files }}</span>
      </div>
    </div>

    <div class="task-footer">
      <span class="task-time">{{ formatTime(task.created_at) }}</span>
      <a-popconfirm
        v-if="task.status === 'running'"
        title="确定取消此任务?"
        @confirm="handleCancel"
      >
        <a-button type="link" danger size="small">取消</a-button>
      </a-popconfirm>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ImportTask } from '@/types'
import StatusBadge from '@/components/common/StatusBadge/StatusBadge.vue'
import ProgressBar from '@/components/common/ProgressBar/ProgressBar.vue'

const props = defineProps<{
  task: ImportTask
}>()

const emit = defineEmits<{
  cancel: [taskId: string]
}>()

const progressPercent = computed(() => {
  if (!props.task.total_files) return 0
  return Math.round((props.task.processed_files / props.task.total_files) * 100)
})

const getStatusText = (status: string): string => {
  const texts: Record<string, string> = {
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    pending: '等待中'
  }
  return texts[status] || status
}

const formatTime = (time: string): string => {
  if (!time) return ''
  return new Date(time).toLocaleString('zh-CN')
}

const handleCancel = () => {
  emit('cancel', props.task.task_id)
}
</script>

<style scoped>
.task-card {
  position: relative;
  background: var(--white, #ffffff);
  border: 1px solid var(--color-border, #e2e8f0);
  border-radius: var(--radius-lg, 12px);
  padding: 16px;
  transition: all 0.2s ease;
  box-shadow: var(--shadow-sm);
}

.task-card:hover {
  border-color: var(--color-primary, #0064ff);
  box-shadow: 0 0 0 3px rgba(0, 100, 255, 0.08), var(--shadow-md);
  transform: translateY(-1px);
}

.task-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.task-id {
  color: var(--color-primary, #0064ff);
  font-family: var(--font-mono);
  font-size: var(--text-caption, 13px);
  font-weight: 600;
}

.task-path {
  color: var(--gray-500, #64748b);
  font-family: var(--font-mono);
  font-size: var(--text-sm, 12px);
  margin-bottom: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.processing-text {
  display: block;
  margin-top: 6px;
  color: var(--color-primary, #0064ff);
  font-size: var(--text-sm, 12px);
}

.task-stats {
  display: flex;
  gap: 24px;
  margin-top: 12px;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-label {
  color: var(--gray-500, #64748b);
  font-size: var(--text-xs, 11px);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 500;
}

.stat-value {
  color: var(--gray-900, #0f172a);
  font-family: var(--font-mono);
  font-size: var(--text-base, 14px);
  font-weight: 600;
}

.stat-value.success {
  color: var(--color-success, #10b981);
}

.stat-value.error {
  color: var(--color-error, #ef4444);
}

.task-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 12px;
  margin-top: 12px;
  border-top: 1px solid var(--color-border-subtle, #f1f5f9);
}

.task-time {
  color: var(--gray-400, #94a3b8);
  font-family: var(--font-mono);
  font-size: var(--text-sm, 12px);
}
</style>
