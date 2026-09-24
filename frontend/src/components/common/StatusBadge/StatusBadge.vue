<template>
  <span class="status-badge" :class="statusClass">
    <span class="status-dot"></span>
    <slot>{{ displayText }}</slot>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AnnotationStatus } from '@/types/annotation'

interface Props {
  status: AnnotationStatus
  text?: string
}

const props = withDefaults(defineProps<Props>(), {
  text: ''
})

const statusLabels: Record<AnnotationStatus, string> = {
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  pending: '等待中',
  partial: '部分失败',
  not_started: '未开始',
  skipped: '已跳过',
}

const statusClass = computed(() => `status-${props.status}`)
const displayText = computed(() => props.text || statusLabels[props.status] || props.status)
</script>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 4px;
  font-family: var(--font-body);
  font-size: var(--text-xs, 11px);
  font-weight: 500;
  letter-spacing: 0.2px;
  transition: all 0.2s ease;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  display: inline-block;
}

/* Completed = tag-gray in design */
.status-completed {
  background: var(--gray-100, #f1f5f9);
  color: var(--gray-600, #475569);
}
.status-completed .status-dot {
  background: #94a3b8;
}

/* Running = tag-green in design */
.status-running {
  background: #d1fae5;
  color: #059669;
}
.status-running .status-dot {
  background: #10b981;
  box-shadow: 0 0 0 2px rgba(16,185,129,0.2);
  animation: dot-pulse 2s infinite;
}

/* Failed = tag-red in design */
.status-failed {
  background: #fee2e2;
  color: #dc2626;
}
.status-failed .status-dot {
  background: #ef4444;
}

/* Cancelled = tag-gray in design */
.status-cancelled,
.status-not_started,
.status-skipped {
  background: var(--gray-100, #f1f5f9);
  color: var(--gray-600, #475569);
}
.status-cancelled .status-dot,
.status-not_started .status-dot,
.status-skipped .status-dot {
  background: var(--gray-300, #cbd5e1);
}

/* Pending = tag-orange in design */
.status-pending {
  background: #ffedd5;
  color: #ea580c;
}
.status-pending .status-dot {
  background: #f97316;
}

.status-partial {
  background: #fef3c7;
  color: #92400e;
}
.status-partial .status-dot {
  background: #d97706;
}

@keyframes dot-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
