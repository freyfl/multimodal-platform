<template>
  <div class="main-layout">
    <a class="skip-link" href="#main-content">跳转到主要内容</a>
    <AppSidebar class="desktop-sidebar" />
    <a-drawer v-model:open="menuOpen" placement="left" :width="264" title="工作台导航" :body-style="{ padding: 0 }" class="navigation-drawer" @after-open-change="restoreNavigationFocus">
      <AppSidebar @navigate="menuOpen = false" />
    </a-drawer>
    <div class="main-content" :inert="menuOpen || undefined">
      <AppHeader ref="header" :menu-open="menuOpen" @toggle-menu="menuOpen = !menuOpen" />
      <main id="main-content" class="content-area" tabindex="-1">
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
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppSidebar from './AppSidebar.vue'
import AppHeader from './AppHeader.vue'

const menuOpen = ref(false)
const header = ref<InstanceType<typeof AppHeader> | null>(null)
const route = useRoute()
const desktopMedia = window.matchMedia('(min-width: 961px)')
const closeOnDesktop = () => { if (desktopMedia.matches) menuOpen.value = false }
function restoreNavigationFocus(open: boolean) {
  if (!open && !desktopMedia.matches) header.value?.focusMenu()
}
watch(() => route.fullPath, () => { menuOpen.value = false })
onMounted(() => desktopMedia.addEventListener('change', closeOnDesktop))
onUnmounted(() => desktopMedia.removeEventListener('change', closeOnDesktop))
</script>

<style scoped>
.main-layout {
  display: flex;
  height: 100dvh;
  overflow: hidden;
}

.main-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--color-bg-page);
}

.content-area {
  flex: 1;
  overflow-y: auto;
  padding: 36px clamp(24px, 3vw, 52px) 48px;
  scrollbar-gutter: stable;
}

.content-area > :deep(*) {
  max-width: 1600px;
  margin-inline: auto;
}

.skip-link {
  position: fixed;
  top: 8px;
  left: 280px;
  z-index: 1100;
  padding: 12px 20px;
  background: white;
  transform: translateY(-150%);
}
.skip-link:focus { transform: translateY(0); }

@media (max-width: 960px) {
  .desktop-sidebar { display: none; }
  .content-area { padding: 24px; }
  .skip-link { left: 16px; }
}
@media (max-width: 600px) {
  .content-area { padding: 24px 16px 32px; scrollbar-gutter: auto; }
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
