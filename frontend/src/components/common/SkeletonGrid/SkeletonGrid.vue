<template>
  <div class="skeleton-grid" :style="{ 'grid-template-columns': `repeat(${columns}, 1fr)` }">
    <div
      v-for="i in count"
      :key="i"
      class="skeleton-card"
      :style="{ '--i': i }"
    >
      <div class="skeleton-preview shimmer-bg"></div>
      <div class="skeleton-info">
        <div class="skeleton-line skeleton-title shimmer-bg"></div>
        <div class="skeleton-line skeleton-tags shimmer-bg"></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  count?: number
  columns?: number
}>(), {
  count: 8,
  columns: 4
})
</script>

<style scoped>
.skeleton-grid {
  display: grid;
  gap: 14px;
}

.skeleton-card {
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid rgba(59, 130, 246, 0.06);
  border-radius: 12px;
  overflow: hidden;
  animation: fadeInUp 0.4s ease both;
  animation-delay: calc(var(--i, 0) * 60ms);
}

.skeleton-preview {
  aspect-ratio: 16 / 10;
}

.skeleton-info {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.skeleton-line {
  border-radius: 4px;
  height: 12px;
}

.skeleton-title {
  width: 70%;
}

.skeleton-tags {
  width: 45%;
  height: 10px;
}
</style>
