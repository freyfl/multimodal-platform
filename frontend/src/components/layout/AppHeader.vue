<template>
  <header class="app-header">
    <div class="header-left">
      <div class="header-breadcrumb">
        <span>AutoDrive</span>
        <i class="breadcrumb-sep">
          <RightOutlined style="font-size: 9px" />
        </i>
        <span class="breadcrumb-current">{{ pageTitle }}</span>
      </div>
    </div>
    <div class="header-actions">
      <div class="notif-wrap">
        <button class="btn-icon">
          <BellOutlined />
        </button>
        <span class="notif-dot"></span>
      </div>
      <button class="btn btn-primary" @click="$router.push('/import')">
        <PlusOutlined />
        导入数据
      </button>
      <a-dropdown :trigger="['click']">
        <div class="user-trigger">
          <div class="header-avatar">{{ userInitial }}</div>
          <span class="header-username">{{ authStore.user?.username || '' }}</span>
        </div>
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
import { BellOutlined, PlusOutlined, RightOutlined, UserOutlined, LockOutlined, LogoutOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

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
  height: 56px;
  min-height: 56px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  padding: 0 24px;
  gap: 16px;
  flex-shrink: 0;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.header-left {
  display: flex;
  align-items: center;
}

.header-breadcrumb {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #94a3b8;
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
  gap: 8px;
}

.notif-wrap {
  position: relative;
  display: inline-flex;
}

.btn-icon {
  width: 32px;
  height: 32px;
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
  padding: 7px 14px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  transition: all 0.15s;
  cursor: pointer;
  border: none;
}

.btn-primary {
  background: #0064ff;
  color: white;
  box-shadow: 0 1px 3px rgba(0, 100, 255, 0.3);
}

.btn-primary:hover {
  background: #0052d9;
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
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, #0064ff 0%, #7c3aed 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.header-username {
  font-size: 13px;
  font-weight: 500;
  color: #334155;
}
</style>
