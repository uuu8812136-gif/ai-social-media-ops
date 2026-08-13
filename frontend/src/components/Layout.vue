<template>
  <el-container class="layout">
    <el-aside width="240px" class="aside desktop-aside">
      <div class="aside-glow"></div>
      <div class="logo">
        <div class="logo-icon-wrap">
          <span class="logo-icon">AI</span>
        </div>
        <div class="logo-text-group">
          <span class="logo-text">社媒协作平台</span>
          <span class="logo-version">v1.0</span>
        </div>
      </div>
      <div class="aside-scroll">
        <el-menu
          :default-active="$route.path"
          :default-openeds="defaultOpeneds"
          router
          background-color="transparent"
          text-color="rgba(255,255,255,0.75)"
          active-text-color="#60a5fa"
          @select="handleMenuSelect"
        >
          <el-sub-menu v-for="section in navSections" :key="section.index" :index="section.index">
            <template #title>
              <span class="menu-section-title">{{ section.title }}</span>
            </template>
            <el-menu-item v-for="item in section.items" :key="item.index" :index="item.index" :aria-label="item.label" :title="item.label">
              <el-icon><component :is="item.icon" /></el-icon>
              <span>{{ item.label }}</span>
            </el-menu-item>
          </el-sub-menu>
        </el-menu>
      </div>
      <div class="aside-footer">
        <div class="user-block">
          <el-avatar :size="36" class="user-avatar">{{ auth.user?.full_name?.[0] || 'U' }}</el-avatar>
          <div class="user-info">
            <span class="user-name">{{ auth.user?.full_name || '未登录' }}</span>
            <span class="user-role">{{ roleLabel }}</span>
          </div>
          <el-button type="danger" link size="small" class="logout-btn" @click="handleLogout" title="退出登录">
            <el-icon><SwitchButton /></el-icon>
            <span class="logout-text">退出</span>
          </el-button>
        </div>
        <div class="sys-status">
          <div :class="['status-dot', healthOk ? 'rb-pulse-dot' : 'status-dot--error']"></div>
          <span>{{ healthText }}</span>
        </div>
      </div>
    </el-aside>
    <el-container class="content-shell">
      <el-header class="desktop-header">
        <div class="header-left">
          <span class="header-title">社媒矩阵运营</span>
        </div>
      </el-header>
      <el-header class="mobile-header">
        <el-button class="mobile-menu-btn" text :icon="MenuIcon" @click="drawerVisible = true" aria-label="展开导航" title="展开导航" />
        <span class="mobile-title">社媒协作平台</span>
      </el-header>
      <el-main class="main-content"><router-view /></el-main>
    </el-container>
    <el-drawer v-model="drawerVisible" direction="ltr" size="240px" :with-header="false" class="mobile-nav-drawer">
      <div class="drawer-aside">
        <div class="logo">
          <div class="logo-icon-wrap">
            <span class="logo-icon">AI</span>
          </div>
          <div class="logo-text-group">
            <span class="logo-text">社媒协作平台</span>
            <span class="logo-version">v1.0</span>
          </div>
        </div>
        <div class="aside-scroll">
          <el-menu
            :default-active="$route.path"
            :default-openeds="defaultOpeneds"
            router
            background-color="transparent"
            text-color="rgba(255,255,255,0.75)"
            active-text-color="#60a5fa"
            @select="handleMenuSelect"
          >
            <el-sub-menu v-for="section in navSections" :key="section.index" :index="section.index">
              <template #title>
                <span class="menu-section-title">{{ section.title }}</span>
              </template>
              <el-menu-item v-for="item in section.items" :key="item.index" :index="item.index" :aria-label="item.label" :title="item.label">
                <el-icon><component :is="item.icon" /></el-icon>
                <span>{{ item.label }}</span>
              </el-menu-item>
            </el-sub-menu>
          </el-menu>
        </div>
      </div>
    </el-drawer>
  </el-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import {
  Calendar,
  Collection,
  DataAnalysis,
  Download,
  Edit,
  Folder,
  Menu as MenuIcon,
  Phone,
  Promotion,
  Setting,
  Shop,
  SwitchButton,
  UserFilled,
} from '@element-plus/icons-vue'

