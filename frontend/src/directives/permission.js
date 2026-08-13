import { useAuthStore } from '../stores/auth'

/**
 * 权限指令 v-permission
 * 用法：
 *   v-permission="'admin'"              // 单角色
 *   v-permission="['admin','operator']" // 多角色（任一满足）
 * 当用户角色不匹配时，元素隐藏
 */
export const permission = {
  mounted(el, binding) {
    const auth = useAuthStore()
    const required = binding.value
    if (!required) return
    const userRole = auth.user?.role
    if (!userRole) {
      el.style.display = 'none'
      return
    }
    const allowed = Array.isArray(required) ? required : [required]
    if (!allowed.includes(userRole)) {
      el.style.display = 'none'
    }
  },
}

/**
 * 角色指令 v-role
 * 用法：v-role="'admin'"
 */
export const role = {
  mounted(el, binding) {
    const auth = useAuthStore()
    const required = binding.value
    if (!required) return
    const userRole = auth.user?.role
    if (!userRole || userRole !== required) {
      el.style.display = 'none'
    }
  },
}

/**
 * 注册所有自定义指令
 */
export function setupDirectives(app) {
  app.directive('permission', permission)
  app.directive('role', role)
}
