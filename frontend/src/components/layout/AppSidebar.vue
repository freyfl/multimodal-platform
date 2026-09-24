<template>
  <aside class="sidebar">
    <!-- Brand Logo -->
    <div class="sidebar-logo">
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
    </div>

    <!-- Navigation Groups -->
    <nav class="sidebar-nav">
      <div v-for="group in navGroups" :key="group.label" class="nav-group">
        <div class="nav-group-label">{{ group.label }}</div>
        <router-link
          v-for="item in group.items"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
        >
          <component :is="item.icon" class="nav-icon" />
          <span class="nav-label">{{ item.name }}</span>
        </router-link>
      </div>
    </nav>


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
  width: 220px;
  min-width: 220px;
  height: 100vh;
  background: #ffffff;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.06);
  z-index: 10;
}

/* Brand Logo */
.sidebar-logo {
  height: 56px;
  min-height: 56px;
  padding: 0 20px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  gap: 10px;
  box-sizing: border-box;
}

.logo-icon {
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, #0064ff 0%, #4080ff 100%);
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(0, 100, 255, 0.3);
}

.logo-text-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.logo-text {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.3px;
  line-height: 1.2;
}

.logo-sub {
  font-size: 10px;
  color: #94a3b8;
  font-weight: 400;
  letter-spacing: 0.5px;
}

/* Navigation */
.sidebar-nav {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0 0;
}

.nav-group {
  padding: 16px 12px 8px;
}

.nav-group-label {
  font-size: 10px;
  font-weight: 600;
  color: #94a3b8;
  letter-spacing: 1px;
  text-transform: uppercase;
  padding: 0 8px;
  margin-bottom: 4px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
  color: #475569;
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  position: relative;
}

.nav-item:hover {
  background: #f8fafc;
  color: #1e293b;
}

.nav-item.active {
  background: #e8f0ff;
  color: #0064ff;
}

.nav-icon {
  font-size: 13px;
  width: 16px;
  text-align: center;
  flex-shrink: 0;
  color: #94a3b8;
}

.nav-item.active .nav-icon {
  color: #0064ff;
}

.nav-label {
  line-height: 1;
}


</style>
