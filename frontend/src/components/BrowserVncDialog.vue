<template>
  <el-dialog
    v-model="dialogVisible"
    :title="dialogTitle"
    width="90%"
    top="5vh"
    append-to-body
    align-center
    :close-on-click-modal="false"
    class="vnc-dialog"
  >
    <div v-if="purpose === 'login'" class="vnc-login-tip">
      请直接在下方真实网页完成扫码、密码、短信或安全验证；登录成功后窗口会自动关闭并保存会话。
    </div>

    <!-- 顶部工具栏 -->
    <div class="vnc-toolbar">
      <div class="vnc-meta">
        <span class="meta-item">
          <span class="meta-label">会话 ID</span>
          <span class="meta-value">{{ sessionId || '—' }}</span>
        </span>
        <span class="meta-item">
          <span class="meta-label">剩余时间</span>
          <span class="meta-value" :class="{ 'is-timeout': remain <= 0 }">{{ remainText }}</span>
        </span>
      </div>
      <div class="vnc-actions">
        <el-button :icon="Refresh" :disabled="!sessionId" @click="refreshIframe">刷新</el-button>
        <el-button
          v-if="purpose !== 'login'"
          type="primary"
          :loading="resuming"
          :disabled="remain <= 0"
          @click="resume"
        >
          {{ actionLabel }}
        </el-button>
      </div>
    </div>

    <!-- 超时提示条 -->
    <div v-if="remain <= 0" class="vnc-timeout-bar">
      会话已超时，请关闭后重新打开远程浏览器再继续。
    </div>

    <!-- 主体 iframe + 加载遮罩 -->
    <div class="vnc-stage">
      <div v-if="loading || (sessionId && iframeLoading)" class="vnc-loading">
        <el-icon class="loading-icon"><Loading /></el-icon>
        <span>{{ loading ? '正在启动登录浏览器…' : '正在连接远程浏览器…' }}</span>
      </div>
      <div v-if="errorMessage" class="vnc-error">
        <strong>登录浏览器启动失败</strong>
        <span>{{ errorMessage }}</span>
        <el-button type="primary" @click="emit('retry')">重试</el-button>
      </div>
      <iframe
        v-if="sessionId && !errorMessage"
        :key="iframeKey"
        :src="iframeSrc"
        class="vnc-iframe"
        frameborder="0"
        allow="clipboard-read; clipboard-write"
        @load="onIframeLoad"
      />
      <div v-else-if="!loading && !errorMessage" class="vnc-empty">
        <span>没有获取到有效的浏览器会话，请关闭后重试。</span>
      </div>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="dialogVisible = false">关闭</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading, Refresh } from '@element-plus/icons-vue'
import { resumePublish } from '../utils/verificationApi'

const props = defineProps({
  visible: { type: Boolean, default: false },
  taskId: { type: [Number, String], default: '' },
  accountInfo: { type: Object, default: () => ({}) },
  sessionId: { type: String, default: '' },
  vncPassword: { type: String, default: '' },
  purpose: { type: String, default: 'publish' },
  connectionScheme: { type: String, default: 'worker_shared' },
  loading: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
})

const emit = defineEmits(['done', 'timeout', 'close', 'retry'])

const PLATFORM_MAP = { xiaohongshu: '小红书', channels: '视频号', douyin: '抖音', kuaishou: '快手', bilibili: 'B站' }
const platformLabel = (p) => PLATFORM_MAP[p] || p || ''

const dialogTitle = computed(() => {
  const acc = props.accountInfo || {}
  const parts = [props.purpose === 'login' ? '平台登录' : '远程浏览器']
  const label = platformLabel(acc.platform)
  if (label) parts.push(label)
  if (acc.nickname) parts.push(acc.nickname)
  if (props.purpose !== 'login') parts.push('人工验证')
  return parts.join(' - ')
})

const iframeSrc = computed(() => {
  const id = encodeURIComponent(props.sessionId || '')
  const prefix = props.connectionScheme === 'managed_session' ? 'vnc' : 'worker-vnc'
  // noVNC resolves a path without a leading slash relative to vnc.html. That
  // duplicates the route prefix, e.g. /worker-vnc/:id/worker-vnc/:id/....
  // Keep the WebSocket endpoint origin-absolute for both VNC backends.
  const query = new URLSearchParams({
    autoconnect: '1',
    reconnect: '1',
    reconnect_delay: '2000',
    resize: 'scale',
    path: `/${prefix}/${id}/websockify`,
    password: props.vncPassword || '',
  })
  return `/${prefix}/${id}/vnc.html?${query.toString()}`
})

