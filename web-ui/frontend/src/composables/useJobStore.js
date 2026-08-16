import { computed, ref } from 'vue'
import { ApiError, processApi, subscribeSse } from '../api'
import { notifyJobCompletion } from './useJobNotifications'

export const ACTIVE_JOB_IDS_KEY = 'b2t.active-job-ids'

const jobsById = ref({})
const trackedJobIds = ref([])
const connectionNotice = ref('')
let stopEvents = null
let pollTimer = null
let pollLoading = false
let started = false
let resyncQueued = false

export const readActiveJobIds = () => {
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(ACTIVE_JOB_IDS_KEY) || '[]'
    )
    return Array.isArray(parsed)
      ? [...new Set(parsed.filter((id) => typeof id === 'string' && id))]
      : []
  } catch {
    return []
  }
}

const writeActiveJobIds = (ids) => {
  const normalized = [...new Set(ids.filter(Boolean))]
  trackedJobIds.value = normalized
  try {
    window.localStorage.setItem(ACTIVE_JOB_IDS_KEY, JSON.stringify(normalized))
  } catch {}
}

const isJobActive = (job) => {
  if (['queued', 'running'].includes(job?.status)) return true
  return (
    job?.status === 'succeeded' &&
    Boolean(job.auto_generate_fancy_html) &&
    ['pending', 'running'].includes(job.fancy_html_status || '')
  )
}

const activeJobs = computed(() =>
  trackedJobIds.value
    .map((jobId) => jobsById.value[jobId])
    .filter((job) => isJobActive(job))
)

const setJob = (job) => {
  const jobId = String(job?.job_id || '').trim()
  if (!jobId) return
  jobsById.value = { ...jobsById.value, [jobId]: job }
}

const stopEventStream = () => {
  stopEvents?.()
  stopEvents = null
}

const stopPolling = () => {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

const queueSync = () => {
  if (!started || resyncQueued) return
  resyncQueued = true
  queueMicrotask(() => {
    resyncQueued = false
    syncJobEvents()
  })
}

const applySnapshots = (data, subscribedIds, preservedIds = new Set()) => {
  const snapshots = Array.isArray(data?.jobs) ? data.jobs : []
  const snapshotsById = new Map(
    snapshots.map((job) => [String(job.job_id || ''), job])
  )
  const nextTrackedIds = []

  for (const jobId of subscribedIds) {
    const job = snapshotsById.get(jobId)
    if (!job) {
      if (preservedIds.has(jobId)) nextTrackedIds.push(jobId)
      continue
    }
    setJob(job)
    if (job.status === 'succeeded') {
      void notifyJobCompletion(job, jobId)
    }
    if (isJobActive(job)) nextTrackedIds.push(jobId)
  }

  const changed =
    nextTrackedIds.length !== trackedJobIds.value.length ||
    nextTrackedIds.some((jobId, index) => trackedJobIds.value[index] !== jobId)
  if (changed) {
    writeActiveJobIds(nextTrackedIds)
    queueSync()
  }
  return nextTrackedIds.length > 0
}

const loadTrackedJobs = async () => {
  if (pollLoading) return
  const subscribedIds = readActiveJobIds()
  if (subscribedIds.length === 0) {
    writeActiveJobIds([])
    stopPolling()
    return
  }

  pollLoading = true
  try {
    const results = await Promise.allSettled(
      subscribedIds.map((jobId) => processApi.getJob(jobId))
    )
    const jobs = []
    const preservedIds = new Set()
    results.forEach((result, index) => {
      if (result.status === 'fulfilled') {
        jobs.push(result.value)
      } else if (
        !(result.reason instanceof ApiError && result.reason.status === 404)
      ) {
        const jobId = subscribedIds[index]
        preservedIds.add(jobId)
        if (jobsById.value[jobId]) jobs.push(jobsById.value[jobId])
      }
    })
    applySnapshots({ jobs }, subscribedIds, preservedIds)
  } finally {
    pollLoading = false
  }
}

const startPollingFallback = () => {
  connectionNotice.value = '实时连接不可用，已切换为兼容模式。'
  stopPolling()
  void loadTrackedJobs()
  pollTimer = window.setInterval(loadTrackedJobs, 5000)
}

export const syncJobEvents = () => {
  stopEventStream()
  stopPolling()
  connectionNotice.value = ''
  const subscribedIds = readActiveJobIds()
  writeActiveJobIds(subscribedIds)
  if (!started || subscribedIds.length === 0) return

  stopEvents = subscribeSse({
    url: processApi.activeJobEventsUrl(subscribedIds),
    eventName: 'jobs',
    onEvent: (data) => {
      connectionNotice.value = ''
      return applySnapshots(data, subscribedIds)
    },
    onFallback: () => {
      stopEvents = null
      startPollingFallback()
    }
  })
}

export const trackJob = (jobId, initialJob = null) => {
  const normalized = String(jobId || '').trim()
  if (!normalized) return
  if (initialJob) setJob(initialJob)
  const ids = readActiveJobIds()
  if (!ids.includes(normalized)) writeActiveJobIds([...ids, normalized])
  queueSync()
}

export const untrackJob = (jobId) => {
  const normalized = String(jobId || '').trim()
  if (!normalized) return
  const ids = readActiveJobIds().filter((id) => id !== normalized)
  writeActiveJobIds(ids)
  queueSync()
}

export const loadJob = async (jobId) => {
  const normalized = String(jobId || '').trim()
  if (!normalized) return null
  const wasTracked = readActiveJobIds().includes(normalized)
  const job = await processApi.getJob(normalized)
  setJob(job)
  if (isJobActive(job)) {
    trackJob(normalized)
  } else if (wasTracked) {
    if (job.status === 'succeeded') void notifyJobCompletion(job, normalized)
    untrackJob(normalized)
  }
  return job
}

export const cancelTrackedJob = async (jobId) => {
  await processApi.cancelJob(jobId)
  try {
    await loadJob(jobId)
  } catch {
    untrackJob(jobId)
  }
}

const onStorage = (event) => {
  if (event.key === ACTIVE_JOB_IDS_KEY) syncJobEvents()
}

export const startJobStore = () => {
  if (started) return
  started = true
  window.addEventListener('storage', onStorage)
  syncJobEvents()
}

export const stopJobStore = () => {
  if (!started) return
  started = false
  stopEventStream()
  stopPolling()
  window.removeEventListener('storage', onStorage)
}

export function useJobStore() {
  return {
    activeJobs,
    connectionNotice,
    getJob: (jobId) => jobsById.value[String(jobId || '')] || null,
    loadJob,
    trackJob,
    untrackJob,
    cancelJob: cancelTrackedJob,
    sync: syncJobEvents
  }
}
