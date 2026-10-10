<template>
  <header class="page-header">
    <div class="header-content">
      <div v-if="eyebrow || $slots.eyebrow" class="eyebrow page-eyebrow">
        <span></span>
        <slot name="eyebrow">{{ eyebrow }}</slot>
      </div>
      <h1 class="page-title">
        <span v-if="$slots.icon" class="title-icon"><slot name="icon"></slot></span>
        <span class="title-text">
          <slot>{{ title }}</slot><span v-if="accent" class="title-period" aria-hidden="true">.</span>
        </span>
      </h1>
      <p v-if="$slots.subtitle || subtitle" class="page-subtitle">
        <slot name="subtitle">{{ subtitle }}</slot>
      </p>
    </div>
    <div v-if="$slots.extra" class="header-extra">
      <slot name="extra"></slot>
    </div>
  </header>
</template>

<script setup lang="ts">
interface Props {
  title?: string
  subtitle?: string
  /** Mono uppercase label above the title, e.g. "MULTIMODAL / SEARCH". */
  eyebrow?: string
  /** Appends the brand accent period after the title. */
  accent?: boolean
}

withDefaults(defineProps<Props>(), {
  title: '',
  subtitle: '',
  eyebrow: '',
  accent: true
})
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 28px;
  gap: 24px;
  animation: fadeInUp .6s var(--ease-out) both;
}

.header-content {
  flex: 1;
  min-width: 0;
}

.page-eyebrow { margin-bottom: 14px; }

.page-title {
  font-size: var(--text-3xl);
  font-weight: 700;
  color: var(--gray-900);
  margin: 0;
  letter-spacing: -0.01em;
  display: flex;
  align-items: center;
  gap: 12px;
  line-height: 1.15;
}

.title-text {
  color: inherit;
}
.title-period { color: var(--color-primary); margin-left: 2px; }

.title-icon {
  display: inline-flex;
  color: var(--mint-deep);
  font-size: 22px;
}

.page-subtitle {
  color: var(--gray-500);
  font-size: 13px;
  margin: 10px 0 0;
  line-height: 1.8;
  max-width: 60ch;
}

.header-extra {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
  padding-bottom: 2px;
}
@media (max-width: 600px) {
  .page-header { flex-direction: column; align-items: stretch; gap: 14px; margin-bottom: 20px; }
  .page-title { font-size: 24px; }
  .page-eyebrow { margin-bottom: 10px; }
  .header-extra { flex-wrap: wrap; }
}
</style>
