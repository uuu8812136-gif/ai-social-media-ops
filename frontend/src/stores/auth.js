import { defineStore } from 'pinia'
import { ref } from 'vue'
import request from '../utils/request'
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from '../utils/authStorage'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const token = ref(getAccessToken())

  async function login(username, password) {
    const res = await request.post('/auth/login', { username, password })
    token.value = res.data.access_token
    setTokens(res.data.access_token, res.data.refresh_token)
    await fetchMe()
    return res
  }

  async function fetchMe() {
    const res = await request.get('/auth/me')
    user.value = res.data
    return res.data
  }

  async function logout() {
    const refreshToken = getRefreshToken()
    token.value = ''
    user.value = null
    clearTokens()
    if (refreshToken) {
      try {
        await request.post('/auth/logout', { refresh_token: refreshToken }, { silentError: true })
      } catch {
        // Local credentials are already cleared; server-side expiry remains the fallback.
      }
    }
  }

  return { user, token, login, fetchMe, logout }
})
