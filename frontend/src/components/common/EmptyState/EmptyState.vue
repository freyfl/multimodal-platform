<template>
  <div class="empty-state">
    <div class="empty-icon-wrap">
      <div v-if="$slots.icon" class="empty-icon">
        <slot name="icon"></slot>
      </div>
      <div v-else-if="icon" class="empty-icon">
        <component :is="icon" />
      </div>
    </div>
    <p v-if="$slots.title || title" class="empty-text">
      <slot name="title">{{ title }}</slot>
    </p>
    <p v-if="$slots.description || description" class="empty-hint">
      <slot name="description">{{ description }}</slot>
    </p>
    <div v-if="$slots.actions" class="empty-actions">
      <slot name="actions"></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Component } from 'vue'

interface Props {
  title?: string
  description?: string
  icon?: Component
}

withDefaults(defineProps<Props>(), {
  title: '暂无数据',
  description: ''
})
</script>

<style scoped>
.empty-state {
  padding: 48px 24px;
  text-align: center;
  color: var(--gray-400, #94a3b8);
}

.empty-icon-wrap {
  margin-bottom: 12px;
}

.empty-icon {
  font-size: 40px;
  opacity: 0.4;
}

.empty-text {
  font-size: 14px;
  font-weight: 500;
  color: var(--gray-500, #64748b);
  margin: 0 0 4px 0;
}

.empty-hint {
  font-size: 12px;
  color: var(--gray-400, #94a3b8);
  margin: 0;
}

.empty-actions {
  margin-top: 20px;
}
</style>
