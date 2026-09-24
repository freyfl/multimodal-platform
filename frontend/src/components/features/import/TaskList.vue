<template>
  <div class="task-list-container">
    <div class="list-header">
      <div class="section-title">
        <UnorderedListOutlined class="title-icon" />
        <span>导入任务</span>
        <span class="task-count" v-if="tasks.length">{{ tasks.length }}</span>
      </div>
      <a-button type="link" @click="handleRefresh" :loading="loading" class="refresh-btn">
        <ReloadOutlined />
        刷新
      </a-button>
    </div>

    <div class="tasks-list" v-if="tasks.length > 0">
      <TaskCard
        v-for="task in tasks"
        :key="task.task_id"
        :task="task"
        @cancel="handleCancel"
      />
    </div>

    <EmptyState
      v-else
      title="暂无导入任务"
      description="配置TOS目录后开始导入"
      :icon="InboxOutlined"
    />
  </div>
</template>

<script setup lang="ts">
import { UnorderedListOutlined, ReloadOutlined, InboxOutlined } from '@ant-design/icons-vue'
import TaskCard from './TaskCard.vue'
import EmptyState from '@/components/common/EmptyState/EmptyState.vue'
import type { ImportTask } from '@/types'

defineProps<{
  tasks: ImportTask[]
  loading?: boolean
}>()

const emit = defineEmits<{
  refresh: []
  cancel: [taskId: string]
}>()

const handleRefresh = () => {
  emit('refresh')
}

const handleCancel = (taskId: string) => {
  emit('cancel', taskId)
}
</script>

<style scoped>
.task-list-container {
  height: 100%;
}

.list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
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
  padding: 2px 10px;
  border-radius: var(--radius, 8px);
  font-size: var(--text-xs, 11px);
  font-weight: 500;
}

.refresh-btn {
  color: var(--gray-500, #64748b);
}

.refresh-btn:hover {
  color: var(--color-primary, #0064ff);
}

.tasks-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: calc(100vh - 280px);
  overflow-y: auto;
  padding-right: 4px;
}

.tasks-list::-webkit-scrollbar {
  width: 6px;
}

.tasks-list::-webkit-scrollbar-track {
  background: transparent;
}

.tasks-list::-webkit-scrollbar-thumb {
  background: var(--gray-300, #cbd5e1);
  border-radius: 3px;
}

.tasks-list::-webkit-scrollbar-thumb:hover {
  background: var(--gray-400, #94a3b8);
}
</style>
