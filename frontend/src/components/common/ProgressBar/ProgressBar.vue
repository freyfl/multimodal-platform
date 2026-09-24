<template>
  <div class="progress-bar-container">
    <div class="progress-bar" :class="[colorClass, { 'progress-animated': animated }]">
      <div class="progress-fill" :style="{ width: `${percent}%` }">
        <div v-if="animated" class="progress-shimmer"></div>
      </div>
    </div>
    <span v-if="showText" class="progress-text">{{ percent }}%</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  percent: number
  animated?: boolean
  showText?: boolean
  color?: 'blue' | 'green' | 'orange'
}

const props = withDefaults(defineProps<Props>(), {
  animated: true,
  showText: true,
  color: 'blue'
})

const colorClass = computed(() => `progress-color-${props.color}`)
</script>

<style scoped>
.progress-bar-container {
  display: flex;
  align-items: center;
  gap: 12px;
}

.progress-bar {
  flex: 1;
  height: 4px;
  background: var(--gray-100, #f1f5f9);
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s ease;
  position: relative;
  overflow: hidden;
}

/* Color variants */
.progress-color-blue .progress-fill {
  background: linear-gradient(90deg, var(--color-primary, #0064ff), var(--color-primary-light, #4080ff));
}
.progress-color-green .progress-fill {
  background: linear-gradient(90deg, #10b981, #34d399);
}
.progress-color-orange .progress-fill {
  background: linear-gradient(90deg, #f97316, #fb923c);
}

.progress-shimmer {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.25) 50%,
    transparent 100%);
  animation: shimmer 2s infinite;
}

@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

.progress-text {
  font-family: var(--font-mono, 'SF Mono', monospace);
  color: var(--gray-500, #64748b);
  font-size: var(--text-xs, 11px);
  font-weight: 500;
  min-width: 36px;
  text-align: right;
}
</style>
