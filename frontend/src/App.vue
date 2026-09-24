<template>
  <a-config-provider :theme="themeConfig">
    <router-view v-if="isAuthPage" />
    <MainLayout v-else-if="authReady" />
    <div v-else class="app-loading">
      <a-spin size="large" />
    </div>
  </a-config-provider>
</template>

<script setup lang="ts">
import { reactive, computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import MainLayout from '@/components/layout/MainLayout.vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const authStore = useAuthStore()
const authReady = ref(false)

const isAuthPage = computed(() => {
  return ['/login', '/register'].includes(route.path)
})

const themeConfig = reactive({
  token: {
    colorPrimary: '#0064ff',
    borderRadius: 8,
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif",
  },
})

onMounted(async () => {
  await authStore.ensureInit()
  authReady.value = true
})
</script>

<style>
/* Global minimal reset for new layout */
body {
  margin: 0;
  padding: 0;
}

#app {
  height: 100vh;
}

.app-loading {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f8fafc;
}
</style>
