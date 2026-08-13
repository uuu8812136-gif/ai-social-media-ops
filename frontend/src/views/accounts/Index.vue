<template>
  <div class="accounts-page rb-enter">
    <div class="page-header">
      <div>
        <h2>社媒账号中心</h2>
        <span class="page-sub">网页登录 · 会话管理 · 发布内容 · 数据指标</span>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" @click="refreshAll">刷新</el-button>
        <el-button type="primary" @click="goSocialTabAndLogin">添加社媒账号</el-button>
      </div>
    </div>

    <div class="page-guide">登录时会直接打开真实平台窗口；请在窗口内完成登录和安全验证，成功后窗口自动隐藏并保存会话。</div>

    <LoginSessionStatus
      :visible="loginStatusVisible"
      :loading="qrLoading"
      :cancelling="qrCancelling"
      :status="qrPollData.status"
      :message="qrError || qrPollData.message"
      :platform-label="socialPlatformLabel(qrPlatform)"
      @cancel="cancelQrLogin"
      @retry="startLogin"
      @dismiss="dismissLoginStatus"
    />

    <!-- 社媒账号 -->
    <div class="social-section panel-card">
      <div class="social-toolbar">
        <div class="social-actions">
          <el-select v-model="filterPlatform" placeholder="平台筛选" clearable style="width:140px" @change="loadSocialAccounts">
            <el-option v-for="p in socialPlatforms" :key="p.platform" :label="p.name" :value="p.platform" />
          </el-select>
          <el-radio-group v-model="viewMode" size="small">
            <el-radio-button value="list">列表</el-radio-button>
            <el-radio-button value="card">卡片</el-radio-button>
          </el-radio-group>
        </div>
        <el-select v-model="qrPlatform" placeholder="选择登录平台" style="width:200px">
          <el-option
            v-for="p in socialPlatforms"
            :key="p.platform"
            :label="p.name"
            :value="p.platform"
            :disabled="!(p.publish && p.publish.available)"
          />
        </el-select>
        <el-button type="primary" :disabled="!qrPlatform || qrLoading" @click="startLogin">打开登录网页</el-button>
      </div>

      <!-- 列表模式 -->
      <el-table v-if="viewMode === 'list'" :data="socialAccounts" v-loading="socialLoading" style="margin-top:12px">
        <el-table-column label="平台" width="90">
          <template #default="{ row }">{{ socialPlatformLabel(row.platform) }}</template>
        </el-table-column>
        <el-table-column label="昵称" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.nickname || '—' }}</template>
        </el-table-column>
        <el-table-column prop="platform_uid" label="平台UID" width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.platform_uid || '—' }}</template>
        </el-table-column>
        <el-table-column label="Cookie 状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="cookieTagType(row.cookie_status)">{{ cookieStatusLabel(row.cookie_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_validated_at" label="最近校验" width="180" show-overflow-tooltip>
          <template #default="{ row }"><span style="white-space:nowrap">{{ formatTime(row.last_validated_at) }}</span></template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.remark || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link size="small" type="primary" @click="validateCookie(row, false)">校验状态</el-button>
            <el-button link size="small" @click="viewPosts(row)">查看内容</el-button>
            <el-dropdown trigger="click" @command="(cmd) => handleAccountCmd(cmd, row)">
              <el-button link size="small">更多<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="async_validate">异步校验</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无社媒账号，请先登录平台账号" :image-size="60" />
        </template>
      </el-table>

      <!-- 卡片模式 -->
      <div v-else class="card-grid">
        <div v-for="acc in socialAccounts" :key="acc.id" class="account-card glass-card">
          <div class="card-header">
            <el-avatar :size="44" :src="acc.avatar_url">{{ (acc.nickname || acc.platform || '?')[0] }}</el-avatar>
            <div class="card-info">
              <div class="card-name">{{ acc.nickname || '未命名' }}</div>
              <div class="card-platform">
                <el-tag size="small" :type="cookieTagType(acc.cookie_status)">{{ cookieStatusLabel(acc.cookie_status) }}</el-tag>
                <span class="card-platform-name">{{ socialPlatformLabel(acc.platform) }}</span>
              </div>
            </div>
          </div>
          <div class="card-meta">
            <div class="meta-row"><span class="meta-label">UID</span><span class="meta-value">{{ acc.platform_uid || '—' }}</span></div>
            <div class="meta-row"><span class="meta-label">校验</span><span class="meta-value">{{ formatTime(acc.last_validated_at) }}</span></div>
            <div class="meta-row"><span class="meta-label">备注</span><span class="meta-value">{{ acc.remark || '—' }}</span></div>
          </div>
          <div class="card-actions">
            <el-button size="small" type="primary" @click="validateCookie(acc, false)">校验</el-button>
            <el-button size="small" @click="viewPosts(acc)">查看内容</el-button>
            <el-dropdown trigger="click" @command="(cmd) => handleAccountCmd(cmd, acc)">
              <el-button size="small">更多<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="async_validate">异步校验</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
        <el-empty v-if="!socialLoading && socialAccounts.length === 0" description="暂无社媒账号" :image-size="60" />
      </div>
    </div>

    <!-- 查看内容抽屉 -->
    <el-drawer v-model="postsDrawerVisible" :title="`${currentAccountName} 的发布内容`" size="60%" direction="rtl">
      <div v-loading="postsLoading">
        <el-table :data="accountPosts" style="margin-bottom:12px">
          <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
          <el-table-column label="状态" width="100">
            <template #default="{ row }"><el-tag size="small" :type="taskTagType(row.status)">{{ taskStatusLabel(row.status) }}</el-tag></template>
          </el-table-column>
          <el-table-column label="发布时间" width="170" show-overflow-tooltip>
            <template #default="{ row }"><span style="white-space:nowrap">{{ formatTime(row.finished_at || row.created_at) }}</span></template>
          </el-table-column>
          <el-table-column label="素材" width="60"><template #default="{ row }">{{ row.media_count }} 个</template></el-table-column>
          <el-table-column label="指标" width="180">
            <template #default="{ row }">
              <div v-if="row.metrics" class="mini-metrics">
                <span v-if="row.metrics.views != null" class="mm">播放 {{ row.metrics.views }}</span>
                <span v-if="row.metrics.likes != null" class="mm">赞 {{ row.metrics.likes }}</span>
                <span v-if="row.metrics.comments != null" class="mm">评 {{ row.metrics.comments }}</span>
              </div>
              <el-tag v-else size="small" type="info">{{ row.metric_sync_status || '未采集' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button link size="small" type="primary" @click="viewPostDetail(row)">详情</el-button>
              <el-button link size="small" @click="syncMetrics(row)">同步数据</el-button>
            </template>
          </el-table-column>
          <template #empty><el-empty description="该账号暂无发布内容" :image-size="50" /></template>
        </el-table>
      </div>
    </el-drawer>

    <!-- 内容详情弹窗 -->
    <el-dialog v-model="postDetailVisible" title="发布内容详情" width="680px" class="post-detail-dialog">
      <div v-if="postDetail" v-loading="postDetailLoading">
        <el-descriptions :column="2" border size="small" style="margin-bottom:12px">
          <el-descriptions-item label="标题">{{ postDetail.title || '—' }}</el-descriptions-item>
          <el-descriptions-item label="平台">{{ socialPlatformLabel(postDetail.platform) }}</el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag size="small" :type="taskTagType(postDetail.status)">{{ taskStatusLabel(postDetail.status) }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="发布模式">{{ postDetail.publish_mode === 'schedule' ? '定时' : '直接' }}</el-descriptions-item>
          <el-descriptions-item label="平台ID">{{ postDetail.external_post_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="发布链接">
            <el-link v-if="postDetail.publish_url" :href="postDetail.publish_url" target="_blank" rel="noopener noreferrer" type="primary">查看原文</el-link>
            <span v-else>—</span>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatTime(postDetail.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="完成时间">{{ formatTime(postDetail.finished_at) }}</el-descriptions-item>
          <el-descriptions-item v-if="postDetail.error_message" label="错误信息" :span="2">
            <span style="color:var(--color-danger)">{{ friendlyError(postDetail.error_message) }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="postDetail.description" style="margin-bottom:12px">
          <div class="detail-section-title">正文摘要</div>
          <div class="detail-text">{{ postDetail.description }}</div>
        </div>

        <div v-if="postDetail.tags && postDetail.tags.length" style="margin-bottom:12px">
          <div class="detail-section-title">标签</div>
          <el-tag v-for="t in postDetail.tags" :key="t" size="small" effect="plain" style="margin-right:4px">{{ t }}</el-tag>
        </div>

        <div v-if="postDetail.media_paths && postDetail.media_paths.length" style="margin-bottom:12px">
          <div class="detail-section-title">素材列表（{{ postDetail.media_paths.length }} 个）</div>
          <div v-for="(m, i) in postDetail.media_paths" :key="i" class="media-item">{{ m }}</div>
        </div>

        <!-- 指标 -->
        <div v-if="postDetail.metric" style="margin-bottom:12px">
          <div class="detail-section-title">数据指标（{{ postDetail.metric.sync_status }}）</div>
          <div class="metric-cards">
            <div v-if="postDetail.metric.metrics?.views != null" class="metric-card"><div class="mc-value">{{ postDetail.metric.metrics.views }}</div><div class="mc-label">播放/阅读</div></div>
            <div v-if="postDetail.metric.metrics?.likes != null" class="metric-card"><div class="mc-value">{{ postDetail.metric.metrics.likes }}</div><div class="mc-label">点赞</div></div>
            <div v-if="postDetail.metric.metrics?.comments != null" class="metric-card"><div class="mc-value">{{ postDetail.metric.metrics.comments }}</div><div class="mc-label">评论</div></div>
            <div v-if="postDetail.metric.metrics?.favorites != null" class="metric-card"><div class="mc-value">{{ postDetail.metric.metrics.favorites }}</div><div class="mc-label">收藏</div></div>
            <div v-if="postDetail.metric.metrics?.shares != null" class="metric-card"><div class="mc-value">{{ postDetail.metric.metrics.shares }}</div><div class="mc-label">分享</div></div>
          </div>
          <div v-if="postDetail.metric.error_message" style="color:var(--color-danger);font-size:13px;margin-top:4px">{{ friendlyError(postDetail.metric.error_message) }}</div>
        </div>

        <!-- 发布日志 -->
        <div v-if="postDetail.logs && postDetail.logs.length" style="margin-bottom:12px">
          <div class="detail-section-title">发布日志</div>
          <div class="log-list">
            <div v-for="(log, i) in postDetail.logs" :key="i" class="log-item" :class="`log-${log.level}`">
              <span class="log-time">{{ formatTime(log.created_at) }}</span>
              <span class="log-level">[{{ log.level }}]</span>
              <span class="log-msg">{{ log.message }}</span>
            </div>
          </div>
        </div>

        <!-- 原始采集数据（仅管理员） -->
        <el-collapse v-if="postDetail.raw_data">
          <el-collapse-item title="原始采集数据（仅管理员可见）">
            <pre class="raw-json">{{ JSON.stringify(postDetail.raw_data, null, 2) }}</pre>
          </el-collapse-item>
        </el-collapse>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Refresh } from '@element-plus/icons-vue'
import request from '../../utils/request'
import { errorMessageFrom, humanizeError } from '../../utils/errorMessage'
import LoginSessionStatus from '../../components/LoginSessionStatus.vue'

const socialLoading = ref(false)
const socialAccounts = ref([])
const socialPlatforms = ref([])
const filterPlatform = ref('')
const viewMode = ref('list')
const qrPlatform = ref('')
const qrLoading = ref(false)
const qrCancelling = ref(false)
const qrError = ref('')
const qrSessionId = ref('')
const qrPollData = ref({ status: '', message: '' })
const loginStatusVisible = computed(() => (
  qrLoading.value
  || !!qrSessionId.value
  || ['starting', 'waiting', 'scanned', 'failed', 'expired'].includes(qrPollData.value.status)
))
let qrPollTimer = null
let qrLoginAttempt = 0

// 查看内容
const postsDrawerVisible = ref(false)
const postsLoading = ref(false)
const accountPosts = ref([])
const currentAccountId = ref('')
const currentAccountName = ref('')

// 内容详情
const postDetailVisible = ref(false)
const postDetailLoading = ref(false)
const postDetail = ref(null)

const PLATFORM_MAP = { douyin: '抖音', xiaohongshu: '小红书', weixin_video: '视频号', channels: '微信视频号', kuaishou: '快手', bilibili: 'B站' }
const socialPlatformLabel = (p) => PLATFORM_MAP[p] || p

const COOKIE_STATUS_MAP = { valid: { label: '有效', type: 'success' }, invalid: { label: '失效', type: 'danger' }, expired: { label: '过期', type: 'warning' }, unknown: { label: '未知', type: 'info' } }
const cookieStatusLabel = (s) => COOKIE_STATUS_MAP[s]?.label || s || '未知'
const cookieTagType = (s) => COOKIE_STATUS_MAP[s]?.type || 'info'

const TASK_STATUS_MAP = {
  pending: { label: '待发布', type: 'warning' },
  queued: { label: '排队中', type: 'info' },
  running: { label: '发布中', type: 'primary' },
  published: { label: '已发布', type: 'success' },
  reviewing: { label: '审核中', type: 'primary' },
  failed: { label: '失败', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' },
  media_required: { label: '缺素材', type: 'warning' },
  publish_error: { label: '发布错误', type: 'danger' },
  cookie_missing: { label: 'Cookie 缺失', type: 'danger' },
}
const taskStatusLabel = (s) => TASK_STATUS_MAP[s]?.label || s || '未知'
const taskTagType = (s) => TASK_STATUS_MAP[s]?.type || 'info'

const friendlyError = (message) => message ? humanizeError(message, { context: 'publish' }) : ''

const formatTime = (t) => {
  if (!t) return '—'
  const d = new Date(t)
  if (isNaN(d.getTime())) return '—'
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function loadSocialPlatforms() {
  try {
    const res = await request.get('/social/accounts/platforms')
    socialPlatforms.value = res.data || []
  } catch (e) { /* ignore */ }
}

async function loadSocialAccounts() {
  socialLoading.value = true
  try {
    const params = { page_size: 100 }
    if (filterPlatform.value) params.platform = filterPlatform.value
    const res = await request.get('/social/accounts/', { params })
    socialAccounts.value = res.data || []
  } catch (e) { /* ignore */ }
  finally { socialLoading.value = false }
}

function refreshAll() {
  loadSocialAccounts()
  loadSocialPlatforms()
}

async function goSocialTabAndLogin() {
  qrPlatform.value = socialPlatforms.value.find(p => p.publish?.available)?.platform || ''
  if (!qrPlatform.value) return ElMessage.warning('暂无可用的登录平台')
  await startLogin()
}

// ===== 真实网页登录 =====
async function startLogin() {
  if (!qrPlatform.value) return ElMessage.warning('请选择平台')
  const attempt = ++qrLoginAttempt
  stopPolling()
  const previousSessionId = qrSessionId.value
  if (previousSessionId) {
    try {
      await request.post('/social/accounts/login/cancel', null, {
        params: { session_id: previousSessionId },
        silentError: true,
      })
    } catch (e) { /* ignore */ }
  }
  qrSessionId.value = ''
  qrError.value = ''
  qrPollData.value = { status: 'starting', message: '' }
  qrLoading.value = true
  try {
    const res = await request.post(
      '/social/accounts/login/start',
      { platform: qrPlatform.value },
      { timeout: 120000, silentError: true },
    )
    const sessionId = res.data?.session_id
    if (attempt !== qrLoginAttempt) {
      if (sessionId) {
        try {
          await request.post('/social/accounts/login/cancel', null, {
            params: { session_id: sessionId },
            silentError: true,
          })
        } catch (e) { /* ignore */ }
      }
      return
    }
    if (!sessionId) throw new Error('登录窗口启动失败：服务端未返回登录会话')
    qrSessionId.value = sessionId
    qrPollData.value = {
      status: res.data?.status || 'waiting',
      message: res.data?.message || '请在弹出的真实平台窗口中完成登录',
    }
    startPolling(attempt)
  } catch (e) {
    if (attempt !== qrLoginAttempt) return
    const reason = errorMessageFrom(e, '登录浏览器启动失败，请重试。', 'login')
    qrError.value = reason
    qrPollData.value = { status: 'failed', message: reason }
    qrSessionId.value = ''
    stopPolling()
  } finally {
    if (attempt === qrLoginAttempt) qrLoading.value = false
  }
}

function startPolling(attempt) {
  stopPolling()
  qrPollTimer = setInterval(async () => {
    const sessionId = qrSessionId.value
    if (!sessionId || attempt !== qrLoginAttempt) return
    try {
      const res = await request.get('/social/accounts/login/status', { params: { session_id: sessionId }, silentError: true })
      if (attempt !== qrLoginAttempt || sessionId !== qrSessionId.value) return
      const payload = res.data || {}
      qrPollData.value = { status: payload.status, message: payload.message || '' }
      if (payload.status === 'confirmed') {
        stopPolling()
        qrSessionId.value = ''
        qrError.value = ''
        qrPollData.value = { status: '', message: '' }
        await loadSocialAccounts()
      } else if (payload.status === 'expired' || payload.status === 'failed') {
        qrError.value = humanizeError(payload.message, {
          context: 'login',
          fallback: '登录失败或会话已超时，请重新打开登录网页。',
        })
        qrSessionId.value = ''
        stopPolling()
      }
    } catch (e) { /* 静默 */ }
  }, 2500)
}

function stopPolling() {
  if (qrPollTimer) { clearInterval(qrPollTimer); qrPollTimer = null }
}

async function cancelQrLogin() {
  ++qrLoginAttempt
  const sessionId = qrSessionId.value
  stopPolling()
  qrLoading.value = false
  qrSessionId.value = ''
  qrError.value = ''
  qrPollData.value = { status: '', message: '' }
  if (!sessionId) return
  qrCancelling.value = true
  try {
    await request.post('/social/accounts/login/cancel', null, {
      params: { session_id: sessionId },
      silentError: true,
    })
  } catch (e) { /* ignore */ }
  finally { qrCancelling.value = false }
}

function dismissLoginStatus() {
  qrError.value = ''
  qrPollData.value = { status: '', message: '' }
}

async function validateCookie(row, asyncMode) {
  if (asyncMode) {
    await request.post(`/social/accounts/${row.id}/validate-async`)
    ElMessage.success('Cookie 校验已派发到 worker，请稍后刷新查看')
  } else {
    ElMessage.info('正在校验 Cookie，请稍候...')
    const res = await request.post(`/social/accounts/${row.id}/validate`)
    const payload = res.data || {}
    if (payload.valid) ElMessage.success('Cookie 有效')
    else ElMessage.warning(`Cookie 失效：${payload.reason || '未知原因'}`)
    loadSocialAccounts()
  }
}

async function deleteSocialAccount(row) {
  await ElMessageBox.confirm(`确认删除社媒账号"${row.nickname || row.platform_uid}"？同时会删除本地 Cookie 文件。`, '删除账号', { type: 'warning' })
  await request.delete(`/social/accounts/${row.id}`)
  ElMessage.success('账号已删除')
  loadSocialAccounts()
}

function handleAccountCmd(cmd, row) {
  if (cmd === 'async_validate') validateCookie(row, true)
  else if (cmd === 'delete') deleteSocialAccount(row)
}

// ===== 查看内容 =====
async function viewPosts(row) {
  currentAccountId.value = row.id
  currentAccountName.value = row.nickname || socialPlatformLabel(row.platform)
  postsDrawerVisible.value = true
  await loadAccountPosts()
}

async function loadAccountPosts() {
  postsLoading.value = true
  try {
    const res = await request.get(`/social/accounts/${currentAccountId.value}/posts`, { params: { page_size: 50 } })
    accountPosts.value = res.data || []
  } catch (e) { /* ignore */ }
  finally { postsLoading.value = false }
}

async function viewPostDetail(row) {
  postDetailVisible.value = true
  postDetailLoading.value = true
  postDetail.value = null
  try {
    const res = await request.get(`/social/accounts/${currentAccountId.value}/posts/${row.id}`)
    postDetail.value = res.data
  } catch (e) {
    ElMessage.error(errorMessageFrom(e, '内容详情加载失败，请刷新后重试。'))
  } finally { postDetailLoading.value = false }
}

async function syncMetrics(row) {
  try {
    await request.post(`/social/accounts/${currentAccountId.value}/posts/${row.id}/sync-metrics`)
    ElMessage.success('指标同步任务已派发到 worker')
    setTimeout(() => loadAccountPosts(), 2000)
  } catch (e) { /* ignore */ }
}

onMounted(() => {
  loadSocialAccounts()
  loadSocialPlatforms()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.accounts-page { padding: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.page-header h2 { margin: 0 0 4px; font-size: 22px; font-weight: 700; color: var(--color-ink); }
.page-sub { color: var(--color-ink-tertiary); font-size: 13px; }
.page-guide { margin-bottom: 12px; padding: 10px 14px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md); font-size: 13px; color: var(--color-ink-secondary); line-height: 1.6; }
.header-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.social-section { padding: 16px; }
.social-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.social-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.panel-card { border-radius: var(--radius-lg); }

/* 卡片网格 */
.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; margin-top: 12px; }
.account-card { padding: 14px; border-radius: 12px; border: 1px solid var(--color-border); background: #fff; display: flex; flex-direction: column; gap: 10px; }
.card-header { display: flex; gap: 10px; align-items: center; }
.card-info { flex: 1; min-width: 0; }
.card-name { font-size: 15px; font-weight: 600; color: var(--color-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-platform { display: flex; gap: 6px; align-items: center; margin-top: 4px; }
.card-platform-name { font-size: 12px; color: var(--color-ink-tertiary); }
.card-meta { font-size: 12px; color: var(--color-ink-secondary); }
.meta-row { display: flex; gap: 8px; margin-bottom: 2px; }
.meta-label { width: 36px; color: var(--color-ink-tertiary); flex-shrink: 0; }
.meta-value { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-actions { display: flex; gap: 6px; align-items: center; }

@media (max-width: 540px) {
  .card-grid { grid-template-columns: 1fr; }
}

/* 内容抽屉 */
.mini-metrics { display: flex; gap: 6px; flex-wrap: wrap; }
.mini-metrics .mm { font-size: 11px; color: var(--color-ink-secondary); background: var(--color-surface-subtle); padding: 1px 4px; border-radius: 3px; }

/* 内容详情 */
.detail-section-title { font-size: 13px; font-weight: 600; color: var(--color-ink); margin-bottom: 6px; }
.detail-text { font-size: 13px; color: var(--color-ink-secondary); line-height: 1.6; background: var(--color-surface); padding: 8px 12px; border-radius: 8px; max-height: 120px; overflow-y: auto; }
.media-item { font-size: 12px; color: var(--color-ink-tertiary); padding: 2px 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.metric-cards { display: flex; gap: 8px; flex-wrap: wrap; }
.metric-card { text-align: center; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 8px; padding: 8px 12px; min-width: 70px; }
.mc-value { font-size: 18px; font-weight: 700; color: var(--color-accent); }
.mc-label { font-size: 11px; color: var(--color-ink-tertiary); margin-top: 2px; }
.log-list { max-height: 200px; overflow-y: auto; background: var(--color-surface); border-radius: 8px; padding: 8px; }
.log-item { font-size: 12px; padding: 2px 0; display: flex; gap: 6px; }
.log-time { color: var(--color-ink-tertiary); flex-shrink: 0; }
.log-level { flex-shrink: 0; font-weight: 600; }
.log-msg { color: var(--color-ink-secondary); }
.log-error .log-level { color: var(--color-danger); }
.log-warning .log-level { color: var(--color-warning); }
.raw-json { font-size: 11px; background: var(--color-surface-subtle); padding: 8px; border-radius: 6px; max-height: 300px; overflow: auto; white-space: pre-wrap; word-break: break-all; }
</style>
