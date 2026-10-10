<template>
  <div
    class="glass-card"
    :class="[
      { 'glass-card-hoverable': hoverable },
      variant ? `glass-card-${variant}` : ''
    ]"
    :style="padding ? { '--card-padding': padding } : {}"
  >
    <div v-if="$slots.header || title" class="glass-card-header">
      <slot name="header">
        <span v-if="title" class="glass-card-title">{{ title }}</span>
      </slot>
    </div>
    <div class="glass-card-body">
      <slot></slot>
    </div>
    <div v-if="$slots.footer" class="glass-card-footer">
      <slot name="footer"></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
interface Props {
  title?: string
  hoverable?: boolean
  padding?: string
  variant?: 'default' | 'bordered' | 'flat'
}

withDefaults(defineProps<Props>(), {
  hoverable: false,
  variant: 'default'
})
</script>

<style scoped>
.glass-card {
  position: relative;
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  overflow: hidden;
  transition: border-color var(--transition-default), box-shadow var(--duration-normal) var(--ease-default), transform var(--duration-normal) var(--ease-out);
  min-width: 0;
}

.glass-card-hoverable:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: var(--color-border-hover);
}

/* Variant: flat - no shadow */
.glass-card-flat {
  box-shadow: none;
}
.glass-card-flat.glass-card-hoverable:hover {
  box-shadow: var(--shadow);
}

/* Variant: bordered - stronger border */
.glass-card-bordered {
  border-width: 2px;
}

.glass-card-header {
  padding: 18px 24px;
  border-bottom: 1px solid var(--color-border-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  min-height: 60px;
}

.glass-card-title,
.glass-card-header :deep(.glass-card-title),
.glass-card-header :deep(.card-title) {
  font-family: var(--font-body);
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--color-text-bright);
  letter-spacing: 0;
}

.glass-card-body {
  padding: var(--card-padding, 24px);
}

.glass-card-footer {
  padding: 14px 20px;
  border-top: 1px solid var(--color-border-subtle);
  background: var(--color-bg-glass-strong);
}
@media (max-width: 600px) {
  .glass-card-header { padding: 14px 18px; min-height: 0; }
  .glass-card-body { padding: var(--card-padding, 18px); }
}
</style>
