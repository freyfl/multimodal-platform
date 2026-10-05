<template>
  <AuthLayout>
    <div class="register-card">
      <!-- Brand -->
      <div class="brand">
        <div class="brand-icon">
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" width="24" height="24">
            <path d="M12 2L2 7l10 5 10-5-10-5z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M2 17l10 5 10-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M2 12l10 5 10-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
        <h1 class="brand-title">创建账号</h1>
        <p class="brand-sub">开启你的多模态数据工作空间。</p>
      </div>

      <!-- Form -->
      <a-form layout="vertical" :model="form" @finish="handleRegister">
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

        <a-form-item label="邮箱（可选）" name="email">
          <a-input
            v-model:value="form.email"
            size="large"
            placeholder="请输入邮箱"
            autocomplete="email"
            type="email"
            :disabled="loading"
          >
            <template #prefix><MailOutlined /></template>
          </a-input>
        </a-form-item>

        <a-form-item label="密码" name="password">
          <a-input-password
            v-model:value="form.password"
            size="large"
            placeholder="请输入密码"
            autocomplete="new-password"
            :disabled="loading"
          >
            <template #prefix><LockOutlined /></template>
          </a-input-password>
          <div class="password-strength" v-if="form.password">
            <div class="strength-bar">
              <div class="strength-fill" :class="passwordStrengthClass" :style="{ width: passwordStrengthPercent + '%' }"></div>
            </div>
            <span class="strength-text" :class="passwordStrengthClass">{{ passwordStrengthLabel }}</span>
          </div>
        </a-form-item>

        <a-form-item label="确认密码" name="confirmPassword">
          <a-input-password
            v-model:value="form.confirmPassword"
            size="large"
            placeholder="请再次输入密码"
            autocomplete="new-password"
            :disabled="loading"
          >
            <template #prefix><LockOutlined /></template>
          </a-input-password>
        </a-form-item>

        <a-button
          type="primary"
          html-type="submit"
          size="large"
          block
          :loading="loading"
          class="register-btn"
        >
          注册
        </a-button>
      </a-form>

      <div class="form-footer">
        已有账号？
        <router-link to="/login" class="link">立即登录</router-link>
      </div>
    </div>
  </AuthLayout>
</template>

<script setup lang="ts">
import { reactive, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { UserOutlined, LockOutlined, MailOutlined } from '@ant-design/icons-vue'
import { useAuthStore } from '@/stores/auth'
import AuthLayout from '@/components/layout/AuthLayout.vue'

const router = useRouter()
const authStore = useAuthStore()

const form = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
})
const loading = ref(false)

// 密码强度计算
const passwordStrength = computed(() => {
  const p = form.password
  if (!p) return 0
  let score = 0
  if (p.length >= 6) score++
  if (p.length >= 10) score++
  if (/[a-z]/.test(p) && /[A-Z]/.test(p)) score++
  if (/\d/.test(p)) score++
  if (/[^a-zA-Z0-9]/.test(p)) score++
  return Math.min(score, 4)
})

const passwordStrengthClass = computed(() => {
  const map: Record<number, string> = { 0: 'weak', 1: 'weak', 2: 'fair', 3: 'good', 4: 'strong' }
  return map[passwordStrength.value]
})

const passwordStrengthPercent = computed(() => (passwordStrength.value / 4) * 100)

const passwordStrengthLabel = computed(() => {
  const map: Record<number, string> = { 0: '弱', 1: '弱', 2: '一般', 3: '良好', 4: '强' }
  return map[passwordStrength.value]
})

async function handleRegister() {
  if (loading.value) return
  if (!form.username || !form.password) {
    message.warning('请填写用户名和密码')
    return
  }
  if (form.password !== form.confirmPassword) {
    message.warning('两次密码输入不一致')
    return
  }
  if (form.password.length < 6) {
    message.warning('密码长度至少 6 位')
    return
  }

  loading.value = true
  try {
    await authStore.register(form.username, form.password, form.email || undefined)
    message.success('注册成功')
    router.push('/dashboard')
  } catch (err: any) {
    const msg = err?.response?.data?.detail || '注册失败，请重试'
    message.error(msg)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.register-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-50, #f8fafc);
  padding: 24px;
}

.register-card {
  width: 100%;
  max-width: 400px;
  padding: 16px;
}

.brand {
  text-align: left;
  margin-bottom: 32px;
}

.brand-icon {
  width: 48px;
  height: 48px;
  background: #e3ebe5;
  border-radius: 10px 2px 10px 2px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #345748;
  margin-bottom: 16px;
}

.brand-title {
  font-size: 30px;
  font-weight: 700;
  color: var(--gray-900, #0f172a);
  margin: 0 0 10px;
  letter-spacing: -0.3px;
}

.brand-sub {
  font-size: 13px;
  color: var(--gray-400, #94a3b8);
  letter-spacing: 0;
  margin: 0;
}

.password-strength {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}

.strength-bar {
  flex: 1;
  height: 4px;
  background: #e2e8f0;
  border-radius: 2px;
  overflow: hidden;
}

.strength-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s, background 0.3s;
}

.strength-fill.weak { background: #ef4444; }
.strength-fill.fair { background: #f97316; }
.strength-fill.good { background: #22c55e; }
.strength-fill.strong { background: #10b981; }

.strength-text {
  font-size: 11px;
  min-width: 28px;
}

.strength-text.weak { color: #ef4444; }
.strength-text.fair { color: #f97316; }
.strength-text.good { color: #22c55e; }
.strength-text.strong { color: #10b981; }

.register-btn {
  height: 44px;
  font-size: 15px;
  font-weight: 600;
  border-radius: 10px;
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
