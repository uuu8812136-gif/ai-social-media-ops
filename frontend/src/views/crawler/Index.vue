<template>
  <div class="crawler-page rb-enter">
    <div class="page-header">
      <div>
        <h2>数据采集</h2>
        <span class="page-sub">MediaCrawler 内嵌采集 · 关键词搜索列表采集</span>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" @click="refreshAll">刷新</el-button>
        <el-button type="primary" @click="openCreate">新建采集任务</el-button>
      </div>
    </div>

    <div class="page-guide">
      采集流程：选择平台 → 输入关键词 → 系统通过 Celery worker 异步执行 MediaCrawler 采集。
      当前小红书、抖音、B站支持关键词搜索列表采集（beta），快手/微博等待接入。创作者主页/笔记详情/评论采集尚未实现。
      采集结果保存到 data/mediacrawler/{platform} 目录，并可一键导入到内容工厂作为创作素材。
    </div>

    <el-tabs v-model="activeTab" class="mt-12">
      <el-tab-pane label="采集任务" name="jobs">
        <div class="panel-card">
          <el-table :data="jobs" v-loading="loadingJobs">
            <el-table-column prop="name" label="任务名" min-width="160" show-overflow-tooltip />
            <el-table-column label="平台" width="100">
              <template #default="{ row }">{{ platformLabel(row.platform) }}</template>
            </el-table-column>
            <el-table-column label="类型" width="100">
              <template #default="{ row }">{{ crawlerTypeLabel(row.crawler_type) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tooltip v-if="row.status === 'failed' && row.error_message" :content="friendlyCrawlerError(row.error_message)" placement="top" :show-after="200">
                  <el-tag size="small" type="danger">{{ jobStatusLabel(row.status) }}</el-tag>
                </el-tooltip>
                <el-tag v-else size="small" :type="jobTagType(row.status)">{{ jobStatusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="items_count" label="条目数" width="80" />
            <el-table-column prop="created_at" label="创建时间" width="190" show-overflow-tooltip>
              <template #default="{ row }"><span style="white-space:nowrap">{{ formatTime(row.created_at) }}</span></template>
            </el-table-column>
            <el-table-column label="操作" width="180" fixed="right">
              <template #default="{ row }">
                <el-button link size="small" type="primary" @click="viewJob(row)">详情</el-button>
                <el-button v-if="canStop(row.status)" link size="small" type="danger" @click="stopJob(row)">停止</el-button>
                <el-button v-if="row.status === 'succeeded' && row.items_count > 0" link size="small" type="success" @click="openImport(row)">导入</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无采集任务" :image-size="60">
                <el-button type="primary" size="small" @click="openCreate">新建采集任务</el-button>
              </el-empty>
            </template>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="数据文件" name="files">
        <div class="panel-card">
          <div class="filter-bar">
            <el-select v-model="fileFilter.platform" placeholder="平台" clearable style="width:160px" @change="loadFiles">
              <el-option
                v-for="p in crawlerPlatforms"
                :key="p.platform"
                :label="p.crawler_available ? p.name : `${p.name}（${p.status_label || '待接入'}）`"
                :value="p.platform"
                :disabled="!p.crawler_available"
              />
            </el-select>
            <el-button @click="loadFiles">刷新</el-button>
          </div>
          <el-table :data="dataFiles" v-loading="loadingFiles">
            <el-table-column prop="name" label="文件名" min-width="240" show-overflow-tooltip />
            <el-table-column label="大小" width="100">
              <template #default="{ row }">{{ formatSize(row.size) }}</template>
            </el-table-column>
            <el-table-column label="修改时间" width="190" show-overflow-tooltip>
              <template #default="{ row }"><span style="white-space:nowrap">{{ formatTime(row.modified) }}</span></template>
            </el-table-column>
            <el-table-column label="操作" width="180" fixed="right">
              <template #default="{ row }">
                <el-button link size="small" type="primary" @click="parseFile(row)">解析</el-button>
                <el-button link size="small" type="success" @click="downloadFile(row)">下载</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无数据文件，采集任务完成后将在此展示" :image-size="60" />
            </template>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 新建采集任务弹窗 -->
    <el-dialog v-model="showCreate" title="新建采集任务" width="560px">
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="任务名">
          <el-input v-model="createForm.name" placeholder="选填，便于识别" />
        </el-form-item>
        <el-form-item label="平台" required>
          <el-select v-model="createForm.platform" style="width:100%" @change="onPlatformChange">
            <el-option
              v-for="p in crawlerPlatforms"
              :key="p.platform"
              :label="p.crawler_available ? p.name : `${p.name}（${p.status_label || '待接入'}）`"
              :value="p.platform"
              :disabled="!p.crawler_available"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="采集类型" required>
          <el-select v-model="createForm.crawler_type" style="width:100%" disabled>
            <el-option label="关键词搜索" value="search" />
            <el-option label="创作者主页（未接入）" value="creator" disabled />
            <el-option label="笔记详情（未接入）" value="detail" disabled />
            <el-option label="评论采集（未接入）" value="comment" disabled />
          </el-select>
        </el-form-item>
        <el-form-item label="关键词" required>
          <el-input v-model="searchKeywords" type="textarea" :rows="2" placeholder="多个关键词用换行分隔" />
        </el-form-item>
        <el-form-item label="最大条数" required>
          <el-input-number v-model="createForm.config.max_notes" :min="1" :max="100" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建并开始采集</el-button>
      </template>
    </el-dialog>

    <!-- 任务详情弹窗 -->
    <el-dialog v-model="jobDetailVisible" title="采集任务详情" width="900px">
      <div v-if="jobDetail">
        <el-descriptions :column="3" border>
          <el-descriptions-item label="任务名">{{ jobDetail.name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="平台">{{ platformLabel(jobDetail.platform) }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ crawlerTypeLabel(jobDetail.crawler_type) }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ jobStatusLabel(jobDetail.status) }}</el-descriptions-item>
          <el-descriptions-item label="条目数">{{ jobDetail.items_count }}</el-descriptions-item>
          <el-descriptions-item label="失败原因">{{ friendlyCrawlerError(jobDetail.error_message) || '—' }}</el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ formatTime(jobDetail.started_at) }}</el-descriptions-item>
          <el-descriptions-item label="完成时间">{{ formatTime(jobDetail.finished_at) }}</el-descriptions-item>
        </el-descriptions>

        <h4 style="margin:16px 0 8px">采集条目（最多显示 100 条）</h4>
        <el-table :data="jobDetail.items || []" size="small" max-height="400">
          <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
          <el-table-column prop="author_name" label="作者" width="120" show-overflow-tooltip />
          <el-table-column prop="liked_count" label="点赞" width="80" />
          <el-table-column prop="collected_count" label="收藏" width="80" />
          <el-table-column prop="comment_count" label="评论" width="80" />
          <el-table-column prop="platform_item_id" label="平台ID" width="140" show-overflow-tooltip />
        </el-table>

        <div v-if="jobDetail.output_files && jobDetail.output_files.length" style="margin-top:16px">
          <h4 style="margin:0 0 8px">原始数据文件</h4>
          <div v-for="(f, idx) in jobDetail.output_files" :key="idx" class="output-file-row">
            <span class="output-file-name">{{ outputFileLabel(f) }}</span>
            <el-button link size="small" type="primary" @click="downloadOutputFile(f)">下载</el-button>
          </div>
        </div>

        <div v-if="jobDetail.status === 'succeeded' && jobDetail.items_count > 0" style="margin-top:16px;text-align:right">
          <el-button type="success" @click="openImport(jobDetail)">导入内容工厂</el-button>
        </div>
      </div>
    </el-dialog>

    <!-- 导入弹窗 -->
    <el-dialog v-model="importVisible" title="导入采集数据到内容工厂" width="500px">
      <div v-if="importJob">
        <p style="margin-bottom:12px">将采集任务「{{ importJob.name || importJob.id }}」的 {{ importJob.items_count }} 条数据导入到内容工厂？</p>
        <el-form label-width="100px">
          <el-form-item label="关联账号" required>
            <el-select v-model="importForm.account_id" placeholder="请选择内容归属账号" style="width:100%">
              <el-option v-for="a in accountsForImport" :key="a.id" :label="accountLabel(a)" :value="a.id" />
            </el-select>
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="submitImport">导入</el-button>
      </template>
    </el-dialog>

    <!-- 文件解析结果弹窗 -->
    <el-dialog v-model="parseResultVisible" title="数据文件解析结果" width="800px">
      <div v-if="parseResult">
        <p style="margin-bottom:8px">文件：{{ parseResult.file_path }}</p>
        <p style="margin-bottom:12px">共 {{ parseResult.items_count }} 条数据（仅显示前 50 条）</p>
        <el-table :data="parseResult.items" size="small" max-height="400">
          <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
          <el-table-column prop="desc" label="描述" min-width="200" show-overflow-tooltip />
          <el-table-column prop="nickname" label="作者" width="120" show-overflow-tooltip />
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>


