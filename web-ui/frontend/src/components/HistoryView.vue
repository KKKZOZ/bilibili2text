<script setup>
  import {
    computed,
    nextTick,
    onBeforeUnmount,
    onMounted,
    ref,
    watch
  } from 'vue'
  import { useRoute, useRouter } from 'vue-router'
  import { BookMarked, ExternalLink } from 'lucide-vue-next'
  import {
    AlertCircle,
    ArrowLeft,
    Brain,
    CalendarDays,
    ChevronDown,
    ChevronLeft,
    ChevronRight,
    ChevronsLeft,
    ChevronsRight,
    Clock,
    FileText,
    LoaderCircle,
    RefreshCw,
    RotateCcw,
    Search,
    SlidersHorizontal,
    Trash2,
    User,
    XCircle
  } from 'lucide-vue-next'
  import FileList from './FileList.vue'
  import {
    ApiError,
    artifactApi,
    historyApi,
    processApi,
    subscribeSse,
    summaryApi
  } from '../api'
  import {
    CUSTOM_LLM_PROFILE_NAME,
    usePublicCredentials
  } from '../composables/usePublicCredentials'
  import { useRuntimeFeatures } from '../composables/useRuntimeFeatures'
  import { useSummaryConfig } from '../composables/useSummaryConfig'
  import {
    formatTime,
    resourceAuthorLabel,
    resourceDisplayLabel,
    resourceUrl
  } from '../utils/fileUtils'
  import { extractRagReferenceItems, renderMarkdown } from '../utils/markdown'

  const route = useRoute()
  const router = useRouter()
  const { runtimeFeatures } = useRuntimeFeatures()
  const allowDelete = computed(() => runtimeFeatures.value.allow_delete)
  const requiresApiKey = computed(
    () => runtimeFeatures.value.requires_user_api_key
  )
  const {
    summaryPresets,
    summaryDefaultPreset,
    summaryProfiles,
    selectedSummaryPreset,
    selectedSummaryProfile
  } = useSummaryConfig()
  const {
    getApiKey,
    getDeepseekApiKey,
    getSummaryTemplate,
    getCustomLlmPayload
  } = usePublicCredentials()

  const historyItems = ref([])
  const historyTotal = ref(0)
  const historyPage = ref(1)
  const historyPageSize = ref(20)
  const historyHasMore = ref(false)
  const historyJumpPage = ref('')
  const historySearch = ref('')
  const historyPlatforms = ref([])
  const historyCategoryTids = ref([])
  const historyAuthors = ref([])
  const historyPlatformOptions = ref([])
  const historyCategoryOptions = ref([])
  const historyAuthorOptions = ref([])
  const historyPlatformMenuOpen = ref(false)
  const historyCategoryMenuOpen = ref(false)
  const historyAuthorMenuOpen = ref(false)
  const historyPlatformFilterRef = ref(null)
  const historyCategoryFilterRef = ref(null)
  const historyAuthorFilterRef = ref(null)
  const historyPlatformMenuRef = ref(null)
  const historyCategoryMenuRef = ref(null)
  const historyAuthorMenuRef = ref(null)
  const historyPlatformMenuHasMore = ref(false)
  const historyCategoryMenuHasMore = ref(false)
  const historyAuthorMenuHasMore = ref(false)
  const historyFiltersLoading = ref(false)
  const historyLoading = ref(false)
  const historyError = ref('')
  const historyDetail = ref(null)
  const historyDetailLoading = ref(false)
  const showHistoryDetail = ref(false)
  const deleteConfirmRunId = ref(null)
  const deleteLoading = ref(false)
  const regenerateLoading = ref(false)
  const regenerateError = ref('')
  const regenerateSuccess = ref('')
  const regenerateOverwriteConfirm = ref(false)
  const selectedHistorySummaryPreset = ref('')
  const selectedHistorySummaryProfile = ref('')
  const ragAnswerMarkdown = ref('')
  const ragAnswerError = ref('')
  const ragAnswerLoading = ref(false)
  const ragFancyHtmlGenerating = ref(false)
  const ragFancyHtmlError = ref('')
  const ragFancyConnectionNotice = ref('')
  let ragFancyHtmlPollTimer = null
  let ragFancyHtmlPollInFlight = false
  let stopRagFancyHtmlEvents = null
  let historyDetailRequestVersion = 0

  // ─── Active jobs (in-progress) ───────────────────────────────
  const ACTIVE_JOB_IDS_KEY = 'b2t.active-job-ids'
  const CUSTOM_SUMMARY_PRESET_VALUE = '__user_custom__'
  const activeJobs = ref([])
  const activeJobsConnectionNotice = ref('')
  let activeJobsPollTimer = null
  let activeJobsLoading = false
  let stopActiveJobEvents = null

  const readActiveJobIds = () => {
    try {
      const raw = window.localStorage.getItem(ACTIVE_JOB_IDS_KEY)
      if (!raw) return []
      const parsed = JSON.parse(raw)
      return Array.isArray(parsed)
        ? parsed.filter((id) => typeof id === 'string' && id)
        : []
    } catch {
      return []
    }
  }

  const removeActiveJobId = (id) => {
    try {
      const ids = readActiveJobIds().filter((i) => i !== id)
      window.localStorage.setItem(ACTIVE_JOB_IDS_KEY, JSON.stringify(ids))
    } catch {}
  }

  const stopActiveJobsPolling = () => {
    if (activeJobsPollTimer !== null) {
      clearInterval(activeJobsPollTimer)
      activeJobsPollTimer = null
    }
  }

  const stopActiveJobsEvents = () => {
    if (stopActiveJobEvents !== null) {
      stopActiveJobEvents()
      stopActiveJobEvents = null
    }
  }

  const loadActiveJobs = async () => {
    if (activeJobsLoading) return
    const ids = readActiveJobIds()
    if (ids.length === 0) {
      activeJobs.value = []
      stopActiveJobsPolling()
      return
    }
    activeJobsLoading = true
    try {
      const results = await Promise.allSettled(
        ids.map((id) => processApi.getJob(id))
      )
      const next = []
      for (let i = 0; i < ids.length; i++) {
        const result = results[i]
        if (result.status === 'fulfilled') {
          const data = result.value
          if (data.status === 'queued' || data.status === 'running') {
            next.push(data)
          } else {
            removeActiveJobId(ids[i])
          }
        } else if (
          result.reason instanceof ApiError &&
          result.reason.status === 404
        ) {
          removeActiveJobId(ids[i])
        }
      }
      activeJobs.value = next
      if (next.length === 0) stopActiveJobsPolling()
    } finally {
      activeJobsLoading = false
    }
  }

  const startActiveJobsPollingFallback = () => {
    activeJobsConnectionNotice.value = '实时连接不可用，已切换为兼容模式。'
    stopActiveJobsPolling()
    loadActiveJobs()
    activeJobsPollTimer = setInterval(loadActiveJobs, 2000)
  }

  const syncActiveJobEvents = () => {
    stopActiveJobsEvents()
    stopActiveJobsPolling()
    activeJobsConnectionNotice.value = ''
    const subscribedIds = readActiveJobIds()
    if (subscribedIds.length === 0) {
      activeJobs.value = []
      return
    }

    stopActiveJobEvents = subscribeSse({
      url: processApi.activeJobEventsUrl(subscribedIds),
      eventName: 'jobs',
      onEvent: (data) => {
        const jobs = Array.isArray(data?.jobs) ? data.jobs : []
        const activeIds = new Set(jobs.map((item) => item.job_id))
        for (const id of subscribedIds) {
          if (!activeIds.has(id)) removeActiveJobId(id)
        }
        activeJobs.value = jobs
        return jobs.length > 0
      },
      onFallback: () => {
        stopActiveJobEvents = null
        startActiveJobsPollingFallback()
      }
    })
  }

  const onActiveJobsStorage = (event) => {
    if (event.key === ACTIVE_JOB_IDS_KEY) syncActiveJobEvents()
  }

  const cancelActiveJob = async (jobId) => {
    try {
      await processApi.cancelJob(jobId)
      removeActiveJobId(jobId)
      activeJobs.value = activeJobs.value.filter((j) => j.job_id !== jobId)
      syncActiveJobEvents()
    } catch (err) {
      historyError.value = err instanceof Error ? err.message : '取消任务失败'
    }
  }

  let searchTimer = null

  const historyTotalPages = computed(() =>
    Math.max(1, Math.ceil(historyTotal.value / historyPageSize.value))
  )
  const hasActiveHistoryFilters = computed(
    () =>
      historyPlatforms.value.length > 0 ||
      historyCategoryTids.value.length > 0 ||
      historyAuthors.value.length > 0
  )
  const historyPlatformFilterLabel = computed(() => {
    if (historyPlatforms.value.length === 0) return '全部平台'
    if (historyPlatforms.value.length > 1) {
      return `已选 ${historyPlatforms.value.length} 个平台`
    }
    return (
      historyPlatformOptions.value.find(
        (option) => option.platform === historyPlatforms.value[0]
      )?.name || historyPlatforms.value[0]
    )
  })
  const historyCategoryFilterLabel = computed(() => {
    if (historyCategoryTids.value.length === 0) return '全部分区'
    if (historyCategoryTids.value.length > 1) {
      return `已选 ${historyCategoryTids.value.length} 个分区`
    }
    const selectedTid = historyCategoryTids.value[0]
    return (
      historyCategoryOptions.value.find((option) => option.tid === selectedTid)
        ?.tname || '已选 1 个分区'
    )
  })
  const historyAuthorFilterLabel = computed(() => {
    if (historyAuthors.value.length === 0) return '全部 UP 主'
    if (historyAuthors.value.length > 1) {
      return `已选 ${historyAuthors.value.length} 位 UP 主`
    }
    return historyAuthors.value[0]
  })
  const showHistorySkeleton = computed(
    () => historyLoading.value && historyItems.value.length === 0
  )
  const routeRunId = computed(() => String(route.params.runId || ''))

  const historyDetailDownloadRows = computed(() => {
    const detail = historyDetail.value
    if (!detail || !Array.isArray(detail.artifacts)) {
      return []
    }
    return detail.artifacts.map((artifact, index) => ({
      kind: artifact.kind,
      key: `${artifact.download_url}-${artifact.filename}-${index}`,
      url: artifact.download_url,
      filename: artifact.filename,
      presetName: artifact.summary_preset || '',
      summaryProfile: artifact.summary_profile || ''
    }))
  })

  const renderedRagAnswer = computed(() =>
    ragAnswerMarkdown.value ? renderMarkdown(ragAnswerMarkdown.value) : ''
  )

  const ragReferenceItems = computed(() =>
    extractRagReferenceItems(ragAnswerMarkdown.value)
  )

  const selectedRegeneratePresetName = computed(() => {
    if (!selectedHistorySummaryPreset.value) {
      return summaryDefaultPreset.value || ''
    }
    return selectedHistorySummaryPreset.value
  })

  const selectedRegenerateProfileName = computed(
    () =>
      selectedHistorySummaryProfile.value || selectedSummaryProfile.value || ''
  )

  const isSelectedSummaryAlreadyGenerated = computed(() => {
    const detail = historyDetail.value
    if (!detail || !Array.isArray(detail.artifacts)) {
      return false
    }
    const preset = selectedRegeneratePresetName.value.trim()
    const profile = selectedRegenerateProfileName.value.trim()
    if (!preset || !profile) {
      return false
    }
    return detail.artifacts.some(
      (artifact) =>
        artifact.kind === 'summary' &&
        (artifact.summary_preset || '').trim() === preset &&
        (artifact.summary_profile || '').trim() === profile
    )
  })

  const regenerateDisabled = computed(() => regenerateLoading.value)

  const formatSummaryProfileLabel = (profile) => {
    if (!profile) return ''
    if (profile.name === CUSTOM_LLM_PROFILE_NAME) {
      return `custom(${profile.model || 'model'})`
    }
    return `${profile.name} (${profile.model})`
  }

  const historyPresetOptions = computed(() => {
    const base = Array.isArray(summaryPresets.value) ? summaryPresets.value : []
    if (!requiresApiKey.value) {
      return base
    }
    return [
      ...base,
      {
        name: CUSTOM_SUMMARY_PRESET_VALUE,
        label: '用户自定义'
      }
    ]
  })

  const loadHistory = async () => {
    historyLoading.value = true
    historyError.value = ''
    try {
      const params = new URLSearchParams({
        page: String(historyPage.value),
        page_size: String(historyPageSize.value)
      })
      const q = historySearch.value.trim()
      if (q) params.set('search', q)
      for (const platform of historyPlatforms.value) {
        params.append('platform', platform)
      }
      for (const tid of historyCategoryTids.value) {
        params.append('category_tid', String(tid))
      }
      for (const author of historyAuthors.value) {
        params.append('author', author)
      }
      const data = await historyApi.list(params)
      historyItems.value = data.items
      historyTotal.value = data.total
      historyHasMore.value = data.has_more
    } catch (err) {
      historyError.value =
        err instanceof Error ? err.message : '获取历史记录失败'
    } finally {
      historyLoading.value = false
    }
  }

  const loadHistoryFilters = async () => {
    historyFiltersLoading.value = true
    try {
      const data = await historyApi.getFilters()
      historyPlatformOptions.value = Array.isArray(data.platforms)
        ? data.platforms
        : []
      historyCategoryOptions.value = Array.isArray(data.categories)
        ? data.categories
        : []
      historyAuthorOptions.value = Array.isArray(data.authors)
        ? data.authors
        : []
    } catch {
      historyPlatformOptions.value = []
      historyCategoryOptions.value = []
      historyAuthorOptions.value = []
    } finally {
      historyFiltersLoading.value = false
    }
  }

  const loadHistoryDetail = async (runId) => {
    const requestedRunId = String(runId || '').trim()
    if (!requestedRunId) {
      return
    }
    const requestVersion = ++historyDetailRequestVersion
    historyDetailLoading.value = true
    showHistoryDetail.value = true
    historyDetail.value = null
    ragAnswerMarkdown.value = ''
    ragAnswerError.value = ''
    ragFancyHtmlError.value = ''
    ragFancyConnectionNotice.value = ''
    regenerateError.value = ''
    regenerateSuccess.value = ''
    regenerateOverwriteConfirm.value = false
    selectedHistorySummaryPreset.value =
      selectedSummaryPreset.value || summaryDefaultPreset.value || ''
    selectedHistorySummaryProfile.value = selectedSummaryProfile.value || ''
    try {
      const data = await historyApi.getDetail(requestedRunId)
      if (
        requestVersion !== historyDetailRequestVersion ||
        routeRunId.value !== requestedRunId
      ) {
        return
      }
      historyDetail.value = data
      ragFancyHtmlError.value = data.fancy_html_error || ''
      syncRagFancyHtmlUpdates()
      if (data.record_type === 'rag_query') {
        await loadRagAnswerMarkdown(data, requestVersion)
      }
    } catch (err) {
      if (requestVersion !== historyDetailRequestVersion) return
      historyError.value = err instanceof Error ? err.message : '获取详情失败'
      showHistoryDetail.value = false
      stopRagFancyHtmlEventStream()
      stopRagFancyHtmlPolling()
    } finally {
      if (requestVersion === historyDetailRequestVersion) {
        historyDetailLoading.value = false
      }
    }
  }

  const openHistoryDetail = (runId) => {
    router.push(`/history/${encodeURIComponent(runId)}`)
  }

  const closeHistoryDetail = () => {
    router.push('/history')
  }

  const stopRagFancyHtmlPolling = () => {
    if (ragFancyHtmlPollTimer !== null) {
      clearInterval(ragFancyHtmlPollTimer)
      ragFancyHtmlPollTimer = null
    }
  }

  const stopRagFancyHtmlEventStream = () => {
    if (stopRagFancyHtmlEvents !== null) {
      stopRagFancyHtmlEvents()
      stopRagFancyHtmlEvents = null
    }
  }

  const startRagFancyHtmlPollingFallback = () => {
    ragFancyConnectionNotice.value = '实时连接不可用，已切换为兼容模式。'
    stopRagFancyHtmlPolling()
    ragFancyHtmlPollTimer = setInterval(async () => {
      if (ragFancyHtmlPollInFlight) return
      const runId = historyDetail.value?.run_id
      if (!runId || !showHistoryDetail.value) {
        stopRagFancyHtmlPolling()
        return
      }
      ragFancyHtmlPollInFlight = true
      try {
        const data = await historyApi.getDetail(runId)
        if (historyDetail.value?.run_id !== runId) return
        historyDetail.value = data
        if (data.record_type === 'rag_query') {
          ragFancyHtmlError.value = data.fancy_html_error || ''
        }
        if (data.fancy_html_status !== 'running') {
          stopRagFancyHtmlPolling()
          await loadHistory()
        }
      } catch {
      } finally {
        ragFancyHtmlPollInFlight = false
      }
    }, 2000)
  }

  const syncRagFancyHtmlUpdates = () => {
    stopRagFancyHtmlEventStream()
    stopRagFancyHtmlPolling()
    ragFancyConnectionNotice.value = ''
    const runId = historyDetail.value?.run_id
    const shouldSubscribe =
      showHistoryDetail.value &&
      historyDetail.value?.record_type === 'rag_query' &&
      ['pending', 'running'].includes(
        historyDetail.value?.fancy_html_status || ''
      )
    if (!shouldSubscribe || !runId) return

    stopRagFancyHtmlEvents = subscribeSse({
      url: historyApi.eventsUrl(runId),
      eventName: 'history',
      onEvent: (data) => {
        if (historyDetail.value?.run_id !== runId) return false
        historyDetail.value = data
        ragFancyHtmlError.value = data.fancy_html_error || ''
        const isActive = ['pending', 'running'].includes(
          data.fancy_html_status || ''
        )
        if (!isActive) loadHistory()
        return isActive
      },
      onDeleted: () => {
        if (historyDetail.value?.run_id !== runId) return
        historyError.value = '转录记录不存在'
        showHistoryDetail.value = false
      },
      onFallback: () => {
        stopRagFancyHtmlEvents = null
        if (historyDetail.value?.run_id === runId) {
          startRagFancyHtmlPollingFallback()
        }
      }
    })
  }

  const generateRagFancyHtml = async () => {
    const artifact = historyDetail.value?.artifacts?.find(
      (item) => item.kind === 'rag_answer'
    )
    if (!artifact?.download_url || ragFancyHtmlGenerating.value) return
    const downloadId = artifact.download_url.split('/').pop()
    if (!downloadId) return
    ragFancyHtmlGenerating.value = true
    ragFancyHtmlError.value = ''
    try {
      const data = await summaryApi.generateFancyHtml({
        download_id: downloadId,
        history_run_id: historyDetail.value?.run_id || null,
        api_key: requiresApiKey.value ? getApiKey() || null : null,
        deepseek_api_key: requiresApiKey.value
          ? getDeepseekApiKey() || null
          : null,
        ...getCustomLlmPayload(requiresApiKey.value)
      })
      if (data.history_detail) {
        historyDetail.value = data.history_detail
        ragFancyHtmlError.value = data.history_detail.fancy_html_error || ''
        syncRagFancyHtmlUpdates()
        await loadHistory()
      }
      if (data.download_url && data.filename) {
        const a = document.createElement('a')
        a.href = data.download_url
        a.download = data.filename
        a.click()
      }
    } catch (err) {
      ragFancyHtmlError.value =
        err instanceof Error ? err.message : '生成 Fancy HTML 失败'
    } finally {
      ragFancyHtmlGenerating.value = false
    }
  }

  const loadRagAnswerMarkdown = async (
    detail = historyDetail.value,
    requestVersion = historyDetailRequestVersion
  ) => {
    const artifact = detail?.artifacts?.find(
      (item) => item.kind === 'rag_answer'
    )
    if (!artifact?.download_url) return
    ragAnswerLoading.value = true
    ragAnswerError.value = ''
    try {
      const markdown = await artifactApi.readText(
        artifact.download_url,
        '读取知识库回答失败'
      )
      if (
        requestVersion !== historyDetailRequestVersion ||
        historyDetail.value?.run_id !== detail?.run_id
      ) {
        return
      }
      ragAnswerMarkdown.value = markdown
    } catch (err) {
      if (requestVersion !== historyDetailRequestVersion) return
      ragAnswerError.value =
        err instanceof Error ? err.message : '读取知识库回答失败'
    } finally {
      if (requestVersion === historyDetailRequestVersion) {
        ragAnswerLoading.value = false
      }
    }
  }

  const regenerateSummary = async (overwriteExisting = false) => {
    const runId = historyDetail.value?.run_id
    if (!runId) {
      return
    }
    let customTemplate = null
    if (
      requiresApiKey.value &&
      selectedHistorySummaryPreset.value === CUSTOM_SUMMARY_PRESET_VALUE
    ) {
      customTemplate = getSummaryTemplate()
      if (!customTemplate) {
        regenerateError.value =
          '请先在「API Key」页面保存自定义总结模板，再选择“用户自定义”模板'
        return
      }
    }
    if (isSelectedSummaryAlreadyGenerated.value && !overwriteExisting) {
      regenerateError.value = ''
      regenerateSuccess.value = ''
      regenerateOverwriteConfirm.value = true
      return
    }

    regenerateOverwriteConfirm.value = false
    regenerateLoading.value = true
    regenerateError.value = ''
    regenerateSuccess.value = ''
    try {
      const data = await historyApi.regenerateSummary(runId, {
        summary_preset: selectedRegeneratePresetName.value || null,
        summary_profile: selectedRegenerateProfileName.value || null,
        summary_prompt_template: customTemplate || null,
        overwrite_existing: overwriteExisting,
        api_key: requiresApiKey.value ? getApiKey() : null,
        deepseek_api_key: requiresApiKey.value
          ? getDeepseekApiKey() || null
          : null,
        ...getCustomLlmPayload(requiresApiKey.value)
      })

      historyDetail.value = data
      regenerateSuccess.value = overwriteExisting
        ? '总结重新生成完成，原有同配置结果已覆盖。'
        : '总结重新生成完成，文件已持久化到存储后端。'
      await loadHistory()
    } catch (err) {
      regenerateError.value =
        err instanceof Error ? err.message : '重新生成总结失败'
    } finally {
      regenerateLoading.value = false
    }
  }

  const cancelRegenerateOverwrite = () => {
    if (!regenerateLoading.value) {
      regenerateOverwriteConfirm.value = false
    }
  }

  const onSearchInput = () => {
    if (searchTimer) clearTimeout(searchTimer)
    searchTimer = setTimeout(() => {
      historyPage.value = 1
      loadHistory()
    }, 400)
  }

  const applyHistoryFilterSelection = (selection, value, checked) => {
    selection.value = checked
      ? [...selection.value, value]
      : selection.value.filter((item) => item !== value)
    historyPage.value = 1
    loadHistory()
  }

  const toggleHistoryPlatform = (platform, checked) => {
    applyHistoryFilterSelection(historyPlatforms, platform, checked)
  }

  const toggleHistoryCategory = (tid, checked) => {
    applyHistoryFilterSelection(historyCategoryTids, tid, checked)
  }

  const toggleHistoryAuthor = (author, checked) => {
    applyHistoryFilterSelection(historyAuthors, author, checked)
  }

  const closeHistoryFilterMenus = () => {
    historyPlatformMenuOpen.value = false
    historyCategoryMenuOpen.value = false
    historyAuthorMenuOpen.value = false
    historyPlatformMenuHasMore.value = false
    historyCategoryMenuHasMore.value = false
    historyAuthorMenuHasMore.value = false
  }

  const updateHistoryFilterScrollHint = (menu, element) => {
    const hasMore = Boolean(
      element &&
      element.scrollHeight - element.scrollTop - element.clientHeight > 2
    )
    if (menu === 'platform') historyPlatformMenuHasMore.value = hasMore
    if (menu === 'category') historyCategoryMenuHasMore.value = hasMore
    if (menu === 'author') historyAuthorMenuHasMore.value = hasMore
  }

  const onHistoryFilterMenuScroll = (menu, event) => {
    updateHistoryFilterScrollHint(menu, event.currentTarget)
  }

  const toggleHistoryFilterMenu = (menu) => {
    const nextOpen =
      menu === 'platform'
        ? !historyPlatformMenuOpen.value
        : menu === 'category'
          ? !historyCategoryMenuOpen.value
          : !historyAuthorMenuOpen.value
    closeHistoryFilterMenus()
    if (menu === 'platform') historyPlatformMenuOpen.value = nextOpen
    if (menu === 'category') historyCategoryMenuOpen.value = nextOpen
    if (menu === 'author') historyAuthorMenuOpen.value = nextOpen
    if (nextOpen) {
      nextTick(() => {
        const element =
          menu === 'platform'
            ? historyPlatformMenuRef.value
            : menu === 'category'
              ? historyCategoryMenuRef.value
              : historyAuthorMenuRef.value
        updateHistoryFilterScrollHint(menu, element)
      })
    }
  }

  const onHistoryFilterPointerDown = (event) => {
    const target = event.target
    if (
      historyPlatformFilterRef.value?.contains(target) ||
      historyCategoryFilterRef.value?.contains(target) ||
      historyAuthorFilterRef.value?.contains(target)
    ) {
      return
    }
    closeHistoryFilterMenus()
  }

  const resetHistoryFilters = () => {
    historyPlatforms.value = []
    historyCategoryTids.value = []
    historyAuthors.value = []
    closeHistoryFilterMenus()
    historyPage.value = 1
    loadHistory()
  }

  const historyPrevPage = () => {
    goToHistoryPage(historyPage.value - 1)
  }

  const historyNextPage = () => {
    goToHistoryPage(historyPage.value + 1)
  }

  const goToHistoryPage = (page) => {
    const parsedPage = Number.parseInt(String(page), 10)
    if (!Number.isFinite(parsedPage)) {
      historyJumpPage.value = ''
      return
    }
    const targetPage = Math.min(
      historyTotalPages.value,
      Math.max(1, parsedPage)
    )
    historyJumpPage.value = ''
    if (targetPage === historyPage.value || historyLoading.value) return
    historyPage.value = targetPage
    loadHistory()
  }

  const submitHistoryPageJump = () => {
    goToHistoryPage(historyJumpPage.value)
  }

  const confirmDelete = (runId) => {
    if (!allowDelete.value) {
      return
    }
    deleteConfirmRunId.value = runId
  }

  const cancelDelete = () => {
    deleteConfirmRunId.value = null
  }

  const deleteHistory = async (runId) => {
    if (!allowDelete.value) {
      return
    }
    deleteLoading.value = true
    try {
      await historyApi.deleteRun(runId)
      // Close detail view if currently viewing deleted item
      if (showHistoryDetail.value && historyDetail.value?.run_id === runId) {
        showHistoryDetail.value = false
        historyDetail.value = null
      }
      // Reload list
      await loadHistory()
      await loadHistoryFilters()
      deleteConfirmRunId.value = null
    } catch (err) {
      historyError.value = err instanceof Error ? err.message : '删除失败'
    } finally {
      deleteLoading.value = false
    }
  }

  const onHistoryArtifactDeleted = (detail) => {
    historyDetail.value = detail
    regenerateError.value = ''
    regenerateSuccess.value = '文件已删除。'
    if (detail?.record_type === 'rag_query') {
      ragFancyHtmlError.value = detail.fancy_html_error || ''
      syncRagFancyHtmlUpdates()
    }
    loadHistory()
  }

  const onHistoryArtifactGenerated = (detail) => {
    historyDetail.value = detail
    regenerateError.value = ''
    regenerateSuccess.value = 'Fancy HTML 已生成并归档。'
    if (detail?.record_type === 'rag_query') {
      ragFancyHtmlError.value = detail.fancy_html_error || ''
      syncRagFancyHtmlUpdates()
    }
    loadHistory()
  }

  defineExpose({
    loadHistory
  })

  onMounted(() => {
    loadHistory()
    loadHistoryFilters()
    if (routeRunId.value) {
      loadHistoryDetail(routeRunId.value)
    }
    syncActiveJobEvents()
    window.addEventListener('storage', onActiveJobsStorage)
    document.addEventListener('pointerdown', onHistoryFilterPointerDown)
  })

  watch(routeRunId, (runId) => {
    if (runId) {
      loadHistoryDetail(runId)
      return
    }
    historyDetailRequestVersion += 1
    showHistoryDetail.value = false
    historyDetail.value = null
    historyDetailLoading.value = false
    ragAnswerMarkdown.value = ''
    ragAnswerError.value = ''
    ragFancyHtmlError.value = ''
    regenerateError.value = ''
    regenerateSuccess.value = ''
    regenerateOverwriteConfirm.value = false
    stopRagFancyHtmlEventStream()
    stopRagFancyHtmlPolling()
  })

  watch(
    [selectedSummaryPreset, summaryDefaultPreset],
    ([selectedPreset, defaultPreset]) => {
      if (showHistoryDetail.value && !selectedHistorySummaryPreset.value) {
        selectedHistorySummaryPreset.value =
          selectedPreset || defaultPreset || ''
      }
    }
  )

  watch(selectedSummaryProfile, (profile) => {
    if (showHistoryDetail.value && !selectedHistorySummaryProfile.value) {
      selectedHistorySummaryProfile.value = profile || ''
    }
  })

  onBeforeUnmount(() => {
    historyDetailRequestVersion += 1
    stopRagFancyHtmlEventStream()
    stopRagFancyHtmlPolling()
    stopActiveJobsEvents()
    stopActiveJobsPolling()
    window.removeEventListener('storage', onActiveJobsStorage)
    document.removeEventListener('pointerdown', onHistoryFilterPointerDown)
  })
