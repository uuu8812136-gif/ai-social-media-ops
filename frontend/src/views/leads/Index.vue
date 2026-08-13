<template>
  <div class="leads-page">
    <div class="page-header">
      <div>
        <h2>线索管理</h2>
        <span class="page-sub">线索三池管理 · 自动/手动分配 · 跟进记录</span>
      </div>
      <el-button type="primary" @click="showDialog = true">录入线索</el-button>
    </div>

    <div class="page-guide">线索流程：录入线索 → 自动/手动分配经销商 → 经销商跟进（联系/量房/报价/签单）。点击线索行可查看详情和添加跟进记录。</div>

    <!-- 统计卡片 -->
    <el-row :gutter="16" style="margin-bottom:16px">
      <el-col :span="6"><div class="panel-card stat-card"><div class="stat-value">{{ stats.total || 0 }}</div><div class="stat-label">总线索</div></div></el-col>
      <el-col :span="6"><div class="panel-card stat-card stat-card--blue"><div class="stat-value">{{ stats.assigned || 0 }}</div><div class="stat-label">已分配</div></div></el-col>
      <el-col :span="6"><div class="panel-card stat-card stat-card--green"><div class="stat-value">{{ stats.signed || 0 }}</div><div class="stat-label">已签单</div></div></el-col>
      <el-col :span="6"><div class="panel-card stat-card stat-card--orange"><div class="stat-value">{{ stats.conversion_rate || 0 }}%</div><div class="stat-label">转化率</div></div></el-col>
    </el-row>

    <!-- 三池 + 状态筛选 -->
    <div class="filter-bar">
      <el-radio-group v-model="filter.pool_type" @change="onFilterChange">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="consumer">C 端池</el-radio-button>
        <el-radio-button value="franchise">招商池</el-radio-button>
        <el-radio-button value="local">同城池</el-radio-button>
      </el-radio-group>
      <el-select v-model="filter.status" placeholder="状态筛选" clearable style="width:160px" @change="onFilterChange">
        <el-option v-for="(v, k) in STATUS_MAP" :key="k" :label="v.label" :value="k" />
      </el-select>
      <el-button @click="loadLeads">刷新</el-button>
    </div>

    <!-- 线索列表 -->
    <el-table :data="leads" v-loading="loading" style="margin-top:12px" @row-click="openDetail">
      <el-table-column label="客户" width="120">
        <template #default="{ row }">
          <div>{{ row.customer_name }}</div>
          <div class="phone-masked">{{ row.customer_phone_masked || '****' }}</div>
        </template>
      </el-table-column>
      <el-table-column label="线索池" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="poolTagType(row.pool_type)">{{ poolLabel(row.pool_type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="130">
        <template #default="{ row }">
          <el-tag size="small" :type="STATUS_MAP[row.status]?.type || 'info'">{{ STATUS_MAP[row.status]?.label || row.status }}</el-tag>
          <el-tag v-if="isTimeout(row)" size="small" type="danger" effect="dark" style="margin-left:4px">超时</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="分配经销商" width="160">
        <template #default="{ row }">
          <span v-if="row.assigned_dealer_id">{{ dealerName(row.assigned_dealer_id) }}</span>
          <el-tag v-else size="small" type="info">未分配</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="requirement" label="需求" min-width="180" show-overflow-tooltip />
      <el-table-column label="分配时间" width="190" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.assigned_at" style="white-space:nowrap">{{ formatTime(row.assigned_at) }}</span>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button link size="small" type="primary" @click.stop="openDetail(row)">详情</el-button>
          <el-button v-if="row.status === 'pending'" link size="small" @click.stop="autoAssign(row.id)">自动分配</el-button>
          <el-button v-if="row.status === 'pending'" link size="small" @click.stop="openAssign(row)">手动分配</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-if="total > filter.page_size"
      style="margin-top:12px;justify-content:flex-end;display:flex"
      background
      layout="prev, pager, next"
      :total="total"
      :page-size="filter.page_size"
      :current-page="filter.page"
      @current-change="onPageChange"
    />

    <!-- 录入线索弹窗 -->
    <el-dialog v-model="showDialog" title="录入线索" width="500px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="线索池">
          <el-select v-model="form.pool_type" style="width:100%">
            <el-option label="C 端池" value="consumer" />
            <el-option label="招商池" value="franchise" />
            <el-option label="同城池" value="local" />
          </el-select>
        </el-form-item>
        <el-form-item label="客户姓名"><el-input v-model="form.customer_name" /></el-form-item>
        <el-form-item label="联系电话"><el-input v-model="form.customer_phone" placeholder="手机号、座机或国际号码" /></el-form-item>
        <el-form-item label="需求"><el-input v-model="form.requirement" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" @click="createLead">确定</el-button>
      </template>
    </el-dialog>

    <!-- 手动分配弹窗 -->
    <el-dialog v-model="assignVisible" title="手动分配经销商" width="440px">
      <el-select v-model="assignDealerId" placeholder="选择经销商" filterable style="width:100%">
        <el-option v-for="d in dealers" :key="d.id" :label="`${d.company_name}（${d.level}级）`" :value="d.id" />
      </el-select>
      <template #footer>
        <el-button @click="assignVisible = false">取消</el-button>
        <el-button type="primary" @click="manualAssign">确认分配</el-button>
      </template>
    </el-dialog>

    <!-- 线索详情抽屉 -->
    <el-drawer v-model="detailVisible" title="线索详情" size="520px" @open="loadFollowups">
      <div v-if="current" class="detail-content">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="客户姓名">{{ current.customer_name }}</el-descriptions-item>
          <el-descriptions-item label="联系电话">{{ current.customer_phone_masked || '****' }}</el-descriptions-item>
          <el-descriptions-item label="线索池">
            <el-tag size="small" :type="poolTagType(current.pool_type)">{{ poolLabel(current.pool_type) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag size="small" :type="STATUS_MAP[current.status]?.type || 'info'">{{ STATUS_MAP[current.status]?.label || current.status }}</el-tag>
            <el-tag v-if="isTimeout(current)" size="small" type="danger" effect="dark" style="margin-left:6px">超时未跟进</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="分配经销商">
            <span v-if="current.assigned_dealer_id">{{ dealerName(current.assigned_dealer_id) }}</span>
            <span v-else style="color:var(--color-ink-tertiary)">未分配</span>
          </el-descriptions-item>
          <el-descriptions-item label="分配时间">{{ current.assigned_at ? formatTime(current.assigned_at) : '—' }}</el-descriptions-item>
          <el-descriptions-item label="需求">{{ current.requirement || '—' }}</el-descriptions-item>
          <el-descriptions-item v-if="current.signed_amount" label="签单金额">¥{{ current.signed_amount }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatTime(current.created_at) }}</el-descriptions-item>
        </el-descriptions>

        <!-- 分配操作 -->
        <div v-if="current.status === 'pending'" class="detail-actions">
          <el-button size="small" type="primary" @click="autoAssign(current.id); detailVisible = false">自动分配</el-button>
          <el-button size="small" @click="openAssign(current)">手动分配</el-button>
        </div>

        <!-- 添加跟进 -->
        <div class="followup-add">
          <div class="section-title">添加跟进记录</div>
          <el-form :model="followupForm" label-width="70px" size="small">
            <el-form-item label="动作">
              <el-select v-model="followupForm.action" style="width:100%">
                <el-option label="已联系" value="contacted" />
                <el-option label="已预约量房" value="appointment_measured" />
                <el-option label="已量房" value="measured" />
                <el-option label="已报价" value="quoted" />
                <el-option label="已签单" value="signed" />
                <el-option label="已流失" value="lost" />
              </el-select>
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="followupForm.note" type="textarea" :rows="2" placeholder="如：签单金额 2.5 万" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" size="small" @click="addFollowup">提交跟进</el-button>
            </el-form-item>
          </el-form>
        </div>

        <!-- 跟进时间线 -->
        <div class="followup-timeline">
          <div class="section-title">跟进时间线</div>
          <el-empty v-if="!followups.length" description="暂无跟进记录" :image-size="60" />
          <el-timeline v-else>
            <el-timeline-item
              v-for="f in followups"
              :key="f.id"
              :timestamp="formatTime(f.created_at)"
              :type="STATUS_MAP[f.action]?.type || 'primary'"
            >
              <div class="timeline-action">
                <el-tag size="small" :type="STATUS_MAP[f.action]?.type || 'primary'">{{ STATUS_MAP[f.action]?.label || f.action }}</el-tag>
                <span class="timeline-operator">{{ f.operator }}</span>
              </div>
              <div v-if="f.note" class="timeline-note">{{ f.note }}</div>
            </el-timeline-item>
          </el-timeline>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import request from '../../utils/request'

const loading = ref(false)
const leads = ref([])
const total = ref(0)
const stats = ref({})
const dealers = ref([])
const dealerMap = ref({})
const showDialog = ref(false)
const detailVisible = ref(false)
const assignVisible = ref(false)
const current = ref(null)
const followups = ref([])
const assignDealerId = ref('')
const assignLeadId = ref('')

const filter = reactive({ page: 1, page_size: 20, pool_type: '', status: '' })
const form = reactive({ pool_type: 'consumer', customer_name: '', customer_phone: '', requirement: '' })
const followupForm = reactive({ action: 'contacted', note: '' })

const STATUS_MAP = {
  pending: { label: '待分配', type: 'info' },
  assigned: { label: '已分配', type: 'primary' },
  contacted: { label: '已联系', type: 'primary' },
  appointment_measured: { label: '已预约', type: 'primary' },
  measured: { label: '已量房', type: 'primary' },
  quoted: { label: '已报价', type: 'warning' },
  signed: { label: '已签单', type: 'success' },
  lost: { label: '已流失', type: 'danger' },
}

const POOL_MAP = {
  consumer: { label: 'C 端池', type: 'primary' },
  franchise: { label: '招商池', type: 'warning' },
  local: { label: '同城池', type: 'success' },
}
const poolLabel = (p) => POOL_MAP[p]?.label || p
const poolTagType = (p) => POOL_MAP[p]?.type || 'info'
const dealerName = (id) => dealerMap.value[id] || '—'
const formatTime = (t) => {
  if (!t) return '—'
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function isTimeout(row) {
  if (row.status !== 'assigned' || !row.assigned_at) return false
  return Date.now() - new Date(row.assigned_at).getTime() > 3600000
}

async function loadDealers() {
  const res = await request.get('/dealers/', { params: { page_size: 100 } })
  dealers.value = res.data || []
  dealerMap.value = Object.fromEntries(dealers.value.map((d) => [d.id, d.company_name]))
}

function onFilterChange() {
  filter.page = 1
  loadLeads()
}

async function loadLeads() {
  loading.value = true
  try {
    const params = { page: filter.page, page_size: filter.page_size }
    if (filter.pool_type) params.pool_type = filter.pool_type
    if (filter.status) params.status = filter.status
    const res = await request.get('/leads/', { params })
    leads.value = res.data || []
    total.value = res.pagination?.total || 0
  } finally { loading.value = false }
}

async function loadStats() {
  const res = await request.get('/leads/stats')
  stats.value = res.data
}

async function createLead() {
  if (!form.customer_name) return ElMessage.warning('请填写客户姓名')
  if (!form.customer_phone) return ElMessage.warning('请填写联系电话')
  if (!/^\+?[0-9 -]{7,20}$/.test(form.customer_phone)) return ElMessage.warning('请输入有效联系电话')
  await request.post('/leads/', form)
  ElMessage.success('线索已录入，可进行分配操作')
  showDialog.value = false
  form.customer_name = ''
  form.customer_phone = ''
  form.requirement = ''
  loadLeads()
  loadStats()
}

async function autoAssign(id) {
  await request.post(`/leads/${id}/auto-assign`)
  ElMessage.success('已自动分配')
  loadLeads()
  loadStats()
}

function openAssign(row) {
  assignLeadId.value = row.id
  assignDealerId.value = ''
  assignVisible.value = true
}

async function manualAssign() {
  if (!assignDealerId.value) return ElMessage.warning('请选择经销商')
  await request.post(`/leads/${assignLeadId.value}/assign`, { dealer_id: assignDealerId.value })
  ElMessage.success('已手动分配')
  assignVisible.value = false
  loadLeads()
  loadStats()
}

function openDetail(row) {
  current.value = row
  detailVisible.value = true
}

async function loadFollowups() {
  if (!current.value) return
  const res = await request.get(`/leads/${current.value.id}/followups`)
  followups.value = res.data || []
}

async function addFollowup() {
  if (!current.value) return
  await request.post(`/leads/${current.value.id}/followups`, followupForm)
  ElMessage.success('跟进记录已添加')
  followupForm.note = ''
  loadFollowups()
  loadLeads()
  loadStats()
  const res = await request.get(`/leads/${current.value.id}`)
  current.value = res.data
}

function onPageChange(p) {
  filter.page = p
  loadLeads()
}

onMounted(async () => {
  await Promise.all([loadDealers(), loadLeads(), loadStats()])
})
</script>

<style scoped>
.leads-page { padding: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h2 { margin: 0; font-size: 22px; font-weight: 700; color: var(--color-ink); }
.page-guide { margin-bottom: 16px; padding: 10px 14px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md); font-size: 13px; color: var(--color-ink-secondary); line-height: 1.6; }

/* 统一 panel-card + stat-card 彩色变体 */
.panel-card { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: 16px; box-shadow: var(--shadow-xs); transition: box-shadow var(--transition-base); }
.panel-card:hover { box-shadow: var(--shadow-sm); transform: none; }
.stat-card { text-align: center; transition: box-shadow var(--transition-base); display: flex; flex-direction: column; justify-content: center; min-height: 110px; position: relative; }
.stat-card:hover { box-shadow: var(--shadow-sm); transform: none; }
.stat-value { font-size: 28px; font-weight: 800; color: var(--color-accent); letter-spacing: -0.02em; position: relative; z-index: 1; }
.stat-label { color: var(--color-ink-tertiary); margin-top: 6px; font-size: 13px; font-weight: 500; position: relative; z-index: 1; }
.stat-card--blue { background: linear-gradient(135deg, rgba(59,130,246,0.08), rgba(59,130,246,0.02)); }
.stat-card--blue .stat-value { color: var(--color-primary, #409eff); }
.stat-card--green { background: linear-gradient(135deg, rgba(34,197,94,0.08), rgba(34,197,94,0.02)); }
.stat-card--green .stat-value { color: var(--color-success, #67c23a); }
.stat-card--orange { background: linear-gradient(135deg, rgba(245,158,11,0.08), rgba(245,158,11,0.02)); }
.stat-card--orange .stat-value { color: var(--color-warning, #e6a23c); }

.filter-bar { display: flex; gap: 12px; align-items: center; }
.phone-masked { font-size: 12px; color: var(--color-ink-tertiary); }
.detail-content { padding: 0 4px; }
.detail-actions { margin: 16px 0; display: flex; gap: 8px; }
.section-title { font-weight: 600; margin: 16px 0 10px; font-size: 14px; color: var(--color-ink); }
.followup-add { background: var(--color-surface-subtle); padding: 12px; border-radius: var(--radius-md); }
.followup-timeline { margin-top: 8px; }
.timeline-action { display: flex; align-items: center; gap: 8px; }
.timeline-operator { font-size: 12px; color: var(--color-ink-tertiary); }
.timeline-note { margin-top: 4px; font-size: 13px; color: var(--color-ink-secondary); }
</style>