<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../../utils/request'
import { errorMessageFrom, humanizeError } from '../../utils/errorMessage'

const activeTab = ref('jobs')
const loadingJobs = ref(false)
const loadingFiles = ref(false)
const creating = ref(false)
const importing = ref(false)
const showCreate = ref(false)
const jobDetailVisible = ref(false)
const importVisible = ref(false)
const parseResultVisible = ref(false)

const jobs = ref([])
const dataFiles = ref([])
const accountsForImport = ref([])
const socialAccountName = (a) => a.nickname || a.user_info?.name || a.user_info?.username || a.platform_uid || platformLabel(a.platform)
const accountLabel = (a) => `${socialAccountName(a)}（${platformLabel(a.platform)}）`
const jobDetail = ref(null)
const importJob = ref(null)
const parseResult = ref(null)

const searchKeywords = ref('')

const fileFilter = reactive({ platform: '' })

const createForm = reactive({
  name: '',
  platform: 'xhs',
  crawler_type: 'search',
  params: {},
  config: { max_notes: 20 },
})

const importForm = reactive({ account_id: '' })

const crawlerPlatforms = ref([])
const PLATFORM_MAP = {
  xhs: '小红书', dy: '抖音', bili: 'B站', ks: '快手', wb: '微博',
  xiaohongshu: '小红书', douyin: '抖音', bilibili: 'B站', kuaishou: '快手', weibo: '微博',
}
const platformLabel = (p) => {
  const hit = crawlerPlatforms.value.find((x) => x.platform === p)
  return hit?.name || PLATFORM_MAP[p] || p
}

