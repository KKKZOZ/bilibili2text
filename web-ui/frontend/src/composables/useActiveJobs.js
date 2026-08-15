import { ref } from 'vue'
import { ApiError, processApi, subscribeSse } from '../api'

export const ACTIVE_JOB_IDS_KEY = 'b2t.active-job-ids'

export const readActiveJobIds = () => {
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(ACTIVE_JOB_IDS_KEY) || '[]'
    )
    return Array.isArray(parsed)
      ? parsed.filter((id) => typeof id === 'string' && id)
      : []
  } catch {
    return []
  }
}

const writeActiveJobIds = (ids) => {
  try {
    window.localStorage.setItem(ACTIVE_JOB_IDS_KEY, JSON.stringify(ids))
  } catch {}
}

export const addActiveJobId = (id) => {
  const ids = readActiveJobIds()
  if (!ids.includes(id)) writeActiveJobIds([...ids, id])
}

export const removeActiveJobId = (id) => {
  writeActiveJobIds(readActiveJobIds().filter((item) => item !== id))
}

export function useActiveJobs() {
  const activeJobs = ref([])
  const connectionNotice = ref('')
  let pollTimer = null
  let loading = false
  let stopEvents = null

  const stopPolling = () => {
    if (pollTimer !== null) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  const stopEventStream = () => {
    stopEvents?.()
    stopEvents = null
  }

  const load = async () => {
    if (loading) return
    const ids = readActiveJobIds()
    if (ids.length === 0) {
      activeJobs.value = []
      stopPolling()
      return
    }
    loading = true
    try {
      const results = await Promise.allSettled(
        ids.map((id) => processApi.getJob(id))
      )
      const next = []
      results.forEach((result, index) => {
        if (result.status === 'fulfilled') {
          if (['queued', 'running'].includes(result.value.status)) {
            next.push(result.value)
          } else {
            removeActiveJobId(ids[index])
          }
        } else if (
          result.reason instanceof ApiError &&
          result.reason.status === 404
        ) {
          removeActiveJobId(ids[index])
        }
      })
      activeJobs.value = next
      if (next.length === 0) stopPolling()
    } finally {
      loading = false
    }
  }

  const startPollingFallback = () => {
    connectionNotice.value = '实时连接不可用，已切换为兼容模式。'
    stopPolling()
    void load()
    pollTimer = setInterval(load, 2000)
  }

  const sync = () => {
    stopEventStream()
    stopPolling()
    connectionNotice.value = ''
    const subscribedIds = readActiveJobIds()
    if (subscribedIds.length === 0) {
      activeJobs.value = []
      return
    }

    stopEvents = subscribeSse({
      url: processApi.activeJobEventsUrl(subscribedIds),
      eventName: 'jobs',
      onEvent: (data) => {
        const jobs = Array.isArray(data?.jobs) ? data.jobs : []
        const activeIds = new Set(jobs.map((item) => item.job_id))
        subscribedIds.forEach((id) => {
          if (!activeIds.has(id)) removeActiveJobId(id)
        })
        activeJobs.value = jobs
        return jobs.length > 0
      },
      onFallback: () => {
        stopEvents = null
        startPollingFallback()
      }
    })
  }

  const cancel = async (jobId) => {
    await processApi.cancelJob(jobId)
    removeActiveJobId(jobId)
    activeJobs.value = activeJobs.value.filter((job) => job.job_id !== jobId)
    sync()
  }

  const onStorage = (event) => {
    if (event.key === ACTIVE_JOB_IDS_KEY) sync()
  }

  const stop = () => {
    stopEventStream()
    stopPolling()
  }

  return {
    activeJobs,
    connectionNotice,
    cancel,
    onStorage,
    sync,
    stop
  }
}
