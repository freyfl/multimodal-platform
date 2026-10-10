<template>
  <div class="empty-state">
    <div class="empty-icon-wrap" aria-hidden="true">
      <svg class="empty-frame" viewBox="0 0 96 96" fill="none">
        <path d="M2 22V2h20M74 2h20v20M2 74v20h20M74 94h20V74" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
      </svg>
      <span class="empty-scan"></span>
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
  padding: 44px 24px;
  text-align: center;
  color: var(--gray-400);
  animation: fadeIn .5s var(--ease-out) both;
}

.empty-icon-wrap {
  position: relative;
  display: inline-grid;
  place-items: center;
  width: 96px;
  height: 96px;
  margin-bottom: 14px;
  overflow: hidden;
}
.empty-frame {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  color: var(--gray-300);
}
.empty-scan {
  position: absolute;
  top: 8px;
  bottom: 8px;
  left: 8px;
  width: 1px;
  background: linear-gradient(to bottom, transparent, var(--mint-deep), transparent);
  opacity: .5;
  animation: scanSweep 4.2s var(--ease-in-out) 1.2s infinite;
}
@keyframes scanSweep {
  0% { transform: translateX(0); opacity: 0; }
  10% { opacity: .55; }
  90% { opacity: .55; }
  100% { transform: translateX(78px); opacity: 0; }
}

.empty-icon {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 54px;
  height: 54px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-mark-lg);
  background: var(--white);
  color: var(--gray-500);
  font-size: 22px;
  box-shadow: var(--shadow);
}

.empty-text {
  font-size: 14px;
  font-weight: 600;
  color: var(--gray-700);
  margin: 0 0 4px 0;
}

.empty-hint {
  font-size: 12px;
  color: var(--gray-400);
  margin: 0;
  line-height: 1.8;
}

.empty-actions {
  margin-top: 18px;
}
@media (prefers-reduced-motion: reduce) {
  .empty-scan { display: none; }
}
</style>