const auth = useAuthStore()
const router = useRouter()
const roleLabel = computed(() => ({ admin: '管理员', operator: '运营官', dealer: '经销商' }[auth.user?.role] || ''))
const drawerVisible = ref(false)
const healthOk = ref(true)
let healthTimer = null

const navSections = computed(() => {
  const sections = [
    {
      index: 'core',
      title: '核心功能',
      items: [
        { index: '/dashboard', label: '数据看板', icon: DataAnalysis },
        { index: '/content', label: '内容工厂', icon: Edit },
        { index: '/knowledge', label: '知识库', icon: Collection },
        { index: '/calendar', label: '内容日历', icon: Calendar },
      ],
    },
    {
      index: 'operation',
      title: '运营管理',
      items: [
        { index: '/leads', label: '线索管理', icon: Phone },
        { index: '/dealers', label: '经销商管理', icon: Shop },
        { index: '/assets', label: '素材库', icon: Folder },
      ],
    },
    {
      index: 'social',
      title: '社媒矩阵',
      items: [
        { index: '/social-publish', label: '社媒矩阵', icon: Promotion },
        { index: '/crawler', label: '数据采集', icon: Download },
      ],
    },
  ]
  if (auth.user?.role === 'admin') {
    sections.push({
      index: 'system',
      title: '系统管理',
      items: [
        { index: '/settings/users', label: '账号管理', icon: UserFilled },
        { index: '/settings/llm', label: '模型配置', icon: Setting },
      ],
    })
  }
  return sections
})
const defaultOpeneds = computed(() => navSections.value.map((section) => section.index))
const healthText = computed(() => (healthOk.value ? '系统运行正常' : '后端连接异常'))

function handleMenuSelect() {
  drawerVisible.value = false
}

async function checkHealth() {
  try {
    const res = await fetch('/health', { cache: 'no-store' })
    healthOk.value = res.ok
  } catch (e) {
    healthOk.value = false
  }
}

onMounted(() => {
  checkHealth()
  healthTimer = window.setInterval(checkHealth, 30000)
})

onUnmounted(() => {
  if (healthTimer) window.clearInterval(healthTimer)
})

async function handleLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.layout { height: 100vh; position: relative; z-index: 1; }
.content-shell { min-width: 0; height: 100vh; }

.aside {
  position: relative;
  background: #001529;
  overflow-y: auto;
  overflow-x: hidden;
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  flex-direction: column;
}
.aside-glow { display: none; }
.drawer-aside {
  height: 100%;
  background: #001529;
  display: flex;
  flex-direction: column;
}
:deep(.mobile-nav-drawer .el-drawer__body) {
  padding: 0;
  background: #001529;
}
.aside::-webkit-scrollbar { width: 4px; }
.aside::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.10); border-radius: 2px; }
.aside::-webkit-scrollbar-thumb:hover { background: rgba(255, 255, 255, 0.20); }

.aside-scroll {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  position: relative;
  z-index: 1;
}
.aside-scroll::-webkit-scrollbar { width: 4px; }
.aside-scroll::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.10); border-radius: 2px; }

