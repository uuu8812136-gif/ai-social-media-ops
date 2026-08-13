<template>
  <div class="llm-settings-page">
    <div class="page-header">
      <div>
        <h2>模型配置</h2>
        <span class="page-sub">配置内容生成、文案改写和 AI 风控使用的模型服务</span>
      </div>
      <el-button :loading="loading" @click="loadConfig">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
    </div>

    <div class="settings-layout" v-loading="loading">
      <section class="config-surface">
        <div class="surface-header">
          <div>
            <h3>API 接入</h3>
            <p>支持 OpenAI 兼容的 Chat Completions 和 Responses 协议</p>
          </div>
          <el-tag :type="config.api_key_configured ? 'success' : 'warning'" effect="light">
            {{ config.api_key_configured ? '密钥已配置' : '密钥未配置' }}
          </el-tag>
        </div>

        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="config-form">
          <div class="form-grid">
            <el-form-item label="配置名称" prop="provider_name">
              <el-input v-model="form.provider_name" maxlength="100" placeholder="如：DeepSeek、通义千问、自建网关" />
            </el-form-item>

            <el-form-item label="接口协议" prop="protocol">
              <el-radio-group v-model="form.protocol" class="protocol-switch">
                <el-radio-button value="chat_completions">Chat Completions</el-radio-button>
                <el-radio-button value="responses">Responses</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <el-form-item label="API Base URL" prop="base_url" class="wide-field">
              <el-input v-model="form.base_url" placeholder="https://api.example.com/v1" />
            </el-form-item>

            <el-form-item label="模型名称" prop="model">
              <el-input v-model="form.model" maxlength="200" placeholder="如：deepseek-chat、qwen-plus" />
            </el-form-item>

            <el-form-item label="请求超时" prop="timeout_seconds">
              <el-input-number v-model="form.timeout_seconds" :min="5" :max="300" :step="5" controls-position="right" />
              <span class="unit-label">秒</span>
            </el-form-item>

            <el-form-item label="API Key" prop="api_key" class="wide-field">
              <el-input
                v-model="form.api_key"
                type="password"
                show-password
                clearable
                autocomplete="new-password"
                :placeholder="keyPlaceholder"
              />
            </el-form-item>
          </div>

          <div class="form-actions">
            <el-button type="primary" :loading="saving" @click="saveConfig">
              <el-icon><Check /></el-icon>
              保存配置
            </el-button>
            <el-button :loading="testing" @click="testConnection">
              <el-icon><Connection /></el-icon>
              测试连接
            </el-button>
            <el-button v-if="config.source === 'database'" type="danger" plain @click="restoreEnvironment">
              恢复环境配置
            </el-button>
          </div>
        </el-form>
      </section>

      <aside class="runtime-surface">
        <div class="surface-header compact">
          <div>
            <h3>当前生效</h3>
            <p>生成任务会即时读取此配置</p>
          </div>
          <el-tag :type="config.source === 'database' ? 'primary' : 'info'" effect="plain">
            {{ config.source === 'database' ? '自定义配置' : '环境变量' }}
          </el-tag>
        </div>

        <dl class="runtime-list">
          <div>
            <dt>服务</dt>
            <dd>{{ config.provider_name || '-' }}</dd>
          </div>
          <div>
            <dt>模型</dt>
            <dd>{{ config.model || '-' }}</dd>
          </div>
          <div>
            <dt>协议</dt>
            <dd>{{ protocolLabel(config.protocol) }}</dd>
          </div>
          <div>
            <dt>地址</dt>
            <dd class="break-value">{{ config.base_url || '-' }}</dd>
          </div>
          <div>
            <dt>密钥</dt>
            <dd>{{ config.api_key_configured ? (config.api_key_hint || '已配置') : '未配置' }}</dd>
          </div>
          <div>
            <dt>超时</dt>
            <dd>{{ config.timeout_seconds || 120 }} 秒</dd>
          </div>
        </dl>

        <div v-if="testResult" class="test-result" role="status">
          <div class="test-result-head">
            <span class="success-dot"></span>
            <strong>连接成功</strong>
            <span>{{ testResult.latency_ms }} ms</span>
          </div>
          <p>{{ testResult.preview || '模型已正常响应' }}</p>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../../utils/request'

const formRef = ref(null)
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const testResult = ref(null)

const emptyConfig = () => ({
  source: 'environment',
  provider_name: '',
  protocol: 'chat_completions',
  base_url: '',
  model: '',
  api_key_configured: false,
  api_key_hint: null,
  timeout_seconds: 120,
})

const config = reactive(emptyConfig())
const form = reactive({
  provider_name: '',
  protocol: 'chat_completions',
  base_url: '',
  model: '',
  api_key: '',
  timeout_seconds: 120,
})

const rules = {
  provider_name: [{ required: true, message: '请输入配置名称', trigger: 'blur' }],
  protocol: [{ required: true, message: '请选择接口协议', trigger: 'change' }],
  base_url: [
    { required: true, message: '请输入 API Base URL', trigger: 'blur' },
    { pattern: /^https?:\/\/[^\s]+$/i, message: '请输入有效的 http/https 地址', trigger: 'blur' },
  ],
  model: [{ required: true, message: '请输入模型名称', trigger: 'blur' }],
  timeout_seconds: [{ required: true, message: '请输入请求超时', trigger: 'change' }],
}

