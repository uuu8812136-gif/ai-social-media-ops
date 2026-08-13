<template>
  <div class="login-page">
    <div class="login-left">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
      <div class="orb orb-3"></div>
      <div class="brand-area">
        <div class="brand-badge">AI-POWERED</div>
        <h1 class="brand-title">社媒矩阵<br />运营系统</h1>
        <p class="brand-desc">AI赋能 · 人工确认 · 合规优先</p>
        <div class="brand-features">
          <div class="feature-item">
            <div class="feature-icon-wrap"><span class="feature-emoji">✦</span></div>
            <div>
              <div class="feature-title">AI 脚本/文案生成</div>
              <div class="feature-sub">风控预检 · 一键生成</div>
            </div>
          </div>
          <div class="feature-item">
            <div class="feature-icon-wrap"><span class="feature-emoji">◈</span></div>
            <div>
              <div class="feature-title">线索三池管理</div>
              <div class="feature-sub">智能分配 · 全链路追踪</div>
            </div>
          </div>
          <div class="feature-item">
            <div class="feature-icon-wrap"><span class="feature-emoji">◉</span></div>
            <div>
              <div class="feature-title">内容排期与发布</div>
              <div class="feature-sub">日历视图 · 发布提醒</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="login-right">
      <div class="login-card">
        <h2>欢迎回来</h2>
        <p class="subtitle">登录以访问管理后台</p>
        <el-form :model="form" :rules="rules" ref="formRef" @submit.prevent="handleLogin">
          <el-form-item prop="username">
            <el-input v-model="form.username" placeholder="用户名" prefix-icon="User" size="large" />
          </el-form-item>
          <el-form-item prop="password">
            <el-input v-model="form.password" type="password" placeholder="密码" prefix-icon="Lock" show-password size="large" />
          </el-form-item>
          <el-button type="primary" native-type="submit" :loading="loading" size="large" style="width:100%">登 录</el-button>
        </el-form>
        <p v-if="showDevHint" class="hint">本地开发默认账号: admin / admin123</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import { errorMessageFrom } from '../utils/errorMessage'

const auth = useAuthStore()
const router = useRouter()
const loading = ref(false)
const showDevHint = import.meta.env.DEV
const formRef = ref(null)
const form = reactive({ username: '', password: '' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin() {
  if (!formRef.value || loading.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await auth.login(form.username, form.password)
    await router.push('/dashboard')
  } catch (err) {
    // request.js handles API errors. Catch here to prevent Axios errors from
    // bubbling into Vue errorHandler and showing repeated page-crash toasts.
    console.error('[Login failed]', err)
    if (!err?.response && !err?.userMessage) {
      ElMessage.error(errorMessageFrom(err, '登录失败，请检查网络后重试。'))
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page { height: 100vh; display: flex; overflow: hidden; }

.login-left {
  flex: 1;
  background: #0c1929;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
}

.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.5;
}
.orb-1 {
  width: 500px; height: 500px;
  background: radial-gradient(circle, rgba(59,158,255,0.15), transparent 70%);
  top: -15%; left: -10%;
  animation: floatSlow 8s ease-in-out infinite;
}
.orb-2 {
  width: 400px; height: 400px;
  background: radial-gradient(circle, rgba(168,85,247,0.12), transparent 70%);
  bottom: -10%; right: -5%;
  animation: floatSlow 10s ease-in-out infinite reverse;
}
.orb-3 {
  width: 300px; height: 300px;
  background: radial-gradient(circle, rgba(16,185,129,0.10), transparent 70%);
  top: 50%; left: 60%;
  animation: floatSlow 12s ease-in-out infinite;
}

.brand-area { position: relative; z-index: 1; color: #fff; padding: 40px; max-width: 520px; }
.brand-badge {
  display: inline-block;
  padding: 4px 14px;
  border-radius: 999px;
  background: rgba(59,158,255,0.12);
  border: 1px solid rgba(59,158,255,0.25);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: #3b9eff;
  margin-bottom: 20px;
}
.brand-title { font-size: 44px; font-weight: 800; line-height: 1.15; letter-spacing: -0.03em; margin-bottom: 12px; }
.brand-desc { font-size: 16px; color: rgba(255, 255, 255, 0.5); margin-bottom: 44px; font-weight: 400; }
.brand-features { display: flex; flex-direction: column; gap: 20px; }
.feature-item { display: flex; align-items: center; gap: 14px; }
.feature-icon-wrap {
  width: 40px; height: 40px;
  border-radius: var(--radius-sm, 10px);
  background: rgba(59,158,255,0.08);
  border: 1px solid rgba(59,158,255,0.15);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.feature-emoji { font-size: 16px; color: #3b9eff; }
.feature-title { font-size: 14px; font-weight: 600; color: rgba(255,255,255,0.9); }
.feature-sub { font-size: 12px; color: rgba(255,255,255,0.4); margin-top: 2px; }

.login-right {
  width: 480px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-surface, #fff);
  border-left: 1px solid var(--color-border, #e5e7eb);
}
.login-card { width: 360px; padding: 20px; }
h2 { font-size: 26px; font-weight: 700; color: var(--color-ink, #0f172a); margin-bottom: 6px; letter-spacing: -0.02em; }
.subtitle { color: var(--color-ink-tertiary, #64748b); margin-bottom: 32px; font-size: 14px; }
.hint { text-align: center; color: var(--color-ink-tertiary, #64748b); font-size: 12px; margin-top: 24px; }

:deep(.el-input__wrapper:hover) { border-color: #3b9eff !important; }
:deep(.el-input__wrapper.is-focus) { border-color: #3b9eff !important; box-shadow: 0 0 0 3px rgba(59,158,255,0.15) !important; }

@keyframes floatSlow {
  0%, 100% { transform: translate3d(0, 0, 0) scale(1); }
  50% { transform: translate3d(16px, -18px, 0) scale(1.04); }
}

@media (max-width: 768px) {
  .login-page {
    flex-direction: column;
    overflow-y: auto;
    background: var(--color-surface, #fff);
  }
  .login-left {
    flex: 0 0 auto;
    min-height: 132px;
    padding: 22px 20px 18px;
    align-items: flex-start;
    justify-content: flex-start;
    overflow: hidden;
  }
  .orb { display: none; }
  .brand-area {
    padding: 0;
    max-width: none;
  }
  .brand-badge,
  .brand-features {
    display: none;
  }
  .brand-title {
    font-size: 26px;
    line-height: 1.2;
    margin-bottom: 8px;
  }
  .brand-title br { display: none; }
  .brand-desc {
    font-size: 13px;
    margin-bottom: 0;
    color: rgba(255, 255, 255, 0.68);
  }
  .login-right {
    width: 100%;
    flex: 1;
    border-left: none;
    align-items: flex-start;
    padding-top: 28px;
  }
  .login-card {
    width: min(100%, 392px);
    padding: 20px;
  }
}
</style>
