<template>
  <div class="not-found">
    <div class="nf-code">404</div>
    <h1 class="nf-title">页面不存在</h1>
    <p class="nf-desc">您访问的页面可能已被移除或链接有误。</p>
    <div class="nf-actions">
      <el-button type="primary" @click="goHome">返回工作台</el-button>
      <el-button @click="goBack">返回上一页</el-button>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
const router = useRouter()
const goHome = () => router.push('/dashboard')
const goBack = () => router.go(-1)
</script>

<style scoped>
.not-found {
  min-height: 70vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 40px 20px;
}
.nf-code {
  font-size: 96px;
  font-weight: 800;
  line-height: 1;
  background: linear-gradient(135deg, #0f6bc5, #3b9eff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin-bottom: 12px;
}
.nf-title { font-size: 22px; color: var(--color-ink); margin-bottom: 8px; }
.nf-desc { color: var(--color-ink-tertiary); margin-bottom: 24px; }
.nf-actions { display: flex; gap: 12px; }
</style>
