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
  background: var(--color-bg-elevated, #ffffff);
  border: 1px solid var(--color-border, #e2e8f0);
  border-radius: var(--radius-lg, 12px);
  box-shadow: var(--shadow, 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.06));
  overflow: hidden;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
  min-width: 0;
}

.glass-card-hoverable:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: var(--color-border-hover, #cbd5e1);
}

/* Variant: flat - no shadow */
.glass-card-flat {
  box-shadow: none;
}
.glass-card-flat.glass-card-hoverable:hover {
  box-shadow: var(--shadow, 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.06));
}

/* Variant: bordered - stronger border */
.glass-card-bordered {
  border-width: 2px;
}

.glass-card-header {
  padding: 18px 24px;
  border-bottom: 1px solid var(--color-border-subtle, #f1f5f9);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.glass-card-title {
  font-family: var(--font-heading);
  font-size: var(--text-base, 14px);
  font-weight: 600;
  color: var(--color-text-bright, #0f172a);
}

.glass-card-body {
  padding: var(--card-padding, 24px);
}

.glass-card-footer {
  padding: 14px 20px;
  border-top: 1px solid var(--color-border-subtle, #f1f5f9);
  background: var(--color-bg-glass-strong, #f8fafc);
}
@media (max-width: 600px) {
  .glass-card-header { padding: 16px 20px; }
  .glass-card-body { padding: var(--card-padding, 20px); }
}
</style>
