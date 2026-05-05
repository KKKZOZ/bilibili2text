<script setup>
  import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
  import { useRoute, useRouter } from 'vue-router'
  import { BookMarked, ExternalLink } from 'lucide-vue-next'
  import {
    AlertCircle,
    ArrowLeft,
    Brain,
    CalendarDays,
    Clock,
    FileText,
    LoaderCircle,
    Search,
    Trash2,
    User,
    XCircle
  } from 'lucide-vue-next'
  import FileList from './FileList.vue'
  import { bilibiliVideoUrl, formatTime } from '../utils/fileUtils'
  import { extractRagReferenceItems, renderMarkdown } from '../utils/markdown'

  const route = useRoute()
  const router = useRouter()

  const props = defineProps({
    summaryPresets: {
      type: Array,
      required: true
    },
    summaryDefaultPreset: {
      type: String,
      required: true
    },
    selectedSummaryPreset: {
      type: String,
      required: true
    },
    summaryProfiles: {
      type: Array,
      required: true
    },
    selectedSummaryProfile: {
      type: String,
      required: true
    },
    allowDelete: {
      type: Boolean,
      default: true
    },
    requiresApiKey: {
      type: Boolean,
      default: false
    }
  })

  const historyItems = ref([])
  const historyTotal = ref(0)
  const historyPage = ref(1)
  const historyPageSize = ref(20)
  const historyHasMore = ref(false)
  const historySearch = ref('')
  const historyRecordType = ref('') // '' | 'transcription' | 'rag_query'
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
  const selectedHistorySummaryPreset = ref('')
  const selectedHistorySummaryProfile = ref('')
  const ragAnswerMarkdown = ref('')
  const ragAnswerError = ref('')
  const ragAnswerLoading = ref(false)
  const ragFancyHtmlGenerating = ref(false)
  const ragFancyHtmlError = ref('')
  let ragFancyHtmlPollTimer = null

  // ─── Active jobs (in-progress) ───────────────────────────────
  const ACTIVE_JOB_IDS_KEY = 'b2t.active-job-ids'
  const LOCAL_API_KEY_KEY = 'b2t.public-api-key'
  const LOCAL_DEEPSEEK_API_KEY_KEY = 'b2t.public-deepseek-api-key'
  const LOCAL_OPEN_PUBLIC_SUMMARY_TEMPLATE_KEY =
    'b2t.open-public-summary-template'
  const CUSTOM_SUMMARY_PRESET_VALUE = '__user_custom__'
  const activeJobs = ref([])
  let activeJobsPollTimer = null

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

  const loadActiveJobs = async () => {
    const ids = readActiveJobIds()
    if (ids.length === 0) {
      activeJobs.value = []
      return
    }
    const results = await Promise.allSettled(
      ids.map((id) => fetch(`/api/process/${id}`).then((r) => r.json()))
    )
    const next = []
    for (let i = 0; i < ids.length; i++) {
      const r = results[i]
      if (r.status === 'fulfilled') {
        const data = r.value
        if (data.status === 'queued' || data.status === 'running') {
          next.push(data)
        } else {
          // Job is done/failed/cancelled – remove from tracking
          removeActiveJobId(ids[i])
        }
      }
    }
    activeJobs.value = next
  }

  const cancelActiveJob = async (jobId) => {
    try {
      const resp = await fetch(`/api/process/${jobId}/cancel`, {
        method: 'POST'
      })
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}))
        throw new Error(data.detail || '取消失败')
      }
      removeActiveJobId(jobId)
      activeJobs.value = activeJobs.value.filter((j) => j.job_id !== jobId)
    } catch (err) {
      historyError.value = err instanceof Error ? err.message : '取消任务失败'
    }
  }

  let searchTimer = null

  const historyTotalPages = computed(() =>
    Math.max(1, Math.ceil(historyTotal.value / historyPageSize.value))
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
    if (
      !selectedHistorySummaryPreset.value ||
      selectedHistorySummaryPreset.value === CUSTOM_SUMMARY_PRESET_VALUE
    ) {
      return props.summaryDefaultPreset || ''
    }
    return selectedHistorySummaryPreset.value
  })

  const selectedRegenerateProfileName = computed(
    () =>
      selectedHistorySummaryProfile.value || props.selectedSummaryProfile || ''
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

  const regenerateDisabled = computed(
    () => regenerateLoading.value || isSelectedSummaryAlreadyGenerated.value
  )

  const getLocalApiKey = () => {
    try {
      return (window.localStorage.getItem(LOCAL_API_KEY_KEY) || '').trim()
    } catch {
      return ''
    }
  }

  const getLocalDeepseekApiKey = () => {
    try {
      return (
        window.localStorage.getItem(LOCAL_DEEPSEEK_API_KEY_KEY) || ''
      ).trim()
    } catch {
      return ''
    }
  }

  const historyPresetOptions = computed(() => {
    const base = Array.isArray(props.summaryPresets) ? props.summaryPresets : []
    if (!props.requiresApiKey) {
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
      if (historyRecordType.value)
        params.set('record_type', historyRecordType.value)
      const resp = await fetch(`/api/history?${params}`)
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || '获取历史记录失败')
      }
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

  const loadHistoryDetail = async (runId) => {
    const requestedRunId = String(runId || '').trim()
    if (!requestedRunId) {
      return
    }
    historyDetailLoading.value = true
    showHistoryDetail.value = true
    historyDetail.value = null
    ragAnswerMarkdown.value = ''
    ragAnswerError.value = ''
    ragFancyHtmlError.value = ''
    regenerateError.value = ''
    regenerateSuccess.value = ''
    selectedHistorySummaryPreset.value =
      props.selectedSummaryPreset || props.summaryDefaultPreset || ''
    selectedHistorySummaryProfile.value = props.selectedSummaryProfile || ''
    try {
      const resp = await fetch(
        `/api/history/${encodeURIComponent(requestedRunId)}`
      )
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || '获取详情失败')
      }
      if (routeRunId.value !== requestedRunId) {
        return
      }
      historyDetail.value = data
      ragFancyHtmlError.value = data.fancy_html_error || ''
      syncRagFancyHtmlPolling()
      if (data.record_type === 'rag_query') {
        await loadRagAnswerMarkdown(data)
      }
    } catch (err) {
      historyError.value = err instanceof Error ? err.message : '获取详情失败'
      showHistoryDetail.value = false
      stopRagFancyHtmlPolling()
    } finally {
      historyDetailLoading.value = false
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

  const syncRagFancyHtmlPolling = () => {
    stopRagFancyHtmlPolling()
    const shouldPoll =
      showHistoryDetail.value &&
      historyDetail.value?.record_type === 'rag_query' &&
      historyDetail.value?.fancy_html_status === 'running'
    if (!shouldPoll) return

    ragFancyHtmlPollTimer = setInterval(async () => {
      const runId = historyDetail.value?.run_id
      if (!runId || !showHistoryDetail.value) {
        stopRagFancyHtmlPolling()
        return
      }
      try {
        const resp = await fetch(`/api/history/${encodeURIComponent(runId)}`)
        const data = await resp.json()
        if (!resp.ok) return
        historyDetail.value = data
        if (data.record_type === 'rag_query') {
          ragFancyHtmlError.value = data.fancy_html_error || ''
        }
        if (data.fancy_html_status !== 'running') {
          stopRagFancyHtmlPolling()
          await loadHistory()
        }
      } catch {}
    }, 2000)
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
      const resp = await fetch('/api/summary/fancy-html', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          download_id: downloadId,
          history_run_id: historyDetail.value?.run_id || null
        })
      })
      const data = await resp.json()
      if (!resp.ok) throw new Error(data.detail || '生成 Fancy HTML 失败')
      if (data.history_detail) {
        historyDetail.value = data.history_detail
        ragFancyHtmlError.value = data.history_detail.fancy_html_error || ''
        syncRagFancyHtmlPolling()
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

  const loadRagAnswerMarkdown = async (detail = historyDetail.value) => {
    const artifact = detail?.artifacts?.find(
      (item) => item.kind === 'rag_answer'
    )
    if (!artifact?.download_url) return
    ragAnswerLoading.value = true
    ragAnswerError.value = ''
    try {
      const resp = await fetch(artifact.download_url)
      if (!resp.ok) {
        throw new Error(`读取知识库回答失败（HTTP ${resp.status}）`)
      }
      ragAnswerMarkdown.value = await resp.text()
    } catch (err) {
      ragAnswerError.value =
        err instanceof Error ? err.message : '读取知识库回答失败'
    } finally {
      ragAnswerLoading.value = false
    }
  }

  const regenerateSummary = async () => {
    const runId = historyDetail.value?.run_id
    if (!runId) {
      return
    }
    if (isSelectedSummaryAlreadyGenerated.value) {
      regenerateError.value =
        '该模型配置与总结模板已经生成过，请选择不同配置后再重新生成。'
      return
    }
    let customTemplate = null
    if (
      props.requiresApiKey &&
      selectedHistorySummaryPreset.value === CUSTOM_SUMMARY_PRESET_VALUE
    ) {
      try {
        customTemplate = (
          window.localStorage.getItem(LOCAL_OPEN_PUBLIC_SUMMARY_TEMPLATE_KEY) ||
          ''
        ).trim()
      } catch {
        customTemplate = ''
      }
      if (!customTemplate) {
        regenerateError.value =
          '请先在「API Key」页面保存自定义总结模板，再选择“用户自定义”模板'
        return
      }
    }

    regenerateLoading.value = true
    regenerateError.value = ''
    regenerateSuccess.value = ''
    try {
      const resp = await fetch(
        `/api/history/${encodeURIComponent(runId)}/regenerate-summary`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            summary_preset: selectedRegeneratePresetName.value || null,
            summary_profile: selectedRegenerateProfileName.value || null,
            summary_prompt_template: customTemplate || null,
            api_key: props.requiresApiKey ? getLocalApiKey() : null,
            deepseek_api_key: props.requiresApiKey
              ? getLocalDeepseekApiKey() || null
              : null
          })
        }
      )
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || '重新生成总结失败')
      }

      historyDetail.value = data
      regenerateSuccess.value = '总结重新生成完成，文件已持久化到存储后端。'
      await loadHistory()
    } catch (err) {
      regenerateError.value =
        err instanceof Error ? err.message : '重新生成总结失败'
    } finally {
      regenerateLoading.value = false
    }
  }

  const onSearchInput = () => {
    if (searchTimer) clearTimeout(searchTimer)
    searchTimer = setTimeout(() => {
      historyPage.value = 1
      loadHistory()
    }, 400)
  }

  const setRecordType = (type) => {
    historyRecordType.value = type
    historyPage.value = 1
    loadHistory()
  }

  const historyPrevPage = () => {
    if (historyPage.value > 1) {
      historyPage.value--
      loadHistory()
    }
  }

  const historyNextPage = () => {
    if (historyHasMore.value) {
      historyPage.value++
      loadHistory()
    }
  }

  const confirmDelete = (runId) => {
    if (!props.allowDelete) {
      return
    }
    deleteConfirmRunId.value = runId
  }

  const cancelDelete = () => {
    deleteConfirmRunId.value = null
  }

  const deleteHistory = async (runId) => {
    if (!props.allowDelete) {
      return
    }
    deleteLoading.value = true
    try {
      const resp = await fetch(`/api/history/${encodeURIComponent(runId)}`, {
        method: 'DELETE'
      })
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || '删除失败')
      }
      // Close detail view if currently viewing deleted item
      if (showHistoryDetail.value && historyDetail.value?.run_id === runId) {
        showHistoryDetail.value = false
        historyDetail.value = null
      }
      // Reload list
      await loadHistory()
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
      syncRagFancyHtmlPolling()
    }
    loadHistory()
  }

  const onHistoryArtifactGenerated = (detail) => {
    historyDetail.value = detail
    regenerateError.value = ''
    regenerateSuccess.value = 'Fancy HTML 已生成并归档。'
    if (detail?.record_type === 'rag_query') {
      ragFancyHtmlError.value = detail.fancy_html_error || ''
      syncRagFancyHtmlPolling()
    }
    loadHistory()
  }

  defineExpose({
    loadHistory
  })

  onMounted(() => {
    loadHistory()
    if (routeRunId.value) {
      loadHistoryDetail(routeRunId.value)
    }
    loadActiveJobs()
    activeJobsPollTimer = setInterval(loadActiveJobs, 2000)
  })

  watch(routeRunId, (runId) => {
    if (runId) {
      loadHistoryDetail(runId)
      return
    }
    showHistoryDetail.value = false
    historyDetail.value = null
    historyDetailLoading.value = false
    ragAnswerMarkdown.value = ''
    ragAnswerError.value = ''
    ragFancyHtmlError.value = ''
    regenerateError.value = ''
    regenerateSuccess.value = ''
    stopRagFancyHtmlPolling()
  })

  onBeforeUnmount(() => {
    stopRagFancyHtmlPolling()
    if (activeJobsPollTimer !== null) {
      clearInterval(activeJobsPollTimer)
      activeJobsPollTimer = null
    }
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
                  class="detail-bvid"
                  :href="bilibiliVideoUrl(historyDetail.bvid)"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {{ historyDetail.bvid }}
                </a>
                <span v-if="historyDetail.author" class="detail-author-tag">
                  <User :size="12" />
                  UP主 {{ historyDetail.author }}
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
                  {{ profile.name }} ({{ profile.model }})
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
              <p
                v-if="
                  requiresApiKey &&
                  selectedHistorySummaryPreset === CUSTOM_SUMMARY_PRESET_VALUE
                "
                class="preset-hint"
              >
                当前将使用你在 API Key 页面保存的自定义模板。
              </p>
            </div>
          </div>

          <button
            class="submit history-regenerate-button"
            type="button"
            :disabled="regenerateDisabled"
            @click="regenerateSummary"
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
            该模型配置与总结模板已经生成过，请选择不同配置后再重新生成。
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
                :href="item.bvid ? bilibiliVideoUrl(item.bvid) : undefined"
                class="rag-history-source-card"
                :class="{ 'no-link': !item.bvid }"
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
                      {{ item.bvid }}
                      <ExternalLink :size="11" />
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
          :summary-presets="summaryPresets"
          :summary-default-preset="summaryDefaultPreset"
          :selected-summary-preset="selectedHistorySummaryPreset"
          :summary-profiles="summaryProfiles"
          :selected-summary-profile="selectedHistorySummaryProfile"
          :bvid="historyDetail.bvid"
          :history-run-id="historyDetail.run_id"
          :allow-delete="allowDelete"
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
        <div class="history-type-tabs">
          <button
            class="history-type-tab"
            :class="{ active: historyRecordType === '' }"
            @click="setRecordType('')"
          >
            全部
          </button>
          <button
            class="history-type-tab"
            :class="{ active: historyRecordType === 'transcription' }"
            @click="setRecordType('transcription')"
          >
            <FileText :size="13" />
            转录记录
          </button>
          <button
            class="history-type-tab"
            :class="{ active: historyRecordType === 'rag_query' }"
            @click="setRecordType('rag_query')"
          >
            <Brain :size="13" />
            知识库查询
          </button>
        </div>
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
                v-if="item.record_type !== 'rag_query' && item.bvid"
                class="history-bvid"
                :href="bilibiliVideoUrl(item.bvid)"
                target="_blank"
                rel="noopener noreferrer"
                @click.stop
              >
                {{ item.bvid }}
              </a>
              <span v-if="item.author" class="history-author-tag">
                <User :size="12" />
                UP主 {{ item.author }}
              </span>
            </div>
            <div class="history-item-meta">
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
        <button :disabled="historyPage <= 1" @click="historyPrevPage">
          上一页
        </button>
        <span>第 {{ historyPage }} 页 / 共 {{ historyTotalPages }} 页</span>
        <button :disabled="!historyHasMore" @click="historyNextPage">
          下一页
        </button>
      </div>
    </article>

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

  .history-type-tabs {
    display: flex;
    gap: 4px;
    background: rgba(148, 163, 184, 0.1);
    border-radius: 10px;
    padding: 3px;
  }

  .history-type-tab {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 5px 12px;
    border: none;
    border-radius: 7px;
    background: transparent;
    color: var(--text-muted, #64748b);
    font-size: 0.82rem;
    font-weight: 600;
    cursor: pointer;
    transition:
      background 0.15s,
      color 0.15s;
    white-space: nowrap;
  }

  .history-type-tab:hover {
    background: rgba(255, 255, 255, 0.7);
    color: var(--text-soft, #334155);
  }

  .history-type-tab.active {
    background: #fff;
    color: var(--brand-strong, #0f766e);
    box-shadow: 0 1px 4px rgba(15, 23, 42, 0.08);
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
    gap: 14px;
  }

  .history-pagination button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 34px;
    padding: 0 14px;
    border: 1px solid var(--line);
    border-radius: 10px;
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
    .history-regenerate-grid {
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 640px) {
    .history-list-header {
      flex-direction: column;
      align-items: stretch;
    }

    .history-type-tabs {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .history-type-tab {
      justify-content: center;
      padding-inline: 8px;
    }

    .history-search-row {
      max-width: none;
      min-width: 0;
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
