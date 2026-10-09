/**
 * Vue Router 配置
 */
import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/',
    redirect: '/dashboard'
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { requiresAuth: false, title: '登录' }
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/Register.vue'),
    meta: { requiresAuth: false, title: '注册' }
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/views/Dashboard.vue'),
    meta: { title: '数据概览' }
  },
  {
    path: '/import',
    name: 'Import',
    component: () => import('@/views/DataImport.vue'),
    meta: { title: '数据导入' }
  },
  {
    path: '/tasks',
    name: 'Tasks',
    component: () => import('@/views/TaskManagement.vue'),
    meta: { title: '任务管理' }
  },
  {
    path: '/search/tags',
    name: 'TagSearch',
    component: () => import('@/views/TagSearch.vue'),
    meta: { title: '标签检索' }
  },
  {
    path: '/search/annotations',
    name: 'AnnotationSearch',
    component: () => import('@/views/AnnotationSearch.vue'),
    meta: { title: '标注查询' }
  },
  {
    path: '/search/text',
    name: 'TextSearch',
    component: () => import('@/views/TextSearch.vue'),
    meta: { title: '文本检索' }
  },
  {
    path: '/search/image',
    name: 'ImageSearch',
    component: () => import('@/views/ImageSearch.vue'),
    meta: { title: '图像检索' }
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/views/Settings.vue'),
    meta: { title: '系统设置' }
  },
  // Legacy redirects for old paths
  {
    path: '/tags',
    redirect: '/search/tags'
  },
  {
    path: '/text',
    redirect: '/search/text'
  },
  {
    path: '/image',
    redirect: '/search/image'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

const publicRoutes = ['/login', '/register']

// 路由守卫 - 认证 + 标题
router.beforeEach(async (to, _from, next) => {
  // 更新页面标题
  document.title = to.meta.title ? `${to.meta.title} - 多模态数据检索平台` : '多模态数据检索平台'

  const isPublic = publicRoutes.includes(to.path)

  // 若 localStorage 中有 token，先等待 auth store 初始化完成再判断
  const token = localStorage.getItem('accessToken')
  if (token && !isPublic) {
    const authStore = useAuthStore()
    await authStore.ensureInit()
  }

  // 初始化完成后重新读取 token（init 可能已清除过期 token）
  const currentToken = localStorage.getItem('accessToken')

  if (!currentToken && !isPublic) {
    next('/login')
  } else if (currentToken && isPublic) {
    next('/dashboard')
  } else {
    next()
  }
})

export default router