const actionLabel = computed(() => '我已完成操作，继续发布')

// ---- iframe 加载 / 刷新 ----
const iframeKey = ref(0)
const iframeLoading = ref(true)

function refreshIframe() {
  if (!props.sessionId) return
  iframeLoading.value = true
  iframeKey.value += 1
}

function onIframeLoad() {
  iframeLoading.value = false
}

// ---- 倒计时 5 分钟 ----
const COUNTDOWN = 300
const remain = ref(COUNTDOWN)
let timer = null
let timeoutEmitted = false

const remainText = computed(() => {
  const m = Math.floor(remain.value / 60)
  const s = remain.value % 60
  return `${m}:${String(s).padStart(2, '0')}`
})

function startCountdown() {
  remain.value = COUNTDOWN
  timeoutEmitted = false
  stopCountdown()
  timer = window.setInterval(() => {
    remain.value -= 1
    if (remain.value <= 0) {
      remain.value = 0
      stopCountdown()
      if (!timeoutEmitted) {
        timeoutEmitted = true
        emit('timeout')
      }
    }
  }, 1000)
}

function stopCountdown() {
  if (timer) {
    window.clearInterval(timer)
    timer = null
  }
}

// ---- 可见性 ----
const dialogVisible = computed({
  get: () => props.visible,
  set: (val) => {
    if (!val) emit('close')
  },
})

watch(
  () => [props.visible, props.sessionId],
  ([visible, sessionId]) => {
    if (visible && sessionId) {
      iframeLoading.value = true
      startCountdown()
    } else {
      stopCountdown()
    }
  }
)

// ---- 继续发布 ----
const resuming = ref(false)

async function resume() {
  if (resuming.value) return
  if (remain.value <= 0) {
    ElMessage.error('会话已超时，无法继续，请重新打开远程浏览器')
    return
  }
  resuming.value = true
  try {
    await resumePublish(props.taskId)
    ElMessage.success('已恢复发布，任务继续执行中')
    emit('done')
  } catch (err) {
    // request.js 已弹出错误提示
  } finally {
    resuming.value = false
  }
}
</script>

<style scoped>
.vnc-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 4px 2px 12px;
  border-bottom: 1px solid var(--color-border, #e2e8f0);
}
.vnc-login-tip {
  margin-bottom: 10px;
  padding: 10px 12px;
  color: #1d4ed8;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.6;
}
.vnc-meta { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }
.meta-item { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
.meta-label { color: var(--color-ink-tertiary, #718096); }
.meta-value { font-weight: 600; color: var(--color-ink, #1a2332); font-variant-numeric: tabular-nums; }
.meta-value.is-timeout { color: var(--color-danger, #dc2626); }

.vnc-actions { display: flex; align-items: center; gap: 10px; }

.vnc-timeout-bar {
  margin-top: 10px;
  padding: 8px 12px;
  font-size: 13px;
  color: var(--color-danger, #dc2626);
  background: rgba(220, 38, 38, 0.08);
  border: 1px solid rgba(220, 38, 38, 0.2);
  border-radius: 8px;
}

.vnc-stage {
  position: relative;
  margin-top: 12px;
  width: 100%;
  height: 70vh;
  background: #1a1a1a;
  border: 1px solid var(--color-border, #e2e8f0);
  border-radius: 8px;
  overflow: hidden;
}
.vnc-iframe {
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
}

.vnc-loading {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #e2e8f0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 2;
  font-size: 14px;
}
.loading-icon { font-size: 26px; }
.loading-icon { animation: vnc-spin 1s linear infinite; }

.vnc-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #cbd5e0;
  font-size: 14px;
}

.vnc-error {
  position: absolute;
  inset: 0;
  z-index: 3;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 32px;
  color: #fee2e2;
  text-align: center;
  background: #262626;
}
.vnc-error strong { font-size: 17px; }
.vnc-error span { max-width: 720px; line-height: 1.6; word-break: break-word; }

.dialog-footer { display: flex; justify-content: flex-end; }

@keyframes vnc-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

@media (prefers-reduced-motion: reduce) {
  .loading-icon { animation: none !important; }
}
</style>
