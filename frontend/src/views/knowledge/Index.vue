<template>
  <div class="knowledge-page">
    <div class="page-header">
      <div>
        <h2>知识库</h2>
        <span class="page-sub">文本资料、关键词分片、生成引用</span>
      </div>
      <div class="header-actions">
        <el-button @click="loadDocuments">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>
          新建资料
        </el-button>
      </div>
    </div>

    <div class="page-guide">知识库用于存储产品资料、案例话术等文本。AI 生成内容时会自动引用知识库资料。操作：新建资料 → 填写正文 → 保存 → 重建索引 → 在右侧"测试检索"验证效果。</div>

    <div class="kb-grid">
      <section class="kb-main">
        <div class="tool-row">
          <el-input
            v-model="filters.q"
            clearable
            placeholder="搜索标题、正文、来源、标签"
            class="filter-input"
            @keyup.enter="loadDocuments"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-select v-model="filters.strategy_type" clearable placeholder="策略" class="filter-select" @change="onFilterChange">
            <el-option label="IP" value="ip" />
            <el-option label="品牌" value="brand" />
          </el-select>
          <el-input v-model="filters.city" clearable placeholder="城市" class="filter-select" @keyup.enter="loadDocuments" />
          <el-select v-model="filters.status" clearable placeholder="状态" class="filter-select" @change="onFilterChange">
            <el-option label="启用" value="active" />
            <el-option label="停用" value="inactive" />
          </el-select>
          <el-button type="primary" @click="loadDocuments">
            <el-icon><Search /></el-icon>
            查询
          </el-button>
        </div>

        <el-table :data="documents" v-loading="loading" class="doc-table">
          <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
          <el-table-column prop="strategy_type" label="策略" width="90">
            <template #default="{ row }">{{ strategyLabel(row.strategy_type) }}</template>
          </el-table-column>
          <el-table-column prop="city" label="城市" width="110">
            <template #default="{ row }">{{ row.city || '通用' }}</template>
          </el-table-column>
          <el-table-column prop="category" label="分类" width="120" show-overflow-tooltip />
          <el-table-column label="标签" min-width="150" show-overflow-tooltip>
            <template #default="{ row }">{{ (row.tags || []).join('、') || '-' }}</template>
          </el-table-column>
          <el-table-column prop="chunk_count" label="分片" width="80" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
                {{ row.status === 'active' ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="更新" width="190" show-overflow-tooltip>
            <template #default="{ row }"><span style="white-space:nowrap">{{ formatTime(row.updated_at) }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <el-button link size="small" @click="viewDocument(row)">详情</el-button>
              <el-button link size="small" type="primary" @click="openEdit(row)">编辑</el-button>
              <el-dropdown trigger="click" @command="(cmd) => handleKnowledgeCmd(cmd, row)">
                <el-button link size="small">更多<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="rebuild" :loading="rebuildingId === row.id">重建索引</el-dropdown-item>
                    <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </template>
          </el-table-column>
        </el-table>

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

      <aside class="search-panel">
        <div class="panel-title">
          <span>测试检索</span>
          <el-tag size="small" effect="plain">{{ searchResults.length }} 条</el-tag>
        </div>
        <el-form :model="searchForm" label-position="top" class="search-form">
          <el-form-item label="选题 / 关键词">
            <el-input v-model="searchForm.topic" placeholder="如：阳台封窗隔音效果对比" />
          </el-form-item>
          <el-form-item label="策略">
            <el-select v-model="searchForm.strategy_type" clearable style="width: 100%">
              <el-option label="IP" value="ip" />
              <el-option label="品牌" value="brand" />
            </el-select>
          </el-form-item>
          <el-form-item label="城市">
            <el-select v-model="searchForm.cities" multiple filterable allow-create default-first-option style="width: 100%">
              <el-option label="广州" value="广州" />
              <el-option label="深圳" value="深圳" />
              <el-option label="佛山" value="佛山" />
              <el-option label="东莞" value="东莞" />
            </el-select>
          </el-form-item>
          <el-button type="primary" class="full-button" :loading="searching" @click="searchKnowledge">
            <el-icon><Search /></el-icon>
            检索
          </el-button>
        </el-form>

        <el-empty v-if="searched && !searchResults.length" description="没有命中片段" />
        <div v-else class="result-stack">
          <article v-for="item in searchResults" :key="item.chunk_id" class="search-result">
            <div class="result-head">
              <strong>{{ item.title }}</strong>
              <span>#{{ item.chunk_index + 1 }}</span>
            </div>
            <p>{{ item.content }}</p>
            <div class="result-meta">
              <span>{{ item.city || '通用' }}</span>
              <span>{{ item.source || item.category || '知识库' }}</span>
            </div>
          </article>
        </div>
      </aside>
    </div>

    <el-drawer v-model="drawerVisible" :title="editingId ? '编辑资料' : '新建资料'" size="520px">
      <el-form :model="form" label-position="top" class="doc-form">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" maxlength="200" show-word-limit />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="知识类型">
              <el-input v-model="form.kb_type" placeholder="content" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="策略">
              <el-select v-model="form.strategy_type" clearable style="width: 100%">
                <el-option label="IP" value="ip" />
                <el-option label="品牌" value="brand" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="城市">
              <el-input v-model="form.city" placeholder="留空表示通用" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="分类">
              <el-input v-model="form.category" placeholder="案例 / 产品 / 话术" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="标签">
          <el-select v-model="form.tags" multiple filterable allow-create default-first-option style="width: 100%" />
        </el-form-item>
        <el-form-item label="来源">
          <el-input v-model="form.source" placeholder="资料来源、URL 或内部编号" />
        </el-form-item>
        <el-form-item label="正文" required>
          <el-input v-model="form.content" type="textarea" :rows="12" resize="vertical" />
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status">
            <el-radio-button label="active">启用</el-radio-button>
            <el-radio-button label="inactive">停用</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <div class="drawer-actions">
          <el-button @click="drawerVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="saveDocument">
            <el-icon><Check /></el-icon>
            保存
          </el-button>
        </div>
      </el-form>
    </el-drawer>

    <el-dialog v-model="detailVisible" title="知识资料详情" width="760px">
      <div v-if="detail" class="detail-box">
        <div class="detail-title">
          <strong>{{ detail.title }}</strong>
          <el-tag :type="detail.status === 'active' ? 'success' : 'info'" size="small">
            {{ detail.status === 'active' ? '启用' : '停用' }}
          </el-tag>
        </div>
        <div class="detail-meta">
          <span>{{ strategyLabel(detail.strategy_type) }}</span>
          <span>{{ detail.city || '通用' }}</span>
          <span>{{ detail.category || '未分类' }}</span>
          <span>{{ detail.source || '未填写来源' }}</span>
        </div>
        <pre class="detail-content">{{ detail.content }}</pre>
        <div class="chunk-title">分片</div>
        <article v-for="chunk in detail.chunks" :key="chunk.id" class="chunk-item">
          <div class="result-head">
            <strong>#{{ chunk.chunk_index + 1 }}</strong>
            <span>{{ (chunk.keywords || []).slice(0, 4).join('、') }}</span>
          </div>
          <p>{{ chunk.content }}</p>
        </article>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import request from '../../utils/request'

const loading = ref(false)
const saving = ref(false)
const searching = ref(false)
const searched = ref(false)
const rebuildingId = ref('')
const drawerVisible = ref(false)
const detailVisible = ref(false)
const editingId = ref('')

const documents = ref([])
const total = ref(0)
const searchResults = ref([])
const detail = ref(null)

const filters = reactive({ page: 1, page_size: 20, q: '', strategy_type: '', city: '', status: '' })
const searchForm = reactive({ topic: '阳台封窗隔音效果对比', strategy_type: 'ip', cities: ['广州'], limit: 5 })
const form = reactive({
  title: '',
  kb_type: 'content',
  strategy_type: '',
  city: '',
  category: '',
  tags: [],
  source: '',
  content: '',
  status: 'active',
})

function resetForm() {
  editingId.value = ''
  Object.assign(form, {
    title: '',
    kb_type: 'content',
    strategy_type: '',
    city: '',
    category: '',
    tags: [],
    source: '',
    content: '',
    status: 'active',
  })
}

function strategyLabel(value) {
  return ({ ip: 'IP', brand: '品牌' }[value] || '通用')
}

const formatTime = (t) => {
  if (!t) return '—'
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function documentPayload() {
  return {
    title: form.title.trim(),
    kb_type: form.kb_type.trim() || 'content',
    strategy_type: form.strategy_type || null,
    city: form.city.trim() || null,
    category: form.category.trim() || null,
    tags: form.tags,
    source: form.source.trim() || null,
    content: form.content.trim(),
    status: form.status,
  }
}

function onFilterChange() {
  filters.page = 1
  loadDocuments()
}

async function loadDocuments() {
  loading.value = true
  try {
    const params = { page: filters.page, page_size: filters.page_size }
    if (filters.q) params.q = filters.q
    if (filters.strategy_type) params.strategy_type = filters.strategy_type
    if (filters.city) params.city = filters.city
    if (filters.status) params.status = filters.status
    const res = await request.get('/knowledge/', { params })
    documents.value = res.data || []
    total.value = res.pagination?.total || 0
  } finally {
    loading.value = false
  }
}

function onPageChange(page) {
  filters.page = page
  loadDocuments()
}

function openCreate() {
  resetForm()
  drawerVisible.value = true
}

async function openEdit(row) {
  const res = await request.get(`/knowledge/${row.id}`)
  const item = res.data
  editingId.value = item.id
  Object.assign(form, {
    title: item.title || '',
    kb_type: item.kb_type || 'content',
    strategy_type: item.strategy_type || '',
    city: item.city || '',
    category: item.category || '',
    tags: item.tags || [],
    source: item.source || '',
    content: item.content || '',
    status: item.status || 'active',
  })
  drawerVisible.value = true
}

async function saveDocument() {
  if (!form.title.trim()) return ElMessage.warning('请填写标题')
  if (!form.content.trim()) return ElMessage.warning('请填写正文')
  saving.value = true
  try {
    const payload = documentPayload()
    if (editingId.value) {
      await request.put(`/knowledge/${editingId.value}`, payload)
      ElMessage.success('资料已更新')
    } else {
      await request.post('/knowledge/', payload)
      ElMessage.success('资料已创建')
    }
    drawerVisible.value = false
    loadDocuments()
  } finally {
    saving.value = false
  }
}

async function viewDocument(row) {
  const res = await request.get(`/knowledge/${row.id}`)
  detail.value = res.data
  detailVisible.value = true
}

function handleKnowledgeCmd(cmd, row) {
  if (cmd === 'rebuild') rebuild(row)
  else if (cmd === 'delete') confirmDelete(row)
}

async function rebuild(row) {
  rebuildingId.value = row.id
  try {
    const res = await request.post(`/knowledge/${row.id}/rebuild`)
    row.chunk_count = res.data.chunk_count
    ElMessage.success(`已重建 ${res.data.chunk_count} 个分片`)
  } finally {
    rebuildingId.value = ''
  }
}

async function confirmDelete(row) {
  await ElMessageBox.confirm('删除后不可恢复，确认删除？', '删除确认', {
    confirmButtonText: '删除',
    cancelButtonText: '取消',
    type: 'warning',
  })
  await deleteDocument(row)
}

async function deleteDocument(row) {
  await request.delete(`/knowledge/${row.id}`)
  ElMessage.success('资料已删除')
  loadDocuments()
}

async function searchKnowledge() {
  searching.value = true
  searched.value = true
  try {
    const res = await request.post('/knowledge/search', {
      topic: searchForm.topic,
      q: searchForm.topic,
      strategy_type: searchForm.strategy_type || null,
      cities: searchForm.cities,
      limit: searchForm.limit,
    })
    searchResults.value = res.data.items || []
  } finally {
    searching.value = false
  }
}

onMounted(() => {
  loadDocuments()
})
</script>

<style scoped>
.knowledge-page { padding: 0; }
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.page-header h2 { margin: 0 0 4px; font-size: 22px; font-weight: 700; color: var(--color-ink); }
.page-sub { color: var(--color-ink-tertiary); font-size: 13px; }
.header-actions { display: flex; gap: 8px; }
.page-guide { margin-bottom: 16px; padding: 10px 14px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md); font-size: 13px; color: var(--color-ink-secondary); line-height: 1.6; }
.kb-grid { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 16px; align-items: start; }
.kb-main, .search-panel {
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  padding: 16px;
  box-shadow: var(--shadow-xs);
}
.tool-row { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
.filter-input { min-width: 260px; flex: 1; }
.filter-select { width: 140px; }
.doc-table { width: 100%; }
.pager { margin-top: 12px; justify-content: flex-end; display: flex; }
.panel-title { display: flex; align-items: center; justify-content: space-between; font-weight: 700; color: var(--color-ink); margin-bottom: 12px; }
.search-form { border-bottom: 1px solid var(--color-border-light); padding-bottom: 12px; margin-bottom: 12px; }
.full-button { width: 100%; }
.result-stack { display: flex; flex-direction: column; gap: 10px; max-height: calc(100vh - 390px); overflow-y: auto; }
.search-result, .chunk-item {
  border: 1px solid var(--color-border);
  border-left: 3px solid var(--color-accent);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  background: var(--color-surface);
}
.result-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; color: var(--color-ink); font-size: 13px; }
.result-head span { color: var(--color-ink-tertiary); font-size: 12px; white-space: nowrap; }
.search-result p, .chunk-item p { margin: 8px 0 0; color: var(--color-ink-secondary); line-height: 1.6; font-size: 13px; white-space: pre-wrap; }
.result-meta { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; color: var(--color-ink-tertiary); font-size: 12px; }
.doc-form { padding-right: 8px; }
.drawer-actions { display: flex; justify-content: flex-end; gap: 8px; padding-top: 8px; }
.detail-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: 16px; color: var(--color-ink); }
.detail-meta { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0; color: var(--color-ink-tertiary); font-size: 13px; }
.detail-content {
  margin: 0;
  padding: 12px;
  background: var(--color-surface-subtle);
  border-radius: var(--radius-sm);
  color: var(--color-ink-secondary);
  white-space: pre-wrap;
  line-height: 1.7;
  font-family: inherit;
}
.chunk-title { margin: 16px 0 8px; font-weight: 700; color: var(--color-ink); }
.chunk-item { margin-bottom: 8px; }

@media (max-width: 1100px) {
  .kb-grid { grid-template-columns: 1fr; }
  .result-stack { max-height: none; }
}

@media (max-width: 760px) {
  .page-header, .tool-row { align-items: stretch; flex-direction: column; }
  .header-actions { width: 100%; }
  .header-actions .el-button { flex: 1; }
  .filter-select, .filter-input { width: 100%; }
}
</style>
