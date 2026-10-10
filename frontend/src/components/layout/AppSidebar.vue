<template>
  <aside class="sidebar">
    <!-- Brand Logo -->
    <router-link to="/dashboard" class="sidebar-logo" aria-label="多模态检索平台首页" @click="$emit('navigate')">
      <div class="logo-icon">
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" width="16" height="16">
          <path d="M12 2L2 7l10 5 10-5-10-5z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
          <path d="M2 17l10 5 10-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M2 12l10 5 10-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>
      <div class="logo-text-wrap">
        <span class="logo-text">多模态检索平台</span>
        <span class="logo-sub">MULTIMODAL RETRIEVAL</span>
      </div>
    </router-link>

    <!-- Navigation Groups -->
    <nav class="sidebar-nav" aria-label="主要导航">
      <div v-for="(group, groupIndex) in navGroups" :key="group.label" class="nav-group">
        <div class="nav-group-label">
          <span class="nav-group-index">0{{ groupIndex + 1 }}</span>
          {{ group.label }}
        </div>
        <router-link
          v-for="(item, itemIndex) in group.items"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
          :style="{ '--i': flatIndex(groupIndex, itemIndex) }"
          :aria-current="isActive(item.path) ? 'page' : undefined"
          @click="$emit('navigate')"
        >
          <component :is="item.icon" class="nav-icon" />
          <span class="nav-label">{{ item.name }}</span>
          <span class="nav-marker" aria-hidden="true"></span>
        </router-link>
      </div>
    </nav>
    <div class="sidebar-footer">
      <span class="workspace-mark" aria-hidden="true">M<span> / </span>M</span>
      <div class="workspace-tagline">感知 · 理解 · 检索</div>
      <div class="workspace-status" :data-state="statusState">
        <span class="status-dot" aria-hidden="true"></span>
        <span class="status-text">{{ statusLabel }}</span>
        <span class="workspace-caption">v{{ appVersion }}</span>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  DashboardOutlined,
  CloudUploadOutlined,
  UnorderedListOutlined,
  TagsOutlined,
  FileSearchOutlined,
  FontSizeOutlined,
  PictureOutlined,
  SettingOutlined,
} from '@ant-design/icons-vue'
import { useSystemStore } from '@/stores/system'

const route = useRoute()
const systemStore = useSystemStore()
defineEmits<{ navigate: [] }>()

const navGroups = [
  {
    label: '数据处理',
    items: [
      { name: '数据概览', path: '/dashboard', icon: DashboardOutlined },
      { name: '数据导入', path: '/import', icon: CloudUploadOutlined },
      { name: '任务管理', path: '/tasks', icon: UnorderedListOutlined },
    ]
  },
  {
    label: '数据检索',
    items: [
      { name: '标签检索', path: '/search/tags', icon: TagsOutlined },
      { name: '标注查询', path: '/search/annotations', icon: FileSearchOutlined },
      { name: '文本检索', path: '/search/text', icon: FontSizeOutlined },
      { name: '图像检索', path: '/search/image', icon: PictureOutlined },
    ]
  },
  {
    label: '系统',
    items: [
      { name: '系统设置', path: '/settings', icon: SettingOutlined },
    ]
  }
]

const isActive = computed(() => (path: string) => route.path === path)

function flatIndex(groupIndex: number, itemIndex: number) {
  return navGroups.slice(0, groupIndex).reduce((sum, group) => sum + group.items.length, 0) + itemIndex
}

const appVersion = computed(() => systemStore.config?.version || '1.0.0')
const statusState = computed(() => (systemStore.isHealthy ? 'ok' : 'pending'))
const statusLabel = computed(() => (systemStore.isHealthy ? '服务在线' : '正在检查服务'))

onMounted(() => {
  if (!systemStore.isHealthy) systemStore.checkHealth()
})
</script>

<style scoped>
.sidebar {
  width: var(--sidebar-w);
  min-width: var(--sidebar-w);
  height: 100%;
  background: var(--ink);
  border-right: 1px solid var(--ink-line);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  z-index: 10;
  position: relative;
  isolation: isolate;
}

/* Faint perception grid, anchored to the bottom of the rail. */
.sidebar::before {
  content: '';
  position: absolute;
  inset: auto 0 0 0;
  height: 46%;
  background-image:
    linear-gradient(rgba(196, 236, 207, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(196, 236, 207, 0.06) 1px, transparent 1px);
  background-size: 28px 28px;
  -webkit-mask-image: linear-gradient(to top, rgba(0, 0, 0, 0.9), transparent);
  mask-image: linear-gradient(to top, rgba(0, 0, 0, 0.9), transparent);
  pointer-events: none;
  z-index: -1;
}

/* Brand Logo */
.sidebar-logo {
  height: 88px;
  min-height: 88px;
  padding: 0 24px;
  border-bottom: 1px solid var(--ink-line);
  display: flex;
  align-items: center;
  gap: 12px;
  box-sizing: border-box;
  color: inherit;
}

.logo-icon {
  width: 32px;
  height: 32px;
  background: var(--mint);
  border-radius: var(--radius-mark);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ink);
  flex-shrink: 0;
  transition: transform var(--duration-slow) var(--ease-spring), border-radius var(--duration-slow) var(--ease-out);
}
.sidebar-logo:hover .logo-icon {
  transform: rotate(-6deg) scale(1.04);
  border-radius: 2px 10px 2px 10px;
}

