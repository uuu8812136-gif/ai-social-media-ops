const ACCESS_TOKEN_KEY = 'access_token'
const REFRESH_TOKEN_KEY = 'refresh_token'

// Tokens are scoped to the current browser session. Migrate once from releases
// that persisted credentials indefinitely, then remove the legacy copies.
for (const key of [ACCESS_TOKEN_KEY, REFRESH_TOKEN_KEY]) {
  const legacyValue = localStorage.getItem(key)
  if (legacyValue && !sessionStorage.getItem(key)) {
    sessionStorage.setItem(key, legacyValue)
  }
  localStorage.removeItem(key)
}

export const getAccessToken = () => sessionStorage.getItem(ACCESS_TOKEN_KEY) || ''
export const getRefreshToken = () => sessionStorage.getItem(REFRESH_TOKEN_KEY) || ''

export function setTokens(accessToken, refreshToken) {
  sessionStorage.setItem(ACCESS_TOKEN_KEY, accessToken)
  if (refreshToken) sessionStorage.setItem(REFRESH_TOKEN_KEY, refreshToken)
}

export function clearTokens() {
  sessionStorage.removeItem(ACCESS_TOKEN_KEY)
  sessionStorage.removeItem(REFRESH_TOKEN_KEY)
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
}
