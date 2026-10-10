<template>
  <a-config-provider :theme="themeConfig" :locale="zhCN">
    <router-view v-if="isAuthPage" />
    <MainLayout v-else-if="authReady" />
    <div v-else class="app-loading" role="status" aria-live="polite">
      <span class="app-loading-mark" aria-hidden="true">M<span> / </span>M</span>
      <span class="app-loading-caption">正在进入工作空间</span>
    </div>
  </a-config-provider>
</template>

<script setup lang="ts">
import { reactive, computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
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
    colorPrimary: '#245bea',
    colorInfo: '#245bea',
    colorSuccess: '#1f9d6b',
    colorWarning: '#d97a12',
    colorError: '#d6453c',
    colorLink: '#245bea',
    borderRadius: 8,
    borderRadiusLG: 12,
    controlHeight: 38,
    colorText: '#26363d',
    colorTextSecondary: '#5f7075',
    colorTextTertiary: '#7f8e92',
    colorBorder: '#dde3df',
    colorBorderSecondary: '#eaeeea',
    colorBgLayout: '#f4f6f3',
    fontFamily: "'Noto Sans SC', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif",
    motionEaseInOut: 'cubic-bezier(0.65, 0, 0.35, 1)',
    motionEaseOut: 'cubic-bezier(0.16, 1, 0.3, 1)',
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
  flex-direction: column;
  gap: 18px;
  align-items: center;
  justify-content: center;
  background: var(--color-bg-page);
}
.app-loading-mark {
  font: 600 34px var(--font-heading);
  letter-spacing: -2px;
  color: var(--ink);
  animation: pulse 1.6s ease-in-out infinite;
}
.app-loading-mark span { color: var(--mint-deep); }
.app-loading-caption {
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.24em;
  color: var(--gray-500);
}
</style>
