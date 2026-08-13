import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '../router'
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from './authStorage'
import { humanizeError } from './errorMessage'

const request = axios.create({ baseURL: '/api/v1', timeout: 30000 })

let isRedirecting = false
let isRefreshing = false
let pendingQueue = []

const TEXT = {
  networkError: '\u7f51\u7edc\u9519\u8bef',
  requestFailed: '\u8bf7\u6c42\u5931\u8d25',
  tokenExpired: '\u767b\u5f55\u5df2\u8fc7\u671f\uff0c\u8bf7\u91cd\u65b0\u767b\u5f55',
  refreshFailed: '\u5237\u65b0\u5931\u8d25',
  validateFailed: '\u9a8c\u8bc1\u5931\u8d25',
  timeout: '\u8bf7\u6c42\u8d85\u65f6\uff0c\u8bf7\u68c0\u67e5\u7f51\u7edc',
  networkFailed: '\u7f51\u7edc\u8fde\u63a5\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5\u7f51\u7edc',
  proxyBad: '\u524d\u7aef API \u4ee3\u7406\u672a\u6b63\u786e\u8f6c\u53d1\u5230\u540e\u7aef\uff0c\u8bf7\u4f7f\u7528 http://localhost:8080 \u6216\u68c0\u67e5 nginx /api \u914d\u7f6e',
}

function redirectToLogin(showMessage = true) {
  clearTokens()
  if (isRedirecting) return
  isRedirecting = true
  if (showMessage) ElMessage.error(TEXT.tokenExpired)
  router.push('/login').finally(() => { isRedirecting = false })
}

request.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

request.interceptors.response.use(
  (res) => {
    const data = res.data
    if (data && data.code !== undefined && data.code !== 0) {
      const msg = data.message || TEXT.requestFailed
      const userMessage = humanizeError(msg, { status: data.code, context: 'request' })
      ElMessage.error(userMessage)
      return Promise.reject({ ...data, message: msg, userMessage })
    }
    return data
  },
  async (err) => {
    const originalRequest = err.config || {}
    const silentError = originalRequest.silentError === true
    const status = err.response?.status
    const url = originalRequest.url || ''

    if (status === 401 && !originalRequest._retried && !url.includes('/auth/refresh')) {
      const refreshToken = getRefreshToken()
      if (refreshToken && !isRefreshing) {
        isRefreshing = true
        try {
          const refreshRes = await axios.post('/api/v1/auth/refresh', { refresh_token: refreshToken })
          const payload = refreshRes.data?.data || refreshRes.data || {}
          const newToken = payload.access_token
          if (!newToken) throw new Error(TEXT.refreshFailed)

          setTokens(newToken, payload.refresh_token)
          isRefreshing = false
          originalRequest._retried = true
          originalRequest.headers = originalRequest.headers || {}
          originalRequest.headers.Authorization = `Bearer ${newToken}`
          pendingQueue.forEach(({ resolve, request: queuedRequest }) => {
            queuedRequest.headers = queuedRequest.headers || {}
            queuedRequest.headers.Authorization = `Bearer ${newToken}`
            resolve(request(queuedRequest))
          })
          pendingQueue = []
          return request(originalRequest)
        } catch (e) {
          isRefreshing = false
          pendingQueue.forEach(({ reject }) => reject(e))
          pendingQueue = []
          redirectToLogin(!silentError)
          return Promise.reject(e)
        }
      }

      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          pendingQueue.push({ resolve, reject, request: originalRequest })
        })
      }
    }

    if (status === 401) {
      redirectToLogin(!silentError)
      return Promise.reject(err)
    }

    const responseDetail = err.response?.data?.detail
    let msg = status === 422 && Array.isArray(responseDetail)
      ? responseDetail
      : (err.response?.data?.message || responseDetail)
    if (!msg && responseDetail && typeof responseDetail === 'object') {
      msg = JSON.stringify(err.response.data.detail)
    }

    const responseData = err.response?.data
    const statusText = err.response?.statusText || ''
    if (!msg && typeof responseData === 'string') {
      const trimmed = responseData.trim()
      if (trimmed.startsWith('<!DOCTYPE') || trimmed.startsWith('<html') || trimmed.includes('<center><h1>')) {
        msg = `${TEXT.requestFailed}\uff08${status || ''} ${statusText}\uff09\uff1a${TEXT.proxyBad}`
      } else {
        msg = trimmed
      }
    }
    if (!msg && status) msg = `${TEXT.requestFailed}\uff08${status} ${statusText || 'HTTP Error'}\uff09`
    if (err.code === 'ECONNABORTED') msg = msg || TEXT.timeout
    else if (err.message === 'Network Error') msg = msg || TEXT.networkFailed
    if (!msg) msg = err.message || TEXT.networkError

    const userMessage = humanizeError(msg || err, {
      status,
      context: 'request',
      fallback: TEXT.requestFailed,
    })
    err.userMessage = userMessage
    if (!silentError) ElMessage.error(userMessage)
    return Promise.reject(err)
  }
)

export default request
