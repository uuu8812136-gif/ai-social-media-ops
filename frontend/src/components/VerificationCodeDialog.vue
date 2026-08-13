<template>
  <el-dialog
    v-model="dialogVisible"
    :title="dialogTitle"
    width="440px"
    append-to-body
    align-center
    :close-on-click-modal="false"
    class="verify-code-dialog"
    @close="onClose"
  >
    <div class="verify-code-body">
      <!-- 6 位验证码输入框 -->
      <div class="code-inputs" role="group" aria-label="6 位验证码输入">
        <input
          v-for="i in 6"
          :key="i"
          :ref="(el) => setRef(el, i - 1)"
          :value="digits[i - 1]"
          type="text"
          inputmode="numeric"
          autocomplete="one-time-code"
          maxlength="1"
          class="code-cell"
          :aria-label="`第 ${i} 位`"
          :disabled="submitting"
          @input="onInput($event, i - 1)"
          @keydown="onKeydown($event, i - 1)"
          @paste="onPaste($event, i - 1)"
        />
      </div>

      <!-- 提示文案 -->
      <p class="code-hint" :class="{ 'is-warning': !smsRequested }">
        <template v-if="smsRequested">验证码请求已发送至</template>
        <template v-else>平台要求短信验证，请检查</template>
        <span class="hint-target">{{ hintTarget }}</span>
      </p>

      <!-- 倒计时 / 超时 -->
      <p class="code-countdown" :class="{ 'is-timeout': isTimeout }">
        <template v-if="isTimeout">验证码已超时，请重新触发发送后再输入</template>
        <template v-else>剩余有效时间 {{ remainText }}</template>
      </p>

      <!-- 截图缩略图（可选，点击放大） -->
      <div v-if="screenshotUrl || screenshotLoading || screenshotSrc || screenshotLoadFailed" class="code-screenshot">
        <span class="screenshot-label">当前验证页面截图（点击放大）</span>
        <div v-if="screenshotLoading" class="screenshot-img screenshot-placeholder">截图加载中…</div>
        <el-image
          v-else-if="screenshotSrc"
          :src="screenshotSrc"
          :preview-src-list="[screenshotSrc]"
          :preview-teleported="true"
          fit="cover"
          class="screenshot-img"
          hide-on-click-modal
        >
          <template #placeholder>
            <div class="screenshot-placeholder">截图加载中…</div>
          </template>
          <template #error>
            <div class="screenshot-placeholder">截图加载失败</div>
          </template>
        </el-image>
        <div v-else class="screenshot-img screenshot-placeholder">截图加载失败</div>
      </div>

      <!-- 内联错误（突出失败原因） -->
      <div v-if="errorMsg" class="code-error">
        <el-icon><CircleCloseFilled /></el-icon>
        <span>{{ errorMsg }}</span>
      </div>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button :disabled="submitting" @click="dialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="submitting"
          :disabled="!isComplete || isTimeout"
          @click="submit"
        >
          提交验证码
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { CircleCloseFilled } from '@element-plus/icons-vue'
import { getVerificationScreenshot, submitPhoneCaptcha } from '../utils/verificationApi'

const props = defineProps({
  visible: { type: Boolean, default: false },
  taskId: { type: [Number, String], default: '' },
  accountInfo: { type: Object, default: () => ({}) },
  captchaHint: { type: String, default: '' },
  screenshotUrl: { type: String, default: '' },
  smsRequested: { type: Boolean, default: false },
})

const emit = defineEmits(['done', 'close'])

const PLATFORM_MAP = { xiaohongshu: '小红书', channels: '视频号', douyin: '抖音', kuaishou: '快手', bilibili: 'B站' }
const platformLabel = (p) => PLATFORM_MAP[p] || p || ''

const dialogTitle = computed(() => {
  const acc = props.accountInfo || {}
  const parts = ['手机验证码']
  const label = platformLabel(acc.platform)
  if (label) parts.push(label)
  if (acc.nickname) parts.push(acc.nickname)
  return parts.join(' - ')
})

const hintTarget = computed(() => {
  if (props.captchaHint) return props.captchaHint
  const acc = props.accountInfo || {}
  if (acc.nickname) return acc.nickname
  return '对应手机'
})

const screenshotSrc = ref('')
const screenshotLoading = ref(false)
const screenshotLoadFailed = ref(false)
let screenshotObjectUrl = ''

function releaseScreenshot() {
  if (screenshotObjectUrl) URL.revokeObjectURL(screenshotObjectUrl)
  screenshotObjectUrl = ''
  screenshotSrc.value = ''
}

async function loadScreenshot() {
  releaseScreenshot()
  screenshotLoadFailed.value = false
  const hasScreenshot = props.screenshotUrl || props.accountInfo?.screenshot_url
  if (!hasScreenshot || !props.taskId) return
  screenshotLoading.value = true
  try {
    const blob = await getVerificationScreenshot(props.taskId, { silentError: true })
    if (!(blob instanceof Blob) || blob.size === 0) throw new Error('empty screenshot')
    screenshotObjectUrl = URL.createObjectURL(blob)
    screenshotSrc.value = screenshotObjectUrl
  } catch {
    screenshotLoadFailed.value = true
  } finally {
    screenshotLoading.value = false
  }
}

// ---- 6 位输入框逻辑 ----
const digits = ref(Array(6).fill(''))
const inputs = ref([])

function setRef(el, i) {
  if (el) inputs.value[i] = el
}

function resetDigits() {
  digits.value = Array(6).fill('')
  errorMsg.value = ''
}

function focusInput(i) {
  const el = inputs.value[i]
  if (el) {
    el.focus()
    if (typeof el.select === 'function') el.select()
  }
}

