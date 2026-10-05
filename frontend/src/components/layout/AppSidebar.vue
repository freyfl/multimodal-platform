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
      <div v-for="group in navGroups" :key="group.label" class="nav-group">
        <div class="nav-group-label">{{ group.label }}</div>
        <router-link
          v-for="item in group.items"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
          @click="$emit('navigate')"
        >
          <component :is="item.icon" class="nav-icon" />
          <span class="nav-label">{{ item.name }}</span>
        </router-link>
      </div>
    </nav>
    <div class="sidebar-footer">
      <span class="workspace-mark" aria-hidden="true">M<span> / </span>M</span>
      <div>感知 · 理解 · 检索</div>
      <span class="workspace-caption">MULTIMODAL WORKSPACE</span>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  DashboardOutlined,
  CloudUploadOutlined,
  UnorderedListOutlined,
  TagsOutlined,
  FileSearchOutlined,
  PictureOutlined,
  SettingOutlined,
} from '@ant-design/icons-vue'

const route = useRoute()
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
      { name: '文本检索', path: '/search/text', icon: FileSearchOutlined },
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

const isActive = computed(() => (path: string) => {
  return route.path === path
})
</script>

<style scoped>
.sidebar {
  width: var(--sidebar-w);
  min-width: var(--sidebar-w);
  height: 100%;
  background: #172126;
  border-right: 1px solid #293338;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  z-index: 10;
}

/* Brand Logo */
.sidebar-logo {
  height: 88px;
  min-height: 88px;
  padding: 0 24px;
  border-bottom: 1px solid #303b40;
  display: flex;
  align-items: center;
  gap: 10px;
  box-sizing: border-box;
}

.logo-icon {
  width: 32px;
  height: 32px;
  background: #c4eccf;
  border-radius: 8px 2px 8px 2px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #172126;
  flex-shrink: 0;
}

.logo-text-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.logo-text {
  font-size: 13px;
  font-weight: 700;
  color: #f1f5f4;
  letter-spacing: -0.3px;
  line-height: 1.2;
}

.logo-sub {
  font-size: 10px;
  color: #a0aeb4;
  font-weight: 400;
  letter-spacing: 0.5px;
}

/* Navigation */
.sidebar-nav {
  flex: 1;
  overflow-y: auto;
  padding: 12px 0;
}

.nav-group {
  padding: 16px 16px 8px;
}

.nav-group-label {
  font-size: 10px;
  font-weight: 600;
  color: #95a6ae;
  letter-spacing: 1px;
  text-transform: uppercase;
  padding: 0 8px;
  margin-bottom: 10px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 12px;
  margin-block: 3px;
  border-radius: 7px;
  cursor: pointer;
  transition: all 0.15s;
  color: #bbc6ca;
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  position: relative;
}

.nav-item:hover {
  background: #273339;
  color: #fff;
}

.nav-item.active {
  background: #c4eccf;
  color: #172126;
}
.nav-item.active::after {
  content: '';
  margin-left: auto;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}

.nav-icon {
  font-size: 16px;
  width: 16px;
  text-align: center;
  flex-shrink: 0;
  color: #94a3b8;
}

.nav-item.active .nav-icon {
  color: #172126;
}

.nav-label {
  line-height: 1;
}
.sidebar-footer {
  padding: 24px 28px 28px;
  border-top: 1px solid #303b40;
  color: #bdc9ce;
  font-size: 12px;
}
.workspace-mark { display: block; margin-bottom: 16px; font: 600 30px var(--font-heading); letter-spacing: -2px; color: #edf5f0; }
.workspace-mark span { color: #c4eccf; }
.workspace-caption { display: block; margin-top: 6px; font: 9px var(--font-mono); letter-spacing: 1px; color: #95a6ae; }
@media (max-height: 700px) {
  .sidebar-footer { display: none; }
  .sidebar-logo { min-height: 72px; height: 72px; }
  .nav-group { padding-top: 10px; }
}
</style>
