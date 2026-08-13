import { ElMessageBox, ElMessage } from 'element-plus'
import { humanizeError } from './errorMessage'

/**
 * 统一确认弹窗（参考 RuoYi 的 confirmBox）
 * 自动处理 cancel rejection，避免控制台报错
 *
 * @param {string} message 提示消息
 * @param {string} title 标题
 * @param {object} options 额外选项
 * @returns {Promise<boolean>} true=确认, false=取消
 */
export async function confirm(message, title = '操作确认', options = {}) {
  try {
    await ElMessageBox.confirm(message, title, {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
      ...options,
    })
    return true
  } catch {
    return false
  }
}

/**
 * 删除确认弹窗
 */
export async function confirmDelete(message = '确认删除？此操作不可撤销。') {
  return confirm(message, '删除确认', { type: 'error', confirmButtonText: '确认删除' })
}

/**
 * 成功提示
 */
export function success(message) {
  ElMessage.success(message)
}

/**
 * 错误提示
 */
export function error(message) {
  ElMessage.error(humanizeError(message))
}

/**
 * 警告提示
 */
export function warning(message) {
  ElMessage.warning(message)
}
