import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('../components/Layout.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'Dashboard', component: () => import('../views/dashboard/Index.vue') },
      { path: 'content', name: 'Content', component: () => import('../views/content/Index.vue') },
      { path: 'knowledge', name: 'Knowledge', component: () => import('../views/knowledge/Index.vue') },
      { path: 'accounts', redirect: '/social-publish' },
      { path: 'calendar', name: 'Calendar', component: () => import('../views/calendar/Index.vue') },
      { path: 'leads', name: 'Leads', component: () => import('../views/leads/Index.vue') },
      { path: 'dealers', name: 'Dealers', component: () => import('../views/dealers/Index.vue') },
      { path: 'assets', name: 'Assets', component: () => import('../views/assets/Index.vue') },
      { path: 'materials', redirect: '/assets' },
      { path: 'social-publish', name: 'SocialPublish', component: () => import('../views/socialPublish/Index.vue') },
      { path: 'crawler', name: 'Crawler', component: () => import('../views/crawler/Index.vue') },
      { path: 'settings/users', name: 'UserSettings', component: () => import('../views/settings/Users.vue'), meta: { roles: ['admin'] } },
      { path: 'settings/llm', name: 'LLMSettings', component: () => import('../views/settings/LLM.vue'), meta: { roles: ['admin'] } },
    ],
  },
  // 404 兜底
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: () => import('../views/NotFound.vue'), meta: { public: true } },
]

const router = createRouter({ history: createWebHistory(), routes })

// 路由级 loading 指示器
let loadingTimer = null
router.beforeEach((to, _from, next) => {
  if (loadingTimer) clearTimeout(loadingTimer)
  loadingTimer = setTimeout(() => document.body.classList.add('route-loading'), 200)
  next()
})
router.afterEach(() => {
  if (loadingTimer) { clearTimeout(loadingTimer); loadingTimer = null }
  document.body.classList.remove('route-loading')
})
router.onError(() => {
  if (loadingTimer) { clearTimeout(loadingTimer); loadingTimer = null }
  document.body.classList.remove('route-loading')
})

router.beforeEach(async (to, _from, next) => {
  const auth = useAuthStore()
  if (to.meta.public) return next()
  if (!auth.token) return next('/login')
  if (!auth.user) {
    try { await auth.fetchMe() } catch { return next('/login') }
  }
  if (to.meta.roles?.length && !to.meta.roles.includes(auth.user?.role)) return next('/dashboard')
  next()
})

export default router
