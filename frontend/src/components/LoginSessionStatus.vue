<template>
  <div
    v-if="visible"
    class="login-session-status"
    :class="`is-${visualStatus}`"
    role="status"
    aria-live="polite"
  >
    <span v-if="isActive" class="status-spinner" aria-hidden="true"></span>
    <span v-else class="status-mark" aria-hidden="true">!</span>

    <div class="status-copy">
      <strong>{{ title }}</strong>
      <span>{{ description }}</span>
    </div>

    <div class="status-actions">
      <el-button v-if="isFailed" size="small" type="primary" plain @click="$emit('retry')">重新打开</el-button>
      <el-button v-if="isFailed" size="small" text @click="$emit('dismiss')">关闭提示</el-button>
      <el-button v-else size="small" text :loading="cancelling" @click="$emit('cancel')">取消登录</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  cancelling: { type: Boolean, default: false },
  status: { type: String, default: '' },
  message: { type: String, default: '' },
  platformLabel: { type: String, default: '' },
})

defineEmits(['cancel', 'retry', 'dismiss'])

const isFailed = computed(() => ['failed', 'expired'].includes(props.status))
const isActive = computed(() => !isFailed.value)
const visualStatus = computed(() => (isFailed.value ? 'failed' : 'active'))

const title = computed(() => {
  if (isFailed.value) return `${props.platformLabel || '平台'}登录未完成`
  if (props.loading || props.status === 'starting') return `正在打开${props.platformLabel || '平台'}登录窗口`
  if (props.status === 'scanned') return '已扫码，请在平台窗口完成确认'
  return `${props.platformLabel || '平台'}登录窗口已打开`
})

const description = computed(() => {
  if (props.message) return props.message
  if (isFailed.value) return '请检查平台页面或网络后重新打开登录窗口。'
  if (props.loading || props.status === 'starting') return '窗口启动后，请直接在真实平台网页完成登录和安全验证。'
  return '请在弹出的真实平台窗口中继续操作；登录成功后账号列表会自动刷新。'
})
</script>

<style scoped>
.login-session-status {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 12px;
  padding: 10px 12px;
  border: 1px solid #b9d5ff;
  border-radius: 10px;
  background: #f3f8ff;
  color: #24568f;
}

.login-session-status.is-failed {
  border-color: #f3b7b7;
  background: #fff5f5;
  color: #b42318;
}

.status-spinner {
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
  border: 2px solid #aac9f6;
  border-top-color: #337ecc;
  border-radius: 50%;
  animation: login-status-spin .8s linear infinite;
}

.status-mark {
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  border-radius: 50%;
  background: #d92d20;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}

.status-copy {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.status-copy strong {
  font-size: 13px;
  font-weight: 600;
}

.status-copy span {
  overflow: hidden;
  color: currentColor;
  font-size: 12px;
  line-height: 1.45;
  opacity: .82;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 4px;
}

@keyframes login-status-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 680px) {
  .login-session-status {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .status-copy span {
    white-space: normal;
  }

  .status-actions {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>