.logo {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  position: relative;
  z-index: 1;
  flex-shrink: 0;
}
.logo-icon-wrap {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: var(--wm-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.logo-icon-wrap:hover { transform: none; }
.logo-icon { font-size: 13px; font-weight: 700; color: #fff; letter-spacing: 0.02em; }
.logo-text-group { display: flex; flex-direction: column; }
.logo-text { color: #f1f5f9; font-size: 15px; font-weight: 700; white-space: nowrap; letter-spacing: -0.01em; }
.logo-version { font-size: 10px; color: rgba(255, 255, 255, 0.35); font-weight: 500; margin-top: 1px; }

.menu-section-title {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: rgba(255, 255, 255, 0.32);
}

:deep(.el-menu) { border-right: none !important; background: transparent !important; }
:deep(.el-sub-menu__title) {
  height: 34px;
  line-height: 34px;
  margin-top: 6px;
  padding: 0 20px !important;
  color: rgba(255, 255, 255, 0.32) !important;
  background: transparent !important;
}
:deep(.el-sub-menu__title:hover) { background: transparent !important; color: rgba(255, 255, 255, 0.45) !important; }
:deep(.el-sub-menu__title .el-sub-menu__icon-arrow) {
  right: 14px;
  color: rgba(255, 255, 255, 0.32);
}
:deep(.el-menu-item) {
  border-radius: 8px;
  margin: 2px 10px;
  height: 40px;
  line-height: 40px;
  transition: background-color 0.2s ease, color 0.2s ease;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.75) !important;
  position: relative;
  overflow: hidden;
}
:deep(.el-menu-item::before) {
  content: "";
  position: absolute;
  left: 0; top: 50%;
  width: 3px; height: 0;
  background: #3b9eff;
  transform: translateY(-50%);
  transition: height 0.2s ease;
  border-radius: 0 3px 3px 0;
}
:deep(.el-menu-item .el-icon) { color: rgba(255, 255, 255, 0.55) !important; transition: color 0.2s ease; font-size: 16px; }
:deep(.el-menu-item:hover) {
  background: rgba(255, 255, 255, 0.06) !important;
  color: #fff !important;
}
:deep(.el-menu-item:hover .el-icon) { color: rgba(255, 255, 255, 0.95) !important; }
:deep(.el-menu-item.is-active) {
  background: var(--wm-primary) !important;
  color: #fff !important;
  font-weight: 500;
}
:deep(.el-menu-item.is-active::before) { height: 0; }
:deep(.el-menu-item.is-active .el-icon) { color: #fff !important; }

.aside-footer {
  margin-top: auto;
  padding: 12px 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  position: relative;
  z-index: 1;
  flex-shrink: 0;
  background: rgba(0, 0, 0, 0.15);
}
.user-block {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 4px 10px;
}
.user-avatar {
  background: var(--wm-primary) !important;
  font-weight: 600;
  font-size: 14px;
  color: #fff !important;
  flex-shrink: 0;
}
.user-info {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
  flex: 1;
  min-width: 0;
}
.user-name {
  font-size: 13px;
  font-weight: 600;
  color: #f1f5f9;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.user-role {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.5);
}
.logout-btn {
  color: rgba(255, 255, 255, 0.5) !important;
  padding: 4px 8px !important;
  min-height: auto !important;
  flex-shrink: 0;
  gap: 4px;
}
.logout-btn:hover { color: #fca5a5 !important; }
.logout-text { font-size: 12px; white-space: nowrap; }
.sys-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.45);
  padding-top: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}
.status-dot--error { background: #f87171; box-shadow: 0 0 0 4px rgba(248, 113, 113, 0.16); }

.main-content {
  background: #f5f7fa;
  padding: 24px;
  overflow-y: auto;
  position: relative;
  z-index: 1;
  height: 100vh;
}
.mobile-header {
  display: none;
  height: 56px;
  align-items: center;
  gap: 10px;
  padding: 0 12px;
  background: #fff;
  border-bottom: 1px solid var(--wm-border-light);
}
.mobile-menu-btn {
  width: 36px;
  height: 36px;
  color: var(--wm-text-primary) !important;
}
.mobile-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--wm-text-primary);
}

.desktop-header {
  display: none; /* 桌面端由媒体查询显示 */
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 56px;
  background: rgba(255,255,255,0.04);
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.header-title { font-size: 15px; color: rgba(255,255,255,0.85); }
.header-right { display: flex; align-items: center; gap: 12px; }
@media (min-width: 992px) {
  .desktop-header { display: flex; }
}

@media (prefers-reduced-motion: reduce) {
  .aside-glow { animation: none !important; }
  .logo-icon-wrap, :deep(.el-menu-item) { transition: none !important; }
}

@media (max-width: 768px) {
  .desktop-aside { display: none; }
  .content-shell { height: 100vh; }
  .mobile-header { display: flex; }
  .main-content { height: calc(100vh - 56px); padding: 12px; }
}
</style>
