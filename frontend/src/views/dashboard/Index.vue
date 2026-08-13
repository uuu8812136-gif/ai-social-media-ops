<template>
  <div class="dashboard rb-enter">
    <div class="page-header">
      <div>
        <h2>数据看板</h2>
        <span class="page-sub">运营总览 · 内容与线索核心指标</span>
      </div>
    </div>

    <!-- 快捷入口 -->
    <div class="dash-guide">
      <div class="guide-row">
        <span class="guide-label">快捷操作</span>
        <el-button size="small" type="primary" @click="router.push('/content')">内容工厂</el-button>
        <el-button size="small" @click="router.push('/knowledge')">知识库</el-button>
        <el-button size="small" @click="router.push('/leads')">线索管理</el-button>
        <el-button size="small" @click="router.push('/calendar')">内容日历</el-button>
        <span class="guide-tip">核心流程：内容工厂生成内容 → 风控检测 → 审核 → 发布 → 数据回流</span>
      </div>
    </div>

    <div class="panel-card operations-card">
      <div class="panel-card__header">
        <div class="card-head">
          <span class="card-title">自动化运行健康</span>
          <el-button link size="small" type="primary" @click="router.push('/social-publish')">处理发布任务</el-button>
        </div>
      </div>
      <el-row :gutter="12">
        <el-col :span="6">
          <div class="mini-stat">
            <div class="mini-value mini-value--success rb-stat-number">{{ operations.publish?.success_rate || 0 }}%</div>
            <div class="mini-label">近 7 天确定结果成功率</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="mini-stat">
            <div class="mini-value mini-value--warning rb-stat-number">{{ operations.publish?.unknown || 0 }}</div>
            <div class="mini-label">结果待人工确认</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="mini-stat">
            <div class="mini-value mini-value--warning rb-stat-number">{{ operations.publish?.verification_required || 0 }}</div>
            <div class="mini-label">等待人工验证</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="mini-stat">
            <div class="mini-value mini-value--danger rb-stat-number">{{ operations.accounts?.needs_attention || 0 }}</div>
            <div class="mini-label">账号状态需处理</div>
          </div>
        </el-col>
      </el-row>
      <div v-if="operations.alerts?.length" class="operations-alerts">
        <el-alert
          v-for="alert in operations.alerts"
          :key="alert.code"
          :title="alert.message"
          :type="alert.severity"
          :closable="false"
          show-icon
        />
      </div>
      <div v-else class="operations-ok">当前没有需要人工处理的自动化异常</div>
    </div>

    <!-- 全空引导 -->
    <div v-if="isEmpty" class="panel-card empty-hero">
      <el-empty description="还没有数据，开始你的第一次运营" :image-size="72">
        <div class="empty-hero-actions">
          <el-button type="primary" @click="router.push('/content')">去创建内容</el-button>
          <el-button type="success" @click="router.push('/social-publish')">添加账号</el-button>
          <el-button type="warning" @click="router.push('/crawler')">开始采集</el-button>
        </div>
      </el-empty>
    </div>

    <!-- 顶部核心指标 -->
    <el-row :gutter="16" class="card-row core-stat-row">
      <el-col :span="6" v-for="(item, idx) in cards" :key="item.label">
        <div :class="['stat-card', 'stat-card--' + cardColors[idx]]">
          <div class="stat-value rb-stat-number">{{ item.value }}</div>
          <div class="stat-label">{{ item.label }}</div>
        </div>
      </el-col>
    </el-row>

    <!-- 内容 & 线索统计 -->
    <el-row :gutter="16" class="card-row">
      <el-col :span="12">
        <div class="panel-card">
          <div class="panel-card__header"><span class="card-title">内容统计</span></div>
          <el-row :gutter="16">
            <el-col :span="6">
              <div class="mini-stat">
                <div class="mini-value rb-stat-number">{{ contentStats.total || 0 }}</div>
                <div class="mini-label">总内容</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="mini-stat">
                <div class="mini-value mini-value--warning rb-stat-number">{{ contentStats.ai_generated || 0 }}</div>
                <div class="mini-label">AI 已生成</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="mini-stat">
                <div class="mini-value mini-value--success rb-stat-number">{{ contentStats.published || 0 }}</div>
                <div class="mini-label">已发布</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="mini-stat">
                <div class="mini-value rb-stat-number">{{ contentStats.publish_rate || 0 }}%</div>
                <div class="mini-label">发布率</div>
              </div>
            </el-col>
          </el-row>
          <el-progress
            :percentage="Number(contentStats.publish_rate || 0)"
            :stroke-width="10"
            status="success"
            style="margin-top:16px"
          />
        </div>
      </el-col>
      <el-col :span="12">
        <div class="panel-card">
          <div class="panel-card__header"><span class="card-title">线索统计</span></div>
          <el-row :gutter="16">
            <el-col :span="6">
              <div class="mini-stat">
                <div class="mini-value rb-stat-number">{{ leadStats.total || 0 }}</div>
                <div class="mini-label">总线索</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="mini-stat">
                <div class="mini-value mini-value--muted rb-stat-number">{{ leadStats.pending || 0 }}</div>
                <div class="mini-label">待分配</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="mini-stat">
                <div class="mini-value mini-value--info rb-stat-number">{{ leadStats.assigned || 0 }}</div>
                <div class="mini-label">已分配</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="mini-stat">
                <div class="mini-value mini-value--success rb-stat-number">{{ leadStats.signed || 0 }}</div>
                <div class="mini-label">已签单</div>
              </div>
            </el-col>
          </el-row>
          <div class="funnel-row" style="margin-top:16px">
            <span class="funnel-label">转化率</span>
            <el-progress
              :percentage="Number(leadStats.conversion_rate || 0)"
              :stroke-width="10"
              status="warning"
            />
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 趋势 + 待发布/待审核 -->
    <el-row :gutter="16" class="card-row">
      <el-col :span="14">
        <div class="panel-card">
          <div class="panel-card__header">
            <div class="card-head">
              <span class="card-title">{{ trendTitle }}</span>
              <el-radio-group v-model="trendDays" size="small" @change="loadTrend">
                <el-radio-button :value="7">7 天</el-radio-button>
                <el-radio-button :value="14">14 天</el-radio-button>
                <el-radio-button :value="30">30 天</el-radio-button>
              </el-radio-group>
            </div>
          </div>
          <el-empty v-if="!trends.length" description="暂无趋势数据，去内容工厂生成或发布内容后回流" :image-size="56" style="padding:24px 0">
            <el-button type="primary" size="small" @click="router.push('/content')">去创建内容</el-button>
          </el-empty>
          <el-table v-else :data="trends" size="small" style="max-height:320px;overflow:auto">
            <el-table-column prop="date" label="日期" width="120">
              <template #default="{ row }">{{ row.date.slice(5) }}</template>
            </el-table-column>
            <el-table-column label="新增线索" min-width="180">
              <template #default="{ row }">
                <div class="bar-cell">
                  <span class="bar-num">{{ row.leads }}</span>
                  <div class="bar-bg">
                    <div class="bar-fill bar-leads" :style="{ width: barWidth(row.leads, maxLeads) }"></div>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="新增内容" min-width="180">
              <template #default="{ row }">
                <div class="bar-cell">
                  <span class="bar-num">{{ row.contents }}</span>
                  <div class="bar-bg">
                    <div class="bar-fill bar-contents" :style="{ width: barWidth(row.contents, maxContents) }"></div>
                  </div>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-col>
      <el-col :span="10">
        <div class="panel-card task-card">
          <div class="panel-card__header">
            <div class="card-head">
              <span class="card-title">待发布/待审核</span>
              <el-tag size="small" type="warning">{{ pendingContents.length }} 条</el-tag>
            </div>
          </div>
          <el-empty v-if="!pendingContents.length" description="暂无待发布/待审核内容" :image-size="56">
            <el-button type="primary" size="small" @click="goContent">去内容工厂生成</el-button>
          </el-empty>
          <div v-else class="task-list">
            <div v-for="c in pendingContents" :key="c.id" class="task-item" @click="goContent">
              <div class="task-item-main">
                <div class="task-item-title">{{ c.title }}</div>
                <div class="task-item-sub">{{ accountName(c.account_id) }} · {{ formatTime(c.created_at) }}</div>
              </div>
              <div class="task-item-actions">
                <el-tag size="small" type="warning">待处理</el-tag>
                <el-button size="small" type="primary" link @click.stop="goContent">去审核</el-button>
              </div>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 平台数据概览 -->
    <el-row :gutter="16" class="card-row">
      <el-col :span="24">
        <div class="panel-card">
          <div class="panel-card__header">
            <div class="card-head">
              <span class="card-title">平台数据概览</span>
              <el-radio-group v-model="dashboardDays" size="small" @change="fetchDashboardStats">
                <el-radio-button :value="7">7 天</el-radio-button>
                <el-radio-button :value="14">14 天</el-radio-button>
                <el-radio-button :value="30">30 天</el-radio-button>
              </el-radio-group>
            </div>
          </div>
          <el-row :gutter="16" v-if="dashboardStats.total_stats" style="margin-bottom:16px">
            <el-col :span="4">
              <div class="mini-stat">
                <div class="mini-value rb-stat-number">{{ dashboardStats.total_stats.views?.toLocaleString() || 0 }}</div>
                <div class="mini-label">总播放</div>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="mini-stat">
                <div class="mini-value mini-value--warning rb-stat-number">{{ dashboardStats.total_stats.likes?.toLocaleString() || 0 }}</div>
                <div class="mini-label">总点赞</div>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="mini-stat">
                <div class="mini-value mini-value--info rb-stat-number">{{ dashboardStats.total_stats.comments?.toLocaleString() || 0 }}</div>
                <div class="mini-label">总评论</div>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="mini-stat">
                <div class="mini-value mini-value--danger rb-stat-number">{{ dashboardStats.total_stats.favorites?.toLocaleString() || 0 }}</div>
                <div class="mini-label">总收藏</div>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="mini-stat">
                <div class="mini-value mini-value--success rb-stat-number">{{ dashboardStats.total_stats.leads?.toLocaleString() || 0 }}</div>
                <div class="mini-label">总线索</div>
              </div>
            </el-col>
            <el-col :span="4">
              <div class="mini-stat">
                <div class="mini-value rb-stat-number">{{ dashboardStats.total_stats.conversion_rate || 0 }}%</div>
                <div class="mini-label">转化率</div>
              </div>
            </el-col>
          </el-row>
          <el-empty v-if="!dashboardStats.platform_stats?.length" description="暂无平台数据，发布内容后回流数据将在此展示" :image-size="56" style="padding:18px 0" />
          <el-table v-else :data="dashboardStats.platform_stats" size="small">
            <el-table-column label="平台" width="120">
              <template #default="{ row }">{{ platformLabel(row.platform) }}</template>
            </el-table-column>
            <el-table-column prop="views" label="播放" min-width="100">
              <template #default="{ row }">{{ row.views?.toLocaleString() || 0 }}</template>
            </el-table-column>
            <el-table-column prop="likes" label="点赞" min-width="100">
              <template #default="{ row }">{{ row.likes?.toLocaleString() || 0 }}</template>
            </el-table-column>
            <el-table-column prop="comments" label="评论" min-width="100">
              <template #default="{ row }">{{ row.comments?.toLocaleString() || 0 }}</template>
            </el-table-column>
            <el-table-column prop="favorites" label="收藏" min-width="100">
              <template #default="{ row }">{{ row.favorites?.toLocaleString() || 0 }}</template>
            </el-table-column>
            <el-table-column prop="leads" label="线索" min-width="80">
              <template #default="{ row }">{{ row.leads || 0 }}</template>
            </el-table-column>
            <el-table-column prop="conversion_rate" label="转化率" width="100">
              <template #default="{ row }">{{ row.conversion_rate || 0 }}%</template>
            </el-table-column>
          </el-table>
        </div>
      </el-col>
    </el-row>


    <!-- 社媒发布与采集统计 -->
    <el-row :gutter="16" class="card-row">
      <el-col :span="12">
        <div class="panel-card">
          <div class="panel-card__header">
            <div class="card-head">
              <span class="card-title">社媒发布任务</span>
              <el-button link size="small" type="primary" @click="router.push('/social-publish')">查看全部</el-button>
            </div>
          </div>
          <el-row :gutter="16">
            <el-col :span="6">
              <div class="mini-stat">
                <div class="mini-value rb-stat-number">{{ socialStats.total || 0 }}</div>
                <div class="mini-label">总任务</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="mini-stat">
                <div class="mini-value mini-value--success rb-stat-number">{{ socialStats.published || 0 }}</div>
                <div class="mini-label">已发布</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="mini-stat">
                <div class="mini-value mini-value--warning rb-stat-number">{{ socialStats.running || 0 }}</div>
                <div class="mini-label">执行中</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="mini-stat">
                <div class="mini-value mini-value--danger rb-stat-number">{{ socialStats.failed || 0 }}</div>
                <div class="mini-label">失败</div>
              </div>
            </el-col>
          </el-row>
          <el-empty v-if="!socialStats.recent?.length" description="暂无发布任务" :image-size="48" style="margin-top:12px">
            <el-button type="primary" size="small" @click="router.push('/social-publish')">去社媒发布</el-button>
          </el-empty>
          <div v-else class="task-list" style="margin-top:12px">
            <div v-for="t in socialStats.recent" :key="t.id" class="task-item" @click="router.push('/social-publish')">
              <div class="task-item-main">
                <div class="task-item-title">{{ t.title }}</div>
                <div class="task-item-sub">{{ formatTime(t.created_at) }}</div>
              </div>
              <el-tag size="small" :type="publishTaskTagType(t.status)">{{ publishTaskStatusLabel(t.status) }}</el-tag>
            </div>
          </div>
        </div>
      </el-col>
      <el-col :span="12">
        <div class="panel-card">
          <div class="panel-card__header">
            <div class="card-head">
              <span class="card-title">数据采集任务</span>
              <el-button link size="small" type="primary" @click="router.push('/crawler')">查看全部</el-button>
            </div>
          </div>
          <el-row :gutter="16">
            <el-col :span="6">
              <div class="mini-stat">
                <div class="mini-value rb-stat-number">{{ crawlerStats.total || 0 }}</div>
                <div class="mini-label">总任务</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="mini-stat">
                <div class="mini-value mini-value--success rb-stat-number">{{ crawlerStats.completed || 0 }}</div>
                <div class="mini-label">已完成</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="mini-stat">
                <div class="mini-value mini-value--warning rb-stat-number">{{ crawlerStats.running || 0 }}</div>
                <div class="mini-label">执行中</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="mini-stat">
                <div class="mini-value mini-value--info rb-stat-number">{{ crawlerStats.items || 0 }}</div>
                <div class="mini-label">采集条目</div>
              </div>
            </el-col>
          </el-row>
          <el-empty v-if="!crawlerStats.recent?.length" description="暂无采集任务" :image-size="48" style="margin-top:12px">
            <el-button type="primary" size="small" @click="router.push('/crawler')">去数据采集</el-button>
          </el-empty>
          <div v-else class="task-list" style="margin-top:12px">
            <div v-for="j in crawlerStats.recent" :key="j.id" class="task-item" @click="router.push('/crawler')">
              <div class="task-item-main">
                <div class="task-item-title">{{ j.name }}</div>
                <div class="task-item-sub">{{ crawlerPlatformLabel(j.platform) }} · {{ formatTime(j.created_at) }}</div>
              </div>
              <el-tag size="small" :type="crawlerJobTagType(j.status)">{{ crawlerJobStatusLabel(j.status) }}</el-tag>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 风控预警 -->
    <el-row :gutter="16" class="card-row">
      <el-col :span="24">
        <div class="panel-card">
          <div class="panel-card__header">
            <div class="card-head">
              <span class="card-title">风控预警</span>
              <el-tag size="small" :type="riskAlerts.length ? 'danger' : 'success'">
                {{ riskAlerts.length ? `${riskAlerts.length} 条未通过` : '全部通过' }}
              </el-tag>
            </div>
          </div>
          <el-empty v-if="!riskAlerts.length" description="暂无风控预警" :image-size="56" />
          <el-table v-else :data="riskAlerts" size="small">
            <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
            <el-table-column label="账号" width="150">
              <template #default="{ row }">{{ accountName(row.account_id) }}</template>
            </el-table-column>
            <el-table-column label="风险词" min-width="220">
              <template #default="{ row }">
                <el-tag
                  v-for="(iss, idx) in (row.risk_check_result?.issues || []).slice(0, 3)"
                  :key="idx"
                  :type="iss.severity === 'high' ? 'danger' : 'warning'"
                  size="small"
                  style="margin-right:4px"
                >{{ iss.word || iss.message }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="140">
              <template #default>
                <el-button link size="small" type="primary" @click="goContent">去处理</el-button>
                <el-button link size="small" @click="goContent">查看详情</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-col>
    </el-row>
  </div>
</template>


<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import request from '../../utils/request'

const router = useRouter()
const overview = ref({})
const contentStats = ref({})
const leadStats = ref({})
const trends = ref([])
const pendingContents = ref([])
const riskAlerts = ref([])
const trendDays = ref(14)
const dashboardStats = ref({})
const dashboardDays = ref(7)
const operations = ref({})

const cards = computed(() => [
  { label: '账号数', value: overview.value.accounts || 0 },
  { label: '内容数', value: overview.value.contents || 0 },
  { label: '线索数', value: overview.value.leads || 0 },
  { label: '签单数', value: overview.value.signed_leads || 0 },
])

// 全空判定：账号/内容/线索均无数据时，引导首次运营
const isEmpty = computed(() =>
  !(overview.value.accounts || 0) &&
  !(overview.value.contents || 0) &&
  !(overview.value.leads || 0)
)

const cardColors = ['blue', 'green', 'amber', 'purple']

const maxLeads = computed(() => Math.max(1, ...trends.value.map((t) => t.leads)))
const maxContents = computed(() => Math.max(1, ...trends.value.map((t) => t.contents)))
const trendTitle = computed(() => `近 ${trendDays.value} 天趋势`)

const accountMap = ref({})
const accountName = (id) => accountMap.value[id] || '—'
const formatTime = (t) => (t ? new Date(t).toLocaleString('zh-CN') : '—')
const barWidth = (val, max) => `${Math.round((val / max) * 100)}%`

const PLATFORM_LABELS = { douyin: '抖音', xiaohongshu: '小红书', channels: '视频号', kuaishou: '快手', bilibili: 'B站' }
const platformLabel = (p) => PLATFORM_LABELS[p] || p

function goContent() {
  router.push('/content')
}

async function loadAccounts() {
  const res = await request.get('/social/accounts/', { params: { page_size: 100, status: 'active' } })
  const list = res.data || []
  accountMap.value = Object.fromEntries(list.map((a) => [
    a.id,
    a.nickname || a.user_info?.name || a.user_info?.username || a.platform_uid || platformLabel(a.platform),
  ]))
}

async function loadOverview() {
  const [o, c, l] = await Promise.all([
    request.get('/dashboard/overview'),
    request.get('/dashboard/content/stats'),
    request.get('/dashboard/lead/stats'),
  ])
  overview.value = o.data
  contentStats.value = c.data
  leadStats.value = l.data
}

async function loadOperations() {
  try {
    const res = await request.get('/dashboard/operations', { params: { days: 7 } })
    operations.value = res.data || {}
  } catch (e) {
    console.warn('loadOperations failed', e)
  }
}

async function loadTrend() {
  const res = await request.get('/dashboard/trend', { params: { period: 'day', days: trendDays.value } })
  trends.value = (res.data.trends || []).reverse()
}

async function loadPendingAndRisk() {
  const res = await request.get('/content/scripts', { params: { page_size: 20 } })
  const list = res.data || []
  pendingContents.value = list.filter((c) => ['ai_generated', 'risk_checked', 'approved'].includes(c.status))
  riskAlerts.value = list.filter((c) => c.risk_check_result && c.risk_check_result.passed === false)
}


const socialStats = ref({})
const crawlerStats = ref({})

const PUBLISH_TASK_STATUS_MAP = {
  queued: { label: '排队中', type: 'info' },
  running: { label: '执行中', type: 'primary' },
  published: { label: '已发布', type: 'success' },
  reviewing: { label: '审核中', type: 'primary' },
  failed: { label: '失败', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' },
  scheduled: { label: '定时待发', type: 'warning' },
}
const publishTaskStatusLabel = (s) => PUBLISH_TASK_STATUS_MAP[s]?.label || s
const publishTaskTagType = (s) => PUBLISH_TASK_STATUS_MAP[s]?.type || 'info'

const CRAWLER_PLATFORM_MAP = { xhs: '小红书', dy: '抖音', bili: 'B站', ks: '快手', wb: '微博', tieba: '贴吧', zhihu: '知乎' }
const crawlerPlatformLabel = (p) => CRAWLER_PLATFORM_MAP[p] || p

const CRAWLER_JOB_STATUS_MAP = {
  pending: { label: '待执行', type: 'info' },
  queued: { label: '排队中', type: 'info' },
  running: { label: '执行中', type: 'primary' },
  succeeded: { label: '已完成', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' },
}
const crawlerJobStatusLabel = (s) => CRAWLER_JOB_STATUS_MAP[s]?.label || s
const crawlerJobTagType = (s) => CRAWLER_JOB_STATUS_MAP[s]?.type || 'info'

async function loadSocialStats() {
  try {
    const res = await request.get('/social/publish/tasks', { params: { page_size: 100 } })
    const tasks = res.data || []
    socialStats.value = {
      total: res.pagination?.total || tasks.length,
      published: tasks.filter(t => t.status === 'published').length,
      running: tasks.filter(t => t.status === 'running' || t.status === 'queued').length,
      failed: tasks.filter(t => t.status === 'failed').length,
      recent: tasks.slice(0, 5),
    }
  } catch (e) {
    console.warn('loadSocialStats failed', e)
  }
}

async function loadCrawlerStats() {
  try {
    const res = await request.get('/crawler/jobs', { params: { page_size: 100 } })
    const jobs = res.data || []
    crawlerStats.value = {
      total: res.pagination?.total || jobs.length,
      completed: jobs.filter(j => j.status === 'succeeded').length,
      running: jobs.filter(j => j.status === 'running' || j.status === 'pending' || j.status === 'queued').length,
      items: jobs.reduce((sum, j) => sum + (j.items_count || 0), 0),
      recent: jobs.slice(0, 5),
    }
  } catch (e) {
    console.warn('loadCrawlerStats failed', e)
  }
}

async function fetchDashboardStats() {
  try {
    const res = await request.get('/dashboard/social/stats', { params: { days: dashboardDays.value } })
    dashboardStats.value = res.data || {}
  } catch (e) {
    console.error('Failed to fetch dashboard stats:', e)
  }
}

onMounted(async () => {
  await Promise.all([loadAccounts(), loadOverview(), loadOperations(), loadTrend(), loadPendingAndRisk(), fetchDashboardStats(), loadSocialStats(), loadCrawlerStats()])
})
</script>

<style scoped>
.dashboard { padding: 0; }
.page-header { margin-bottom: 20px; }
.page-header h2 { margin: 0 0 4px; font-size: 24px; font-weight: 800; letter-spacing: -0.02em; }
.page-sub { color: var(--color-ink-tertiary); font-size: 13px; }
.card-row { margin-bottom: 16px; }
.operations-card { margin-bottom: 16px; }
.operations-alerts { display: grid; gap: 8px; margin-top: 14px; }
.operations-ok { margin-top: 14px; padding: 10px 12px; border-radius: 10px; color: #15803d; background: #f0fdf4; font-size: 13px; }

/* 快捷入口 */
.dash-guide { margin-bottom: 16px; padding: 14px 18px; background: var(--color-surface, #fff); border: 1px solid var(--color-border, #e2e8f0); border-radius: var(--radius-lg, 14px); box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
.guide-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.guide-label { font-size: 13px; font-weight: 600; color: var(--color-ink-secondary); margin-right: 4px; }
.guide-tip { color: var(--color-ink-tertiary); font-size: 12px; margin-left: 8px; }

/* 全空引导 */
.empty-hero { margin-bottom: 16px; padding: 24px 0; }
.empty-hero-actions { display: flex; gap: 10px; justify-content: center; }

/* stat-card 玻璃发光卡片 */
.stat-card {
  position: relative;
  padding: 22px 18px;
  border-radius: var(--radius-lg);
  background: var(--color-surface, #fff);
  border: 1px solid var(--color-border, #e2e8f0);
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 110px;
}
.stat-card::before {
  content: "";
  position: absolute;
  top: 0; left: 0; right: 0; height: 3px;
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
}
.stat-card--blue::before    { background: linear-gradient(90deg, #0f6bc5, #3b9eff); }
.stat-card--green::before   { background: linear-gradient(90deg, #0d9668, #10b981); }
.stat-card--amber::before   { background: linear-gradient(90deg, #d97706, #f59e0b); }
.stat-card--purple::before  { background: linear-gradient(90deg, #8b5cf6, #ec4899); }
.stat-value { font-size: 32px; font-weight: 800; letter-spacing: -0.02em; line-height: 1.15; position: relative; z-index: 1; }
.stat-card--blue .stat-value    { color: var(--color-accent); }
.stat-card--green .stat-value   { color: var(--color-success); }
.stat-card--amber .stat-value   { color: var(--color-warning); }
.stat-card--purple .stat-value  { color: #8b5cf6; }
.stat-label { color: var(--color-ink-tertiary); font-size: 13px; margin-top: 6px; font-weight: 500; position: relative; z-index: 1; }

.card-title { font-weight: 600; font-size: 15px; color: var(--color-ink); }
.card-head { display: flex; justify-content: space-between; align-items: center; }

/* panel-card header */
.panel-card { border-radius: var(--radius-lg); }
.panel-card__header { padding: 14px 18px; border-bottom: 1px solid var(--color-border-light); color: var(--color-ink); }

/* 迷你统计 */
.mini-stat { text-align: center; }
.mini-value { font-size: 26px; font-weight: 800; color: var(--color-accent); letter-spacing: -0.02em; }
.mini-value--warning { color: var(--color-warning); }
.mini-value--success { color: var(--color-success); }
.mini-value--info { color: var(--color-info); }
.mini-value--danger { color: var(--color-danger); }
.mini-value--muted { color: var(--color-ink-tertiary); }
.mini-label { color: var(--color-ink-tertiary); font-size: 12px; margin-top: 4px; font-weight: 500; }

.funnel-row { display: grid; grid-template-columns: 72px 1fr; align-items: center; gap: 12px; }
.funnel-label { white-space: nowrap; color: var(--color-ink-tertiary); font-size: 13px; font-weight: 500; }

/* 趋势条形图 */
.bar-cell { display: flex; align-items: center; gap: 8px; }
.bar-num { width: 28px; text-align: right; font-size: 13px; color: var(--color-ink-secondary); font-weight: 600; }
.bar-bg { flex: 1; height: 16px; background: var(--color-surface-subtle); border-radius: var(--radius-md); overflow: hidden; }
.bar-fill { height: 100%; border-radius: var(--radius-md); transition: width 0.6s cubic-bezier(0.22,1,0.36,1); }
.bar-leads { background: linear-gradient(90deg, #0f6bc5, #3b9eff); }
.bar-contents { background: linear-gradient(90deg, #d97706, #f59e0b); }

/* 待审核任务列表 */
.task-list { display: flex; flex-direction: column; gap: 6px; max-height: 320px; overflow: auto; }
.task-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
  border: 1px solid transparent;
}
.task-item:hover { background: rgba(15,107,197,0.06); border-color: rgba(59, 158, 255, 0.3); transform: translateX(3px); }
.task-item-title { font-size: 14px; font-weight: 500; color: var(--color-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 220px; }
.task-item-sub { font-size: 12px; color: var(--color-ink-tertiary); margin-top: 2px; }
.task-item-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }

@media (max-width: 768px) {
  .page-header { margin-bottom: 14px; }
  .page-header h2 { font-size: 22px; }
  .dash-guide { padding: 12px; }
  .guide-label, .guide-tip { width: 100%; margin-left: 0; }

  .card-row { margin-bottom: 4px; }
  .card-row > .el-col {
    flex: 0 0 100%;
    max-width: 100%;
    margin-bottom: 12px;
  }
  .core-stat-row > .el-col {
    flex: 0 0 50%;
    max-width: 50%;
  }
  .stat-card { min-height: 92px; padding: 18px 14px; }
  .stat-value { font-size: 28px; }
  .stat-label { white-space: nowrap; }

  .panel-card > .el-row > .el-col {
    flex: 0 0 50%;
    max-width: 50%;
    margin-bottom: 12px;
  }
  .card-head { align-items: flex-start; flex-direction: column; gap: 10px; }
  .mini-label { white-space: nowrap; }
  .empty-hero-actions { flex-wrap: wrap; }
}
</style>
