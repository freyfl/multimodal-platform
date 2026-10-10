<template>
  <AuthLayout>
    <div class="register-card">
      <!-- Brand -->
      <div class="brand stagger-item" style="--i: 2">
        <div class="brand-icon">
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" width="24" height="24">
            <path d="M12 2L2 7l10 5 10-5-10-5z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M2 17l10 5 10-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M2 12l10 5 10-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
        <span class="eyebrow brand-eyebrow"><span></span>账户 / 注册</span>
        <h1 class="brand-title">创建账号<span class="title-period" aria-hidden="true">.</span></h1>
        <p class="brand-sub">开启你的多模态数据工作空间。</p>
      </div>

      <!-- Form -->
      <a-form layout="vertical" :model="form" class="stagger-item" style="--i: 5" @finish="handleRegister">
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
          <span>创建并进入</span>
          <ArrowRightOutlined class="register-arrow" />
        </a-button>
      </a-form>

      <div class="form-footer stagger-item" style="--i: 8">
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
import { UserOutlined, LockOutlined, MailOutlined, ArrowRightOutlined } from '@ant-design/icons-vue'
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
.register-card {
  width: 100%;
  max-width: 400px;
  padding: 16px;
}

.brand {
  text-align: left;
  margin-bottom: 30px;
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
.title-period { color: var(--color-accent); margin-left: 2px; }

.brand-sub {
  font-size: 13px;
  color: var(--gray-500);
  margin: 0;
}

.password-strength {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}

.strength-bar {
  flex: 1;
  height: 3px;
  background: var(--gray-200);
  border-radius: 2px;
  overflow: hidden;
}

.strength-fill {
  height: 100%;
  border-radius: 2px;
  transition: width var(--duration-slow) var(--ease-out), background var(--duration-slow) var(--ease-default);
}

.strength-fill.weak { background: var(--color-error); }
.strength-fill.fair { background: var(--color-warning); }
.strength-fill.good { background: var(--mint-deep); }
.strength-fill.strong { background: var(--color-success); }

.strength-text {
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.06em;
  min-width: 28px;
}

.strength-text.weak { color: var(--color-error); }
.strength-text.fair { color: var(--color-warning); }
.strength-text.good { color: var(--mint-deep); }
.strength-text.strong { color: var(--color-success); }

.register-btn {
  height: 48px;
  font-size: 15px;
  font-weight: 600;
  border-radius: var(--radius-md) !important;
  margin-top: 6px;
  gap: 10px !important;
}
.register-arrow { font-size: 13px; color: var(--mint); transition: transform var(--duration-normal) var(--ease-out); }
.register-btn:hover .register-arrow { transform: translateX(4px); }

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

.register-card :deep(.ant-input-affix-wrapper) { padding: 11px 14px; border-radius: var(--radius-md) !important; }
.register-card :deep(.ant-input-prefix) { margin-right: 10px; color: var(--gray-400); transition: color var(--transition-default); }
.register-card :deep(.ant-input-affix-wrapper-focused .ant-input-prefix) { color: var(--color-primary); }
.register-card :deep(.ant-form-item-label) { padding-bottom: 8px; }
.register-card :deep(.ant-form-item) { margin-bottom: 18px; }
</style>
