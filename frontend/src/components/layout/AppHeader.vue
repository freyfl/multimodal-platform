<template>
  <header class="app-header" :class="{ scrolled }">
    <div class="header-left">
      <button ref="menuButton" class="btn-icon mobile-menu" aria-label="打开导航菜单" :aria-expanded="menuOpen" @click="$emit('toggle-menu')">
        <MenuOutlined />
      </button>
      <nav class="header-breadcrumb" aria-label="当前位置">
        <span class="breadcrumb-root">工作空间</span>
        <i class="breadcrumb-sep" aria-hidden="true">/</i>
        <transition name="crumb" mode="out-in">
          <span :key="pageTitle" class="breadcrumb-current">{{ pageTitle }}</span>
        </transition>
      </nav>
    </div>
    <div class="header-actions">
      <button v-if="route.path !== '/import'" class="btn btn-primary" @click="$router.push('/import')">
        <PlusOutlined />
        <span class="btn-label">导入数据</span>
      </button>
      <a-dropdown :trigger="['click']">
        <button class="user-trigger" aria-label="账户菜单" aria-haspopup="menu">
          <div class="header-avatar">{{ userInitial }}</div>
          <span class="header-username">{{ authStore.user?.username || '' }}</span>
          <DownOutlined class="user-chevron" />
        </button>
        <template #overlay>
          <a-menu @click="handleMenuClick">
            <a-menu-item key="profile" disabled>
              <UserOutlined />
              <span style="margin-left: 8px;">{{ authStore.user?.email || '无邮箱' }}</span>
            </a-menu-item>
            <a-menu-item v-if="authStore.user?.is_demo !== 1" key="password">
              <LockOutlined />
              <span style="margin-left: 8px;">修改密码</span>
            </a-menu-item>
            <a-menu-divider />
            <a-menu-item key="logout" style="color: #ef4444;">
              <LogoutOutlined />
              <span style="margin-left: 8px;">退出登录</span>
            </a-menu-item>
          </a-menu>
        </template>
      </a-dropdown>
    </div>
  </header>

  <!-- 修改密码弹窗 -->
  <a-modal
    v-model:open="passwordModalOpen"
    title="修改密码"
    @ok="handleChangePassword"
    :confirmLoading="changingPassword"
    :okText="'确认'"
    :cancelText="'取消'"
  >
    <a-form layout="vertical">
      <a-form-item label="当前密码">
        <a-input-password v-model:value="pwdForm.oldPassword" placeholder="请输入当前密码" />
      </a-form-item>
      <a-form-item label="新密码">
        <a-input-password v-model:value="pwdForm.newPassword" placeholder="请输入新密码" />
      </a-form-item>
      <a-form-item label="确认新密码">
        <a-input-password v-model:value="pwdForm.confirmPassword" placeholder="请再次输入新密码" />
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MenuOutlined, DownOutlined, PlusOutlined, UserOutlined, LockOutlined, LogoutOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
defineProps<{ menuOpen: boolean; scrolled?: boolean }>()
defineEmits<{ 'toggle-menu': [] }>()
const menuButton = ref<HTMLButtonElement | null>(null)
defineExpose({ focusMenu: () => menuButton.value?.focus() })

const pageTitle = computed(() => {
  return (route.meta?.title as string) || '多模态检索平台'
})

const userInitial = computed(() =>
  authStore.user?.username?.charAt(0)?.toUpperCase() || '?'
)

// 修改密码
const passwordModalOpen = ref(false)
const changingPassword = ref(false)
const pwdForm = reactive({ oldPassword: '', newPassword: '', confirmPassword: '' })

function handleMenuClick({ key }: { key: string }) {
  if (key === 'logout') {
    authStore.logout().then(() => router.push('/login'))
  } else if (key === 'password') {
    pwdForm.oldPassword = ''
    pwdForm.newPassword = ''
    pwdForm.confirmPassword = ''
    passwordModalOpen.value = true
  }
}

