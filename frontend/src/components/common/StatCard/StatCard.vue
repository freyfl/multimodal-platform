<template>
  <component
    :is="to ? RouterLink : 'div'"
    class="stat-card"
    :class="[colorClass, { 'is-action': !!to }]"
    v-bind="to ? { to } : {}"
  >
    <div class="stat-card-body">
      <div class="stat-content">
        <div class="stat-label">
          <span v-if="index" class="stat-index">{{ index }}</span>
          {{ title }}
          <ArrowRightOutlined v-if="to" class="stat-go" aria-hidden="true" />
        </div>
        <div class="stat-value" :class="{ 'is-placeholder': !isNumeric }">
          <span v-if="isNumeric" class="stat-digits" aria-hidden="true">{{ displayValue }}</span>
          <span v-else class="stat-digits">{{ value }}</span>
          <span v-if="isNumeric" class="sr-only">{{ Number(value).toLocaleString('zh-CN') }}</span>
        </div>
        <div v-if="trend" class="stat-change" :class="trendClass">
          <span class="trend-arrow">{{ trendIcon }}</span>
          {{ trend }}
        </div>
      </div>
      <div v-if="$slots.icon" class="stat-icon-wrapper">
        <slot name="icon" />
      </div>
    </div>
  </component>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, type RouteLocationRaw } from 'vue-router'
import { ArrowRightOutlined } from '@ant-design/icons-vue'

interface Props {
  title: string
  value: string | number
  trend?: string
  trendType?: 'up' | 'down' | 'neutral'
  color?: string
  /** Optional mono index shown before the label, e.g. "01". */
  index?: string
  /** When set, the card is a link instead of a static tile. */
  to?: RouteLocationRaw
}

const props = withDefaults(defineProps<Props>(), {
  trendType: 'neutral',
  color: 'blue',
  index: ''
})

const colorClass = computed(() => `stat-color-${props.color}`)
const isNumeric = computed(() => typeof props.value === 'number' && Number.isFinite(props.value))

const reduceMotion = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
const shown = ref(0)
let frame = 0

function animateTo(target: number) {
  cancelAnimationFrame(frame)
  if (reduceMotion || target === shown.value) {
    shown.value = target
    return
  }
  const from = shown.value
  const start = performance.now()
  const duration = 720
  const step = (now: number) => {
    const t = Math.min(1, (now - start) / duration)
    const eased = 1 - Math.pow(1 - t, 4)
    shown.value = Math.round(from + (target - from) * eased)
    if (t < 1) frame = requestAnimationFrame(step)
  }
  frame = requestAnimationFrame(step)
}

watch(() => props.value, (next) => {
  if (typeof next === 'number' && Number.isFinite(next)) animateTo(next)
})
onMounted(() => { if (isNumeric.value) animateTo(props.value as number) })
onUnmounted(() => cancelAnimationFrame(frame))

const displayValue = computed(() => shown.value.toLocaleString('zh-CN'))

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
  background: var(--color-bg-elevated);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  padding: 22px 24px;
  box-shadow: var(--shadow);
  position: relative;
  overflow: hidden;
  transition: box-shadow var(--duration-normal) var(--ease-default), border-color var(--transition-default), background var(--transition-default);
}
.stat-card:hover { border-color: var(--color-border-hover); }
.stat-card.is-action {
  display: block;
  color: inherit;
  cursor: pointer;
  text-decoration: none;
}
.stat-card.is-action:hover {
  color: inherit;
  background: var(--gray-50);
}
.stat-card.is-action:active { background: var(--gray-100); }
.stat-card.is-action:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: -3px;
  z-index: 1;
}
.stat-go {
  align-self: center;
  color: var(--color-accent);
  font-size: 11px;
  transition: transform var(--duration-normal) var(--ease-out);
}
.stat-card.is-action:hover .stat-go { transform: translateX(3px); }

.stat-card-body {
  position: relative;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.stat-content {
  flex: 1;
  min-width: 0;
}

.stat-icon-wrapper {
  width: 34px;
  height: 34px;
  border-radius: var(--radius-mark);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  flex-shrink: 0;
  background: var(--gray-50);
  color: var(--gray-600);
  border: 1px solid var(--color-border);
  transition: background var(--transition-default), color var(--transition-default), transform var(--duration-slow) var(--ease-spring);
}
.stat-card:hover .stat-icon-wrapper {
  background: var(--mint-soft);
  color: var(--mint-deep);
  border-color: transparent;
  transform: rotate(-6deg);
}

.stat-label {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
  color: var(--gray-500);
  font-weight: 500;
  margin-bottom: 18px;
  letter-spacing: 0.02em;
}
.stat-index {
  font: 500 10px var(--font-mono);
  color: var(--gray-400);
  letter-spacing: 0.08em;
}

.stat-value {
  font-family: var(--font-heading);
  font-size: clamp(30px, 2.6vw, 40px);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--gray-900);
  letter-spacing: var(--tracking-numeric);
  line-height: 1;
  margin-bottom: 6px;
}
.stat-value.is-placeholder { color: var(--gray-300); }
.stat-digits { display: inline-block; }

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

.stat-change {
  font-size: var(--text-xs);
  color: var(--gray-400);
  display: flex;
  align-items: center;
  gap: 4px;
}

.trend-up {
  color: var(--color-success);
}

.trend-down {
  color: var(--color-error);
}

.trend-neutral {
  color: var(--gray-400);
}

.trend-arrow {
  font-weight: 700;
  font-size: 12px;
}
</style>
