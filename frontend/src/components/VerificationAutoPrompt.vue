<template>
  <div class="verification-auto-host">
    <BrowserVncDialog
      :visible="vncDialogVisible"
      :task-id="activeTaskId"
      :account-info="activeAccountInfo"
      :session-id="vncSession.session_id"
      :vnc-password="vncSession.vnc_password"
      @close="closeActive"
      @done="finishActive"
      @timeout="finishActive"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import BrowserVncDialog from './BrowserVncDialog.vue'
import { getPendingVerifications, getVncSession } from '../utils/verificationApi'
import { VERIFICATION_TYPES, statusToVerificationType } from '../utils/verificationStatus'

const POLL_INTERVAL = 5000

const pending = ref([])
const activeTask = ref(null)
const vncDialogVisible = ref(false)
const vncSession = ref({ session_id: '', vnc_password: '' })
const dismissedKeys = new Set()

let pollTimer = null
let refreshing = false
let openingVnc = false

const taskIdOf = (item) => item?.task_id ?? item?.taskId ?? item?.id ?? ''
function verificationTypeOf(item) {
  const rawType = item?.verification_type
  if (rawType === 'phone' || rawType === VERIFICATION_TYPES.PHONE_CAPTCHA) {
    return VERIFICATION_TYPES.PHONE_CAPTCHA
  }
  if (rawType === 'human' || rawType === VERIFICATION_TYPES.HUMAN_CAPTCHA) {
    return VERIFICATION_TYPES.HUMAN_CAPTCHA
  }
  return statusToVerificationType(item?.status) || VERIFICATION_TYPES.PHONE_CAPTCHA
}
const itemKey = (item) => `${taskIdOf(item)}-${verificationTypeOf(item)}`

const activeTaskId = computed(() => taskIdOf(activeTask.value))
const activeAccountInfo = computed(() => {
  const task = activeTask.value || {}
  return {
    platform: task.platform,
    nickname: task.nickname,
    screenshot_url: task.screenshot_url || task.screenshotUrl || '',
  }
})
function dialogIsOpen() {
  return vncDialogVisible.value || openingVnc
}

async function openPending(item) {
  if (!item || dialogIsOpen()) return

  openingVnc = true
  try {
    const session = await getVncSession(taskIdOf(item), { silentError: true })
    const sessionId = session?.session_id || session?.sessionId || ''
    if (!sessionId) return

    activeTask.value = item
    vncSession.value = {
      session_id: sessionId,
      vnc_password: session?.vnc_password || session?.vncPassword || '',
    }
    vncDialogVisible.value = true
  } catch {
    // 会话可能仍在启动；下一轮轮询会继续尝试，不弹消息打断用户。
  } finally {
    openingVnc = false
  }
}

async function openNextPending() {
  if (dialogIsOpen()) return
  const next = pending.value.find((item) => !dismissedKeys.has(itemKey(item)))
  if (next) await openPending(next)
}

async function refresh() {
  if (refreshing) return
  refreshing = true
  try {
    const list = await getPendingVerifications({ silentError: true })
    pending.value = Array.isArray(list) ? list : []

    // 用户关闭过的同一条验证不反复弹；任务状态消失后允许未来的新验证再次弹出。
    const liveKeys = new Set(pending.value.map(itemKey))
    // worker 已完成、失败或被终止时，主动关闭仍显示的旧验证窗口。
    if (activeTask.value && !liveKeys.has(itemKey(activeTask.value))) {
      resetActive()
    }
    for (const key of dismissedKeys) {
      if (!liveKeys.has(key)) dismissedKeys.delete(key)
    }
  } catch {
    // 后端短暂不可用时保持静默，轮询会自动恢复。
  } finally {
    refreshing = false
  }
  await openNextPending()
}

function resetActive() {
  vncDialogVisible.value = false
  activeTask.value = null
  vncSession.value = { session_id: '', vnc_password: '' }
}

function closeActive() {
  if (activeTask.value) dismissedKeys.add(itemKey(activeTask.value))
  resetActive()
  window.setTimeout(openNextPending, 0)
}

function finishActive() {
  if (activeTask.value) dismissedKeys.add(itemKey(activeTask.value))
  resetActive()
  window.setTimeout(refresh, 500)
}

onMounted(() => {
  refresh()
  pollTimer = window.setInterval(refresh, POLL_INTERVAL)
})

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<style scoped>
.verification-auto-host { display: contents; }
</style>
