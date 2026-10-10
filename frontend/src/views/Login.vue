<template>
  <AuthLayout>
    <div class="login-card">
      <!-- Brand -->
      <div class="brand stagger-item" style="--i: 2">
        <div class="brand-icon">
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" width="24" height="24">
            <path d="M12 2L2 7l10 5 10-5-10-5z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M2 17l10 5 10-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M2 12l10 5 10-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
        <span class="eyebrow brand-eyebrow"><span></span>SIGN IN</span>
        <h1 class="brand-title">欢迎回来<span class="title-period" aria-hidden="true">.</span></h1>
        <p class="brand-sub">登录，继续你的数据探索。</p>
      </div>

      <!-- Form -->
      <a-form layout="vertical" :model="form" class="stagger-item" style="--i: 5" @finish="handleLogin">
        <a-form-item label="用户名" name="username">
          <a-input
            v-model:value="form.username"
            size="large"
            placeholder="请输入用户名"
            autocomplete="username"
            :disabled="loading"
          >
            <template #prefix><UserOutlined /></template>
          </a-input>
        </a-form-item>

        <a-form-item label="密码" name="password">
          <a-input-password
            v-model:value="form.password"
            size="large"
            placeholder="请输入密码"
            autocomplete="current-password"
            :disabled="loading"
          >
            <template #prefix><LockOutlined /></template>
          </a-input-password>
        </a-form-item>

        <a-button
          type="primary"
          size="large"
          block
          :loading="loading"
          class="login-btn"
          html-type="submit"
        >
          <span>进入工作空间</span>
          <ArrowRightOutlined class="login-arrow" />
        </a-button>

      </a-form>

      <div class="form-footer stagger-item" style="--i: 8">
        还没有账号？
        <router-link to="/register" class="link">立即注册</router-link>
      </div>
    </div>
  </AuthLayout>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { UserOutlined, LockOutlined, ArrowRightOutlined } from '@ant-design/icons-vue'
import { useAuthStore } from '@/stores/auth'
import AuthLayout from '@/components/layout/AuthLayout.vue'

const router = useRouter()
const authStore = useAuthStore()

const form = reactive({
  username: '',
  password: '',
})
const loading = ref(false)

async function handleLogin() {
  if (loading.value) return
  if (!form.username || !form.password) {
    message.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await authStore.login(form.username, form.password)
    message.success('登录成功')
    router.push('/dashboard')
  } catch (err: any) {
    const msg = err?.response?.data?.detail || '登录失败，请检查用户名和密码'
    message.error(msg)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-card {
  width: 100%;
  max-width: 400px;
  padding: 20px 16px;
}

.brand {
  text-align: left;
  margin-bottom: 34px;
}

.brand-icon {
  width: 48px;
  height: 48px;
  background: var(--mint);
  border-radius: var(--radius-mark);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ink);
  margin-bottom: 22px;
}
.brand-eyebrow { display: flex; margin-bottom: 12px; }

.brand-title {
  font-size: 32px;
  font-weight: 700;
  color: var(--gray-900);
  margin: 0 0 10px;
  letter-spacing: -0.01em;
}
.title-period { color: var(--color-primary); margin-left: 2px; }

.brand-sub {
  font-size: 13px;
  color: var(--gray-500);
  margin: 0;
}

.login-btn {
  height: 48px;
  font-size: 15px;
  font-weight: 600;
  border-radius: var(--radius-md) !important;
  margin-top: 6px;
  gap: 10px !important;
}
.login-arrow { font-size: 13px; transition: transform var(--duration-normal) var(--ease-out); }
.login-btn:hover .login-arrow { transform: translateX(4px); }

.form-footer {
  text-align: center;
  margin-top: 22px;
  font-size: 13px;
  color: var(--gray-500);
}

.form-footer .link {
  color: var(--color-primary);
  font-weight: 500;
  text-decoration: none;
  position: relative;
}
.form-footer .link::after {
  content: '';
  position: absolute;
  left: 0; right: 0; bottom: -2px;
  height: 1px;
  background: currentColor;
  transform: scaleX(0);
  transform-origin: right;
  transition: transform var(--duration-normal) var(--ease-out);
}
.form-footer .link:hover::after { transform: scaleX(1); transform-origin: left; }

.login-card :deep(.ant-input-affix-wrapper) { padding: 11px 14px; border-radius: var(--radius-md) !important; }
.login-card :deep(.ant-input-prefix) { margin-right: 10px; color: var(--gray-400); transition: color var(--transition-default); }
.login-card :deep(.ant-input-affix-wrapper-focused .ant-input-prefix) { color: var(--color-primary); }
.login-card :deep(.ant-form-item-label) { padding-bottom: 8px; }
.login-card :deep(.ant-form-item) { margin-bottom: 20px; }
</style>
