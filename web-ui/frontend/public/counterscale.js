;(async () => {
  if (document.getElementById('counterscale-script')) {
    return
  }

  let runtime
  try {
    const response = await fetch('/api/runtime')
    if (!response.ok) {
      return
    }
    runtime = await response.json()
  } catch {
    return
  }

  const siteId = String(runtime?.counterscale_site_id || '').trim()
  const trackerUrl = String(runtime?.counterscale_tracker_url || '').trim()
  if (!siteId || !trackerUrl) {
    return
  }

  const script = document.createElement('script')
  script.id = 'counterscale-script'
  script.dataset.siteId = siteId
  script.src = trackerUrl
  script.defer = true
  document.head.appendChild(script)
})()
