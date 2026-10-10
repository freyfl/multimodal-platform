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
  gap: 7px;
  padding: 3px 10px 3px 8px;
  border-radius: var(--radius-pill);
  font-family: var(--font-body);
  font-size: var(--text-xs);
  font-weight: 500;
  letter-spacing: 0.02em;
  white-space: nowrap;
  transition: background var(--transition-default), color var(--transition-default);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  display: inline-block;
}

/* Completed */
.status-completed {
  background: var(--gray-100);
  color: var(--gray-700);
}
.status-completed .status-dot {
  background: var(--ink);
}

/* Running */
.status-running {
  background: var(--color-accent-light);
  color: var(--color-accent-dark);
}
.status-running .status-dot {
  background: var(--color-accent);
  box-shadow: 0 0 0 2px var(--color-accent-glow);
  animation: dot-pulse 1.8s ease-in-out infinite;
}

/* Failed */
.status-failed {
  background: var(--color-error-light);
  color: var(--color-error);
}
.status-failed .status-dot {
  background: var(--color-error);
}

/* Cancelled / idle */
.status-cancelled,
.status-not_started,
.status-skipped {
  background: var(--gray-100);
  color: var(--gray-600);
}
.status-cancelled .status-dot,
.status-not_started .status-dot,
.status-skipped .status-dot {
  background: var(--gray-300);
}

/* Pending */
.status-pending {
  background: var(--color-warning-light);
  color: var(--color-warning);
}
.status-pending .status-dot {
  background: var(--color-warning);
}

.status-partial {
  background: #fbf0d6;
  color: #8a5a0b;
}
.status-partial .status-dot {
  background: #c7861a;
}

@keyframes dot-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}
</style>
