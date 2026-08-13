// 验证码 / 人机验证 / noVNC 远程桌面相关 API
// 复用 frontend/src/utils/request.js 的 axios 实例（baseURL=/api/v1，timeout=30000）
// request 响应拦截器会返回完整响应体 { code, message, data }，因此这里取 res.data 作为业务数据
//
// 路径前缀 /social/publish 与后端 social_publish.py 路由一致
// （注意：/publish 是内容发布包路由 publish.py，不要混淆）

import request from './request'

// 获取所有待处理的验证任务列表
// 返回: [{ task_id, platform, nickname, verification_type, status, appeared_at, captcha_hint, screenshot_url, ... }]
export async function getPendingVerifications(config = {}) {
  const res = await request.get('/social/publish/verifications/pending', config)
  return res.data || []
}

// 提交手机验证码
// payload: { code }
export async function submitPhoneCaptcha(taskId, code) {
  const res = await request.post(
    `/social/publish/tasks/${taskId}/captcha`,
    { code },
    { silentError: true }
  )
  return res.data
}

// 验证截图需要登录鉴权，必须通过 request 取 Blob，不能把相对路径直接交给 img。
export async function getVerificationScreenshot(taskId, config = {}) {
  return request.get(`/social/publish/tasks/${taskId}/verification/screenshot`, {
    ...config,
    responseType: 'blob',
  })
}

// 人机验证完成后恢复发布
export async function resumePublish(taskId) {
  const res = await request.post(`/social/publish/tasks/${taskId}/resume`)
  return res.data
}

// 获取该任务的 noVNC 会话信息
// 返回: { session_id, vnc_password, ... }
export async function getVncSession(taskId, config = {}) {
  const res = await request.get(`/social/publish/tasks/${taskId}/vnc-session`, config)
  return res.data || {}
}

// 忽略该验证（标记为放弃，任务失败）
export async function dismissVerification(taskId) {
  const res = await request.post(`/social/publish/tasks/${taskId}/verification/dismiss`)
  return res.data
}
