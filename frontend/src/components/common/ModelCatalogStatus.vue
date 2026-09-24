<template>
  <a-alert v-if="!system.catalogReady" show-icon :type="system.configError ? 'error' : 'info'"
    :message="system.configError || '正在加载模型目录，相关操作暂不可用'">
    <template #action>
      <a-button size="small" :loading="system.configLoading" @click="system.fetchConfig()">重试</a-button>
    </template>
  </a-alert>
  <div v-else class="catalog-info">
    方舟向量模型：{{ system.catalog?.defaults.embedding_model }} · {{ system.catalog?.defaults.embedding_dimension }} 维
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useSystemStore } from '@/stores/system'
const system = useSystemStore()
onMounted(() => {
  if (!system.catalogReady) void system.fetchConfig()
})
</script>

<style scoped>
.catalog-info { color: var(--gray-500); font-size: 12px; margin: 8px 0; overflow-wrap: anywhere; }
</style>
