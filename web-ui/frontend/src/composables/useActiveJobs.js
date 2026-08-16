import {
  ACTIVE_JOB_IDS_KEY,
  cancelTrackedJob,
  readActiveJobIds,
  syncJobEvents,
  trackJob,
  untrackJob,
  useJobStore
} from './useJobStore'

export { ACTIVE_JOB_IDS_KEY, readActiveJobIds }
export const addActiveJobId = trackJob
export const removeActiveJobId = untrackJob

export function useActiveJobs() {
  const store = useJobStore()
  return {
    activeJobs: store.activeJobs,
    connectionNotice: store.connectionNotice,
    cancel: cancelTrackedJob,
    onStorage: (event) => {
      if (event.key === ACTIVE_JOB_IDS_KEY) syncJobEvents()
    },
    sync: syncJobEvents,
    stop: () => {}
  }
}