</script>

<template>
  <section class="history-layout">
    <!-- Detail View -->
    <article v-if="showHistoryDetail" class="panel panel-history">
      <header class="history-detail-header">
        <button class="detail-back" @click="closeHistoryDetail">
          <ArrowLeft :size="16" />
          <span>返回列表</span>
        </button>
      </header>

      <div v-if="historyDetailLoading" class="history-detail-skeleton">
        <div class="history-skeleton-line skeleton-title"></div>
        <div class="history-skeleton-line skeleton-meta"></div>
        <div class="history-skeleton-line skeleton-meta short"></div>
        <div class="history-skeleton-block"></div>
        <div class="history-skeleton-block compact"></div>
      </div>

      <template v-else-if="historyDetail">
        <div class="detail-info">
          <div class="detail-header-row">
            <div>
              <h2 class="detail-title">{{ historyDetail.title }}</h2>
              <div class="detail-meta">
                <a
                  v-if="resourceUrl(historyDetail.bvid, historyDetail.page)"
                  class="detail-bvid"
                  :href="resourceUrl(historyDetail.bvid, historyDetail.page)"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {{
                    resourceDisplayLabel(historyDetail.bvid, historyDetail.page)
                  }}
                </a>
                <span v-else class="detail-bvid">
                  {{
                    resourceDisplayLabel(historyDetail.bvid, historyDetail.page)
                  }}
                </span>
                <span v-if="historyDetail.author" class="detail-author-tag">
                  <User :size="12" />
                  {{ resourceAuthorLabel(historyDetail.bvid) }}
                  {{ historyDetail.author }}
                </span>
                <span v-if="historyDetail.pubdate" class="detail-pubdate">
                  <CalendarDays :size="14" />
                  发布时间：{{ historyDetail.pubdate }}
                </span>
                <span class="detail-time">
                  <Clock :size="14" />
                  {{
                    historyDetail.record_type === 'rag_query'
                      ? '查询时间：'
                      : '转录时间：'
                  }}{{ formatTime(historyDetail.created_at) }}
                </span>
              </div>
            </div>
            <button
              v-if="allowDelete"
              class="delete-button"
              @click="confirmDelete(historyDetail.run_id)"
              :disabled="deleteLoading"
            >
              <Trash2 :size="16" />
              <span>删除</span>
            </button>
          </div>
        </div>

        <div
          v-if="historyDetail.record_type !== 'rag_query'"
          class="history-regenerate"
        >
          <div class="history-regenerate-head">
            <p class="history-regenerate-kicker">重新生成配置</p>
            <h3>总结参数</h3>
            <p>
              可切换模型配置与 preset，对同一条历史转录重新生成总结。
              <template v-if="requiresApiKey">
                选择“用户自定义”时，会使用你在 API Key 页面保存的模板。
              </template>
            </p>
          </div>

          <div class="history-regenerate-grid">
            <div class="summary-preset history-summary-preset">
              <label for="history-summary-profile-select">模型配置</label>
              <select
                id="history-summary-profile-select"
                v-model="selectedHistorySummaryProfile"
                class="preset-select history-preset-select"
                :disabled="regenerateLoading || summaryProfiles.length === 0"
              >
                <option v-if="summaryProfiles.length === 0" value="">
                  未获取到模型配置（将使用后端默认）
                </option>
                <option
                  v-for="profile in summaryProfiles"
                  :key="profile.name"
                  :value="profile.name"
                >
                  {{ formatSummaryProfileLabel(profile) }}
                </option>
              </select>
            </div>

            <div class="summary-preset history-summary-preset">
              <label for="history-summary-preset-select">总结模板</label>
              <select
                id="history-summary-preset-select"
                v-model="selectedHistorySummaryPreset"
                class="preset-select history-preset-select"
                :disabled="
                  regenerateLoading || historyPresetOptions.length === 0
                "
              >
                <option v-if="historyPresetOptions.length === 0" value="">
                  未获取到 preset（将使用后端默认）
                </option>
                <option
                  v-for="preset in historyPresetOptions"
                  :key="preset.name"
                  :value="preset.name"
                >
                  {{ preset.label }}
                </option>
              </select>
            </div>
          </div>

          <button
            class="submit history-regenerate-button"
            type="button"
            :disabled="regenerateDisabled"
            @click="regenerateSummary(false)"
          >
            <LoaderCircle v-if="regenerateLoading" :size="16" class="spin" />
            <span>{{
              regenerateLoading ? '生成中...' : '用当前配置重新生成总结'
            }}</span>
          </button>
          <p
            v-if="isSelectedSummaryAlreadyGenerated"
            class="preset-hint duplicate-summary-hint"
          >
            该模型配置与总结模板已经生成过；重新生成前将要求确认并覆盖原结果。
          </p>
          <p v-if="regenerateError" class="inline-error">
            <AlertCircle :size="16" />
            <span>{{ regenerateError }}</span>
          </p>
          <p v-if="regenerateSuccess" class="preset-hint">
            {{ regenerateSuccess }}
          </p>
        </div>

        <div
          v-if="historyDetail.record_type === 'rag_query'"
          class="rag-history-preview"
        >
          <div class="rag-history-preview-head">
            <div>
              <p class="history-regenerate-kicker">知识库回答</p>
              <h3>渲染预览</h3>
            </div>
            <div class="rag-fancy-actions">
              <button
                class="rag-fancy-btn"
                :disabled="
                  ragFancyHtmlGenerating ||
                  ragAnswerLoading ||
                  historyDetail.fancy_html_status === 'running'
                "
                @click="generateRagFancyHtml"
              >
                <LoaderCircle
                  v-if="
                    ragFancyHtmlGenerating ||
                    historyDetail.fancy_html_status === 'running'
                  "
                  :size="13"
                  class="spin"
                />
                <FileText v-else :size="13" />
                <span>{{
                  historyDetail.fancy_html_status === 'running'
                    ? '生成中...'
                    : 'Fancy HTML'
                }}</span>
              </button>
            </div>
          </div>
          <p
            v-if="historyDetail.fancy_html_status === 'running'"
            class="preset-hint"
            style="margin-top: 6px"
          >
            Fancy HTML 正在后台生成，离开当前页面后稍后再回来，状态仍会保留。
          </p>
          <p v-if="ragFancyConnectionNotice" class="connection-notice">
            <AlertCircle :size="14" />
            <span>{{ ragFancyConnectionNotice }}</span>
          </p>
          <p
            v-if="ragFancyHtmlError"
            class="inline-error"
            style="margin-top: 6px"
          >
            <AlertCircle :size="14" />
            <span>{{ ragFancyHtmlError }}</span>
          </p>
          <div v-if="ragAnswerLoading" class="status-loading">
            <LoaderCircle :size="14" class="spin" />
            <span>加载回答中…</span>
          </div>
          <p v-else-if="ragAnswerError" class="inline-error">
            <AlertCircle :size="16" />
            <span>{{ ragAnswerError }}</span>
          </p>
          <article
            v-else-if="renderedRagAnswer"
            class="rag-history-markdown"
            v-html="renderedRagAnswer"
          />

          <section v-if="ragReferenceItems.length" class="rag-history-sources">
            <h3 class="rag-history-sources-heading">
              <BookMarked :size="15" />
              <span>参考来源</span>
              <span class="rag-history-sources-count">{{
                ragReferenceItems.length
              }}</span>
            </h3>
            <div class="rag-history-sources-grid">
              <a
                v-for="item in ragReferenceItems"
                :id="`source-${item.index}`"
                :key="`${item.index}-${item.bvid}-${item.title}`"
                :href="item.bvid ? resourceUrl(item.bvid) : undefined"
                class="rag-history-source-card"
                :class="{ 'no-link': !resourceUrl(item.bvid) }"
                target="_blank"
                rel="noopener noreferrer"
              >
                <div class="rag-history-source-top">
                  <span class="rag-history-source-index">{{ item.index }}</span>
                  <div class="rag-history-source-meta">
                    <span class="rag-history-source-title">{{
                      item.title || item.bvid || '未知视频'
                    }}</span>
                    <span v-if="item.bvid" class="rag-history-source-bvid">
                      {{ resourceDisplayLabel(item.bvid) }}
                      <ExternalLink v-if="resourceUrl(item.bvid)" :size="11" />
                    </span>
                  </div>
                  <div class="rag-history-source-score">{{ item.score }}%</div>
                </div>
                <p class="rag-history-source-excerpt">{{ item.text }}</p>
              </a>
            </div>
          </section>
        </div>

        <FileList
          class="detail-download-list"
          :items="historyDetailDownloadRows"
          :selected-summary-preset="selectedHistorySummaryPreset"
          :selected-summary-profile="selectedHistorySummaryProfile"
          :bvid="historyDetail.bvid"
          :history-run-id="historyDetail.run_id"
          title="文件列表"
          :filter-kinds="
            historyDetail.record_type === 'rag_query'
              ? ['rag_answer', 'summary_fancy_html']
              : [
                  'markdown',
                  'summary',
                  'summary_no_table',
                  'summary_fancy_html',
                  'summary_table_md',
                  'summary_table_pdf',
                  'summary_timeline',
                  'text',
                  'json',
                  'audio'
                ]
          "
          @artifact-deleted="onHistoryArtifactDeleted"
          @artifact-generated="onHistoryArtifactGenerated"
        />
      </template>
    </article>

    <!-- List View -->
    <article v-else class="panel panel-history">
      <header class="history-list-header">
        <h2>历史记录</h2>
        <div class="history-search-row">
          <Search :size="16" />
          <input
            v-model="historySearch"
            type="text"
            placeholder="搜索标题、BV 号或 UP 主..."
            @input="onSearchInput"
          />
        </div>
      </header>

      <!-- Active jobs section -->
      <p
        v-if="activeJobsConnectionNotice && activeJobs.length > 0"
        class="connection-notice"
      >
        <AlertCircle :size="14" />
        <span>{{ activeJobsConnectionNotice }}</span>
      </p>
      <div v-if="activeJobs.length > 0" class="active-jobs-section">
        <h3 class="active-jobs-heading">
          <LoaderCircle :size="14" class="spin" />
          进行中的任务
        </h3>
        <div
          v-for="job in activeJobs"
          :key="job.job_id"
          class="active-job-card"
          @click="router.push(`/process/${job.job_id}`)"
        >
          <div class="active-job-info">
            <p class="active-job-title-text">
              {{ job.title || job.bvid || '转录中...' }}
            </p>
            <div class="active-job-meta">
              <span v-if="job.bvid && job.title" class="active-job-bvid">{{
                job.bvid
              }}</span>
              <span v-if="job.author" class="active-job-author">
                <User :size="11" />
                {{ job.author }}
              </span>
            </div>
            <p class="active-job-stage">{{ job.stage_label }}</p>
            <div class="active-job-progress-bar">
              <div
                class="active-job-progress-fill"
                :style="{ width: job.progress + '%' }"
              ></div>
            </div>
          </div>
          <button
            class="active-job-cancel"
            type="button"
            title="取消任务"
            @click.stop="cancelActiveJob(job.job_id)"
          >
            <XCircle :size="16" />
          </button>
        </div>
      </div>

      <div class="history-filter-bar">
        <div class="history-filter-heading">
          <SlidersHorizontal :size="15" />
          <span>筛选</span>
        </div>
        <div ref="historyPlatformFilterRef" class="history-filter-field">
          <span>平台</span>
          <button
            type="button"
            class="history-filter-trigger"
            :class="{ active: historyPlatforms.length > 0 }"
            :disabled="historyFiltersLoading"
            :aria-expanded="historyPlatformMenuOpen"
            @click="toggleHistoryFilterMenu('platform')"
          >
            <span>{{ historyPlatformFilterLabel }}</span>
            <ChevronDown :size="15" />
          </button>
          <div v-if="historyPlatformMenuOpen" class="history-filter-menu-shell">
            <div
              ref="historyPlatformMenuRef"
              class="history-filter-menu"
              :class="{
                'history-filter-menu-has-more': historyPlatformMenuHasMore
              }"
              role="group"
              aria-label="平台筛选"
              @scroll="onHistoryFilterMenuScroll('platform', $event)"
            >
              <label
                v-for="option in historyPlatformOptions"
                :key="option.platform"
                class="history-filter-option"
              >
                <input
                  type="checkbox"
                  :checked="historyPlatforms.includes(option.platform)"
                  @change="
                    toggleHistoryPlatform(
                      option.platform,
                      $event.target.checked
                    )
                  "
                />
                <span>{{ option.name }}</span>
                <span class="history-filter-option-count">{{
                  option.count
                }}</span>
              </label>
              <span
                v-if="historyPlatformOptions.length === 0"
                class="history-filter-empty"
              >
                暂无平台
              </span>
            </div>
            <div
              v-if="historyPlatformMenuHasMore"
              class="history-filter-scroll-hint"
              aria-hidden="true"
            >
              <span>向下滚动查看更多</span>
              <ChevronDown :size="14" />
            </div>
          </div>
        </div>
        <div ref="historyCategoryFilterRef" class="history-filter-field">
          <span>分区</span>
          <button
            type="button"
            class="history-filter-trigger"
            :class="{ active: historyCategoryTids.length > 0 }"
            :disabled="historyFiltersLoading"
            :aria-expanded="historyCategoryMenuOpen"
            @click="toggleHistoryFilterMenu('category')"
          >
            <span>{{ historyCategoryFilterLabel }}</span>
            <ChevronDown :size="15" />
          </button>
          <div v-if="historyCategoryMenuOpen" class="history-filter-menu-shell">
            <div
              ref="historyCategoryMenuRef"
              class="history-filter-menu"
              :class="{
                'history-filter-menu-has-more': historyCategoryMenuHasMore
              }"
              role="group"
              aria-label="分区筛选"
              @scroll="onHistoryFilterMenuScroll('category', $event)"
            >
              <label
                v-for="option in historyCategoryOptions"
                :key="`${option.tid}-${option.is_parent ? 'parent' : 'item'}`"
                class="history-filter-option"
                :class="{
                  'history-filter-option-child': option.parent_tid,
                  'history-filter-option-parent': option.is_parent
                }"
              >
                <input
                  type="checkbox"
                  :checked="historyCategoryTids.includes(option.tid)"
                  @change="
                    toggleHistoryCategory(option.tid, $event.target.checked)
                  "
                />
                <span>
                  {{
                    option.is_parent ? `${option.tname} · 全部` : option.tname
                  }}
                </span>
                <span class="history-filter-option-count">{{
                  option.count
                }}</span>
              </label>
              <span
                v-if="historyCategoryOptions.length === 0"
                class="history-filter-empty"
              >
                暂无分区
              </span>
            </div>
            <div
              v-if="historyCategoryMenuHasMore"
              class="history-filter-scroll-hint"
              aria-hidden="true"
            >
              <span>向下滚动查看更多</span>
              <ChevronDown :size="14" />
            </div>
          </div>
        </div>
        <div ref="historyAuthorFilterRef" class="history-filter-field">
          <span>UP 主</span>
          <button
            type="button"
            class="history-filter-trigger"
            :class="{ active: historyAuthors.length > 0 }"
            :disabled="historyFiltersLoading"
            :aria-expanded="historyAuthorMenuOpen"
            @click="toggleHistoryFilterMenu('author')"
          >
            <span>{{ historyAuthorFilterLabel }}</span>
            <ChevronDown :size="15" />
          </button>
          <div v-if="historyAuthorMenuOpen" class="history-filter-menu-shell">
            <div
              ref="historyAuthorMenuRef"
              class="history-filter-menu"
              :class="{
                'history-filter-menu-has-more': historyAuthorMenuHasMore
              }"
              role="group"
              aria-label="UP 主筛选"
              @scroll="onHistoryFilterMenuScroll('author', $event)"
            >
              <label
                v-for="option in historyAuthorOptions"
                :key="option.author"
                class="history-filter-option"
              >
                <input
                  type="checkbox"
                  :checked="historyAuthors.includes(option.author)"
                  @change="
                    toggleHistoryAuthor(option.author, $event.target.checked)
                  "
                />
                <span>{{ option.author }}</span>
                <span class="history-filter-option-count">{{
                  option.count
                }}</span>
              </label>
              <span
                v-if="historyAuthorOptions.length === 0"
                class="history-filter-empty"
              >
                暂无 UP 主
              </span>
            </div>
            <div
              v-if="historyAuthorMenuHasMore"
              class="history-filter-scroll-hint"
              aria-hidden="true"
            >
              <span>向下滚动查看更多</span>
              <ChevronDown :size="14" />
            </div>
          </div>
        </div>
        <button
          type="button"
          class="history-filter-reset"
          :disabled="!hasActiveHistoryFilters"
          @click="resetHistoryFilters"
        >
          <RotateCcw :size="14" />
          <span>重置</span>
        </button>
      </div>

      <div
        v-if="showHistorySkeleton"
        class="history-list-skeleton"
        aria-hidden="true"
      >
        <div v-for="idx in 6" :key="idx" class="history-skeleton-item">
          <div class="history-skeleton-main">
            <div class="history-skeleton-line skeleton-title"></div>
            <div class="history-skeleton-line skeleton-bvid"></div>
            <div class="history-skeleton-line skeleton-meta"></div>
          </div>
          <div class="history-skeleton-action"></div>
        </div>
      </div>
      <p v-else-if="historyError" class="inline-error">
        <AlertCircle :size="16" />
        <span>{{ historyError }}</span>
      </p>
      <div v-else-if="historyItems.length === 0" class="history-empty">
        <FileText :size="32" />
        <p>暂无历史转录记录。</p>
      </div>

      <ul v-else class="history-list">
        <li
          v-for="item in historyItems"
          :key="item.run_id"
          class="history-item"
        >
          <div
            class="history-item-content"
            @click="openHistoryDetail(item.run_id)"
          >
            <div class="history-item-main">
              <span
                v-if="item.record_type === 'rag_query'"
                class="history-record-badge history-record-badge-rag"
              >
                <Brain :size="11" />
                知识库查询
              </span>
              <span class="history-title">{{ item.title || item.bvid }}</span>
              <a
                v-if="
                  item.record_type !== 'rag_query' &&
                  item.bvid &&
                  resourceUrl(item.bvid, item.page)
                "
                class="history-bvid"
                :href="resourceUrl(item.bvid, item.page)"
                target="_blank"
                rel="noopener noreferrer"
                @click.stop
              >
                {{ resourceDisplayLabel(item.bvid, item.page) }}
              </a>
              <span
                v-else-if="item.record_type !== 'rag_query' && item.bvid"
                class="history-bvid"
              >
                {{ resourceDisplayLabel(item.bvid, item.page) }}
              </span>
              <span v-if="item.author" class="history-author-tag">
                <User :size="12" />
                {{ resourceAuthorLabel(item.bvid) }} {{ item.author }}
              </span>
            </div>
            <div class="history-item-meta">
              <span
                v-if="item.parent_tname"
                class="history-category-tag history-category-tag-parent"
              >
                {{ item.parent_tname }}
              </span>
              <span
                v-if="item.tname"
                class="history-category-tag history-category-tag-child"
              >
                {{ item.tname }}
              </span>
              <span v-if="item.pubdate" class="history-pubdate">
                <CalendarDays :size="13" />
                发布时间：{{ item.pubdate }}
              </span>
              <span class="history-time">
                <Clock :size="13" />
                {{
                  item.record_type === 'rag_query'
                    ? '查询时间：'
                    : '转录时间：'
                }}{{ formatTime(item.created_at) }}
              </span>
              <span class="history-file-count"
                >{{ item.file_count }} 个文件</span
              >
            </div>
          </div>
          <button
            v-if="allowDelete"
            class="history-item-delete"
            @click.stop="confirmDelete(item.run_id)"
            :disabled="deleteLoading"
            title="删除"
          >
            <Trash2 :size="16" />
          </button>
        </li>
      </ul>

      <!-- Pagination -->
      <div v-if="historyTotal > historyPageSize" class="history-pagination">
        <button
          class="pagination-icon-button"
          :disabled="historyPage <= 1 || historyLoading"
          title="第一页"
          aria-label="跳转到第一页"
          @click="goToHistoryPage(1)"
        >
          <ChevronsLeft :size="16" />
        </button>
        <button
          class="pagination-icon-button"
          :disabled="historyPage <= 1 || historyLoading"
          title="上一页"
          aria-label="跳转到上一页"
          @click="historyPrevPage"
        >
          <ChevronLeft :size="16" />
        </button>
        <span class="pagination-status">
          第 {{ historyPage }} 页 / 共 {{ historyTotalPages }} 页
        </span>
        <form class="pagination-jump" @submit.prevent="submitHistoryPageJump">
          <input
            v-model="historyJumpPage"
            type="number"
            inputmode="numeric"
            min="1"
            :max="historyTotalPages"
            placeholder="页码"
            aria-label="输入要跳转的页码"
            :disabled="historyLoading"
          />
          <button type="submit" :disabled="historyLoading || !historyJumpPage">
            跳转
          </button>
        </form>
        <button
          class="pagination-icon-button"
          :disabled="!historyHasMore || historyLoading"
          title="下一页"
          aria-label="跳转到下一页"
          @click="historyNextPage"
        >
          <ChevronRight :size="16" />
        </button>
        <button
          class="pagination-icon-button"
          :disabled="!historyHasMore || historyLoading"
          title="最后一页"
          aria-label="跳转到最后一页"
          @click="goToHistoryPage(historyTotalPages)"
        >
          <ChevronsRight :size="16" />
        </button>
      </div>
    </article>

    <div
      v-if="regenerateOverwriteConfirm"
      class="modal-overlay"
      @click="cancelRegenerateOverwrite"
    >
      <div
        class="modal-content"
        role="dialog"
        aria-modal="true"
        aria-labelledby="regenerate-overwrite-title"
        @click.stop
      >
        <h3 id="regenerate-overwrite-title">确认覆盖总结</h3>
        <p>
          当前模型配置“{{ selectedRegenerateProfileName }}”与总结模板“{{
            selectedRegeneratePresetName
          }}”已经生成过。继续后将重新生成总结，并替换原总结及其表格、时间线和导出文件。
        </p>
        <div class="modal-actions">
          <button class="cancel-button" @click="cancelRegenerateOverwrite">
            取消
          </button>
          <button
            class="confirm-delete-button"
            @click="regenerateSummary(true)"
          >
            <RefreshCw :size="16" />
            <span>确认覆盖并生成</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Delete Confirmation Modal -->
    <div
      v-if="allowDelete && deleteConfirmRunId"
      class="modal-overlay"
      @click="cancelDelete"
    >
      <div class="modal-content" @click.stop>
        <h3>确认删除</h3>
        <p>确定要删除这条历史记录吗？此操作将删除所有相关文件，且无法恢复。</p>
        <div class="modal-actions">
          <button
            class="cancel-button"
            @click="cancelDelete"
            :disabled="deleteLoading"
          >
            取消
          </button>
          <button
            class="confirm-delete-button"
            @click="deleteHistory(deleteConfirmRunId)"
            :disabled="deleteLoading"
          >
            <Trash2 v-if="!deleteLoading" :size="16" />
            <LoaderCircle v-else :size="16" class="spin" />
            <span>{{ deleteLoading ? '删除中...' : '确认删除' }}</span>
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
  /* ─── Layout & Panel variant ─────────────────────────────────── */

  .history-layout {
    position: relative;
    z-index: 2;
    max-width: 1160px;
    margin: 0 auto;
  }

  .panel-history {
    padding: 28px;
  }

  /* ─── List header ────────────────────────────────────────────── */

  .history-list-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
  }

  .history-record-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 7px;
    border-radius: 5px;
    font-size: 0.72rem;
    font-weight: 700;
    flex-shrink: 0;
  }

  .history-record-badge-rag {
    background: var(--brand-soft, #e6fffb);
    color: var(--brand-strong, #0f766e);
    border: 1px solid rgba(13, 148, 136, 0.2);
  }

  .history-list-header h2 {
    margin: 0;
    font-size: 1.14rem;
    white-space: nowrap;
  }

  .history-search-row {
    display: flex;
    align-items: center;
    gap: 8px;
    border: 1px solid var(--line);
    background: rgba(255, 255, 255, 0.9);
    border-radius: 12px;
    padding: 0 12px;
    min-height: 40px;
    min-width: 240px;
    max-width: 360px;
    flex: 1;
    transition:
      border-color 0.2s ease,
      box-shadow 0.2s ease;
  }

  .history-search-row:focus-within {
    border-color: #22d3ee;
    box-shadow: 0 0 0 4px rgba(34, 211, 238, 0.16);
  }

  .history-search-row svg {
    color: #94a3b8;
    flex-shrink: 0;
  }

  .history-search-row input {
    width: 100%;
    border: none;
    outline: none;
    background: transparent;
    color: var(--text-main);
    height: 38px;
    font-size: 0.9rem;
  }

  .history-filter-bar {
    display: grid;
    grid-template-columns:
      auto minmax(140px, 0.8fr) minmax(170px, 1fr) minmax(190px, 1.2fr)
      auto;
    align-items: end;
    gap: 12px;
    margin: 18px -28px 0;
    padding: 12px 28px;
    border-top: 1px solid rgba(148, 163, 184, 0.2);
    border-bottom: 1px solid rgba(148, 163, 184, 0.2);
    background: #f8fafc;
  }

  .history-filter-heading {
    display: inline-flex;
    align-items: center;
    align-self: center;
    gap: 6px;
    color: #475569;
    font-size: 0.82rem;
    font-weight: 700;
    white-space: nowrap;
  }

  .history-filter-heading svg {
    color: #0f766e;
  }

  .history-filter-field {
    position: relative;
    display: grid;
    gap: 5px;
    min-width: 0;
  }

  .history-filter-field > span {
    color: #64748b;
    font-size: 0.72rem;
    font-weight: 700;
  }

  .history-filter-trigger {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    width: 100%;
    min-width: 0;
    height: 36px;
    padding: 0 9px 0 10px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #fff;
    color: #334155;
    font: inherit;
    font-size: 0.82rem;
    cursor: pointer;
    text-align: left;
  }

  .history-filter-trigger > span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .history-filter-trigger svg {
    flex-shrink: 0;
    color: #64748b;
    transition: transform 0.15s ease;
  }

  .history-filter-trigger[aria-expanded='true'] svg {
    transform: rotate(180deg);
  }

  .history-filter-trigger:hover:not(:disabled),
  .history-filter-trigger.active {
    border-color: #94a3b8;
  }

  .history-filter-trigger:focus-visible {
    border-color: #14b8a6;
    outline: 3px solid rgba(20, 184, 166, 0.14);
  }

  .history-filter-trigger:disabled {
    cursor: wait;
    opacity: 0.65;
  }

  .history-filter-menu-shell {
    position: absolute;
    z-index: 20;
    top: calc(100% + 6px);
    left: 0;
    width: max(100%, 220px);
    max-width: min(320px, calc(100vw - 40px));
  }

  .history-filter-menu {
    width: 100%;
    max-height: 280px;
    overflow-y: auto;
    padding: 5px;
    box-sizing: border-box;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #fff;
    box-shadow: 0 12px 28px rgba(15, 23, 42, 0.16);
  }

  .history-filter-menu-has-more {
    padding-bottom: 38px;
  }

  .history-filter-scroll-hint {
    position: absolute;
    right: 1px;
    bottom: 1px;
    left: 1px;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    gap: 3px;
    height: 45px;
    padding-bottom: 7px;
    box-sizing: border-box;
    border-radius: 0 0 5px 5px;
    background: linear-gradient(
      to bottom,
      rgba(255, 255, 255, 0),
      rgba(255, 255, 255, 0.96) 48%
    );
    color: #64748b;
    font-size: 0.7rem;
    font-weight: 600;
    pointer-events: none;
  }

  .history-filter-option {
    display: grid;
    grid-template-columns: 16px minmax(0, 1fr) auto;
    align-items: center;
    gap: 8px;
    min-height: 34px;
    padding: 5px 7px;
    border-radius: 4px;
    color: #334155;
    font-size: 0.8rem;
    cursor: pointer;
  }

  .history-filter-option:hover {
    background: #f1f5f9;
  }

  .history-filter-option input {
    width: 15px;
    height: 15px;
    margin: 0;
    accent-color: #0f766e;
  }

  .history-filter-option > span:not(.history-filter-option-count) {
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .history-filter-option-child {
    padding-left: 23px;
  }

  .history-filter-option-parent {
    font-weight: 700;
  }

  .history-filter-option-count {
    color: #94a3b8;
    font-size: 0.72rem;
    font-variant-numeric: tabular-nums;
  }

  .history-filter-empty {
    display: block;
    padding: 9px;
    color: #94a3b8;
    font-size: 0.78rem;
    text-align: center;
  }

  .history-filter-reset {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
    height: 36px;
    padding: 0 10px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #fff;
    color: #475569;
    font-size: 0.78rem;
    font-weight: 700;
    cursor: pointer;
  }

  .history-filter-reset:hover:not(:disabled) {
    border-color: #94a3b8;
    background: #f1f5f9;
  }

  .history-filter-reset:disabled {
    cursor: not-allowed;
    opacity: 0.45;
  }

  /* ─── Skeleton loading ───────────────────────────────────────── */

  .history-skeleton-line,
  .history-skeleton-block,
  .history-skeleton-action {
    position: relative;
    overflow: hidden;
    background: #e2e8f0;
  }

  .history-skeleton-line::after,
  .history-skeleton-block::after,
  .history-skeleton-action::after {
    content: '';
    position: absolute;
    inset: 0;
    transform: translateX(-100%);
    background: linear-gradient(
      90deg,
      rgba(255, 255, 255, 0) 0%,
      rgba(255, 255, 255, 0.68) 50%,
      rgba(255, 255, 255, 0) 100%
    );
    animation: history-skeleton-shimmer 1.1s ease-in-out infinite;
  }

  .history-list-skeleton {
    margin-top: 18px;
    display: grid;
    gap: 8px;
  }

  .history-skeleton-item {
    display: flex;
    align-items: stretch;
    gap: 10px;
    padding: 14px 16px;
    border-radius: 14px;
    border: 1px solid rgba(148, 163, 184, 0.2);
    background: rgba(255, 255, 255, 0.78);
  }

  .history-skeleton-main {
    flex: 1;
    min-width: 0;
    display: grid;
    gap: 8px;
  }

  .history-skeleton-line {
    border-radius: 10px;
  }

  .history-skeleton-line.skeleton-title {
    width: min(56%, 420px);
    height: 18px;
  }

  .history-skeleton-line.skeleton-bvid {
    width: 140px;
    height: 14px;
  }

  .history-skeleton-line.skeleton-meta {
    width: min(62%, 480px);
    height: 13px;
  }

  .history-skeleton-line.skeleton-meta.short {
    width: min(42%, 320px);
  }

  .history-skeleton-action {
    width: 34px;
    height: 34px;
    border-radius: 10px;
    align-self: center;
    flex-shrink: 0;
  }

  .history-detail-skeleton {
    display: grid;
    gap: 10px;
  }

  .history-skeleton-block {
    width: 100%;
    height: 118px;
    border-radius: 14px;
  }

  .history-skeleton-block.compact {
    height: 92px;
  }

  /* ─── Empty state ────────────────────────────────────────────── */

  .history-empty {
    margin-top: 32px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    color: #94a3b8;
    padding: 40px 0;
  }

  .history-empty svg {
    opacity: 0.5;
  }

  .history-empty p {
    margin: 0;
    font-size: 0.92rem;
  }

  /* ─── History list ───────────────────────────────────────────── */

  .history-list {
    margin: 18px 0 0;
    padding: 0;
    list-style: none;
    display: grid;
    gap: 8px;
  }

  .history-item {
    border: 1px solid rgba(148, 163, 184, 0.3);
    border-radius: 14px;
    padding: 14px 16px;
    background: rgba(255, 255, 255, 0.84);
    display: flex;
    align-items: center;
    gap: 12px;
    transition:
      border-color 0.2s ease,
      background-color 0.2s ease,
      box-shadow 0.2s ease;
  }

  .history-item:hover {
    border-color: #99f6e4;
    background: rgba(240, 253, 250, 0.7);
    box-shadow: 0 4px 16px rgba(13, 148, 136, 0.08);
  }

  .history-item-content {
    flex: 1;
    cursor: pointer;
    min-width: 0;
  }

  .history-item-delete {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: 8px;
    background: rgba(254, 242, 242, 0.6);
    color: #dc2626;
    cursor: pointer;
    transition: all 0.2s ease;
    padding: 0;
  }

  .history-item-delete:hover:not(:disabled) {
    border-color: #fca5a5;
    background: #fef2f2;
    transform: scale(1.05);
  }

  .history-item-delete:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .history-item-main {
    display: flex;
    align-items: baseline;
    gap: 10px;
    flex-wrap: wrap;
  }

  .history-title {
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--text-main);
    word-break: break-word;
  }

  .history-bvid {
    font-size: 0.8rem;
    color: var(--brand-strong);
    font-weight: 600;
    font-family: 'SFMono-Regular', Menlo, Monaco, Consolas, monospace;
    flex-shrink: 0;
    text-decoration: none;
  }

  .history-bvid:hover {
    text-decoration: underline;
  }

  .history-item-meta {
    margin-top: 8px;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }

  .history-time,
  .history-pubdate {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.8rem;
    color: var(--text-muted);
  }

  .history-category-tag {
    display: inline-flex;
    align-items: center;
    min-height: 22px;
    padding: 2px 7px;
    border: 1px solid transparent;
    border-radius: 5px;
    font-size: 0.72rem;
    font-weight: 700;
    line-height: 1;
    white-space: nowrap;
  }

  .history-category-tag-parent {
    border-color: #cbd5e1;
    background: #f8fafc;
    color: #475569;
  }

  .history-category-tag-child {
    border-color: #99f6e4;
    background: #f0fdfa;
    color: #0f766e;
  }

  .history-author-tag {
    display: inline-flex;
    align-items: center;
    min-height: 22px;
    padding: 0 8px;
    border-radius: 999px;
    gap: 4px;
    border: 1px solid #bfdbfe;
    background: #eff6ff;
    color: #1d4ed8;
    font-size: 0.72rem;
    font-weight: 700;
  }

  .history-file-count {
    font-size: 0.8rem;
    color: var(--text-muted);
  }

  /* ─── Pagination ─────────────────────────────────────────────── */

  .history-pagination {
    margin-top: 18px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  .history-pagination button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 34px;
    padding: 0 14px;
    border: 1px solid var(--line);
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.9);
    color: var(--text-soft);
    font-size: 0.84rem;
    font-weight: 600;
    cursor: pointer;
    transition:
      border-color 0.2s ease,
      background-color 0.2s ease;
  }

  .history-pagination button:hover:not(:disabled) {
    border-color: #99f6e4;
    background: #f0fdfa;
  }

  .history-pagination button:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .history-pagination span {
    font-size: 0.82rem;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }

  .history-pagination .pagination-icon-button {
    width: 34px;
    min-width: 34px;
    padding: 0;
  }

  .pagination-status {
    min-width: 132px;
    text-align: center;
  }

  .pagination-jump {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }

  .pagination-jump input {
    width: 70px;
    height: 34px;
    padding: 0 8px;
    border: 1px solid var(--line);
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.9);
    color: var(--text);
    font: inherit;
    font-size: 0.84rem;
    text-align: center;
    font-variant-numeric: tabular-nums;
  }

  .pagination-jump input:focus {
    outline: 2px solid rgba(20, 184, 166, 0.2);
    border-color: #14b8a6;
  }

  /* ─── Detail header ──────────────────────────────────────────── */

  .history-detail-header {
    margin-bottom: 16px;
  }

  .detail-back {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    border: none;
    background: transparent;
    color: var(--brand-strong);
    font-size: 0.88rem;
    font-weight: 600;
    cursor: pointer;
    padding: 0;
    transition: opacity 0.2s ease;
  }

  .detail-back:hover {
    opacity: 0.7;
  }

  /* ─── Detail info ────────────────────────────────────────────── */

  .detail-info {
    margin-bottom: 20px;
  }

  .status-loading {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.84rem;
    color: var(--text-muted, #64748b);
  }

  .detail-header-row {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
  }

  .rag-history-preview {
    display: flex;
    flex-direction: column;
    gap: 14px;
    margin-bottom: 22px;
    padding: 18px 20px;
    border: 1px solid rgba(148, 163, 184, 0.22);
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.72);
  }

  .rag-history-preview-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
  }

  .rag-history-preview-head h3 {
    margin: 3px 0 0;
    font-size: 1rem;
    color: var(--text-main);
  }

  .rag-fancy-actions {
    flex-shrink: 0;
  }

  .rag-fancy-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 5px 12px;
    border: 1.5px solid rgba(249, 115, 22, 0.35);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.8);
    color: #c2410c;
    font-size: 0.8rem;
    font-weight: 700;
    cursor: pointer;
    transition:
      border-color 0.15s,
      background 0.15s;
  }

  .rag-fancy-btn:hover:not(:disabled) {
    border-color: #f97316;
    background: rgba(249, 115, 22, 0.08);
  }

  .rag-fancy-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .rag-history-markdown {
    color: var(--text-main, #0f172a);
    font-size: 0.94rem;
    line-height: 1.8;
  }

  .rag-history-markdown :deep(h1),
  .rag-history-markdown :deep(h2),
  .rag-history-markdown :deep(h3),
  .rag-history-markdown :deep(h4) {
    margin: 0.9em 0 0.45em;
    line-height: 1.35;
    color: var(--text-main, #0f172a);
  }

  .rag-history-markdown :deep(h1) {
    font-size: 1.3rem;
  }

  .rag-history-markdown :deep(h2) {
    font-size: 1.08rem;
  }

  .rag-history-markdown :deep(h3) {
    font-size: 0.98rem;
  }

  .rag-history-markdown :deep(p),
  .rag-history-markdown :deep(ol),
  .rag-history-markdown :deep(ul),
  .rag-history-markdown :deep(blockquote),
  .rag-history-markdown :deep(pre) {
    margin: 0.7em 0;
  }

  .rag-history-markdown :deep(ol),
  .rag-history-markdown :deep(ul) {
    padding-left: 1.4em;
  }

  .rag-history-markdown :deep(li + li) {
    margin-top: 0.3em;
  }

  .rag-history-markdown :deep(blockquote) {
    margin-left: 0;
    padding: 10px 14px;
    border-left: 3px solid rgba(13, 148, 136, 0.28);
    background: rgba(240, 253, 250, 0.8);
    border-radius: 0 12px 12px 0;
    color: var(--text-soft, #334155);
  }

  .rag-history-markdown :deep(code) {
    padding: 0.15em 0.4em;
    border-radius: 6px;
    background: rgba(148, 163, 184, 0.16);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.88em;
  }

  .rag-history-markdown :deep(pre) {
    overflow: auto;
    padding: 12px 14px;
    border-radius: 14px;
    background: #0f172a;
    color: #e2e8f0;
  }

  .rag-history-markdown :deep(pre code) {
    padding: 0;
    background: transparent;
    color: inherit;
  }

  .rag-history-markdown :deep(a) {
    color: var(--brand-strong, #0f766e);
    text-decoration: none;
  }

  .rag-history-markdown :deep(a:hover) {
    text-decoration: underline;
  }

  .rag-history-markdown :deep(table) {
    display: block;
    width: 100%;
    max-width: 100%;
    border-collapse: collapse;
    margin: 0.9em 0;
    overflow-x: auto;
    border-radius: 12px;
    border: 1px solid rgba(148, 163, 184, 0.24);
  }

  .rag-history-markdown :deep(th),
  .rag-history-markdown :deep(td) {
    padding: 10px 12px;
    border-bottom: 1px solid rgba(148, 163, 184, 0.18);
    text-align: left;
    vertical-align: top;
  }

  .rag-history-markdown :deep(th) {
    background: rgba(241, 245, 249, 0.9);
    font-size: 0.8rem;
    font-weight: 700;
    color: var(--text-soft, #334155);
  }

  .rag-history-markdown :deep(td) {
    font-size: 0.85rem;
  }

  .rag-history-markdown :deep(.citation-ref) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 18px;
    height: 18px;
    padding: 0 4px;
    margin: 0 1px;
    border-radius: 5px;
    background: var(--brand-soft, #e6fffb);
    color: var(--brand-strong, #0f766e);
    font-size: 0.72rem;
    font-weight: 700;
    vertical-align: middle;
  }

  .rag-history-sources {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .rag-history-sources-heading {
    display: flex;
    align-items: center;
    gap: 7px;
    margin: 0;
    font-size: 0.86rem;
    font-weight: 700;
    color: var(--text-soft, #334155);
  }

  .rag-history-sources-count {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 20px;
    height: 20px;
    padding: 0 6px;
    border-radius: 99px;
    background: var(--brand-soft, #e6fffb);
    color: var(--brand-strong, #0f766e);
    font-size: 0.74rem;
    font-weight: 700;
  }

  .rag-history-sources-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 12px;
  }

  .rag-history-source-card {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 14px 16px;
    background: rgba(255, 255, 255, 0.82);
    border: 1px solid var(--panel-border, rgba(148, 163, 184, 0.28));
    border-radius: 16px;
    text-decoration: none;
    color: inherit;
    transition:
      transform 0.18s ease,
      box-shadow 0.18s ease,
      border-color 0.18s ease;
  }

  .rag-history-source-card:hover {
    transform: translateY(-1px);
    border-color: rgba(13, 148, 136, 0.34);
    box-shadow: 0 10px 22px rgba(15, 23, 42, 0.06);
  }

  .rag-history-source-card.no-link {
    cursor: default;
  }

  .rag-history-source-card.no-link:hover {
    transform: none;
    box-shadow: none;
  }

  .rag-history-source-top {
    display: flex;
    align-items: flex-start;
    gap: 10px;
  }

  .rag-history-source-index {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border-radius: 8px;
    background: #0f172a;
    color: #fff;
    font-size: 0.75rem;
    font-weight: 800;
    flex-shrink: 0;
  }

  .rag-history-source-meta {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
    flex: 1;
  }

  .rag-history-source-title {
    font-size: 0.88rem;
    font-weight: 700;
    color: var(--text-main, #0f172a);
  }

  .rag-history-source-bvid {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.76rem;
    color: var(--brand-strong, #0f766e);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }

  .rag-history-source-score {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 4px 8px;
    border-radius: 999px;
    background: rgba(13, 148, 136, 0.1);
    color: var(--brand-strong, #0f766e);
    font-size: 0.74rem;
    font-weight: 700;
    flex-shrink: 0;
  }

  .rag-history-source-excerpt {
    margin: 0;
    color: var(--text-soft, #334155);
    font-size: 0.82rem;
    line-height: 1.7;
  }

  .detail-header-row > :first-child {
    flex: 1;
    min-width: 0;
  }

  .detail-title {
    margin: 0 0 10px;
    font-size: 1.24rem;
    line-height: 1.3;
    word-break: break-word;
    overflow-wrap: anywhere;
  }

  .detail-meta {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }

  .detail-bvid {
    font-size: 0.86rem;
    color: var(--brand-strong);
    font-weight: 600;
    font-family: 'SFMono-Regular', Menlo, Monaco, Consolas, monospace;
    text-decoration: none;
  }

  .detail-bvid:hover {
    text-decoration: underline;
  }

  .detail-time,
  .detail-pubdate {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.84rem;
    color: var(--text-muted);
  }

  .detail-author-tag {
    display: inline-flex;
    align-items: center;
    min-height: 22px;
    padding: 0 8px;
    border-radius: 999px;
    gap: 4px;
    border: 1px solid #bfdbfe;
    background: #eff6ff;
    color: #1d4ed8;
    font-size: 0.72rem;
    font-weight: 700;
  }

  /* ─── Delete button ──────────────────────────────────────────── */

  .delete-button {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-height: 36px;
    padding: 0 14px;
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: 10px;
    background: rgba(254, 242, 242, 0.8);
    color: #dc2626;
    font-size: 0.86rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
  }

  .delete-button:hover:not(:disabled) {
    border-color: #fca5a5;
    background: #fef2f2;
    box-shadow: 0 2px 8px rgba(239, 68, 68, 0.15);
  }

  .delete-button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  /* ─── Regenerate section ─────────────────────────────────────── */

  .history-regenerate {
    margin-bottom: 20px;
    padding: 14px;
    border: 1px solid rgba(14, 165, 233, 0.18);
    border-radius: 14px;
    background: linear-gradient(180deg, #ffffff 0%, #f8fdff 100%);
    display: grid;
    gap: 12px;
  }

  .history-regenerate-head {
    display: grid;
    gap: 4px;
  }

  .history-regenerate-kicker {
    margin: 0;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    color: #0284c7;
  }

  .history-regenerate-head h3 {
    margin: 0;
    font-size: 1.06rem;
    color: #0f172a;
  }

  .history-regenerate-head p {
    margin: 0;
    font-size: 0.84rem;
    line-height: 1.5;
    color: #475569;
    overflow-wrap: anywhere;
  }

  .history-regenerate-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    min-width: 0;
  }

  .history-summary-preset {
    gap: 6px;
    min-width: 0;
  }

  .history-summary-preset label {
    font-size: 0.84rem;
    font-weight: 700;
    color: #334155;
  }

  .history-preset-select {
    min-height: 46px;
    border-radius: 12px;
    border-color: #cbd5e1;
    background: linear-gradient(145deg, #ffffff, #f8fafc);
    box-shadow: 0 1px 4px rgba(15, 23, 42, 0.04);
  }

  .history-preset-select:hover:not(:disabled) {
    border-color: #93c5fd;
    box-shadow: 0 6px 16px rgba(59, 130, 246, 0.08);
  }

  .history-preset-select:focus {
    border-color: #38bdf8;
    box-shadow: 0 0 0 4px rgba(56, 189, 248, 0.18);
  }

  .history-regenerate-button {
    margin-top: 2px;
  }

  .detail-download-list {
    margin-top: 0;
  }

  /* ─── Responsive ─────────────────────────────────────────────── */

  @media (max-width: 980px) {
    .history-filter-bar {
      grid-template-columns: auto repeat(3, minmax(0, 1fr));
    }

    .history-filter-reset {
      grid-column: 2 / -1;
      justify-self: start;
    }

    .history-regenerate-grid {
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 640px) {
    .history-list-header {
      flex-direction: column;
      align-items: stretch;
    }

    .history-search-row {
      max-width: none;
      min-width: 0;
      width: 100%;
    }

    .history-filter-bar {
      grid-template-columns: 1fr;
      margin-inline: -20px;
      padding-inline: 20px;
    }

    .history-filter-heading,
    .history-filter-reset {
      grid-column: auto;
    }

    .history-filter-reset {
      width: 100%;
    }

    .panel-history {
      padding: 20px;
    }

    .history-skeleton-line.skeleton-title,
    .history-skeleton-line.skeleton-meta,
    .history-skeleton-line.skeleton-meta.short {
      width: 100%;
    }

    .history-skeleton-item {
      padding: 12px;
    }

    .history-skeleton-action {
      width: 30px;
      height: 30px;
    }

    .history-item-main {
      flex-direction: column;
      gap: 4px;
    }

    .detail-header-row {
      flex-direction: column;
      align-items: stretch;
      gap: 12px;
    }

    .delete-button {
      justify-content: center;
      width: 100%;
    }

    .history-regenerate {
      padding: 12px;
    }

    .rag-history-preview {
      padding: 16px;
    }

    .rag-history-sources-grid {
      grid-template-columns: 1fr;
    }
  }
  /* ─── Active jobs ────────────────────────────────────────────── */

  .active-jobs-section {
    margin-bottom: 18px;
    display: grid;
    gap: 8px;
  }

  .active-jobs-heading {
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 0 0 4px;
    font-size: 0.82rem;
    font-weight: 700;
    color: #0284c7;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .active-job-card {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 14px;
    border: 1px solid #bae6fd;
    border-radius: 12px;
    background: linear-gradient(135deg, #f0f9ff, #e0f2fe);
    cursor: pointer;
    transition:
      box-shadow 0.2s ease,
      border-color 0.2s ease;
  }

  .active-job-card:hover {
    border-color: #7dd3fc;
    box-shadow: 0 2px 8px rgba(14, 165, 233, 0.12);
  }

  .active-job-info {
    flex: 1;
    min-width: 0;
    display: grid;
    gap: 4px;
  }

  .active-job-title-text {
    margin: 0;
    font-size: 0.92rem;
    font-weight: 700;
    color: #0f172a;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .active-job-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  .active-job-bvid {
    font-size: 0.8rem;
    font-weight: 600;
    color: #0369a1;
  }

  .active-job-author {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-size: 0.8rem;
    color: #64748b;
  }

  .active-job-stage {
    margin: 0;
    font-size: 0.82rem;
    color: #475569;
  }

  .active-job-progress-bar {
    height: 4px;
    border-radius: 999px;
    background: #bae6fd;
    overflow: hidden;
  }

  .active-job-progress-fill {
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(90deg, #0ea5e9, #14b8a6);
    transition: width 0.6s ease;
  }

  .active-job-cancel {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border: none;
    border-radius: 8px;
    background: transparent;
    color: #94a3b8;
    cursor: pointer;
    transition:
      color 0.2s ease,
      background-color 0.2s ease;
  }

  .active-job-cancel:hover {
    color: #dc2626;
    background: #fee2e2;
  }
</style>