async function loadCrawlerPlatforms() {
  try {
    const res = await request.get('/crawler/platforms')
    crawlerPlatforms.value = res.data?.platforms || []
  } catch (e) { /* 拦截器已提示 */ }
}

const CRAWLER_TYPE_MAP = {
  search: '关键词搜索', creator: '创作者', detail: '笔记详情', comment: '评论',
}
const crawlerTypeLabel = (t) => CRAWLER_TYPE_MAP[t] || t

const JOB_STATUS_MAP = {
  pending: { label: '待执行', type: 'info' },
  queued: { label: '排队中', type: 'info' },
  running: { label: '执行中', type: 'primary' },
  succeeded: { label: '成功', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' },
}
const jobStatusLabel = (s) => JOB_STATUS_MAP[s]?.label || s
const jobTagType = (s) => JOB_STATUS_MAP[s]?.type || 'info'
const canStop = (s) => ['pending', 'queued', 'running'].includes(s)
const friendlyCrawlerError = (message) => message ? humanizeError(message, { context: 'crawler' }) : ''

const hasActiveJobs = computed(() =>
  jobs.value.some((j) => ['pending', 'queued', 'running'].includes(j.status))
)

const formatTime = (t) => {
  if (!t) return '—'
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const formatSize = (bytes) => {
  if (!bytes) return '—'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

async function loadJobs() {
  loadingJobs.value = true
  try {
    const res = await request.get('/crawler/jobs', { params: { page_size: 50 } })
    jobs.value = res.data || []
  } finally { loadingJobs.value = false }
}

async function loadFiles() {
  loadingFiles.value = true
  try {
    const params = {}
    if (fileFilter.platform) params.platform = fileFilter.platform
    const res = await request.get('/crawler/data/files', { params })
    dataFiles.value = res.data || []
  } finally { loadingFiles.value = false }
}

function openCreate() {
  createForm.name = ''
  createForm.platform = 'xhs'
  createForm.crawler_type = 'search'
  createForm.params = {}
  createForm.config = { max_notes: 20 }
  searchKeywords.value = ''
  showCreate.value = true
}

function onPlatformChange() {
  // 平台切换时无需额外操作
}

async function submitCreate() {
  if (!createForm.platform) {
    ElMessage.warning('请选择采集平台')
    return
  }

  // 整理参数
  const params = { ...createForm.params }
  if (createForm.crawler_type === 'search') {
    const keywords = searchKeywords.value.split('\n').map((s) => s.trim()).filter(Boolean)
    if (keywords.length === 0) {
      ElMessage.warning('请输入至少一个关键词')
      return
    }
    params.keywords = keywords
  }

  creating.value = true
  try {
    await request.post('/crawler/jobs', {
      name: createForm.name,
      platform: createForm.platform,
      crawler_type: createForm.crawler_type,
      params,
      config: createForm.config,
    })
    ElMessage.success('采集任务已创建并派发到 worker')
    showCreate.value = false
    loadJobs()
  } finally { creating.value = false }
}

async function viewJob(row) {
  const res = await request.get(`/crawler/jobs/${row.id}`)
  jobDetail.value = res.data
  jobDetailVisible.value = true
}

async function stopJob(row) {
  await ElMessageBox.confirm(`确认停止采集任务"${row.name || row.id}"？`, '停止任务')
  await request.post(`/crawler/jobs/${row.id}/stop`)
  ElMessage.success('任务已停止')
  loadJobs()
}

async function openImport(row) {
  importJob.value = row
  importForm.account_id = ''
  // 加载账号列表供选择
  const res = await request.get('/social/accounts/', { params: { page_size: 100, status: 'active' } })
  accountsForImport.value = (res.data || []).map((a) => ({
    ...a,
    account_name: socialAccountName(a),
  }))
  importVisible.value = true
}

async function submitImport() {
  if (!importJob.value) return
  if (!importForm.account_id) {
    ElMessage.warning('请选择内容归属账号')
    return
  }
  importing.value = true
  try {
    const payload = {
      job_id: importJob.value.id,
      target: 'content',
      account_id: importForm.account_id,
    }
    const res = await request.post('/crawler/data/import', payload)
    ElMessage.success(`导入完成：${res.data.imported}/${res.data.total} 条成功`)
    importVisible.value = false
  } finally { importing.value = false }
}

async function parseFile(row) {
  const res = await request.get('/crawler/data/files/parse', { params: { file_path: row.path } })
  parseResult.value = res.data
  parseResultVisible.value = true
}

async function downloadFile(row) {
  try {
    const resp = await request.get('/crawler/data/files/download', {
      params: { file_path: row.path },
      responseType: 'blob',
    })
    const blob = new Blob([resp])
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = row.name || 'crawler_data'
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error(errorMessageFrom(e, '文件下载失败，请刷新后重试。', 'crawler'))
  }
}

function outputFileLabel(f) {
  if (typeof f === 'string') return f.split('/').pop().split('\\').pop() || f
  return f.name || f.filename || '文件'
}

async function downloadOutputFile(f) {
  const filePath = typeof f === 'string' ? f : (f.path || f.file || f.file_path || f.name)
  if (!filePath) {
    ElMessage.warning('文件路径缺失，无法下载')
    return
  }
  await downloadFile({ path: filePath, name: outputFileLabel(f) })
}

function refreshAll() {
  loadJobs()
  loadFiles()
}

let pollTimer = null
function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(() => {
    if (activeTab.value === 'jobs') loadJobs()
  }, 5000)
}
function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

watch(hasActiveJobs, (val) => {
  if (val) startPolling()
  else stopPolling()
})

onMounted(() => {
  loadJobs()
  loadFiles()
  loadCrawlerPlatforms()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.crawler-page { padding: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.page-header h2 { margin: 0 0 4px; font-size: 24px; font-weight: 800; letter-spacing: -0.02em; }
.page-sub { color: var(--color-ink-tertiary); font-size: 13px; }
.header-actions { display: flex; gap: 8px; align-items: center; }
.page-guide { margin-bottom: 12px; padding: 12px 16px; font-size: 13px; color: var(--color-ink-secondary); line-height: 1.6; border-radius: var(--radius-lg); }
.mt-12 { margin-top: 12px; }
.panel-card { border-radius: var(--radius-lg); padding: 4px; }
.filter-bar { display: flex; gap: 12px; margin-bottom: 12px; }
.output-file-row { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px dashed var(--color-border); }
.output-file-row:last-child { border-bottom: none; }
.output-file-name { font-size: 13px; color: var(--color-ink-secondary); word-break: break-all; margin-right: 12px; }
</style>