.logo-text-wrap {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.logo-text {
  font-size: 13px;
  font-weight: 700;
  color: #f1f5f4;
  letter-spacing: 0;
  line-height: 1.2;
}

.logo-sub {
  font: 500 9px var(--font-mono);
  color: var(--ink-text-muted);
  letter-spacing: 0.16em;
}

/* Navigation */
.sidebar-nav {
  flex: 1;
  overflow-y: auto;
  padding: 10px 0 12px;
  scrollbar-width: thin;
}

.nav-group {
  padding: 18px 16px 6px;
}

.nav-group-label {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 10px;
  font-weight: 600;
  color: var(--ink-text-muted);
  letter-spacing: 0.14em;
  padding: 0 12px;
  margin-bottom: 10px;
}
.nav-group-index {
  font: 500 9px var(--font-mono);
  color: var(--mint);
  opacity: .7;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 12px;
  margin-block: 2px;
  border-radius: var(--radius);
  cursor: pointer;
  color: var(--ink-text);
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  position: relative;
  overflow: hidden;
  transition:
    color var(--duration-fast) var(--ease-default),
    background-color var(--duration-fast) var(--ease-default),
    transform var(--duration-normal) var(--ease-out);
  animation: navReveal .55s var(--ease-out) both;
  animation-delay: calc(var(--i, 0) * 40ms + 80ms);
}

@keyframes navReveal {
  from { opacity: 0; transform: translateX(-10px); }
  to { opacity: 1; transform: translateX(0); }
}

.nav-item:hover {
  background: var(--ink-3);
  color: #fff;
}
.nav-item:hover .nav-icon { color: var(--mint); transform: translateX(1px) scale(1.06); }

.nav-item.active {
  background: var(--mint);
  color: var(--ink);
}
.nav-item.active .nav-icon { color: var(--ink); }

.nav-marker {
  margin-left: auto;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0;
  transform: scale(.4);
  transition: opacity var(--duration-normal) var(--ease-out), transform var(--duration-normal) var(--ease-spring);
}
.nav-item.active .nav-marker { opacity: 1; transform: scale(1); }

.nav-icon {
  font-size: 16px;
  width: 16px;
  text-align: center;
  flex-shrink: 0;
  color: var(--ink-text-muted);
  transition: color var(--duration-fast) var(--ease-default), transform var(--duration-normal) var(--ease-out);
}

.nav-label {
  line-height: 1;
}

.sidebar-footer {
  padding: 22px 24px 24px;
  border-top: 1px solid var(--ink-line);
  color: var(--ink-text);
  font-size: 12px;
}
.workspace-mark {
  display: block;
  margin-bottom: 12px;
  font: 600 30px/1 var(--font-heading);
  letter-spacing: -2px;
  color: #edf5f0;
}
.workspace-mark span { color: var(--mint); }
.workspace-tagline { letter-spacing: 0.08em; color: var(--ink-text); }

.workspace-status {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px dashed rgba(196, 236, 207, 0.16);
  font: 500 9px var(--font-mono);
  letter-spacing: 0.12em;
  color: var(--ink-text-muted);
  text-transform: uppercase;
}
.status-dot {
  position: relative;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ink-text-muted);
  flex-shrink: 0;
}
.status-dot::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: inherit;
}
.workspace-status[data-state="ok"] .status-dot { background: var(--mint); box-shadow: 0 0 8px rgba(196, 236, 207, .6); }
.workspace-status[data-state="ok"] .status-dot::after { animation: statusPing 2.4s var(--ease-out) infinite; }
.workspace-status[data-state="ok"] .status-text { color: var(--mint); }
.workspace-status[data-state="pending"] .status-dot { animation: pulse 1.4s ease-in-out infinite; }
.workspace-caption { margin-left: auto; }

@media (max-height: 760px) {
  .workspace-mark { display: none; }
  .workspace-tagline { display: none; }
  .workspace-status { margin-top: 0; padding-top: 0; border-top: 0; }
  .sidebar-footer { padding: 16px 24px; }
}
@media (max-height: 640px) {
  .sidebar-footer { display: none; }
  .sidebar-logo { min-height: 72px; height: 72px; }
  .nav-group { padding-top: 10px; }
}
</style>
