<template>
  <div class="assets-page">
    <div class="page-header">
      <div>
        <h2>素材库</h2>
        <span class="page-sub">图片/视频/脚本/模板 · 上传共享 · 下载统计</span>
      </div>
      <el-button type="primary" @click="openUpload">上传素材</el-button>
    </div>

    <div class="page-guide">素材库用于管理内容创作所需的图片、视频、脚本等素材。上传后可在内容生成时引用。支持设置"对经销商公开"供经销商下载使用。</div>

    <div class="filter-bar">
      <el-select v-model="filter.asset_type" placeholder="类型筛选" clearable style="width:120px" @change="load">
        <el-option label="视频" value="video" />
        <el-option label="图片" value="image" />
        <el-option label="脚本" value="script" />
        <el-option label="模板" value="template" />
        <el-option label="音频" value="audio" />
      </el-select>
      <el-select v-model="filter.category" placeholder="分类筛选" clearable style="width:140px" @change="load">
        <el-option label="门店照片" value="store_photo" />
        <el-option label="产品图片" value="product_image" />
        <el-option label="案例图片" value="case_image" />
        <el-option label="视频素材" value="video_asset" />
        <el-option label="封面图片" value="cover_image" />
        <el-option label="产品展示" value="产品展示" />
        <el-option label="案例实拍" value="案例实拍" />
        <el-option label="品牌宣传" value="品牌宣传" />
        <el-option label="活动素材" value="活动素材" />
        <el-option label="培训资料" value="培训资料" />
      </el-select>
      <el-input v-model="filter.keyword" placeholder="搜索标题" clearable style="width:200px" @clear="load" @keyup.enter="load" />
      <el-button @click="load">刷新</el-button>
    </div>

    <el-table :data="assets" v-loading="loading" style="margin-top:12px">
      <el-table-column label="预览" width="80">
        <template #default="{ row }">
          <el-image
            v-if="row.asset_type === 'image' && (row.preview_url || row.thumbnail_url)"
            :src="row.preview_url || row.thumbnail_url"
            fit="cover"
            style="width:50px;height:50px;border-radius:4px"
            :preview-src-list="[row.preview_url || row.thumbnail_url]"
          />
          <el-icon v-else style="font-size:32px;color:var(--color-ink-tertiary)">
            <VideoCamera v-if="row.asset_type === 'video'" />
            <Document v-else />
          </el-icon>
        </template>
      </el-table-column>
      <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
      <el-table-column label="类型" width="80">
        <template #default="{ row }">{{ typeLabel(row.asset_type) }}</template>
      </el-table-column>
      <el-table-column prop="category" label="分类" width="100">
        <template #default="{ row }">{{ categoryLabel(row.category) || '—' }}</template>
      </el-table-column>
      <el-table-column label="标签" min-width="160">
        <template #default="{ row }">
          <el-tag v-for="t in (row.tags || []).slice(0, 3)" :key="t" size="small" effect="plain" style="margin-right:4px">{{ t }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="公开" width="70">
        <template #default="{ row }">
          <el-tag size="small" :type="row.is_public ? 'success' : 'info'">{{ row.is_public ? '是' : '否' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="download_count" label="下载" width="70" show-overflow-tooltip />
      <el-table-column label="大小" width="90">
        <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button link size="small" type="primary" @click="viewDetail(row)">详情</el-button>
          <el-button link size="small" @click="download(row)">下载</el-button>
          <el-dropdown trigger="click" @command="(cmd) => handleAssetCmd(cmd, row)">
            <el-button link size="small">更多<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="edit">编辑</el-dropdown-item>
                <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>

    <!-- 上传弹窗 -->
    <el-dialog v-model="uploadVisible" title="上传素材" width="560px">
      <el-form :model="uploadForm" label-width="90px">
        <el-form-item label="文件">
          <el-upload ref="uploadRef" :auto-upload="false" :on-change="handleFileChange" :limit="1" :show-file-list="true">
            <el-button>选择文件</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item label="标题"><el-input v-model="uploadForm.title" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="uploadForm.asset_type" style="width:100%">
            <el-option label="视频" value="video" />
            <el-option label="图片" value="image" />
            <el-option label="脚本" value="script" />
            <el-option label="模板" value="template" />
            <el-option label="音频" value="audio" />
          </el-select>
        </el-form-item>
        <el-form-item label="分类"><el-input v-model="uploadForm.category" placeholder="如：产品展示" /></el-form-item>
        <el-form-item label="标签"><el-input v-model="uploadForm.tags_str" placeholder="逗号分隔，如：阳台,隔音,实测" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="uploadForm.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="对经销商公开">
          <el-switch v-model="uploadForm.is_public" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="doUpload">上传</el-button>
      </template>
    </el-dialog>

    <!-- 编辑弹窗 -->
    <el-dialog v-model="editVisible" title="编辑素材" width="520px">
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="标题"><el-input v-model="editForm.title" /></el-form-item>
        <el-form-item label="分类"><el-input v-model="editForm.category" /></el-form-item>
        <el-form-item label="标签"><el-input v-model="editForm.tags_str" placeholder="逗号分隔" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="editForm.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="对经销商公开">
          <el-switch v-model="editForm.is_public" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 详情弹窗 -->
    <el-dialog v-model="detailVisible" title="素材详情" width="600px">
      <div v-if="detail" class="detail-content">
        <el-image v-if="detail.asset_type === 'image' && detail.preview_url" :src="detail.preview_url" fit="contain" style="max-width:100%;max-height:300px;margin-bottom:12px" />
        <video v-else-if="detail.asset_type === 'video' && detail.preview_url" :src="detail.preview_url" controls preload="metadata" style="width:100%;max-height:340px;margin-bottom:12px" />
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="标题">{{ detail.title }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ typeLabel(detail.asset_type) }}</el-descriptions-item>
          <el-descriptions-item label="分类">{{ categoryLabel(detail.category) || '—' }}</el-descriptions-item>
          <el-descriptions-item label="大小">{{ formatSize(detail.file_size) }}</el-descriptions-item>
          <el-descriptions-item label="下载次数">{{ detail.download_count }}</el-descriptions-item>
          <el-descriptions-item label="公开">{{ detail.is_public ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="描述" :span="2">{{ detail.description || '—' }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="detail.tags?.length" style="margin-top:8px">
          <el-tag v-for="t in detail.tags" :key="t" size="small" effect="plain" style="margin-right:4px">{{ t }}</el-tag>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, ArrowDown, VideoCamera } from '@element-plus/icons-vue'
import request from '../../utils/request'
import { errorMessageFrom } from '../../utils/errorMessage'

const loading = ref(false)
const uploading = ref(false)
const assets = ref([])
const uploadVisible = ref(false)
const editVisible = ref(false)
const detailVisible = ref(false)
const detail = ref(null)
const uploadRef = ref(null)
const selectedFile = ref(null)

const filter = reactive({ asset_type: '', category: '', keyword: '' })
const uploadForm = reactive({ title: '', asset_type: 'image', category: '', tags_str: '', description: '', is_public: true })
const editForm = reactive({ id: '', title: '', category: '', tags_str: '', description: '', is_public: true })

const TYPE_MAP = { video: '视频', image: '图片', script: '脚本', template: '模板', audio: '音频' }
const CATEGORY_MAP = { store_photo: '门店照片', product_image: '产品图片', case_image: '案例图片', video_asset: '视频素材', cover_image: '封面图片' }
const typeLabel = (t) => TYPE_MAP[t] || t
const categoryLabel = (c) => CATEGORY_MAP[c] || c
const formatSize = (b) => {
  if (!b) return '—'
  if (b < 1024) return b + 'B'
  if (b < 1048576) return (b / 1024).toFixed(1) + 'KB'
  return (b / 1048576).toFixed(1) + 'MB'
}

async function load() {
  loading.value = true
  try {
    const params = { page_size: 50 }
    if (filter.asset_type) params.asset_type = filter.asset_type
    if (filter.category) params.category = filter.category
    if (filter.keyword) params.keyword = filter.keyword
    const res = await request.get('/assets/', { params })
    assets.value = res.data || []
  } finally { loading.value = false }
}

function openUpload() {
  Object.assign(uploadForm, { title: '', asset_type: 'image', category: '', tags_str: '', description: '', is_public: true })
  selectedFile.value = null
  uploadRef.value?.clearFiles()
  uploadVisible.value = true
}

function handleFileChange(file) {
  if (file.size > 50 * 1024 * 1024) {
    ElMessage.warning('文件大小不能超过 50MB')
    uploadRef.value?.clearFiles()
    return
  }
  selectedFile.value = file.raw
  if (!uploadForm.title) uploadForm.title = file.name
}

async function doUpload() {
  if (!selectedFile.value) return ElMessage.warning('请选择文件')
  if (!uploadForm.title.trim()) return ElMessage.warning('请输入标题')
  uploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)
    const tags = uploadForm.tags_str ? uploadForm.tags_str.split(',').map(t => t.trim()).filter(Boolean) : []
    const params = {
      title: uploadForm.title,
      asset_type: uploadForm.asset_type,
      category: uploadForm.category || '',
      description: uploadForm.description || '',
      is_public: String(uploadForm.is_public),
      tags: JSON.stringify(tags),
    }
    await request.post('/assets/upload', formData, {
      params,
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
    ElMessage.success('上传成功')
    uploadVisible.value = false
    uploadRef.value?.clearFiles()
    load()
  } catch (e) {
    ElMessage.error(errorMessageFrom(e, '素材上传失败，请重新选择文件后再试。', 'upload'))
  } finally { uploading.value = false }
}

function editAsset(row) {
  editForm.id = row.id
  editForm.title = row.title
  editForm.category = row.category || ''
  editForm.tags_str = (row.tags || []).join(', ')
  editForm.description = row.description || ''
  editForm.is_public = row.is_public
  editVisible.value = true
}

async function submitEdit() {
  const tags = editForm.tags_str ? editForm.tags_str.split(',').map(t => t.trim()).filter(Boolean) : []
  await request.put(`/assets/${editForm.id}`, {
    title: editForm.title,
    category: editForm.category,
    tags,
    description: editForm.description,
    is_public: editForm.is_public,
  })
  ElMessage.success('素材已更新')
  editVisible.value = false
  load()
}

async function download(row) {
  const res = await request.post(`/assets/${row.id}/download`)
  if (res.data?.download_url) window.open(res.data.download_url, '_blank', 'noopener,noreferrer')
  else ElMessage.success('下载已记录')
}

function viewDetail(row) {
  detail.value = row
  detailVisible.value = true
}

async function deleteAsset(id) {
  await ElMessageBox.confirm('确定删除此素材？', '确认')
  await request.delete(`/assets/${id}`)
  ElMessage.success('已删除')
  load()
}

function handleAssetCmd(cmd, row) {
  if (cmd === 'edit') editAsset(row)
  else if (cmd === 'delete') deleteAsset(row.id)
}

onMounted(load)
</script>

<style scoped>
.assets-page { padding: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.page-header h2 { margin: 0; font-size: 22px; font-weight: 700; color: var(--color-ink); }
.page-sub { color: var(--color-ink-tertiary); font-size: 13px; }
.page-guide { margin-bottom: 12px; padding: 10px 14px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md); font-size: 13px; color: var(--color-ink-secondary); line-height: 1.6; }
.filter-bar { display: flex; gap: 12px; align-items: center; margin-bottom: 8px; }
.detail-content { padding: 4px 0; }
</style>
