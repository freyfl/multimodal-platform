<template>
  <span class="tag-badge" :class="colorClass">
    <span class="tag-badge-label">{{ label }}</span>
    <button
      v-if="closable"
      class="tag-badge-close"
      @click.stop="$emit('close')"
      aria-label="移除标签"
    >
      ×
    </button>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  label: string
  color?: string
  closable?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  color: 'gray',
  closable: false
})

defineEmits<{
  close: []
}>()

const presetColors = [
  'blue', 'green', 'red', 'orange', 'purple',
  'cyan', 'pink', 'yellow', 'gray', 'indigo'
]

const colorClass = computed(() => {
  if (presetColors.includes(props.color)) {
    return `tag-color-${props.color}`
  }
  return 'tag-color-custom'
})
</script>

<style scoped>
.tag-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  line-height: 1.5;
  white-space: nowrap;
  transition: all var(--transition-default, 0.15s ease);
}

.tag-badge-label {
  display: inline-block;
}

.tag-badge-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border: none;
  background: none;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  opacity: 0.6;
  padding: 0;
  border-radius: 2px;
  color: inherit;
  transition: opacity 0.15s, background 0.15s;
}
.tag-badge-close:hover {
  opacity: 1;
  background: rgba(0, 0, 0, 0.08);
}

/* ── Preset color pairs: light bg + dark text ── */
.tag-color-blue {
  background: var(--color-primary-bg, #e8f0ff);
  color: var(--color-primary, #0064ff);
}
.tag-color-green {
  background: #d1fae5;
  color: #059669;
}
.tag-color-red {
  background: #fee2e2;
  color: #dc2626;
}
.tag-color-orange {
  background: #ffedd5;
  color: #ea580c;
}
.tag-color-purple {
  background: #ede9fe;
  color: #7c3aed;
}
.tag-color-cyan {
  background: #cffafe;
  color: #0891b2;
}
.tag-color-pink {
  background: #fce7f3;
  color: #db2777;
}
.tag-color-yellow {
  background: #fef9c3;
  color: #ca8a04;
}
.tag-color-gray {
  background: var(--gray-100, #f3f4f6);
  color: var(--gray-600, #475569);
}
.tag-color-indigo {
  background: #e0e7ff;
  color: #4338ca;
}

/* Custom color - uses CSS variable set inline if needed */
.tag-color-custom {
  background: var(--gray-100, #f3f4f6);
  color: var(--gray-600, #475569);
}
</style>
