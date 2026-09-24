<template>
  <div class="main-layout">
    <AppSidebar />
    <div class="main-content">
      <AppHeader />
      <div class="content-area">
        <router-view v-slot="{ Component }">
          <Suspense>
            <template #default>
              <transition name="page" mode="out-in">
                <component :is="Component" />
              </transition>
            </template>
            <template #fallback>
              <div class="suspense-loading">
                <div class="loading-spinner" />
              </div>
            </template>
          </Suspense>
        </router-view>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import AppSidebar from './AppSidebar.vue'
import AppHeader from './AppHeader.vue'
</script>

<style scoped>
.main-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f8fafc;
}

.content-area {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

/* Suspense fallback */
.suspense-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #e2e8f0;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Page transition */
.page-enter-active,
.page-leave-active {
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.page-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.page-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
