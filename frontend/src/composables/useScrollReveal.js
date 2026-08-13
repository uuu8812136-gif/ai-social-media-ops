import { onMounted, onUnmounted } from 'vue'

/**
 * 滚动揭示：监听所有 .rb-reveal 元素，进入视口时加 .rb-visible
 * 用 MutationObserver 兜底动态插入的元素（路由切换、异步数据渲染）
 */
export function useScrollReveal() {
  let observer = null
  let mutationObserver = null
  let debounceTimer = null

  const observe = () => {
    if (!observer) return
    document.querySelectorAll('.rb-reveal:not(.rb-visible)').forEach(el => observer.observe(el))
  }

  const debouncedObserve = () => {
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(observe, 150)
  }

  onMounted(() => {
    observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('rb-visible')
          observer.unobserve(entry.target)
        }
      })
    }, { threshold: 0.1, rootMargin: '0px 0px -50px 0px' })

    observe()

    // MutationObserver 兜底：异步数据渲染、路由切换插入的新 .rb-reveal 元素
    mutationObserver = new MutationObserver(debouncedObserve)
    mutationObserver.observe(document.body, { childList: true, subtree: true })
  })

  onUnmounted(() => {
    if (observer) observer.disconnect()
    if (mutationObserver) mutationObserver.disconnect()
    if (debounceTimer) clearTimeout(debounceTimer)
  })
}
