<template>
  <div class="main-layout">
    <a class="skip-link" href="#main-content">跳转到主要内容</a>
    <AppSidebar class="desktop-sidebar" />
    <a-drawer v-model:open="menuOpen" placement="left" :width="272" title="工作台导航" :body-style="{ padding: 0 }" class="navigation-drawer" @after-open-change="restoreNavigationFocus">
      <AppSidebar @navigate="menuOpen = false" />
    </a-drawer>
    <div class="main-content" :inert="menuOpen || undefined">
      <main id="main-content" ref="scrollRegion" class="content-area" tabindex="-1" @scroll.passive="onScroll">
        <AppHeader ref="header" :menu-open="menuOpen" :scrolled="scrolled" @toggle-menu="menuOpen = !menuOpen" />
        <div class="content-inner">
          <router-view v-slot="{ Component }">
            <Suspense>
              <template #default>
                <transition name="page" mode="out-in">
                  <component :is="Component" />
                </transition>
              </template>
              <template #fallback>
                <div class="suspense-loading" role="status" aria-label="页面加载中">
                  <span class="loading-mark">M<span> / </span>M</span>
                </div>
              </template>
            </Suspense>
          </router-view>
        </div>
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
const scrolled = ref(false)
const header = ref<InstanceType<typeof AppHeader> | null>(null)
const scrollRegion = ref<HTMLElement | null>(null)
const route = useRoute()
const desktopMedia = window.matchMedia('(min-width: 961px)')
const closeOnDesktop = () => { if (desktopMedia.matches) menuOpen.value = false }
function restoreNavigationFocus(open: boolean) {
  if (!open && !desktopMedia.matches) header.value?.focusMenu()
}
function onScroll() {
  scrolled.value = (scrollRegion.value?.scrollTop ?? 0) > 8
}
watch(() => route.fullPath, () => {
  menuOpen.value = false
  scrollRegion.value?.scrollTo({ top: 0 })
  scrolled.value = false
})
onMounted(() => desktopMedia.addEventListener('change', closeOnDesktop))
onUnmounted(() => desktopMedia.removeEventListener('change', closeOnDesktop))
</script>

<style scoped>
.main-layout {
  display: flex;
  height: 100dvh;
  overflow: hidden;
  background: var(--color-bg-page);
}

.main-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
  isolation: isolate;
}

/* Perception-field texture: large faint grid fading in from the top-right. */
.main-content::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(23, 33, 38, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(23, 33, 38, 0.045) 1px, transparent 1px);
  background-size: 56px 56px;
  -webkit-mask-image: radial-gradient(ellipse 70% 60% at 100% 0%, rgba(0, 0, 0, 0.9), transparent 70%);
  mask-image: radial-gradient(ellipse 70% 60% at 100% 0%, rgba(0, 0, 0, 0.9), transparent 70%);
  pointer-events: none;
  z-index: -1;
}

.content-area {
  flex: 1;
  overflow-y: auto;
  scrollbar-gutter: stable;
  outline: none;
}

.content-inner {
  padding: 28px var(--page-gutter) 64px;
}

.content-inner > :deep(*) {
  max-width: var(--content-max);
  margin-inline: auto;
}

.skip-link {
  position: fixed;
  top: 8px;
  left: 280px;
  z-index: 1100;
  padding: 12px 20px;
  background: var(--ink);
  color: var(--mint);
  border-radius: var(--radius);
  font-size: 13px;
  transform: translateY(-150%);
  transition: transform var(--duration-normal) var(--ease-out);
}
.skip-link:focus { transform: translateY(0); }

@media (max-width: 960px) {
  .desktop-sidebar { display: none; }
  .content-inner { padding: 20px 24px 48px; }
  .skip-link { left: 16px; }
}
@media (max-width: 600px) {
  .content-inner { padding: 16px 16px 40px; }
  .content-area { scrollbar-gutter: auto; }
}

/* Suspense fallback */
.suspense-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 240px;
}
.loading-mark {
  font: 600 28px var(--font-heading);
  letter-spacing: -2px;
  color: var(--gray-300);
  animation: pulse 1.6s ease-in-out infinite;
}
.loading-mark span { color: var(--mint-deep); }
</style>