const keyPlaceholder = computed(() => {
  if (config.source === 'database' && config.api_key_configured) {
    return `留空保留当前密钥 ${config.api_key_hint || ''}`.trim()
  }
  return '输入 API Key'
})

function protocolLabel(value) {
  return value === 'responses' ? 'Responses' : 'Chat Completions'
}

function applyConfig(data) {
  Object.assign(config, emptyConfig(), data || {})
  Object.assign(form, {
    provider_name: config.provider_name,
    protocol: config.protocol,
    base_url: config.base_url,
    model: config.model,
    api_key: '',
    timeout_seconds: config.timeout_seconds,
  })
  testResult.value = null
}

function payload() {
  return {
    provider_name: form.provider_name.trim(),
    protocol: form.protocol,
    base_url: form.base_url.trim().replace(/\/+$/, ''),
    model: form.model.trim(),
    api_key: form.api_key.trim() || null,
    timeout_seconds: form.timeout_seconds,
  }
}

async function loadConfig() {
  loading.value = true
  try {
    const res = await request.get('/settings/llm')
    applyConfig(res.data)
  } finally {
    loading.value = false
  }
}

async function validateForm() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return false
  if (!form.api_key.trim() && config.source !== 'database') {
    ElMessage.warning('首次保存或测试需要填写 API Key')
    return false
  }
  return true
}

async function saveConfig() {
  if (!(await validateForm())) return
  saving.value = true
  try {
    const res = await request.put('/settings/llm', payload())
    applyConfig(res.data)
    ElMessage.success('模型配置已保存并立即生效')
  } finally {
    saving.value = false
  }
}

async function testConnection() {
  if (!(await validateForm())) return
  testing.value = true
  testResult.value = null
  try {
    const res = await request.post('/settings/llm/test', payload(), { timeout: 310000 })
    testResult.value = res.data
    ElMessage.success(`连接成功，耗时 ${res.data.latency_ms} ms`)
  } finally {
    testing.value = false
  }
}

async function restoreEnvironment() {
  await ElMessageBox.confirm('确认删除自定义模型配置并恢复环境变量配置？', '恢复环境配置', {
    type: 'warning',
    confirmButtonText: '确认恢复',
    cancelButtonText: '取消',
  })
  const res = await request.delete('/settings/llm')
  applyConfig(res.data)
  ElMessage.success('已恢复环境变量配置')
}

onMounted(loadConfig)
</script>

<style scoped>
.llm-settings-page { max-width: 1180px; margin: 0 auto; }
.settings-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 330px;
  gap: 16px;
  align-items: start;
}
.config-surface,
.runtime-surface {
  background: var(--wm-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-xs);
}
.config-surface { padding: 20px; }
.runtime-surface { overflow: hidden; }
.surface-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}
.runtime-surface .surface-header { padding: 18px 18px 14px; margin-bottom: 0; border-bottom: 1px solid var(--color-border); }
.surface-header h3 { margin: 0 0 4px; color: var(--color-ink); font-size: 16px; line-height: 1.4; }
.surface-header p { margin: 0; color: var(--color-ink-tertiary); font-size: 13px; line-height: 1.5; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 18px; }
.wide-field { grid-column: 1 / -1; }
.protocol-switch { display: flex; width: 100%; }
.protocol-switch :deep(.el-radio-button) { flex: 1; }
.protocol-switch :deep(.el-radio-button__inner) { width: 100%; }
.config-form :deep(.el-input-number) { width: calc(100% - 36px); }
.unit-label { margin-left: 10px; color: var(--color-ink-secondary); font-size: 13px; }
.form-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding-top: 4px; }
.runtime-list { margin: 0; padding: 4px 18px 10px; }
.runtime-list > div {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 12px;
  padding: 11px 0;
  border-bottom: 1px solid var(--wm-surface-subtle);
}
.runtime-list > div:last-child { border-bottom: 0; }
.runtime-list dt { color: var(--color-ink-tertiary); font-size: 12px; }
.runtime-list dd { margin: 0; color: var(--color-ink); font-size: 13px; font-weight: 600; text-align: right; }
.break-value { overflow-wrap: anywhere; line-height: 1.45; }
.test-result { margin: 0 18px 18px; padding: 12px; border-radius: var(--radius-sm); background: rgba(13, 150, 104, 0.07); }
.test-result-head { display: flex; align-items: center; gap: 8px; color: var(--color-success); font-size: 13px; }
.test-result-head span:last-child { margin-left: auto; color: var(--color-ink-secondary); }
.success-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--color-success); flex: 0 0 auto; }
.test-result p { margin: 8px 0 0; color: var(--color-ink-secondary); font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
@media (max-width: 960px) {
  .settings-layout { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .config-surface { padding: 16px; }
  .form-grid { grid-template-columns: 1fr; }
  .wide-field { grid-column: auto; }
  .protocol-switch { display: grid; grid-template-columns: 1fr; }
  .form-actions .el-button { width: 100%; margin-left: 0; }
}
</style>
