import { apiUrl } from './api/url.js'
;(async () => {
  if (document.getElementById('analytics-script')) {
    return
  }

  let scriptUrl = (import.meta.env.VITE_ANALYTICS_SCRIPT_URL || '').trim()
  if (!scriptUrl) {
    try {
      const response = await fetch(apiUrl('/api/runtime'))
      if (!response.ok) {
        return
      }
      const runtime = await response.json()
      scriptUrl = String(runtime?.analytics_script_url || '').trim()
    } catch {
      return
    }
  }

  if (!scriptUrl || document.getElementById('analytics-script')) {
    return
  }

  const script = document.createElement('script')
  script.id = 'analytics-script'
  script.src = scriptUrl
  script.defer = true
  document.head.appendChild(script)
})()
