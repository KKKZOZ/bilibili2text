const NOTIFIED_JOB_IDS_KEY = 'b2t.notified-job-ids'
const MAX_NOTIFIED_JOB_IDS = 100
let notificationPermissionRequest = null

const supportsNotifications = () =>
  typeof window !== 'undefined' && 'Notification' in window

const readNotifiedJobIds = () => {
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(NOTIFIED_JOB_IDS_KEY) || '[]'
    )
    return Array.isArray(parsed)
      ? parsed.filter((id) => typeof id === 'string' && id)
      : []
  } catch {
    return []
  }
}

const markJobAsNotified = (jobId) => {
  try {
    const ids = readNotifiedJobIds().filter((id) => id !== jobId)
    window.localStorage.setItem(
      NOTIFIED_JOB_IDS_KEY,
      JSON.stringify([...ids, jobId].slice(-MAX_NOTIFIED_JOB_IDS))
    )
  } catch {}
}

export const requestJobNotificationPermission = () => {
  if (!supportsNotifications() || Notification.permission !== 'default') {
    return null
  }
  if (notificationPermissionRequest) {
    return notificationPermissionRequest
  }

  try {
    const request = Notification.requestPermission()
    notificationPermissionRequest = request
    void request.finally(() => {
      if (Notification.permission === 'default') {
        notificationPermissionRequest = null
      }
    })
    return request
  } catch {
    return null
  }
}

const resolveNotificationPermission = async () => {
  if (!supportsNotifications()) return 'unsupported'
  if (Notification.permission !== 'default') return Notification.permission
  if (!notificationPermissionRequest) return 'default'
  try {
    return await notificationPermissionRequest
  } catch {
    return 'default'
  }
}

export const notifyJobCompletion = async (job, fallbackJobId = '') => {
  if (!job || job.status !== 'succeeded') return false
  const jobId = String(job.job_id || fallbackJobId || '').trim()
  if (!jobId || readNotifiedJobIds().includes(jobId)) return false
  if ((await resolveNotificationPermission()) !== 'granted') return false
  if (readNotifiedJobIds().includes(jobId)) return false

  const resourceName = String(job.title || job.bvid || '转录任务').trim()
  try {
    const notification = new Notification('转录已完成', {
      body: `${resourceName} 已处理完成`,
      icon: '/favicon.svg',
      tag: `b2t-job-${jobId}`
    })
    markJobAsNotified(jobId)
    notification.onclick = () => {
      window.focus()
      window.location.hash = `/process/${encodeURIComponent(jobId)}`
      notification.close()
    }
    return true
  } catch {
    return false
  }
}
