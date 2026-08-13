<template>
  <el-config-provider :locale="zhCn">
    <router-view v-slot="{ Component }">
      <transition name="rb-route" mode="out-in">
        <component :is="Component" />
      </transition>
    </router-view>
    <div class="route-loading-bar" aria-hidden="true"></div>
  </el-config-provider>
</template>

<script setup>
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import { useScrollReveal } from './composables/useScrollReveal'
useScrollReveal()
</script>

<style>
/* ===== 路由切换顶部进度条 ===== */
.route-loading-bar {
  position: fixed; top: 0; left: 0; height: 2px; width: 0;
  background: #0f6bc5;
  z-index: 9999; opacity: 0;
  transition: width 0.3s ease, opacity 0.2s ease;
  pointer-events: none;
}
body.route-loading .route-loading-bar {
  opacity: 1; width: 80%;
  animation: route-loading-grow 1.2s ease-out forwards;
}
@keyframes route-loading-grow {
  0% { width: 0; }
  50% { width: 70%; }
  100% { width: 90%; }
}

/* ===== 路由切换转场 ===== */
.rb-route-enter-active { animation: rb-page-enter 0.25s ease-out; }
.rb-route-leave-active { animation: rb-page-leave 0.15s ease-out forwards; }
@keyframes rb-page-enter {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes rb-page-leave {
  from { opacity: 1; }
  to   { opacity: 0; }
}

/* ===== 设计 Token ===== */
:root {
  --color-bg: #f5f7fa;
  --color-surface: #ffffff;
  --color-surface-subtle: #f0f3f7;
  --color-ink: #1a2332;
  --color-ink-secondary: #4a5568;
  --color-ink-tertiary: #718096;
  --color-border: #e2e8f0;
  --color-border-light: #edf2f7;

  --color-accent: #0f6bc5;
  --color-accent-light: #3b9eff;
  --color-accent-dark: #0a4d8f;
  --color-success: #0d9668;
  --color-warning: #d97706;
  --color-danger: #dc2626;
  --color-info: #0891b2;

  --shadow-xs: 0 1px 2px rgba(0,0,0,0.04);
  --shadow-sm: 0 2px 8px rgba(0,0,0,0.06);
  --shadow-md: 0 4px 16px rgba(0,0,0,0.08);

  --radius-sm: 8px;
  --radius-md: 10px;
  --radius-lg: 14px;

  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;

  --transition-fast: 0.15s ease;
  --transition-base: 0.2s ease;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
  background: var(--color-bg);
  color: var(--color-ink);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

*:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; }

/* ===== Element Plus 覆盖：按钮统一加大、primary 纯色白字 ===== */
.el-button {
  min-height: 36px;
  padding: 8px 16px;
  font-size: 14px;
  border-radius: var(--radius-sm) !important;
  transition: background-color var(--transition-fast), border-color var(--transition-fast), color var(--transition-fast) !important;
}
.el-button:active { transform: scale(0.98); }
.el-button--small {
  min-height: 30px;
  padding: 5px 12px;
  font-size: 13px;
}
.el-button--large {
  min-height: 42px;
  padding: 11px 20px;
  font-size: 15px;
}
/* primary：纯色 #0f6bc5，白字，hover 更深蓝 */
.el-button--primary {
  background: #0f6bc5 !important;
  border: 1px solid #0f6bc5 !important;
  color: #ffffff !important;
  box-shadow: none !important;
}
.el-button--primary:hover,
.el-button--primary:focus {
  background: #0a4d8f !important;
  border-color: #0a4d8f !important;
  color: #ffffff !important;
  transform: none !important;
  box-shadow: none !important;
}
.el-button--primary.is-plain {
  background: rgba(15, 107, 197, 0.08) !important;
  border: 1px solid rgba(15, 107, 197, 0.3) !important;
  color: #0f6bc5 !important;
}
.el-button--primary.is-plain:hover {
  background: #0f6bc5 !important;
  border-color: #0f6bc5 !important;
  color: #ffffff !important;
}
.el-button--success {
  background: #0d9668 !important;
  border: 1px solid #0d9668 !important;
  color: #ffffff !important;
  box-shadow: none !important;
}
.el-button--success:hover { background: #065f46 !important; border-color: #065f46 !important; }
.el-button--warning {
  background: #d97706 !important;
  border: 1px solid #d97706 !important;
  color: #ffffff !important;
  box-shadow: none !important;
}
.el-button--warning:hover { background: #92400e !important; border-color: #92400e !important; }
.el-button--danger {
  background: #dc2626 !important;
  border: 1px solid #dc2626 !important;
  color: #ffffff !important;
  box-shadow: none !important;
}
.el-button--danger:hover { background: #991b1b !important; border-color: #991b1b !important; }
/* link 按钮可读：适合后台表格点击 */
.el-button.is-link {
  min-height: 28px;
  padding: 4px 8px;
  line-height: 20px;
  box-shadow: none !important;
}
.el-button.is-link:hover { transform: none !important; }
/* logout-btn 在 Layout 侧边栏底部，保持紧凑布局 */
.logout-btn.el-button.is-link {
  min-height: auto !important;
  padding: 4px 8px !important;
  line-height: 1.4 !important;
}

/* ===== el-card：普通白卡，不再全站玻璃 ===== */
.el-main .el-card {
  border-radius: var(--radius-lg) !important;
  border: 1px solid var(--color-border) !important;
  background: var(--color-surface) !important;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  color: var(--color-ink) !important;
  box-shadow: var(--shadow-xs) !important;
  transition: box-shadow var(--transition-fast) !important;
}
.el-main .el-card:hover {
  transform: none !important;
  box-shadow: var(--shadow-sm) !important;
}

/* ===== 标签：稳定，不弹跳 ===== */
.el-tag { transition: none !important; }
.el-tag:hover { transform: none !important; }

/* ===== 输入框：稳定白底 ===== */
.el-main .el-input__wrapper {
  border-radius: var(--radius-sm) !important;
  background: var(--color-surface) !important;
  box-shadow: none !important;
  border: 1px solid var(--color-border) !important;
  transition: border-color var(--transition-fast) !important;
}
.el-main .el-input__wrapper:hover { border-color: var(--color-accent-light) !important; box-shadow: none !important; }
.el-main .el-input__wrapper.is-focus { border-color: var(--color-accent) !important; box-shadow: 0 0 0 3px rgba(15, 107, 197, 0.1) !important; }
.el-main .el-input__inner { color: var(--color-ink) !important; }
.el-main .el-input__inner::placeholder { color: var(--color-ink-tertiary) !important; }
.el-main .el-select .el-input__wrapper { border-radius: var(--radius-sm) !important; }

/* ===== 对话框：白底 ===== */
.el-dialog {
  border-radius: var(--radius-lg) !important;
  background: var(--color-surface) !important;
  border: 1px solid var(--color-border) !important;
  box-shadow: var(--shadow-md) !important;
}
.el-dialog__title { color: var(--color-ink) !important; font-weight: 600; }
.el-dialog__headerbtn:hover .el-dialog__close { color: var(--color-accent) !important; }

/* ===== Tabs：active 纯色下划线 ===== */
.el-main .el-tabs__item { font-weight: 500; color: var(--color-ink-secondary) !important; transition: color var(--transition-fast) !important; }
.el-main .el-tabs__item.is-active { color: var(--color-accent) !important; font-weight: 600; }
.el-main .el-tabs__item:hover { color: var(--color-accent) !important; }
.el-main .el-tabs__active-bar { background: var(--color-accent) !important; height: 2px !important; }
.el-main .el-tabs__nav-wrap::after { background-color: var(--color-border-light) !important; }

/* ===== 表格：稳定可读，不做行进入动画，hover 轻微底色 ===== */
.el-main .el-table {
  font-size: 14px;
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: var(--color-surface-subtle);
  --el-table-row-hover-bg-color: rgba(15, 107, 197, 0.04);
  --el-table-border-color: var(--color-border);
  --el-table-text-color: var(--color-ink);
  --el-table-header-text-color: var(--color-ink-secondary);
}
.el-main .el-table th.el-table__cell { background: var(--color-surface-subtle) !important; font-weight: 600; }
.el-main .el-table__row { transition: background-color var(--transition-fast) !important; }
.el-main .el-table__row:hover { transform: none !important; }
.el-main .el-table .cell { line-height: 1.5; }
.el-main .el-empty__description p { color: var(--color-ink-tertiary) !important; }
.el-main .el-form-item__label { color: var(--color-ink-secondary) !important; }
.el-main .el-textarea__inner {
  background: var(--color-surface) !important;
  color: var(--color-ink) !important;
  border-color: var(--color-border) !important;
  border-radius: var(--radius-sm) !important;
}

/* ===== 下拉/弹层：白底 ===== */
.el-select-dropdown { background: var(--color-surface) !important; border-color: var(--color-border) !important; backdrop-filter: none; }
.el-select-dropdown__item { color: var(--color-ink-secondary) !important; }
.el-select-dropdown__item.hover, .el-select-dropdown__item:hover { background: rgba(15, 107, 197, 0.06) !important; color: var(--color-ink) !important; }
.el-select-dropdown__item.selected { color: var(--color-accent) !important; font-weight: 600; }
.el-popper.is-light { background: var(--color-surface) !important; border-color: var(--color-border) !important; backdrop-filter: none; }
.el-popper.is-light .el-popper__arrow::before { background: var(--color-surface) !important; border-color: var(--color-border) !important; }
.el-message-box { background: var(--color-surface) !important; border-color: var(--color-border) !important; border-radius: var(--radius-lg) !important; backdrop-filter: none; }
.el-message-box__title { color: var(--color-ink) !important; }
.el-message-box__message { color: var(--color-ink-secondary) !important; }
.el-overlay-message-box {
  padding: 24px !important;
  align-items: center !important;
  justify-content: center !important;
}
.review-confirm-box {
  width: min(440px, calc(100vw - 32px)) !important;
  padding: 22px 24px 20px !important;
  border: 1px solid rgba(15, 107, 197, 0.16) !important;
  border-radius: 16px !important;
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.22) !important;
}
.review-confirm-box .el-message-box__header {
  padding-bottom: 14px !important;
}
.review-confirm-box .el-message-box__title {
  font-size: 18px !important;
  font-weight: 700 !important;
  line-height: 1.4 !important;
}
.review-confirm-box .el-message-box__content {
  padding: 4px 0 18px !important;
}
.review-confirm-box .el-message-box__container {
  align-items: flex-start !important;
  gap: 12px;
}
.review-confirm-box .el-message-box__status {
  margin-top: 2px;
  color: var(--color-success) !important;
}
.review-confirm-box .el-message-box__message {
  padding: 0 !important;
  font-size: 14px;
  line-height: 1.75;
}
.review-confirm-box .el-message-box__btns {
  gap: 10px;
  padding-top: 2px !important;
}
.review-confirm-box .el-message-box__btns .el-button {
  min-width: 96px;
  margin-left: 0 !important;
}
.el-overlay {
  position: fixed !important;
  inset: 0 !important;
  width: 100vw !important;
  height: 100vh !important;
  min-height: 100vh !important;
  background-color: rgba(15, 23, 42, 0.45) !important;
  backdrop-filter: none;
}
.el-overlay-dialog {
  position: fixed !important;
  inset: 0 !important;
  min-height: 100vh !important;
  overflow: auto !important;
}
.el-message { background: var(--color-surface) !important; border: 1px solid var(--color-border) !important; border-radius: var(--radius-md) !important; backdrop-filter: none; }

@media (max-width: 520px) {
  .el-overlay-message-box { padding: 16px !important; }
  .review-confirm-box { padding: 20px 18px 18px !important; }
  .review-confirm-box .el-message-box__btns {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
  .review-confirm-box .el-message-box__btns .el-button { width: 100%; }
}

/* ===== 分页 ===== */
.el-main .el-pagination {
  --el-pagination-bg-color: var(--color-surface);
  --el-pagination-text-color: var(--color-ink-secondary);
  --el-pagination-button-bg-color: var(--color-surface-subtle);
  --el-pagination-hover-color: var(--color-accent);
}

/* ===== 进度条/描述列表 ===== */
.el-main .el-progress-bar__outer { background-color: rgba(15, 23, 42, 0.08) !important; }
.el-main .el-descriptions { background: transparent !important; }
.el-main .el-descriptions__body { background: transparent !important; }
.el-main .el-descriptions.is-bordered .el-descriptions__body { border-radius: var(--radius-md); overflow: hidden; }

/* ===== radio-button：active 纯色 ===== */
.el-main .el-radio-button__inner { transition: color var(--transition-fast), background-color var(--transition-fast) !important; }
.el-main .el-radio-button__original-radio:checked + .el-radio-button__inner {
  background: #0f6bc5 !important;
  border-color: #0f6bc5 !important;
  color: #fff !important;
  box-shadow: none !important;
}
</style>
