<template>
  <div class="calendar-page">
    <div class="page-header">
      <div>
        <h2>内容日历</h2>
        <span class="page-sub">内容排期 · 发布提醒 · 日历视图</span>
      </div>
      <el-button type="primary" @click="openCreate">新增排期</el-button>
    </div>

    <div class="page-guide">在内容工厂审核通过后，可在此创建排期。选择账号和日期，设置发布时间，系统会在排期日发送发布提醒。</div>

    <!-- 月历视图 -->
    <div class="calendar-toolbar">
      <el-button @click="prevMonth">&lt;</el-button>
      <span class="month-label">{{ currentYear }}年{{ currentMonth }}月</span>
      <el-button @click="nextMonth">&gt;</el-button>
      <el-radio-group v-model="viewMode" size="small" style="margin-left:16px">
        <el-radio-button value="calendar">日历</el-radio-button>
        <el-radio-button value="list">列表</el-radio-button>
      </el-radio-group>
    </div>

    <!-- 日历模式 -->
    <div v-if="viewMode === 'calendar'" class="calendar-grid">
      <div class="calendar-header">
        <div v-for="d in weekDays" :key="d" class="calendar-header-cell">{{ d }}</div>
      </div>
      <div class="calendar-body">
        <div v-for="(day, idx) in calendarDays" :key="idx" class="calendar-cell" :class="{ 'other-month': !day.current, 'today': day.isToday }">
          <div class="cell-date">{{ day.day }}</div>
          <div class="cell-items">
            <div v-for="item in day.items" :key="item.id" class="cell-item" :class="`status-${item.publish_status}`" @click="viewItem(item)">
              <span class="cell-item-time">{{ item.scheduled_time || '' }}</span>
              {{ item.account_name || '未关联' }} - {{ item.publish_status_label }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 列表模式 -->
    <el-table v-else :data="items" v-loading="loading" style="margin-top:12px">
      <el-table-column label="日期" width="120">
        <template #default="{ row }">{{ row.scheduled_date }}</template>
      </el-table-column>
      <el-table-column label="时间" width="100">
        <template #default="{ row }">{{ row.scheduled_time || '—' }}</template>
      </el-table-column>
      <el-table-column label="账号" width="160">
        <template #default="{ row }">{{ accountName(row.account_id) }}</template>
      </el-table-column>
      <el-table-column label="内容" min-width="200">
        <template #default="{ row }">{{ row.content_title || row.content_id || '待排期' }}</template>
      </el-table-column>
      <el-table-column label="发布状态" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="publishStatusType(row.publish_status)">{{ publishStatusLabel(row.publish_status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="提醒" width="80">
        <template #default="{ row }">
          <el-tag v-if="row.remind_sent" size="small" type="success">已发</el-tag>
          <el-tag v-else size="small" type="info">未发</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="170" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.publish_status === 'pending'" link size="small" type="success" @click="markStatus(row, 'published')">标记已发布</el-button>
          <el-dropdown trigger="click" @command="(cmd) => handleCalendarCmd(cmd, row)">
            <el-button link size="small">更多<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-if="row.publish_status === 'pending'" command="skip">跳过</el-dropdown-item>
                <el-dropdown-item command="remind">发送提醒</el-dropdown-item>
                <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新增排期弹窗 -->
    <el-dialog v-model="showDialog" title="新增排期" width="520px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="账号">
          <el-select v-model="form.account_id" placeholder="选择账号" filterable style="width:100%">
            <el-option v-for="a in accounts" :key="a.id" :label="accountLabel(a)" :value="a.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="日期">
          <el-date-picker v-model="form.scheduled_date" type="date" value-format="YYYY-MM-DD" style="width:100%" />
        </el-form-item>
        <el-form-item label="时间">
          <el-time-picker v-model="form.scheduled_time" format="HH:mm" value-format="HH:mm" placeholder="选择时间" style="width:100%" />
        </el-form-item>
        <el-form-item label="内容ID"><el-input v-model="form.content_id" placeholder="选填，关联已有内容" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" @click="createItem">确定</el-button>
      </template>
    </el-dialog>

    <!-- 日历项详情弹窗 -->
    <el-dialog v-model="itemDetailVisible" title="排期详情" width="480px">
      <div v-if="itemDetail" class="item-detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="日期">{{ itemDetail.scheduled_date }}</el-descriptions-item>
          <el-descriptions-item label="时间">{{ itemDetail.scheduled_time || '—' }}</el-descriptions-item>
          <el-descriptions-item label="账号">{{ accountName(itemDetail.account_id) }}</el-descriptions-item>
          <el-descriptions-item label="发布状态">
            <el-tag size="small" :type="publishStatusType(itemDetail.publish_status)">{{ publishStatusLabel(itemDetail.publish_status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="提醒">{{ itemDetail.remind_sent ? '已发送' : '未发送' }}</el-descriptions-item>
        </el-descriptions>
        <div style="margin-top:12px;display:flex;gap:8px">
          <el-button v-if="itemDetail.publish_status === 'pending'" size="small" type="success" @click="markStatus(itemDetail, 'published'); itemDetailVisible = false">标记已发布</el-button>
          <el-button v-if="itemDetail.publish_status === 'pending'" size="small" @click="markStatus(itemDetail, 'skipped'); itemDetailVisible = false">跳过</el-button>
          <el-button size="small" @click="sendRemind(itemDetail)">发送提醒</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import request from '../../utils/request'

const loading = ref(false)
const items = ref([])
const accounts = ref([])
const accountMap = ref({})
const showDialog = ref(false)
const itemDetailVisible = ref(false)
const itemDetail = ref(null)
const viewMode = ref('calendar')
const currentYear = ref(new Date().getFullYear())
const currentMonth = ref(new Date().getMonth() + 1)

const form = reactive({ account_id: '', scheduled_date: '', scheduled_time: '', content_id: '' })

const weekDays = ['一', '二', '三', '四', '五', '六', '日']

const PUBLISH_STATUS = {
  pending: { label: '待发布', type: 'warning' },
  published: { label: '已发布', type: 'success' },
  skipped: { label: '已跳过', type: 'info' },
  failed: { label: '发布失败', type: 'danger' },
}

const publishStatusLabel = (s) => PUBLISH_STATUS[s]?.label || s
const publishStatusType = (s) => PUBLISH_STATUS[s]?.type || 'info'
const accountName = (id) => accountMap.value[id] || '—'
const platformLabel = (p) => ({ xiaohongshu: '小红书', channels: '视频号', douyin: '抖音', kuaishou: '快手', bilibili: 'B站' }[p] || p)
const accountLabel = (a) => `${a.account_name}（${platformLabel(a.platform)}）`

async function loadAccounts() {
  const res = await request.get('/social/accounts/', { params: { page_size: 100, status: 'active' } })
  accounts.value = (res.data || []).map((a) => ({
    ...a,
    account_name: a.nickname || a.user_info?.name || a.user_info?.username || a.platform_uid || platformLabel(a.platform),
  }))
  accountMap.value = Object.fromEntries(accounts.value.map(a => [a.id, a.account_name]))
}

async function load() {
  loading.value = true
  try {
    const res = await request.get('/calendar/', { params: { page_size: 100 } })
    items.value = (res.data || []).map(item => ({
      ...item,
      account_name: accountName(item.account_id),
      publish_status_label: publishStatusLabel(item.publish_status),
    }))
  } finally { loading.value = false }
}

const calendarDays = computed(() => {
  const y = currentYear.value
  const m = currentMonth.value
  const firstDay = new Date(y, m - 1, 1)
  const lastDay = new Date(y, m, 0)
  const startOffset = (firstDay.getDay() + 6) % 7
  const days = []
  const today = new Date()

  const endOffset = lastDay.getDay() === 0 ? 0 : (7 - lastDay.getDay())
  for (let i = -startOffset; i < lastDay.getDate() + endOffset; i++) {
    const d = new Date(y, m - 1, i + 1)
    const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    days.push({
      day: d.getDate(),
      dateStr,
      current: d.getMonth() === m - 1,
      isToday: d.toDateString() === today.toDateString(),
      items: items.value.filter(item => item.scheduled_date === dateStr),
    })
  }
  return days
})

function prevMonth() {
  if (currentMonth.value === 1) { currentMonth.value = 12; currentYear.value-- }
  else currentMonth.value--
}

function nextMonth() {
  if (currentMonth.value === 12) { currentMonth.value = 1; currentYear.value++ }
  else currentMonth.value++
}

function openCreate() {
  form.account_id = accounts.value[0]?.id || ''
  form.scheduled_date = ''
  form.scheduled_time = ''
  form.content_id = ''
  showDialog.value = true
}

async function createItem() {
  if (!form.account_id || !form.scheduled_date) return ElMessage.warning('请选择账号和日期')
  await request.post('/calendar/', {
    ...form,
    content_id: form.content_id || null,
    scheduled_time: form.scheduled_time || null,
  })
  ElMessage.success('排期已创建')
  showDialog.value = false
  load()
}

async function markStatus(row, status) {
  await request.put(`/calendar/${row.id}/status`, { publish_status: status })
  ElMessage.success(`已标记：${publishStatusLabel(status)}`)
  load()
}

async function sendRemind(row) {
  await request.post('/calendar/remind', {
    calendar_id: row.id,
    user_id: 'operator',
    content_title: row.content_title || '待发布内容',
    scheduled_time: `${row.scheduled_date} ${row.scheduled_time || ''}`,
  })
  ElMessage.success('提醒已发送')
  load()
}

async function deleteItem(id) {
  await ElMessageBox.confirm('确认删除此排期？', '删除确认')
  await request.delete(`/calendar/${id}`)
  ElMessage.success('已删除')
  load()
}

function handleCalendarCmd(cmd, row) {
  if (cmd === 'skip') markStatus(row, 'skipped')
  else if (cmd === 'remind') sendRemind(row)
  else if (cmd === 'delete') deleteItem(row.id)
}

function viewItem(item) {
  itemDetail.value = item
  itemDetailVisible.value = true
}

onMounted(async () => {
  await loadAccounts()
  load()
})
</script>

<style scoped>
.calendar-page { padding: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.page-header h2 { margin: 0; font-size: 22px; font-weight: 700; color: var(--color-ink); }
.page-sub { color: var(--color-ink-tertiary); font-size: 13px; }
.page-guide { margin-bottom: 12px; padding: 10px 14px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md); font-size: 13px; color: var(--color-ink-secondary); line-height: 1.6; }
.calendar-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.month-label { font-size: 16px; font-weight: 600; min-width: 120px; text-align: center; color: var(--color-ink); }
.calendar-grid { border: 1px solid var(--color-border); border-radius: var(--radius-sm); overflow: hidden; }
.calendar-header { display: grid; grid-template-columns: repeat(7, 1fr); background: var(--color-surface-subtle); }
.calendar-header-cell { padding: 8px; text-align: center; font-size: 13px; font-weight: 600; color: var(--color-ink-secondary); border-right: 1px solid var(--color-border); }
.calendar-header-cell:last-child { border-right: none; }
.calendar-body { display: grid; grid-template-columns: repeat(7, 1fr); }
.calendar-cell { min-height: 80px; padding: 4px; border-right: 1px solid var(--color-border); border-bottom: 1px solid var(--color-border); }
.calendar-cell:nth-child(7n) { border-right: none; }
.calendar-cell.other-month { background: var(--color-surface-subtle); }
.calendar-cell.today { background: rgba(15,107,197,0.06); }
.cell-date { font-size: 12px; color: var(--color-ink-tertiary); margin-bottom: 2px; }
.today .cell-date { color: var(--color-accent); font-weight: bold; }
.cell-items { display: flex; flex-direction: column; gap: 2px; }
.cell-item { font-size: 11px; padding: 2px 4px; border-radius: 3px; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cell-item-time { font-weight: 600; margin-right: 2px; }
.cell-item.status-pending { background: rgba(217,119,6,0.08); color: var(--color-warning); }
.cell-item.status-published { background: rgba(13,150,104,0.08); color: var(--color-success); }
.cell-item.status-skipped { background: var(--color-surface-subtle); color: var(--color-ink-tertiary); }
.cell-item.status-failed { background: rgba(220,38,38,0.08); color: var(--color-danger); }
.item-detail { padding: 4px 0; }
</style>
