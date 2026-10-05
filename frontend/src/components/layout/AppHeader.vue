<template>
  <header class="app-header">
    <div class="header-left">
      <button ref="menuButton" class="btn-icon mobile-menu" aria-label="打开导航菜单" :aria-expanded="menuOpen" @click="$emit('toggle-menu')">
        <MenuOutlined />
      </button>
      <div class="header-breadcrumb">
        <span class="breadcrumb-root">工作空间</span>
        <i class="breadcrumb-sep">
          <RightOutlined style="font-size: 9px" />
        </i>
        <span class="breadcrumb-current">{{ pageTitle }}</span>
      </div>
    </div>
    <div class="header-actions">
      <button class="btn btn-primary" @click="$router.push('/import')">
        <PlusOutlined />
        导入数据
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
import { MenuOutlined, DownOutlined, PlusOutlined, RightOutlined, UserOutlined, LockOutlined, LogoutOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
defineProps<{ menuOpen: boolean }>()
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
  height: var(--header-h);
  min-height: var(--header-h);
  background: var(--color-bg-page);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  padding: 0 clamp(24px, 3vw, 52px);
  gap: 16px;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-breadcrumb {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: var(--gray-500);
}

.breadcrumb-sep {
  display: flex;
  align-items: center;
  font-style: normal;
}

.breadcrumb-current {
  color: #1e293b;
  font-weight: 600;
}

.header-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 20px;
}

.notif-wrap {
  position: relative;
  display: inline-flex;
}

.btn-icon {
  width: 40px;
  height: 40px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  color: #64748b;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 0.15s;
  font-size: 16px;
}

.btn-icon:hover {
  background: #f1f5f9;
  color: #334155;
}

.notif-dot {
  width: 8px;
  height: 8px;
  background: #ef4444;
  border-radius: 50%;
  position: absolute;
  top: 6px;
  right: 6px;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 38px;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  transition: all 0.15s;
  cursor: pointer;
  border: none;
}

.btn-primary {
  background: var(--color-primary);
  color: white;
  box-shadow: none;
}

.btn-primary:hover {
  background: var(--color-primary-dark);
  box-shadow: 0 2px 8px rgba(0, 100, 255, 0.4);
  transform: translateY(-1px);
}

.user-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}

.user-trigger:hover {
  background: #f1f5f9;
}

.header-avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: #dfe7e4;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #34483d;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.header-username {
  font-size: 13px;
  font-weight: 500;
  color: #334155;
}
.user-chevron { font-size: 9px; color: var(--gray-500); }
.mobile-menu { display: none; }
@media (max-width: 960px) {
  .mobile-menu { display: inline-flex; }
}
@media (max-width: 600px) {
  .app-header { padding: 0 12px; gap: 8px; }
  .header-actions { gap: 8px; }
  .header-username, .user-chevron, .breadcrumb-root, .breadcrumb-sep { display: none; }
  .btn { padding: 8px 12px; }
  .user-trigger { padding: 4px; }
  .header-breadcrumb { white-space: nowrap; }
}
</style>
