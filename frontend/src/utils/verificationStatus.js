// 验证码 / 人机验证相关常量与映射

// 验证类型
export const VERIFICATION_TYPES = {
  PHONE_CAPTCHA: 'phone_captcha',
  HUMAN_CAPTCHA: 'human_captcha',
}

// 验证类型中文文案
export const VERIFICATION_TYPE_LABELS = {
  phone_captcha: '手机验证码',
  human_captcha: '人机验证',
}

// 任务状态中与验证相关的值
export const VERIFICATION_TASK_STATUS = {
  NEEDS_PHONE_CAPTCHA: 'needs_phone_captcha',
  NEEDS_HUMAN_CAPTCHA: 'needs_human_captcha',
  AWAITING_RESUME: 'awaiting_resume',
}

// 验证相关状态集合（用于 isVerificationStatus 判断）
export const VERIFICATION_STATUS_SET = new Set([
  VERIFICATION_TASK_STATUS.NEEDS_PHONE_CAPTCHA,
  VERIFICATION_TASK_STATUS.NEEDS_HUMAN_CAPTCHA,
  VERIFICATION_TASK_STATUS.AWAITING_RESUME,
])

// 验证类型元信息：图标名（@element-plus/icons-vue）、颜色、el-tag 类型
export const VERIFICATION_TYPE_META = {
  phone_captcha: {
    label: '手机验证码',
    icon: 'Cellphone',
    color: '#d97706',
    tagType: 'warning',
  },
  human_captcha: {
    label: '人机验证',
    icon: 'Monitor',
    color: '#8b5cf6',
    tagType: 'primary',
  },
}

// 默认元信息（未知类型兜底）
const DEFAULT_META = {
  label: '未知验证',
  icon: 'QuestionFilled',
  color: '#718096',
  tagType: 'info',
}

// 判断任务状态是否属于验证相关状态
export function isVerificationStatus(status) {
  return VERIFICATION_STATUS_SET.has(status)
}

// 根据验证类型获取中文文案
export function verificationTypeLabel(type) {
  return VERIFICATION_TYPE_LABELS[type] || type || '未知验证'
}

// 根据验证类型获取元信息（图标 / 颜色 / tag 类型）
export function verificationTypeMeta(type) {
  return VERIFICATION_TYPE_META[type] || { ...DEFAULT_META }
}

// 任务状态 → 验证类型映射（needs_phone_captcha → phone_captcha 等）
export function statusToVerificationType(status) {
  if (status === VERIFICATION_TASK_STATUS.NEEDS_PHONE_CAPTCHA) return VERIFICATION_TYPES.PHONE_CAPTCHA
  if (status === VERIFICATION_TASK_STATUS.NEEDS_HUMAN_CAPTCHA) return VERIFICATION_TYPES.HUMAN_CAPTCHA
  return null
}
