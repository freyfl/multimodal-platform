<template>
  <div class="login-page">
    <div class="login-card">
      <!-- Brand -->
      <div class="brand">
        <div class="brand-icon">
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" width="24" height="24">
            <path d="M12 2L2 7l10 5 10-5-10-5z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M2 17l10 5 10-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M2 12l10 5 10-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
        <h1 class="brand-title">多模态检索平台</h1>
        <p class="brand-sub">MULTIMODAL RETRIEVAL</p>
      </div>

      <!-- Form -->
      <a-form layout="vertical" :model="form" @finish="handleLogin">
        <a-form-item label="用户名" name="username">
          <a-input
            v-model:value="form.username"
            size="large"
            placeholder="请输入用户名"
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
            :disabled="loading"
            @pressEnter="handleLogin"
          >
            <template #prefix><LockOutlined /></template>
          </a-input-password>
        </a-form-item>

        <div class="form-extra">
          <a-checkbox v-model:checked="rememberMe">记住我</a-checkbox>
        </div>

        <a-button
          type="primary"
          size="large"
          block
          :loading="loading"
          class="login-btn"
          html-type="submit"
          @click="handleLogin"
        >
          登录
        </a-button>

      </a-form>

      <div class="form-footer">
        还没有账号？
        <router-link to="/register" class="link">立即注册</router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { UserOutlined, LockOutlined } from '@ant-design/icons-vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const form = reactive({
  username: '',
  password: '',
})
const rememberMe = ref(true)
const loading = ref(false)

async function handleLogin() {
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
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-50, #f8fafc);
  padding: 24px;
}

.login-card {
  width: 100%;
  max-width: 400px;
  background: #fff;
  border-radius: 16px;
  padding: 40px 36px 32px;
  box-shadow: var(--shadow-lg, 0 10px 15px rgba(0,0,0,0.08), 0 4px 6px rgba(0,0,0,0.05));
}

.brand {
  text-align: center;
  margin-bottom: 32px;
}

.brand-icon {
  width: 48px;
  height: 48px;
  background: linear-gradient(135deg, #0064ff 0%, #4080ff 100%);
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: white;
  margin-bottom: 16px;
  box-shadow: 0 4px 12px rgba(0, 100, 255, 0.3);
}

.brand-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--gray-900, #0f172a);
  margin: 0 0 4px;
  letter-spacing: -0.3px;
}

.brand-sub {
  font-size: 11px;
  color: var(--gray-400, #94a3b8);
  letter-spacing: 2px;
  margin: 0;
}

.form-extra {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.login-btn {
  height: 44px;
  font-size: 15px;
  font-weight: 600;
  border-radius: 10px;
}

.demo-hint {
  text-align: center;
  margin-top: 14px;
  font-size: 13px;
  color: #e53e3e;
  font-weight: 500;
}

.demo-hint strong {
  font-weight: 700;
}

.form-footer {
  text-align: center;
  margin-top: 20px;
  font-size: 13px;
  color: var(--gray-500, #64748b);
}

.form-footer .link {
  color: var(--color-primary, #0064ff);
  font-weight: 500;
  text-decoration: none;
}

.form-footer .link:hover {
  text-decoration: underline;
}
</style>
