<script setup>
  import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
  import { useRoute, useRouter } from 'vue-router'
  import { RefreshCw, Search, Trash2 } from 'lucide-vue-next'
  import ConfirmDialog from './common/ConfirmDialog.vue'
  import HistoryFilters from './history/HistoryFilters.vue'
  import HistoryDetail from './history/HistoryDetail.vue'
  import HistoryList from './history/HistoryList.vue'
  import HistoryPagination from './history/HistoryPagination.vue'
  import ActiveJobsPanel from './jobs/ActiveJobsPanel.vue'
  import { artifactApi, historyApi, subscribeSse, summaryApi } from '../api'
  import { useActiveJobs } from '../composables/useActiveJobs'
  import { usePublicCredentials } from '../composables/usePublicCredentials'
  import { useRuntimeFeatures } from '../composables/useRuntimeFeatures'
  import {
    CUSTOM_SUMMARY_PRESET_VALUE,
    useSummaryConfig,
    withCustomSummaryPreset
  } from '../composables/useSummaryConfig'
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
    summaryDefaultPromptTemplate,
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
  const historySearch = ref('')
  const historyPlatforms = ref([])
  const historyCategoryTids = ref([])
  const historyAuthors = ref([])
  const historyPlatformOptions = ref([])
  const historyCategoryOptions = ref([])
  const historyAuthorOptions = ref([])
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

  const {
    activeJobs,
    connectionNotice: activeJobsConnectionNotice,
    cancel: cancelTrackedJob,
    onStorage: onActiveJobsStorage,
    sync: syncActiveJobEvents,
    stop: stopActiveJobs
  } = useActiveJobs()

  const cancelActiveJob = async (jobId) => {
    try {
      await cancelTrackedJob(jobId)
    } catch (err) {
      historyError.value = err instanceof Error ? err.message : '取消任务失败'
    }
  }

  let searchTimer = null

  const historyTotalPages = computed(() =>
    Math.max(1, Math.ceil(historyTotal.value / historyPageSize.value))
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
  const historyPlatformSelectOptions = computed(() =>
    historyPlatformOptions.value.map((option) => ({
      value: option.platform,
      label: option.name,
      count: option.count
    }))
  )
  const historyCategorySelectOptions = computed(() =>
    historyCategoryOptions.value.map((option) => ({
      value: option.tid,
      label: option.is_parent ? `${option.tname} · 全部` : option.tname,
      count: option.count,
      kind: option.is_parent ? 'parent' : option.parent_tid ? 'child' : ''
    }))
  )
  const historyAuthorSelectOptions = computed(() =>
    historyAuthorOptions.value.map((option) => ({
      value: option.author,
      label: option.author,
      count: option.count
    }))
  )
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

  const historyPresetOptions = computed(() => {
    return withCustomSummaryPreset(summaryPresets.value, requiresApiKey.value)
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

  const updateHistoryFilter = (selection, values) => {
    selection.value = values
    historyPage.value = 1
    loadHistory()
  }

  const resetHistoryFilters = () => {
    historyPlatforms.value = []
    historyCategoryTids.value = []
    historyAuthors.value = []
    historyPage.value = 1
    loadHistory()
  }

  const goToHistoryPage = (page) => {
    const parsedPage = Number.parseInt(String(page), 10)
    if (!Number.isFinite(parsedPage)) {
      return
    }
    const targetPage = Math.min(
      historyTotalPages.value,
      Math.max(1, parsedPage)
    )
    if (targetPage === historyPage.value || historyLoading.value) return
    historyPage.value = targetPage
    loadHistory()
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
    stopActiveJobs()
    window.removeEventListener('storage', onActiveJobsStorage)
  })
</script>

<template>
  <section class="history-layout">
    <!-- Detail View -->
    <HistoryDetail
      v-if="showHistoryDetail"
      :detail="historyDetail"
      :loading="historyDetailLoading"
      :allow-delete="allowDelete"
      :delete-loading="deleteLoading"
      :download-rows="historyDetailDownloadRows"
      :selected-profile="selectedHistorySummaryProfile"
      :selected-preset="selectedHistorySummaryPreset"
      :profiles="summaryProfiles"
      :presets="historyPresetOptions"
      :regenerate-loading="regenerateLoading"
      :requires-api-key="requiresApiKey"
      :custom-prompt-template="getSummaryTemplate(summaryDefaultPromptTemplate)"
      :fallback-prompt-template="summaryDefaultPromptTemplate"
      :custom-preset-value="CUSTOM_SUMMARY_PRESET_VALUE"
      :regenerate-error="regenerateError"
      :regenerate-success="regenerateSuccess"
      :rag-answer-html="renderedRagAnswer"
      :rag-references="ragReferenceItems"
      :rag-answer-loading="ragAnswerLoading"
      :rag-answer-error="ragAnswerError"
      :rag-fancy-generating="ragFancyHtmlGenerating"
      :rag-fancy-error="ragFancyHtmlError"
      :rag-connection-notice="ragFancyConnectionNotice"
      @back="closeHistoryDetail"
      @delete="confirmDelete"
      @update:selected-profile="selectedHistorySummaryProfile = $event"
      @update:selected-preset="selectedHistorySummaryPreset = $event"
      @regenerate="regenerateSummary(false)"
      @generate-fancy="generateRagFancyHtml"
      @artifact-deleted="onHistoryArtifactDeleted"
      @artifact-generated="onHistoryArtifactGenerated"
    />

    <!-- List View -->
    <article v-else class="history-workspace">
      <header class="history-list-header">
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

      <ActiveJobsPanel
        :jobs="activeJobs"
        :connection-notice="activeJobsConnectionNotice"
        @open="router.push(`/process/${$event}`)"
        @cancel="cancelActiveJob"
      />

      <HistoryFilters
        :platforms="historyPlatforms"
        :categories="historyCategoryTids"
        :authors="historyAuthors"
        :platform-options="historyPlatformSelectOptions"
        :category-options="historyCategorySelectOptions"
        :author-options="historyAuthorSelectOptions"
        :platform-label="historyPlatformFilterLabel"
        :category-label="historyCategoryFilterLabel"
        :author-label="historyAuthorFilterLabel"
        :loading="historyFiltersLoading"
        @update:platforms="updateHistoryFilter(historyPlatforms, $event)"
        @update:categories="updateHistoryFilter(historyCategoryTids, $event)"
        @update:authors="updateHistoryFilter(historyAuthors, $event)"
        @reset="resetHistoryFilters"
      />

      <HistoryList
        :items="historyItems"
        :loading="showHistorySkeleton"
        :error="historyError"
        :allow-delete="allowDelete"
        :delete-loading="deleteLoading"
        @open="openHistoryDetail"
        @delete="confirmDelete"
      />

      <HistoryPagination
        v-if="historyTotal > historyPageSize"
        :page="historyPage"
        :total-pages="historyTotalPages"
        :has-more="historyHasMore"
        :loading="historyLoading"
        @go="goToHistoryPage"
      />
    </article>

    <ConfirmDialog
      :open="regenerateOverwriteConfirm"
      title="确认覆盖总结"
      confirm-label="确认覆盖并生成"
      busy-label="生成中..."
      :busy="regenerateLoading"
      @cancel="cancelRegenerateOverwrite"
      @confirm="regenerateSummary(true)"
    >
      <p>
        当前模型配置“{{ selectedRegenerateProfileName }}”与总结模板“{{
          selectedRegeneratePresetName
        }}”已经生成过。继续后将重新生成总结，并替换原总结及其表格、时间线和导出文件。
      </p>
      <template #confirm-icon><RefreshCw :size="16" /></template>
    </ConfirmDialog>

    <ConfirmDialog
      :open="allowDelete && Boolean(deleteConfirmRunId)"
      title="确认删除"
      confirm-label="确认删除"
      busy-label="删除中..."
      :busy="deleteLoading"
      @cancel="cancelDelete"
      @confirm="deleteHistory(deleteConfirmRunId)"
    >
      <p>确定要删除这条历史记录吗？此操作将删除所有相关文件，且无法恢复。</p>
      <template #confirm-icon><Trash2 :size="16" /></template>
    </ConfirmDialog>
  </section>
</template>

<style scoped>
  .history-layout {
    max-width: 1220px;
    margin: 0 auto;
  }

  .history-list-header {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 12px;
    margin-bottom: 12px;
  }

  .history-search-row {
    display: flex;
    align-items: center;
    gap: 8px;
    width: min(320px, 100%);
    min-height: 40px;
    padding: 0 12px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #fff;
    color: #64748b;
  }

  .history-search-row:focus-within {
    border-color: var(--brand);
    box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.12);
  }

  .history-search-row input {
    flex: 1;
    min-width: 0;
    border: 0;
    outline: 0;
    background: transparent;
    color: var(--text-main);
    font: inherit;
  }

  @media (max-width: 640px) {
    .history-list-header {
      align-items: stretch;
      flex-direction: column;
    }

    .history-search-row {
      width: 100%;
    }
  }
</style>