function onInput(e, i) {
  const raw = e.target.value
  const digit = raw.replace(/\D/g, '').slice(-1)
  digits.value[i] = digit
  e.target.value = digit
  errorMsg.value = ''
  if (digit && i < 5) focusInput(i + 1)
}

function onKeydown(e, i) {
  if (e.key === 'Backspace') {
    if (!digits.value[i] && i > 0) {
      e.preventDefault()
      digits.value[i - 1] = ''
      focusInput(i - 1)
    }
  } else if (e.key === 'ArrowLeft' && i > 0) {
    e.preventDefault()
    focusInput(i - 1)
  } else if (e.key === 'ArrowRight' && i < 5) {
    e.preventDefault()
    focusInput(i + 1)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    submit()
  }
}

function onPaste(e, i) {
  e.preventDefault()
  const text = (e.clipboardData || window.clipboardData)?.getData('text') || ''
  const chars = text.replace(/\D/g, '').slice(0, 6).split('')
  if (!chars.length) return
  for (let k = 0; k < 6; k++) {
    digits.value[k] = chars[k] || ''
    const el = inputs.value[k]
    if (el) el.value = digits.value[k]
  }
  errorMsg.value = ''
  const focusIdx = Math.min(chars.length, 5)
  focusInput(focusIdx)
}

const code = computed(() => digits.value.join(''))
const isComplete = computed(() => code.value.length === 6)

// ---- 倒计时 300 秒 ----
const COUNTDOWN = 300
const remain = ref(COUNTDOWN)
const isTimeout = ref(false)
let timer = null

const remainText = computed(() => {
  const m = Math.floor(remain.value / 60)
  const s = remain.value % 60
  return `${m}:${String(s).padStart(2, '0')}`
})

function startCountdown() {
  remain.value = COUNTDOWN
  isTimeout.value = false
  stopCountdown()
  timer = window.setInterval(() => {
    remain.value -= 1
    if (remain.value <= 0) {
      remain.value = 0
      isTimeout.value = true
      stopCountdown()
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

function onClose() {
  // el-dialog 关闭（X / ESC）兜底，确保父组件隐藏
  emit('close')
}

watch(
  () => props.visible,
  (v) => {
    if (v) {
      resetDigits()
      startCountdown()
      loadScreenshot()
      nextTick(() => focusInput(0))
    } else {
      stopCountdown()
      releaseScreenshot()
    }
  }
)

onBeforeUnmount(() => {
  stopCountdown()
  releaseScreenshot()
})

// ---- 提交 ----
const submitting = ref(false)
const errorMsg = ref('')

async function submit() {
  if (submitting.value) return
  if (!isComplete.value) {
    errorMsg.value = '请输入完整的 6 位验证码'
    return
  }
  if (isTimeout.value) {
    errorMsg.value = '验证码已超时，请重新触发发送后再输入'
    return
  }
  submitting.value = true
  errorMsg.value = ''
  try {
    await submitPhoneCaptcha(props.taskId, code.value)
    emit('done')
  } catch (err) {
    const msg = String(err?.userMessage || err?.message || '')
    if (/过期|expired|超时|timeout/i.test(msg)) {
      errorMsg.value = '验证码已过期，请重新触发发送后再输入'
    } else if (/错误|invalid|incorrect|不正确|不匹配|mismatch/i.test(msg)) {
      errorMsg.value = '验证码不正确，请检查后重新输入'
    } else {
      errorMsg.value = msg || '验证码提交失败，请稍后重试'
    }
    // 验证错误只在当前弹窗内展示，不再额外弹消息通知。
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.verify-code-body { padding: 4px 2px 0; }

.code-inputs {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}
.code-cell {
  width: 48px;
  height: 56px;
  text-align: center;
  font-size: 24px;
  font-weight: 600;
  color: var(--color-ink, #1a2332);
  background: var(--wm-surface, #fff);
  border: 1px solid var(--color-border, #e2e8f0);
  border-radius: 8px;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  caret-color: var(--wm-primary, #0f6bc5);
}
.code-cell:focus {
  border-color: var(--wm-primary, #0f6bc5);
  box-shadow: 0 0 0 3px rgba(15, 107, 197, 0.12);
}
.code-cell:disabled { background: var(--wm-surface-subtle, #f0f3f7); cursor: not-allowed; }

.code-hint {
  margin: 16px 0 6px;
  font-size: 13px;
  color: var(--color-ink-secondary, #4a5568);
}
.hint-target { margin-left: 4px; font-weight: 600; color: var(--color-ink, #1a2332); }
.code-hint.is-warning { color: var(--color-warning, #b7791f); }

.code-countdown {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--color-ink-tertiary, #718096);
}
.code-countdown.is-timeout { color: var(--color-danger, #dc2626); font-weight: 600; }

.code-screenshot { margin-top: 4px; }
.screenshot-label { display: block; font-size: 12px; color: var(--color-ink-tertiary, #718096); margin-bottom: 6px; }
.screenshot-img {
  width: 100%;
  max-width: 220px;
  height: 120px;
  border-radius: 8px;
  border: 1px solid var(--color-border, #e2e8f0);
  cursor: zoom-in;
  overflow: hidden;
}
.screenshot-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: var(--color-ink-tertiary, #718096);
  background: var(--wm-surface-subtle, #f0f3f7);
}

.code-error {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  padding: 8px 10px;
  font-size: 13px;
  color: var(--color-danger, #dc2626);
  background: rgba(220, 38, 38, 0.08);
  border: 1px solid rgba(220, 38, 38, 0.2);
  border-radius: 8px;
}
.code-error .el-icon { flex-shrink: 0; font-size: 15px; }

.dialog-footer { display: flex; justify-content: flex-end; gap: 10px; }

@media (prefers-reduced-motion: reduce) {
  .code-cell { transition: none !important; }
}
</style>
