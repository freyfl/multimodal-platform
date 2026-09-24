<template>
  <div class="stat-card" :class="colorClass">
    <div class="stat-card-body">
      <div class="stat-content">
        <div class="stat-label">{{ title }}</div>
        <div class="stat-value">{{ value }}</div>
        <div v-if="trend" class="stat-change" :class="trendClass">
          <span class="trend-arrow">{{ trendIcon }}</span>
          {{ trend }}
        </div>
      </div>
      <div v-if="$slots.icon" class="stat-icon-wrapper" :class="`icon-${color}`">
        <slot name="icon" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  title: string
  value: string | number
  trend?: string
  trendType?: 'up' | 'down' | 'neutral'
  color?: string
}

const props = withDefaults(defineProps<Props>(), {
  trendType: 'neutral',
  color: 'blue'
})

const colorClass = computed(() => `stat-color-${props.color}`)

const trendClass = computed(() => {
  if (props.trendType === 'up') return 'trend-up'
  if (props.trendType === 'down') return 'trend-down'
  return 'trend-neutral'
})

const trendIcon = computed(() => {
  if (props.trendType === 'up') return '↑'
  if (props.trendType === 'down') return '↓'
  return ''
})
</script>

<style scoped>
.stat-card {
  background: var(--color-bg-elevated, #ffffff);
  border-radius: var(--radius-lg, 12px);
  border: 1px solid var(--color-border, #e2e8f0);
  padding: 20px;
  box-shadow: var(--shadow, 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.06));
  position: relative;
  overflow: hidden;
  transition: box-shadow 0.2s ease, transform 0.2s ease;
}

.stat-card:hover {
  box-shadow: var(--shadow-md, 0 4px 6px rgba(0,0,0,0.07), 0 2px 4px rgba(0,0,0,0.06));
  transform: translateY(-2px);
}

/* Top gradient bar */
.stat-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
}

.stat-color-blue::before {
  background: linear-gradient(90deg, var(--color-primary, #0064ff), var(--color-primary-light, #4080ff));
}
.stat-color-green::before {
  background: linear-gradient(90deg, #10b981, #34d399);
}
.stat-color-orange::before {
  background: linear-gradient(90deg, #f97316, #fb923c);
}
.stat-color-purple::before {
  background: linear-gradient(90deg, #8b5cf6, #a78bfa);
}
.stat-color-red::before {
  background: linear-gradient(90deg, #ef4444, #f87171);
}
.stat-color-cyan::before {
  background: linear-gradient(90deg, #06b6d4, #22d3ee);
}

.stat-card-body {
  position: relative;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.stat-content {
  flex: 1;
  min-width: 0;
}

.stat-icon-wrapper {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
  margin-left: 12px;
}

.icon-blue {
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
}
.icon-green {
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
}
.icon-orange {
  background: rgba(249, 115, 22, 0.1);
  color: #f97316;
}
.icon-purple {
  background: rgba(139, 92, 246, 0.1);
  color: #8b5cf6;
}
.icon-red {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}
.icon-cyan {
  background: rgba(6, 182, 212, 0.1);
  color: #06b6d4;
}

.stat-label {
  font-size: 12px;
  color: var(--gray-500, #64748b);
  font-weight: 500;
  margin-bottom: 8px;
}

.stat-value {
  font-size: var(--text-3xl, 28px);
  font-weight: 700;
  color: var(--gray-900, #111827);
  letter-spacing: -1px;
  line-height: 1;
  margin-bottom: 6px;
}

.stat-change {
  font-size: var(--text-xs, 11px);
  color: var(--gray-400, #9ca3af);
  display: flex;
  align-items: center;
  gap: 4px;
}

.trend-up {
  color: var(--color-success, #10b981);
}

.trend-down {
  color: var(--color-error, #ef4444);
}

.trend-neutral {
  color: var(--gray-400, #9ca3af);
}

.trend-arrow {
  font-weight: 700;
  font-size: 12px;
}
</style>
