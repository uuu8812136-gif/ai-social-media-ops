<template>
  <div class="dealers-page">
    <div class="page-header">
      <div>
        <h2>经销商管理</h2>
        <span class="page-sub">经销商信息 · 等级管理 · 线索分配对象</span>
      </div>
      <el-button type="primary" @click="openCreate">新增经销商</el-button>
    </div>

    <div class="page-guide">经销商是线索分配的接收方。新增经销商后，在"线索管理"中可将线索分配给对应经销商。支持 A/B/C 三个等级。</div>

    <div class="filter-bar">
      <el-select v-model="filter.level" placeholder="等级筛选" clearable style="width:120px" @change="load">
        <el-option label="A级" value="A" />
        <el-option label="B级" value="B" />
        <el-option label="C级" value="C" />
      </el-select>
      <el-select v-model="filter.status" placeholder="状态筛选" clearable style="width:120px" @change="load">
        <el-option label="合作中" value="active" />
        <el-option label="已暂停" value="paused" />
        <el-option label="已停用" value="disabled" />
      </el-select>
      <el-button @click="load">刷新</el-button>
    </div>

    <el-table :data="dealers" v-loading="loading" style="margin-top:12px">
      <el-table-column prop="company_name" label="公司名称" min-width="180" />
      <el-table-column prop="contact_name" label="联系人" width="100" />
      <el-table-column label="联系电话" width="140">
        <template #default="{ row }">
          <span>{{ row.contact_phone_masked || maskPhone(row.contact_phone) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="城市" width="100">
        <template #default="{ row }">
          <span>{{ cityName(row.city_id) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="等级" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="levelTagType(row.level)">{{ row.level }}级</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="wecom_id" label="企微ID" width="120" show-overflow-tooltip>
        <template #default="{ row }">{{ row.wecom_id || '—' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button link size="small" type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link size="small" @click="viewStats(row)">数据</el-button>
          <el-dropdown trigger="click" @command="(cmd) => handleDealerCmd(cmd, row)">
            <el-button link size="small">更多<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="leads">线索</el-dropdown-item>
                <el-dropdown-item v-if="row.status === 'active'" command="pause">暂停</el-dropdown-item>
                <el-dropdown-item v-if="row.status === 'paused'" command="enable">启用</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新增/编辑弹窗 -->
    <el-dialog v-model="showDialog" :title="editingId ? '编辑经销商' : '新增经销商'" width="560px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="公司名称"><el-input v-model="form.company_name" /></el-form-item>
        <el-form-item label="联系人"><el-input v-model="form.contact_name" /></el-form-item>
        <el-form-item label="联系电话"><el-input v-model="form.contact_phone" /></el-form-item>
        <el-form-item label="城市">
          <el-select v-model="form.city_id" placeholder="选择城市" style="width:100%">
            <el-option v-for="c in cities" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="等级">
          <el-select v-model="form.level" style="width:100%">
            <el-option label="A级（深度合作）" value="A" />
            <el-option label="B级（标准合作）" value="B" />
            <el-option label="C级（基础合作）" value="C" />
          </el-select>
        </el-form-item>
        <el-form-item label="企微ID"><el-input v-model="form.wecom_id" placeholder="选填" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>

    <!-- 数据弹窗 -->
    <el-dialog v-model="statsVisible" title="经销商运营数据" width="520px">
      <div v-if="stats" class="stats-content">
        <el-row :gutter="16">
          <el-col :span="8">
            <div class="mini-stat">
              <div class="mini-value">{{ stats.total_leads || 0 }}</div>
              <div class="mini-label">总线索</div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="mini-stat mini-stat--green">
              <div class="mini-value">{{ stats.signed_count || 0 }}</div>
              <div class="mini-label">已签单</div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="mini-stat mini-stat--orange">
              <div class="mini-value">{{ stats.signing_rate || 0 }}%</div>
              <div class="mini-label">签单率</div>
            </div>
          </el-col>
        </el-row>
        <div v-if="stats.status_breakdown" style="margin-top:16px">
          <div v-for="(count, status) in stats.status_breakdown" :key="status" class="stat-row">
            <span class="stat-row-label">{{ statusLabel(status) }}</span>
            <el-progress :percentage="stats.total_leads ? Math.round(count / stats.total_leads * 100) : 0" :stroke-width="14" />
            <span class="stat-row-count">{{ count }}</span>
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 线索弹窗 -->
    <el-dialog v-model="leadsVisible" title="经销商线索列表" width="700px">
      <el-table :data="dealerLeads" size="small">
        <el-table-column prop="customer_name" label="客户" width="100" />
        <el-table-column label="电话" width="120">
          <template #default="{ row }">{{ row.customer_phone_masked || '****' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="requirement" label="需求" min-width="180" show-overflow-tooltip />
        <el-table-column label="创建时间" width="190" show-overflow-tooltip>
          <template #default="{ row }"><span style="white-space:nowrap">{{ formatTime(row.created_at) }}</span></template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import request from '../../utils/request'

const loading = ref(false)
const dealers = ref([])
const cities = ref([])
const cityMap = ref({})
const showDialog = ref(false)
const editingId = ref(null)
const statsVisible = ref(false)
const stats = ref(null)
const leadsVisible = ref(false)
const dealerLeads = ref([])

const filter = reactive({ level: '', status: '' })
const form = reactive({ company_name: '', contact_name: '', contact_phone: '', city_id: '', level: 'C', wecom_id: '' })

const STATUS_MAP = {
  active: { label: '合作中', type: 'success' },
  paused: { label: '已暂停', type: 'warning' },
  disabled: { label: '已停用', type: 'danger' },
}

const statusLabel = (s) => STATUS_MAP[s]?.label || s
const statusTagType = (s) => STATUS_MAP[s]?.type || 'info'
const levelTagType = (l) => ({ A: 'danger', B: 'warning', C: 'info' }[l] || 'info')
const cityName = (id) => cityMap.value[id] || '—'
const maskPhone = (p) => p ? p.slice(0, 3) + '****' + p.slice(-4) : '—'
const formatTime = (t) => {
  if (!t) return '—'
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function loadCities() {
  const res = await request.get('/leads/cities')
  cities.value = res.data || []
  cityMap.value = Object.fromEntries(cities.value.map(c => [c.id, c.name]))
}

async function load() {
  loading.value = true
  try {
    const params = { page_size: 100 }
    if (filter.level) params.level = filter.level
    if (filter.status) params.status = filter.status
    const res = await request.get('/dealers/', { params })
    dealers.value = res.data || []
  } finally { loading.value = false }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { company_name: '', contact_name: '', contact_phone: '', city_id: cities.value[0]?.id || '', level: 'C', wecom_id: '' })
  showDialog.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    company_name: row.company_name,
    contact_name: row.contact_name,
    contact_phone: row.contact_phone || '',
    city_id: row.city_id,
    level: row.level,
    wecom_id: row.wecom_id || '',
  })
  showDialog.value = true
}

async function submitForm() {
  if (!form.company_name) return ElMessage.warning('请输入公司名称')
  if (editingId.value) {
    await request.put(`/dealers/${editingId.value}`, form)
    ElMessage.success('经销商已更新')
  } else {
    await request.post('/dealers/', form)
    ElMessage.success('经销商已创建')
  }
  showDialog.value = false
  load()
}

async function toggleStatus(row, status) {
  await ElMessageBox.confirm(`确认${status === 'paused' ? '暂停' : '启用'}经销商"${row.company_name}"？`, '状态变更')
  await request.put(`/dealers/${row.id}`, { status })
  ElMessage.success(`状态已更新：${statusLabel(status)}`)
  load()
}

async function viewStats(row) {
  const res = await request.get(`/dealers/${row.id}/stats`)
  stats.value = res.data
  statsVisible.value = true
}

function handleDealerCmd(cmd, row) {
  if (cmd === 'leads') viewLeads(row)
  else if (cmd === 'pause') toggleStatus(row, 'paused')
  else if (cmd === 'enable') toggleStatus(row, 'active')
}

async function viewLeads(row) {
  const res = await request.get(`/dealers/${row.id}/leads`)
  dealerLeads.value = res.data || []
  leadsVisible.value = true
}

onMounted(async () => {
  await loadCities()
  load()
})
</script>

<style scoped>
.dealers-page { padding: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.page-header h2 { margin: 0; font-size: 22px; font-weight: 700; color: var(--color-ink); }
.page-sub { color: var(--color-ink-tertiary); font-size: 13px; }
.page-guide { margin-bottom: 12px; padding: 10px 14px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md); font-size: 13px; color: var(--color-ink-secondary); line-height: 1.6; }
.filter-bar { display: flex; gap: 12px; align-items: center; margin-bottom: 8px; }
.stats-content { padding: 8px 0; }
.mini-stat { text-align: center; }
.mini-value { font-size: 24px; font-weight: 800; color: var(--color-accent); }
.mini-label { color: var(--color-ink-tertiary); font-size: 13px; margin-top: 4px; }
.mini-stat--green .mini-value { color: var(--color-success); }
.mini-stat--orange .mini-value { color: var(--color-warning); }
.stat-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.stat-row-label { width: 100px; font-size: 13px; color: var(--color-ink-secondary); }
.stat-row-count { width: 40px; text-align: right; font-size: 13px; color: var(--color-ink-tertiary); }
</style>