async function handleChangePassword() {
  if (!pwdForm.oldPassword || !pwdForm.newPassword) {
    message.warning('请填写完整')
    return
  }
  if (pwdForm.newPassword !== pwdForm.confirmPassword) {
    message.warning('两次密码不一致')
    return
  }
  changingPassword.value = true
  try {
    await authApi.changePassword(pwdForm.oldPassword, pwdForm.newPassword)
    message.success('密码修改成功')
    passwordModalOpen.value = false
  } catch (err: any) {
    const msg = err?.response?.data?.detail || '修改失败'
    message.error(msg)
  } finally {
    changingPassword.value = false
  }
}
</script>

<style scoped>
.app-header {
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
  height: var(--header-h);
  min-height: var(--header-h);
  background: color-mix(in srgb, var(--color-bg-page) 82%, transparent);
  -webkit-backdrop-filter: blur(14px) saturate(1.2);
  backdrop-filter: blur(14px) saturate(1.2);
  border-bottom: 1px solid transparent;
  display: flex;
  align-items: center;
  padding: 0 var(--page-gutter);
  gap: 16px;
  flex-shrink: 0;
  transition: border-color var(--duration-normal) var(--ease-default), box-shadow var(--duration-normal) var(--ease-default);
}
.app-header.scrolled {
  border-bottom-color: var(--color-border);
  box-shadow: 0 8px 24px -16px rgba(23, 33, 38, 0.18);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.header-breadcrumb {
  display: flex;
  align-items: center;
  gap: 10px;
  font: 500 10px var(--font-mono);
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--gray-500);
  min-width: 0;
}

.breadcrumb-sep {
  font-style: normal;
  color: var(--gray-300);
}

.breadcrumb-current {
  display: inline-block;
  font: 600 13px var(--font-body);
  letter-spacing: 0;
  text-transform: none;
  color: var(--gray-900);
  white-space: nowrap;
}
.crumb-enter-active, .crumb-leave-active { transition: opacity var(--duration-normal) var(--ease-out), transform var(--duration-normal) var(--ease-out); }
.crumb-enter-from { opacity: 0; transform: translateY(6px); }
.crumb-leave-to { opacity: 0; transform: translateY(-6px); }

.header-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 14px;
}

.btn-icon {
  width: 40px;
  height: 40px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius);
  color: var(--gray-600);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: background var(--transition-default), color var(--transition-default);
  font-size: 16px;
}

.btn-icon:hover {
  background: var(--gray-100);
  color: var(--gray-900);
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 38px;
  padding: 8px 16px;
  border-radius: var(--radius);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: none;
}

.btn-primary {
  background: var(--color-primary);
  color: white;
  box-shadow: var(--shadow-primary);
}
.btn-primary .anticon { transition: transform var(--duration-normal) var(--ease-spring); }
.btn-primary:hover .anticon { transform: rotate(90deg); }

.user-trigger {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 10px 4px 4px;
  border-radius: var(--radius-pill);
  cursor: pointer;
  border: 1px solid transparent;
  transition: background var(--transition-default), border-color var(--transition-default);
}

.user-trigger:hover,
.user-trigger[aria-expanded="true"] {
  background: var(--white);
  border-color: var(--color-border);
}

.header-avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: var(--ink);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--mint);
  font: 600 11px var(--font-heading);
  flex-shrink: 0;
}

.header-username {
  font-size: 13px;
  font-weight: 500;
  color: var(--gray-800);
}
.user-chevron { font-size: 9px; color: var(--gray-500); transition: transform var(--duration-normal) var(--ease-out); }
.user-trigger[aria-expanded="true"] .user-chevron { transform: rotate(180deg); }
.mobile-menu { display: none; }
@media (max-width: 960px) {
  .mobile-menu { display: inline-flex; margin-left: -8px; }
}
@media (max-width: 600px) {
  .app-header { padding: 0 12px; gap: 8px; height: 60px; min-height: 60px; }
  .header-actions { gap: 8px; }
  .header-username, .user-chevron, .breadcrumb-root, .breadcrumb-sep { display: none; }
  .btn { padding: 0; width: 38px; justify-content: center; }
  .btn-label { display: none; }
  .user-trigger { padding: 2px; }
  .header-breadcrumb { white-space: nowrap; }
}
</style>
