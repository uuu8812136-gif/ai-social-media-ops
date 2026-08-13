<template>
  <div class="users-page">
    <div class="page-header">
      <div>
        <h2>账号管理</h2>
        <span class="page-sub">管理后台登录账号、角色和启用状态</span>
      </div>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>
        新增账号
      </el-button>
    </div>

    <div class="filter-bar">
      <el-input v-model="filters.q" clearable placeholder="搜索用户名或姓名" class="search-input" @keyup.enter="loadUsers">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="filters.role" clearable placeholder="全部角色" class="filter-select" @change="onFilterChange">
        <el-option label="管理员" value="admin" />
        <el-option label="运营官" value="operator" />
        <el-option label="经销商" value="dealer" />
      </el-select>
      <el-select v-model="filters.status" clearable placeholder="全部状态" class="filter-select" @change="onFilterChange">
        <el-option label="已启用" value="active" />
        <el-option label="已停用" value="disabled" />
      </el-select>
      <el-button :loading="loading" @click="loadUsers">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
    </div>

    <section class="users-surface">
      <el-table :data="users" v-loading="loading" size="small" class="users-table desktop-users-table">
        <el-table-column label="账号" min-width="190">
          <template #default="{ row }">
            <div class="account-cell">
              <el-avatar :size="34">{{ row.full_name?.[0] || row.username?.[0] || 'U' }}</el-avatar>
              <div>
                <strong>{{ row.full_name }}</strong>
                <span>{{ row.username }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="110">
          <template #default="{ row }">
            <el-tag :type="roleType(row.role)" size="small">{{ roleLabel(row.role) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="绑定经销商" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.dealer_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
              {{ row.is_active ? '已启用' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link size="small" @click="openResetPassword(row)">重置密码</el-button>
            <el-button
              v-if="row.id !== auth.user?.id"
              link
              :type="row.is_active ? 'danger' : 'success'"
              size="small"
              @click="toggleStatus(row)"
            >
              {{ row.is_active ? '停用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="没有符合条件的后台账号" :image-size="72">
            <el-button type="primary" @click="openCreate">新增账号</el-button>
          </el-empty>
        </template>
      </el-table>

      <div v-loading="loading" class="mobile-user-list">
        <article v-for="row in users" :key="row.id" class="mobile-user-item">
          <div class="mobile-user-head">
            <el-avatar :size="36">{{ row.full_name?.[0] || row.username?.[0] || 'U' }}</el-avatar>
            <div class="mobile-user-identity">
              <strong>{{ row.full_name }}</strong>
              <span>{{ row.username }}</span>
            </div>
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
              {{ row.is_active ? '已启用' : '已停用' }}
            </el-tag>
          </div>
          <dl class="mobile-user-meta">
            <div><dt>角色</dt><dd>{{ roleLabel(row.role) }}</dd></div>
            <div><dt>经销商</dt><dd>{{ row.dealer_name || '—' }}</dd></div>
            <div><dt>创建时间</dt><dd>{{ formatTime(row.created_at) }}</dd></div>
          </dl>
          <div class="mobile-user-actions">
            <el-button size="small" type="primary" plain @click="openEdit(row)">编辑</el-button>
            <el-button size="small" @click="openResetPassword(row)">重置密码</el-button>
            <el-button
              v-if="row.id !== auth.user?.id"
              size="small"
              :type="row.is_active ? 'danger' : 'success'"
              plain
              @click="toggleStatus(row)"
            >
              {{ row.is_active ? '停用' : '启用' }}
            </el-button>
          </div>
        </article>
        <el-empty v-if="!loading && !users.length" description="没有符合条件的后台账号" :image-size="64">
          <el-button type="primary" @click="openCreate">新增账号</el-button>
        </el-empty>
      </div>

      <el-pagination
        v-if="total > filters.page_size"
        class="pager"
        background
        layout="prev, pager, next"
        :total="total"
        :page-size="filters.page_size"
        :current-page="filters.page"
        @current-change="onPageChange"
      />
    </section>

    <el-dialog v-model="editorVisible" :title="editingId ? '编辑账号' : '新增账号'" width="520px" destroy-on-close>
      <el-form ref="editorRef" :model="form" :rules="editorRules" label-position="top">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="Boolean(editingId)" maxlength="50" placeholder="小写字母、数字、下划线、点或连字符" />
        </el-form-item>
        <el-form-item label="姓名" prop="full_name">
          <el-input v-model="form.full_name" maxlength="100" placeholder="后台显示名称" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="form.role" :disabled="editingId === auth.user?.id" style="width: 100%">
            <el-option label="管理员" value="admin" />
            <el-option label="运营官" value="operator" />
            <el-option label="经销商" value="dealer" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.role === 'dealer'" label="绑定经销商" prop="dealer_id">
          <el-select v-model="form.dealer_id" clearable filterable placeholder="可选" style="width: 100%">
            <el-option v-for="dealer in dealers" :key="dealer.id" :label="dealer.company_name" :value="dealer.id" />
          </el-select>
        </el-form-item>
        <template v-if="!editingId">
          <el-form-item label="初始密码" prop="password">
            <el-input v-model="form.password" type="password" show-password autocomplete="new-password" placeholder="至少 8 位，同时包含字母和数字" />
          </el-form-item>
          <el-form-item label="确认密码" prop="confirm_password">
            <el-input v-model="form.confirm_password" type="password" show-password autocomplete="new-password" />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitUser">
          {{ editingId ? '保存修改' : '创建账号' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="passwordVisible" title="重置密码" width="460px" destroy-on-close>
      <div class="reset-target">账号：<strong>{{ resetTarget?.username }}</strong></div>
      <el-form ref="passwordRef" :model="passwordForm" :rules="passwordRules" label-position="top">
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="passwordForm.new_password" type="password" show-password autocomplete="new-password" placeholder="至少 8 位，同时包含字母和数字" />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirm_password">
          <el-input v-model="passwordForm.confirm_password" type="password" show-password autocomplete="new-password" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetting" @click="submitPasswordReset">确认重置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '../../stores/auth'
import request from '../../utils/request'

const auth = useAuthStore()
const loading = ref(false)
const submitting = ref(false)
const resetting = ref(false)
const users = ref([])
const dealers = ref([])
const total = ref(0)
const editorVisible = ref(false)
const passwordVisible = ref(false)
const editingId = ref(null)
const resetTarget = ref(null)
const editorRef = ref(null)
const passwordRef = ref(null)

const filters = reactive({ q: '', role: '', status: '', page: 1, page_size: 20 })
const form = reactive({ username: '', full_name: '', role: 'operator', dealer_id: null, password: '', confirm_password: '' })
const passwordForm = reactive({ new_password: '', confirm_password: '' })

const passwordPattern = /^(?=.*[A-Za-z])(?=.*\d).{8,128}$/
const editorRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { pattern: /^[a-z0-9_.-]{3,50}$/, message: '使用 3-50 位小写字母、数字、下划线、点或连字符', trigger: 'blur' },
  ],
  full_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
  password: [
    { required: true, message: '请输入初始密码', trigger: 'blur' },
    { pattern: passwordPattern, message: '密码至少 8 位且同时包含字母和数字', trigger: 'blur' },
  ],
  confirm_password: [{
    validator: (_rule, value, callback) => value === form.password ? callback() : callback(new Error('两次输入的密码不一致')),
    trigger: 'blur',
  }],
}
const passwordRules = {
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { pattern: passwordPattern, message: '密码至少 8 位且同时包含字母和数字', trigger: 'blur' },
  ],
  confirm_password: [{
    validator: (_rule, value, callback) => value === passwordForm.new_password ? callback() : callback(new Error('两次输入的密码不一致')),
    trigger: 'blur',
  }],
}

const roleLabel = (role) => ({ admin: '管理员', operator: '运营官', dealer: '经销商' }[role] || role)
const roleType = (role) => ({ admin: 'danger', operator: 'primary', dealer: 'warning' }[role] || 'info')
const formatTime = (value) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'

async function loadUsers() {
  loading.value = true
  try {
    const params = { page: filters.page, page_size: filters.page_size }
    if (filters.q.trim()) params.q = filters.q.trim()
    if (filters.role) params.role = filters.role
    if (filters.status) params.is_active = filters.status === 'active'
    const res = await request.get('/users', { params })
    users.value = res.data || []
    total.value = res.pagination?.total || 0
  } finally {
    loading.value = false
  }
}

async function loadDealers() {
  const res = await request.get('/dealers/', { params: { page_size: 100 } })
  dealers.value = res.data || []
}

function resetEditor() {
  Object.assign(form, { username: '', full_name: '', role: 'operator', dealer_id: null, password: '', confirm_password: '' })
}

function openCreate() {
  editingId.value = null
  resetEditor()
  editorVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    username: row.username,
    full_name: row.full_name,
    role: row.role,
    dealer_id: row.dealer_id || null,
    password: '',
    confirm_password: '',
  })
  editorVisible.value = true
}

async function submitUser() {
  const valid = await editorRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    if (editingId.value) {
      await request.put(`/users/${editingId.value}`, {
        full_name: form.full_name.trim(),
        role: form.role,
        dealer_id: form.role === 'dealer' ? form.dealer_id : null,
      })
      ElMessage.success('账号已更新')
    } else {
      await request.post('/users', {
        username: form.username.trim().toLowerCase(),
        full_name: form.full_name.trim(),
        role: form.role,
        dealer_id: form.role === 'dealer' ? form.dealer_id : null,
        password: form.password,
      })
      ElMessage.success('账号创建成功')
    }
    editorVisible.value = false
    await loadUsers()
  } finally {
    submitting.value = false
  }
}

async function toggleStatus(row) {
  const nextActive = !row.is_active
  await ElMessageBox.confirm(
    `确认${nextActive ? '启用' : '停用'}账号“${row.username}”？`,
    `${nextActive ? '启用' : '停用'}账号`,
    { type: nextActive ? 'info' : 'warning' },
  )
  await request.put(`/users/${row.id}`, { is_active: nextActive })
  ElMessage.success(`账号已${nextActive ? '启用' : '停用'}`)
  await loadUsers()
}

function openResetPassword(row) {
  resetTarget.value = row
  Object.assign(passwordForm, { new_password: '', confirm_password: '' })
  passwordVisible.value = true
}

async function submitPasswordReset() {
  const valid = await passwordRef.value?.validate().catch(() => false)
  if (!valid || !resetTarget.value) return
  resetting.value = true
  try {
    await request.post(`/users/${resetTarget.value.id}/reset-password`, { new_password: passwordForm.new_password })
    passwordVisible.value = false
    ElMessage.success('密码已重置')
  } finally {
    resetting.value = false
  }
}

function onFilterChange() {
  filters.page = 1
  loadUsers()
}

function onPageChange(page) {
  filters.page = page
  loadUsers()
}

onMounted(() => Promise.all([loadUsers(), loadDealers()]))
</script>

<style scoped>
.users-page { max-width: 1240px; margin: 0 auto; }
.filter-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.search-input { width: min(320px, 100%); }
.filter-select { width: 140px; }
.users-surface { background: var(--wm-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md); overflow: hidden; }
.mobile-user-list { display: none; }
.account-cell { display: flex; align-items: center; gap: 10px; min-width: 0; }
.account-cell .el-avatar { flex: 0 0 auto; background: var(--wm-primary); color: #fff; }
.account-cell div { min-width: 0; display: flex; flex-direction: column; }
.account-cell strong { color: var(--color-ink); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.account-cell span { color: var(--color-ink-tertiary); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pager { display: flex; justify-content: flex-end; padding: 14px 16px; border-top: 1px solid var(--color-border); }
.reset-target { margin-bottom: 16px; padding: 10px 12px; background: var(--wm-surface-subtle); border-radius: var(--radius-sm); color: var(--color-ink-secondary); font-size: 13px; }
@media (max-width: 640px) {
  .search-input, .filter-select, .filter-bar .el-button { width: 100%; }
  .filter-bar { align-items: stretch; }
  .desktop-users-table { display: none; }
  .mobile-user-list { display: block; padding: 10px; }
  .mobile-user-item { padding: 12px; border-bottom: 1px solid var(--color-border); }
  .mobile-user-item:last-child { border-bottom: 0; }
  .mobile-user-head { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .mobile-user-head .el-avatar { flex: 0 0 auto; background: var(--wm-primary); color: #fff; }
  .mobile-user-identity { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .mobile-user-identity strong, .mobile-user-identity span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .mobile-user-identity strong { color: var(--color-ink); font-size: 13px; }
  .mobile-user-identity span { color: var(--color-ink-tertiary); font-size: 12px; }
  .mobile-user-meta { margin: 12px 0; display: grid; gap: 7px; }
  .mobile-user-meta div { display: grid; grid-template-columns: 64px minmax(0, 1fr); gap: 10px; }
  .mobile-user-meta dt { color: var(--color-ink-tertiary); font-size: 12px; }
  .mobile-user-meta dd { margin: 0; color: var(--color-ink-secondary); font-size: 12px; overflow-wrap: anywhere; }
  .mobile-user-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .mobile-user-actions .el-button { width: 100%; margin-left: 0; }
  :deep(.el-dialog) { width: calc(100vw - 24px) !important; margin: 12px auto; }
}
</style>
