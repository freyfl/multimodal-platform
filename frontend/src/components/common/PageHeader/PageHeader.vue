<template>
  <div class="page-header">
    <div class="header-content">
      <h1 class="page-title">
        <slot name="icon" v-if="$slots.icon" class="title-icon"></slot>
        <span class="title-text">
          <slot>{{ title }}</slot>
        </span>
      </h1>
      <p v-if="$slots.subtitle || subtitle" class="page-subtitle">
        <slot name="subtitle">{{ subtitle }}</slot>
      </p>
    </div>
    <div v-if="$slots.extra" class="header-extra">
      <slot name="extra"></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
interface Props {
  title?: string
  subtitle?: string
}

withDefaults(defineProps<Props>(), {
  title: '',
  subtitle: ''
})
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 24px;
  gap: 20px;
}

.header-content {
  flex: 1;
}

.page-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--gray-900, #0f172a);
  margin: 0 0 10px 0;
  letter-spacing: -.8px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-text {
  color: inherit;
}

.title-icon {
  color: #3b82f6;
}

.page-subtitle {
  color: var(--gray-500, #64748b);
  font-size: 13px;
  margin: 0;
  line-height: 1.8;
}

.header-extra {
  display: flex;
  align-items: center;
  gap: 12px;
}
@media (max-width: 600px) {
  .page-header { flex-direction: column; gap: 12px; }
  .page-title { font-size: 24px; }
  .header-extra { flex-wrap: wrap; }
}
</style>
