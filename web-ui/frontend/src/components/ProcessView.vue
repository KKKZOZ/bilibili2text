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
  import {
    AlertCircle,
    ArrowLeft,
    CheckCircle2,
    ChevronDown,
    CircleHelp,
    FileAudio2,
    FileVideo2,
    Link2,
    LoaderCircle,
    Minus,
    Plus
  } from 'lucide-vue-next'
  import ProgressPanel from './ProgressPanel.vue'
  import FileList from './FileList.vue'
  import { ApiError, processApi, subscribeSse } from '../api'
  import {
    CUSTOM_LLM_PROFILE_NAME,
    usePublicCredentials
  } from '../composables/usePublicCredentials'
  import { useRuntimeFeatures } from '../composables/useRuntimeFeatures'
  import { useSummaryConfig } from '../composables/useSummaryConfig'
  import { inferSummaryPresetFromFilename } from '../utils/fileUtils'

  const route = useRoute()
  const router = useRouter()
  const { runtimeFeatures } = useRuntimeFeatures()
  const allowUpload = computed(() => runtimeFeatures.value.allow_upload_audio)
  const requiresApiKey = computed(
    () => runtimeFeatures.value.requires_user_api_key
  )
  const {
    summaryPresets,
    summaryDefaultPromptTemplate,
    summaryProfiles,
    selectedSummaryPreset,
    selectedSummaryProfile,
    summaryPresetError,
    summaryProfileError,
    isLoadingSummaryPresets,
    isLoadingSummaryProfiles,
    loadSummaryPresets,
    loadSummaryProfiles
  } = useSummaryConfig()
  const {
    apiKeyConfigured,
    deepseekApiKeyConfigured,
    customLlmConfigured,
    getApiKey,
    getDeepseekApiKey,
    getSummaryTemplate,
    getCustomLlmPayload,
    appendCustomLlmFormData
  } = usePublicCredentials()

  const url = ref('')
  const error = ref('')
  const connectionNotice = ref('')
  const inputMode = ref('url')
  const uploadedAudioFile = ref(null)
  const uploadFileInput = ref(null)
  const enableSummary = ref(true)
  const preferBilibiliSubtitle = ref(true)
  const autoGenerateFancyHtml = ref(false)
  const includeComments = ref(true)
  const commentLimit = ref(300)
  const downloadAllComments = ref(false)
  const currentSkipSummary = ref(false)
  const isStarting = ref(false)
  const isPolling = ref(false)
  const pollErrorCount = ref(0)
  const jobId = ref('')
  const logsViewport = ref(null)
  const job = ref({
    status: 'idle',
    stage: 'queued',
    stage_label: '等待开始',
    progress: 0,
    download_url: '',
    filename: '',
    txt_download_url: '',
    txt_filename: '',
    summary_download_url: '',
    summary_filename: '',
    summary_txt_download_url: '',
    summary_txt_filename: '',
    summary_table_pdf_download_url: '',
    summary_table_pdf_filename: '',
    summary_preset: '',
    summary_profile: '',
    auto_generate_fancy_html: false,
    fancy_html_status: 'idle',
    fancy_html_error: '',
    used_bilibili_subtitle: false,
    already_transcribed: false,
    notice: '',
    all_downloads: [],
    error: '',
    logs: [],
    stage_durations: {},
    created_at: '',
    updated_at: '',
    author: '',
    pubdate: '',
    bvid: '',
    history_run_id: '',
    is_ephemeral_upload: false,
    expires_at: ''
  })

  let pollTimer = null
  let stopJobEvents = null
  let lastRenderedJobSignature = ''
  const maxPollErrors = 3
  const ACTIVE_JOB_IDS_KEY = 'b2t.active-job-ids'
  const CUSTOM_SUMMARY_PRESET_VALUE = '__user_custom__'
  const uploadAccept =
    '.aac,.flac,.m4a,.mp3,.ogg,.opus,.wav,.webm,.avi,.m4v,.mkv,.mov,.mp4'
  const uploadFilenamePattern =
    /^(BV[0-9A-Za-z]{10})_.+\.(aac|flac|m4a|mp3|ogg|opus|wav|webm)$/i
  const openPublicUploadPattern =
    /\.(aac|flac|m4a|mp3|ogg|opus|wav|webm|avi|m4v|mkv|mov|mp4)$/i
  const userSummaryPromptTemplate = ref('')
  const summaryPresetDropdownRef = ref(null)
  const isSummaryPresetMenuOpen = ref(false)
  const hoveredSummaryPresetName = ref('')

  // Job from route param
  const routeJobId = computed(() => String(route.params.jobId || ''))
  const isJobDetailMode = computed(() => !!routeJobId.value)
  const isOpenPublic = requiresApiKey
  const presetOptions = computed(() => {
    const base = Array.isArray(summaryPresets.value) ? summaryPresets.value : []
    if (!isOpenPublic.value) {
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
  const effectiveSummaryPromptTemplate = computed(() => {
    if (!enableSummary.value) {
      return ''
    }
    if (!isOpenPublic.value) {
      return ''
    }
    if (selectedSummaryPreset.value !== CUSTOM_SUMMARY_PRESET_VALUE) {
      return ''
    }
    return userSummaryPromptTemplate.value.trim()
  })
  const selectedSummaryPresetOption = computed(
    () =>
      presetOptions.value.find(
        (item) => item.name === selectedSummaryPreset.value
      ) ||
      presetOptions.value[0] ||
      null
  )
  const previewedSummaryPresetName = computed(
    () =>
      hoveredSummaryPresetName.value ||
      selectedSummaryPresetOption.value?.name ||
      ''
  )
  const previewedSummaryPresetOption = computed(
    () =>
      presetOptions.value.find(
        (item) => item.name === previewedSummaryPresetName.value
      ) ||
      selectedSummaryPresetOption.value ||
      null
  )

  const buildSummaryPresetPreviewText = (template) => {
    const normalized = String(template || '')
      .replace(/\r\n/g, '\n')
      .split('\n')
      .map((line) => line.replace(/[^\S\n]+/g, ' ').trim())
      .join('\n')
      .trim()

    if (!normalized) {
      return '此模板暂无可预览内容。'
    }

    return normalized
  }

  const getSummaryPresetPromptTemplate = (presetName) => {
    if (presetName === CUSTOM_SUMMARY_PRESET_VALUE) {
      return (
        userSummaryPromptTemplate.value.trim() ||
        summaryDefaultPromptTemplate.value ||
        ''
      )
    }

    const matched = summaryPresets.value.find(
      (item) => item.name === presetName
    )
    return typeof matched?.prompt_template === 'string'
      ? matched.prompt_template
      : ''
  }

  const normalizedCommentLimit = computed(() => {
    if (downloadAllComments.value) {
      return null
    }
    const parsed = Number(commentLimit.value)
    if (!Number.isFinite(parsed)) {
      return 300
    }
    return Math.min(1000, Math.max(1, Math.floor(parsed)))
  })

  const adjustCommentLimit = (delta) => {
    const current = Number(commentLimit.value)
    const base = Number.isFinite(current) ? Math.floor(current) : 300
    commentLimit.value = Math.min(1000, Math.max(1, base + delta))
  }

  const normalizeCommentLimitInput = () => {
    commentLimit.value = normalizedCommentLimit.value ?? 300
  }

  const previewedSummaryPresetText = computed(() =>
    buildSummaryPresetPreviewText(
      getSummaryPresetPromptTemplate(
        previewedSummaryPresetOption.value?.name || ''
      )
    )
  )

  // Multi-job localStorage helpers (shared with HistoryView for active job tracking)
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

  const addActiveJobId = (id) => {
    try {
      const ids = readActiveJobIds()
      if (!ids.includes(id)) {
        ids.push(id)
        window.localStorage.setItem(ACTIVE_JOB_IDS_KEY, JSON.stringify(ids))
      }
    } catch {}
  }

  const removeActiveJobId = (id) => {
    try {
      const ids = readActiveJobIds().filter((i) => i !== id)
      window.localStorage.setItem(ACTIVE_JOB_IDS_KEY, JSON.stringify(ids))
    } catch {}
  }

  const clearActiveJobId = () => {
    if (jobId.value) removeActiveJobId(jobId.value)
    jobId.value = ''
  }

  const formatSummaryProfileLabel = (profile) => {
    if (!profile) return ''
    if (profile.name === CUSTOM_LLM_PROFILE_NAME) {
      return `custom(${profile.model || 'model'})`
    }
    return `${profile.name} (${profile.model})`
  }

  const loadLocalSummaryPromptTemplate = () => {
    if (!isOpenPublic.value) {
      userSummaryPromptTemplate.value = ''
      return
    }
    userSummaryPromptTemplate.value = getSummaryTemplate(
      summaryDefaultPromptTemplate.value
    )
  }

  const isRunning = computed(
    () => job.value.status === 'queued' || job.value.status === 'running'
  )
  const isDone = computed(() => job.value.status === 'succeeded')
  const isFancyHtmlPending = computed(
    () =>
      Boolean(job.value.auto_generate_fancy_html) &&
      ['pending', 'running'].includes(job.value.fancy_html_status || '')
  )
  const shouldSkipSummary = computed(() => {
    if (job.value.status === 'idle') {
      return !enableSummary.value
    }
    return currentSkipSummary.value
  })
  const isUploadMode = computed(
    () => allowUpload.value && inputMode.value === 'upload'
  )

  watch(
    allowUpload,
    (allowUpload) => {
      if (allowUpload || inputMode.value !== 'upload') {
        return
      }
      inputMode.value = 'url'
      uploadedAudioFile.value = null
      if (uploadFileInput.value) {
        uploadFileInput.value.value = ''
      }
    },
    { immediate: true }
  )

  const allDownloadRows = computed(() => {
    const downloads = Array.isArray(job.value.all_downloads)
      ? job.value.all_downloads
      : []
    return downloads.map((item) => ({
      kind: item.kind,
      key: `${item.url}-${item.filename}`,
      url: item.url,
      filename: item.filename,
      presetName:
        job.value.summary_preset ||
        inferSummaryPresetFromFilename(item.filename) ||
        selectedSummaryPreset.value,
      summaryProfile: job.value.summary_profile || selectedSummaryProfile.value
    }))
  })

  const stopPolling = () => {
    if (pollTimer !== null) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  const stopEventSubscription = () => {
    if (stopJobEvents !== null) {
      stopJobEvents()
      stopJobEvents = null
    }
  }

  const getLogSignature = (logs) => {
    if (!Array.isArray(logs) || logs.length === 0) {
      return '0::'
    }
    return `${logs.length}:${logs.at(-1) || ''}`
  }

  const getDownloadSignature = (downloads) => {
    if (!Array.isArray(downloads) || downloads.length === 0) {
      return ''
    }
    return downloads
      .map((item) =>
        [
          item.kind || '',
          item.url || '',
          item.filename || '',
          item.download_url || ''
        ].join(':')
      )
      .join('|')
  }

  const getJobRenderSignature = (payload) =>
    [
      payload.status || '',
      payload.skip_summary ? '1' : '0',
      payload.stage || '',
      payload.stage_label || '',
      payload.progress ?? '',
      payload.download_url || '',
      payload.filename || '',
      payload.txt_download_url || '',
      payload.txt_filename || '',
      payload.summary_download_url || '',
      payload.summary_filename || '',
      payload.summary_txt_download_url || '',
      payload.summary_txt_filename || '',
      payload.summary_table_pdf_download_url || '',
      payload.summary_table_pdf_filename || '',
      payload.summary_preset || '',
      payload.summary_profile || '',
      payload.auto_generate_fancy_html ? '1' : '0',
      payload.fancy_html_status || '',
      payload.fancy_html_error || '',
      payload.used_bilibili_subtitle ? '1' : '0',
      payload.already_transcribed ? '1' : '0',
      payload.notice || '',
      payload.error || '',
      getDownloadSignature(payload.all_downloads),
      getLogSignature(payload.logs),
      payload.author || '',
      payload.pubdate || '',
      payload.bvid || '',
      payload.title || '',
      payload.history_run_id || '',
      payload.is_ephemeral_upload ? '1' : '0',
      payload.expires_at || ''
    ].join('\u001f')

  const syncLogScroll = () => {
    if (logsViewport.value === null) {
      return
    }
    logsViewport.value.scrollTop = logsViewport.value.scrollHeight
  }

  const resetJob = () => {
    lastRenderedJobSignature = ''
    job.value = {
      status: 'idle',
      skip_summary: false,
      stage: 'queued',
      stage_label: '等待开始',
      progress: 0,
      download_url: '',
      filename: '',
      txt_download_url: '',
      txt_filename: '',
      summary_download_url: '',
      summary_filename: '',
      summary_txt_download_url: '',
      summary_txt_filename: '',
      summary_table_pdf_download_url: '',
      summary_table_pdf_filename: '',
      summary_preset: '',
      summary_profile: '',
      auto_generate_fancy_html: false,
      fancy_html_status: 'idle',
      fancy_html_error: '',
      used_bilibili_subtitle: false,
      already_transcribed: false,
      notice: '',
      all_downloads: [],
      error: '',
      logs: [],
      stage_durations: {},
      created_at: '',
      updated_at: '',
      author: '',
      pubdate: '',
      bvid: '',
      history_run_id: '',
      is_ephemeral_upload: false,
      expires_at: ''
    }
  }

  const setInputMode = (mode) => {
    if (mode === 'upload' && !allowUpload.value) {
      return
    }
    inputMode.value = mode
    error.value = ''
  }

  const onUploadFileChange = (event) => {
    const target = event.target
    if (!target || !target.files || target.files.length === 0) {
      uploadedAudioFile.value = null
      return
    }
    uploadedAudioFile.value = target.files[0]
  }

  const validateUploadedAudio = (file) => {
    if (!file) {
      return '请先选择音频或视频文件'
    }
    const normalizedName = String(file.name || '').trim()
    if (isOpenPublic.value) {
      if (!openPublicUploadPattern.test(normalizedName)) {
        return '仅支持常见音频或视频格式：aac、flac、m4a、mp3、ogg、opus、wav、webm、avi、m4v、mkv、mov、mp4'
      }
      return ''
    }
    if (!uploadFilenamePattern.test(normalizedName)) {
      return '上传文件名必须符合 `BV号_视频标题.xxx`，例如 `BV1R9i4BoE7H_视频标题.m4a`'
    }
    return ''
  }

  const openSummaryPresetMenu = () => {
    if (isLoadingSummaryPresets.value || presetOptions.value.length === 0) {
      return
    }
    hoveredSummaryPresetName.value = selectedSummaryPreset.value || ''
    isSummaryPresetMenuOpen.value = true
  }

  const closeSummaryPresetMenu = () => {
    isSummaryPresetMenuOpen.value = false
    hoveredSummaryPresetName.value = ''
  }

  const toggleSummaryPresetMenu = () => {
    if (isSummaryPresetMenuOpen.value) {
      closeSummaryPresetMenu()
      return
    }
    openSummaryPresetMenu()
  }

  const previewSummaryPreset = (presetName) => {
    hoveredSummaryPresetName.value = presetName
  }

  const selectSummaryPreset = (presetName) => {
    selectedSummaryPreset.value = presetName
    closeSummaryPresetMenu()
  }

  const onDocumentPointerDown = (event) => {
    if (!isSummaryPresetMenuOpen.value) {
      return
    }
    if (summaryPresetDropdownRef.value?.contains(event.target)) {
      return
    }
    closeSummaryPresetMenu()
  }

  const applyJobUpdate = (data) => {
    const previousLogCount = Array.isArray(job.value.logs)
      ? job.value.logs.length
      : 0
    const nextRenderSignature = getJobRenderSignature(data)
    const shouldRenderJob = nextRenderSignature !== lastRenderedJobSignature
    if (shouldRenderJob) {
      job.value = data
      lastRenderedJobSignature = nextRenderSignature
      currentSkipSummary.value = Boolean(data.skip_summary)
      if (
        isOpenPublic.value &&
        typeof data.summary_prompt_template === 'string' &&
        data.summary_prompt_template.trim()
      ) {
        userSummaryPromptTemplate.value = data.summary_prompt_template
      }
    }
    pollErrorCount.value = 0
    error.value = ''
    const currentLogCount = Array.isArray(data.logs) ? data.logs.length : 0
    if (shouldRenderJob && currentLogCount !== previousLogCount) {
      nextTick(syncLogScroll)
    }

    if (data.status === 'failed') {
      error.value = data.error || '处理失败'
      clearActiveJobId()
      return false
    } else if (data.status === 'cancelled') {
      error.value = data.error || '任务已取消'
      clearActiveJobId()
      return false
    } else if (
      data.status === 'succeeded' &&
      !(
        data.auto_generate_fancy_html &&
        ['pending', 'running'].includes(data.fancy_html_status || '')
      )
    ) {
      clearActiveJobId()
      return false
    }
    return true
  }

  const pollStatus = async () => {
    if (!jobId.value || isPolling.value) {
      return
    }

    isPolling.value = true
    try {
      const data = await processApi.getJob(jobId.value)
      if (!applyJobUpdate(data)) stopPolling()
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        clearActiveJobId()
        stopPolling()
      }
      pollErrorCount.value += 1
      const message = err instanceof Error ? err.message : '获取任务进度失败'
      if (pollErrorCount.value >= maxPollErrors) {
        error.value = message
        stopPolling()
      } else {
        error.value = `${message}，正在重试（${pollErrorCount.value}/${maxPollErrors}）`
      }
    } finally {
      isPolling.value = false
    }
  }

  const startPollingFallback = () => {
    connectionNotice.value = '实时连接不可用，已切换为兼容模式。'
    stopPolling()
    pollStatus()
    pollTimer = setInterval(pollStatus, 1200)
  }

  const startJobEvents = () => {
    stopEventSubscription()
    stopPolling()
    connectionNotice.value = ''
    const subscribedJobId = jobId.value
    if (!subscribedJobId) return

    stopJobEvents = subscribeSse({
      url: processApi.jobEventsUrl(subscribedJobId),
      eventName: 'job',
      onEvent: (data) => {
        if (jobId.value !== subscribedJobId) return false
        return applyJobUpdate(data)
      },
      onDeleted: () => {
        if (jobId.value !== subscribedJobId) return
        clearActiveJobId()
        error.value = '任务不存在或已过期'
      },
      onFallback: () => {
        stopJobEvents = null
        if (jobId.value === subscribedJobId) startPollingFallback()
      }
    })
  }

  const submit = async () => {
    isStarting.value = true
    error.value = ''
    connectionNotice.value = ''
    stopEventSubscription()
    stopPolling()
    clearActiveJobId()
    resetJob()

    try {
      if (requiresApiKey.value && !apiKeyConfigured.value) {
        throw new Error('请先在「API Key」页面配置阿里云 DashScope API Key')
      }
      if (
        enableSummary.value &&
        selectedSummaryPreset.value === CUSTOM_SUMMARY_PRESET_VALUE &&
        !effectiveSummaryPromptTemplate.value
      ) {
        throw new Error(
          '请先在「API Key」页面保存自定义总结模板，再选择“用户自定义”模板'
        )
      }

      const skipSummary = !enableSummary.value
      currentSkipSummary.value = skipSummary
      pollErrorCount.value = 0

      let data
      if (isUploadMode.value) {
        if (!allowUpload.value) {
          throw new Error('当前模式不允许上传音频，请改为输入播客/视频链接')
        }
        const validationMessage = validateUploadedAudio(uploadedAudioFile.value)
        if (validationMessage) {
          throw new Error(validationMessage)
        }
        const formData = new FormData()
        formData.append('file', uploadedAudioFile.value)
        formData.append('skip_summary', String(skipSummary))
        if (
          !skipSummary &&
          selectedSummaryPreset.value &&
          (selectedSummaryPreset.value !== CUSTOM_SUMMARY_PRESET_VALUE ||
            effectiveSummaryPromptTemplate.value)
        ) {
          formData.append('summary_preset', selectedSummaryPreset.value)
        }
        if (!skipSummary && selectedSummaryProfile.value) {
          formData.append('summary_profile', selectedSummaryProfile.value)
        }
        if (!skipSummary && effectiveSummaryPromptTemplate.value) {
          formData.append(
            'summary_prompt_template',
            effectiveSummaryPromptTemplate.value
          )
        }
        if (!skipSummary) {
          formData.append(
            'auto_generate_fancy_html',
            String(autoGenerateFancyHtml.value)
          )
        }
        if (requiresApiKey.value) {
          formData.append('api_key', getApiKey())
          const dsKey = getDeepseekApiKey()
          if (dsKey) formData.append('deepseek_api_key', dsKey)
          appendCustomLlmFormData(formData, true)
        }
        data = await processApi.startFromUpload(formData)
      } else {
        if (!url.value.trim()) {
          throw new Error('请输入播客链接或视频 URL')
        }
        data = await processApi.startFromUrl({
          url: url.value.trim(),
          skip_summary: skipSummary,
          summary_preset:
            skipSummary || !selectedSummaryPreset.value
              ? null
              : selectedSummaryPreset.value,
          summary_profile:
            skipSummary || !selectedSummaryProfile.value
              ? null
              : selectedSummaryProfile.value,
          summary_prompt_template:
            skipSummary || !effectiveSummaryPromptTemplate.value
              ? null
              : effectiveSummaryPromptTemplate.value,
          auto_generate_fancy_html: skipSummary
            ? false
            : autoGenerateFancyHtml.value,
          prefer_bilibili_subtitle: preferBilibiliSubtitle.value,
          include_comments:
            !skipSummary && includeComments.value && !isUploadMode.value,
          comment_limit: normalizedCommentLimit.value,
          api_key: requiresApiKey.value ? getApiKey() : null,
          deepseek_api_key: requiresApiKey.value
            ? getDeepseekApiKey() || null
            : null,
          ...getCustomLlmPayload(requiresApiKey.value)
        })
      }

      jobId.value = data.job_id
      addActiveJobId(data.job_id)
      // Navigate to the job detail URL
      await router.push(`/process/${data.job_id}`)
      startJobEvents()
    } catch (err) {
      error.value = err instanceof Error ? err.message : '提交任务失败'
    } finally {
      isStarting.value = false
    }
  }

  onMounted(async () => {
    document.addEventListener('mousedown', onDocumentPointerDown)
    loadLocalSummaryPromptTemplate()
    if (!routeJobId.value) {
      return
    }

    jobId.value = routeJobId.value
    pollErrorCount.value = 0
    await pollStatus()
    if (
      jobId.value &&
      (job.value.status === 'queued' ||
        job.value.status === 'running' ||
        (job.value.status === 'succeeded' && isFancyHtmlPending.value))
    ) {
      startJobEvents()
    }
  })

  onBeforeUnmount(() => {
    stopEventSubscription()
    stopPolling()
    document.removeEventListener('mousedown', onDocumentPointerDown)
  })

  watch(
    summaryDefaultPromptTemplate,
    () => {
      if (!isOpenPublic.value) {
        return
      }
      const hasLocalValue = userSummaryPromptTemplate.value.trim().length > 0
      if (!hasLocalValue) {
        userSummaryPromptTemplate.value =
          summaryDefaultPromptTemplate.value || ''
      }
    },
    { immediate: true }
  )

  watch(
    requiresApiKey,
    () => {
      loadLocalSummaryPromptTemplate()
    },
    { immediate: true }
  )

  watch(selectedSummaryPreset, () => {
    if (!isSummaryPresetMenuOpen.value) {
      return
    }
    hoveredSummaryPresetName.value = selectedSummaryPreset.value || ''
  })
</script>

<template>
  <div>
    <section class="layout">
      <article class="panel panel-main">
        <header class="header">
          <h1>bilibili-to-text</h1>
          <p>
            {{
              allowUpload
                ? isOpenPublic
                  ? '输入 B 站视频链接，或上传音频/视频生成临时转录和大模型总结。'
                  : '输入 B 站视频链接，或上传符合命名规范的音频文件，自动生成转录内容和大模型总结。'
                : '输入 B 站视频链接，自动生成转录内容和大模型总结。'
            }}
          </p>
          <div class="hero-meta">
            <span class="hero-pill">
              {{ isRunning ? '处理中' : '准备就绪' }}
            </span>
            <span class="hero-pill hero-pill-soft">
              总结{{ enableSummary ? '已开启' : '已关闭' }}
            </span>
            <span v-if="enableSummary" class="hero-pill hero-pill-soft">
              Fancy HTML{{ autoGenerateFancyHtml ? '自动生成' : '手动生成' }}
            </span>
            <span
              v-if="job.is_ephemeral_upload"
              class="hero-pill hero-pill-soft"
            >
              临时结果 2 小时后删除
            </span>
          </div>
        </header>

        <form class="form" @submit.prevent="submit">
          <div class="input-mode-tabs">
            <button
              type="button"
              class="input-mode-button"
              :class="{ active: !isUploadMode }"
              :disabled="isStarting || isRunning"
              @click="setInputMode('url')"
            >
              <Link2 :size="15" />
              <span>链接 / BV</span>
            </button>
            <button
              v-if="allowUpload"
              type="button"
              class="input-mode-button"
              :class="{ active: isUploadMode }"
              :disabled="isStarting || isRunning"
              @click="setInputMode('upload')"
            >
              <FileVideo2 v-if="isOpenPublic" :size="15" />
              <FileAudio2 v-else :size="15" />
              <span>{{ isOpenPublic ? '上传音频 / 视频' : '上传音频' }}</span>
            </button>
          </div>

          <template v-if="!isUploadMode">
            <label for="video-url">视频/播客 URL</label>
            <div class="input-row">
              <Link2 :size="18" />
              <input
                id="video-url"
                v-model="url"
                type="text"
                placeholder="支持 Bilibili、小宇宙 FM、喜马拉雅播客链接..."
              />
            </div>
            <div class="input-example">
              <span>示例：</span>
              <a
                href="https://www.bilibili.com/video/BV1R9i4BoE7H"
                target="_blank"
                rel="noopener noreferrer"
              >
                https://www.bilibili.com/video/BV1R9i4BoE7H
              </a>
              <a
                href="https://www.xiaoyuzhoufm.com/episode/6a0a7365e1eb34a93997ffa2"
                target="_blank"
                rel="noopener noreferrer"
              >
                https://www.xiaoyuzhoufm.com/episode/6a0a7365e1eb34a93997ffa2
              </a>
              <span
                >支持 Bilibili / 小宇宙 / 喜马拉雅链接，自动下载音频并转录</span
              >
            </div>
            <label class="switch" for="prefer-bilibili-subtitle">
              <input
                id="prefer-bilibili-subtitle"
                v-model="preferBilibiliSubtitle"
                type="checkbox"
              />
              <span class="switch-track">
                <span class="switch-thumb"></span>
              </span>
              <span class="switch-label">优先使用 B 站字幕</span>
            </label>
            <div
              class="summary-preset process-summary-field process-summary-toggle comments-summary-field"
            >
              <div class="comments-summary-toggle-row">
                <label class="switch switch-compact" for="include-comments">
                  <input
                    id="include-comments"
                    v-model="includeComments"
                    type="checkbox"
                  />
                  <span class="switch-track">
                    <span class="switch-thumb"></span>
                  </span>
                  <span class="switch-label">总结精选评论</span>
                </label>
                <span class="comments-help">
                  <button
                    type="button"
                    class="comments-help-trigger"
                    aria-label="查看精选评论下载说明"
                    aria-describedby="comments-help-tooltip"
                  >
                    <CircleHelp :size="17" aria-hidden="true" />
                  </button>
                  <span
                    id="comments-help-tooltip"
                    class="comments-help-tooltip"
                    role="tooltip"
                  >
                    支持 B 站和小宇宙。默认按热门排序下载前 300
                    条主评论；每条主评论的全部子评论都会下载，UP主回复会加粗。打开“下载全部主评论”后不限制主评论数量。
                  </span>
                </span>
              </div>
              <div v-if="includeComments" class="comments-options">
                <span class="comments-options-label">主评论数量</span>
                <div
                  class="comment-range-segments"
                  role="group"
                  aria-label="主评论下载范围"
                >
                  <button
                    type="button"
                    class="comment-range-segment"
                    :class="{ active: !downloadAllComments }"
                    :aria-pressed="!downloadAllComments"
                    @click="downloadAllComments = false"
                  >
                    指定数量
                  </button>
                  <button
                    type="button"
                    class="comment-range-segment"
                    :class="{ active: downloadAllComments }"
                    :aria-pressed="downloadAllComments"
                    @click="downloadAllComments = true"
                  >
                    全部
                  </button>
                </div>
                <div v-if="!downloadAllComments" class="comment-limit-stepper">
                  <button
                    type="button"
                    class="comment-limit-stepper-button"
                    aria-label="减少主评论数量"
                    title="减少 10 条"
                    @click="adjustCommentLimit(-10)"
                  >
                    <Minus :size="15" aria-hidden="true" />
                  </button>
                  <input
                    id="comment-limit"
                    v-model.number="commentLimit"
                    type="number"
                    min="1"
                    max="1000"
                    step="1"
                    aria-label="主评论数量"
                    @blur="normalizeCommentLimitInput"
                  />
                  <span class="comment-limit-unit">条</span>
                  <button
                    type="button"
                    class="comment-limit-stepper-button"
                    aria-label="增加主评论数量"
                    title="增加 10 条"
                    @click="adjustCommentLimit(10)"
                  >
                    <Plus :size="15" aria-hidden="true" />
                  </button>
                </div>
              </div>
            </div>
          </template>

          <template v-else>
            <label for="audio-file">
              {{
                isOpenPublic
                  ? '音频或视频文件'
                  : '音频文件（文件名必须包含 BV 号）'
              }}
            </label>
            <div class="upload-row">
              <input
                id="audio-file"
                ref="uploadFileInput"
                type="file"
                :accept="uploadAccept"
                @change="onUploadFileChange"
              />
            </div>
            <p v-if="isOpenPublic" class="input-example">
              上传结果不会进入历史记录，仅能通过当前任务链接访问，并会在完成后 2
              小时自动删除。支持常见音频和视频格式。
            </p>
            <p v-else class="input-example">
              文件名必须符合
              <code>BV号_视频标题.xxx</code>
              ，例如
              <code>BV1R9i4BoE7H_视频标题.m4a</code>
            </p>
          </template>

          <label class="switch" for="enable-summary">
            <input
              id="enable-summary"
              v-model="enableSummary"
              type="checkbox"
            />
            <span class="switch-track">
              <span class="switch-thumb"></span>
            </span>
            <span class="switch-label">启用 LLM 整理总结</span>
          </label>

          <div v-if="enableSummary" class="process-summary-config">
            <div class="process-summary-head">
              <h3>总结参数</h3>
              <p>
                选择模型配置与总结模板，生成更符合用途的总结内容。
                <template v-if="isOpenPublic">
                  选择“用户自定义”时，会使用你在 API Key 页面保存的模板。
                </template>
              </p>
            </div>

            <div class="process-summary-grid">
              <div
                class="summary-preset process-summary-field process-summary-toggle"
              >
                <label
                  class="switch switch-compact"
                  for="auto-generate-fancy-html"
                >
                  <input
                    id="auto-generate-fancy-html"
                    v-model="autoGenerateFancyHtml"
                    type="checkbox"
                  />
                  <span class="switch-track">
                    <span class="switch-thumb"></span>
                  </span>
                  <span class="switch-label"
                    >总结完成后自动生成 Fancy HTML</span
                  >
                </label>
                <p class="preset-hint">
                  总结文件会先显示，Fancy HTML 稍后在后台生成并自动加入列表。
                </p>
              </div>

              <div
                class="summary-preset process-summary-field process-summary-inline-field"
              >
                <label for="summary-profile-select">模型配置</label>
                <div class="summary-profile-select-wrap">
                  <select
                    id="summary-profile-select"
                    :value="selectedSummaryProfile"
                    class="preset-select process-preset-select summary-profile-select"
                    :disabled="
                      isLoadingSummaryProfiles || summaryProfiles.length === 0
                    "
                    @change="selectedSummaryProfile = $event.target.value"
                  >
                    <option v-if="isLoadingSummaryProfiles" value="">
                      正在加载模型配置...
                    </option>
                    <option v-else-if="summaryProfiles.length === 0" value="">
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
                  <ChevronDown
                    :size="16"
                    class="summary-profile-select-icon"
                    aria-hidden="true"
                  />
                </div>
                <p
                  v-if="summaryProfileError"
                  class="preset-hint preset-hint-error"
                >
                  {{ summaryProfileError }}
                  <button
                    class="preset-retry"
                    type="button"
                    @click="loadSummaryProfiles"
                  >
                    重试
                  </button>
                </p>
                <p v-else-if="summaryProfiles.length === 0" class="preset-hint">
                  暂未连接到后端模型配置接口，提交时会使用服务端默认模型。
                </p>
              </div>

              <div
                class="summary-preset process-summary-field process-summary-inline-field"
              >
                <label for="summary-preset-select">总结模板</label>
                <div
                  ref="summaryPresetDropdownRef"
                  class="summary-preset-dropdown"
                  :class="{ open: isSummaryPresetMenuOpen }"
                  @keydown.esc.stop="closeSummaryPresetMenu"
                >
                  <button
                    id="summary-preset-select"
                    type="button"
                    class="preset-select process-preset-select summary-preset-trigger"
                    :disabled="
                      isLoadingSummaryPresets || presetOptions.length === 0
                    "
                    aria-haspopup="listbox"
                    :aria-expanded="isSummaryPresetMenuOpen ? 'true' : 'false'"
                    @click="toggleSummaryPresetMenu"
                  >
                    <span class="summary-preset-trigger-text">
                      {{
                        isLoadingSummaryPresets
                          ? '正在加载模板...'
                          : presetOptions.length === 0
                            ? '未获取到模板（将使用后端默认）'
                            : selectedSummaryPresetOption?.label ||
                              '请选择总结模板'
                      }}
                    </span>
                    <ChevronDown :size="16" />
                  </button>

                  <div
                    v-if="
                      isSummaryPresetMenuOpen &&
                      !isLoadingSummaryPresets &&
                      presetOptions.length > 0
                    "
                    class="summary-preset-popover"
                  >
                    <div class="summary-preset-option-list" role="listbox">
                      <button
                        v-for="preset in presetOptions"
                        :id="`summary-preset-option-${preset.name}`"
                        :key="preset.name"
                        type="button"
                        class="summary-preset-option"
                        :class="{
                          active: preset.name === selectedSummaryPreset,
                          previewing:
                            preset.name === previewedSummaryPresetOption?.name
                        }"
                        @mouseenter="previewSummaryPreset(preset.name)"
                        @focus="previewSummaryPreset(preset.name)"
                        @click="selectSummaryPreset(preset.name)"
                      >
                        <span class="summary-preset-option-label">
                          {{ preset.label }}
                        </span>
                        <span
                          v-if="preset.name === selectedSummaryPreset"
                          class="summary-preset-option-tag"
                        >
                          当前
                        </span>
                      </button>
                    </div>

                    <div class="summary-preset-preview">
                      <p class="summary-preset-preview-kicker">模板预览</p>
                      <h4>
                        {{ previewedSummaryPresetOption?.label || '总结模板' }}
                      </h4>
                      <p class="summary-preset-preview-body">
                        {{ previewedSummaryPresetText }}
                      </p>
                    </div>
                  </div>
                </div>
                <p
                  v-if="summaryPresetError"
                  class="preset-hint preset-hint-error"
                >
                  {{ summaryPresetError }}
                  <button
                    class="preset-retry"
                    type="button"
                    @click="loadSummaryPresets"
                  >
                    重试
                  </button>
                </p>
                <p v-else-if="presetOptions.length === 0" class="preset-hint">
                  暂未连接到后端模板接口，提交时会使用服务端默认模板。
                </p>
              </div>
            </div>
          </div>

          <div v-if="isJobDetailMode" class="new-job-hint">
            <button
              type="button"
              class="new-job-btn"
              @click="router.push('/process')"
            >
              <ArrowLeft :size="14" />
              <span>新建转录</span>
            </button>
            <span class="new-job-hint-text"
              >当前任务在后台进行，可从历史记录中查看进度</span
            >
          </div>

          <button
            class="submit"
            type="submit"
            :disabled="isStarting || isRunning"
          >
            <LoaderCircle
              v-if="isStarting || isRunning"
              class="spin"
              :size="16"
            />
            <span>
              {{ isStarting || isRunning ? '处理中...' : '开始处理' }}
            </span>
          </button>
        </form>

        <p v-if="error" class="inline-error">
          <AlertCircle :size="16" />
          <span>{{ error }}</span>
        </p>
        <p v-if="connectionNotice" class="connection-notice">
          <AlertCircle :size="16" />
          <span>{{ connectionNotice }}</span>
        </p>
      </article>

      <ProgressPanel :job="job" :skip-summary="shouldSkipSummary" />
    </section>

    <section class="download-layout">
      <article class="panel panel-download">
        <div class="download-card">
          <p v-if="isDone && job.already_transcribed" class="cache-hit-note">
            <CheckCircle2 :size="16" />
            <span>{{
              job.notice || '该视频曾经转录过，已直接返回历史文件。'
            }}</span>
          </p>

          <div
            v-if="isDone && (job.author || job.pubdate || job.bvid)"
            class="video-metadata"
          >
            <h3>视频信息</h3>
            <div class="metadata-items">
              <span v-if="job.bvid" class="metadata-item">
                <strong>资源 ID:</strong> {{ job.bvid }}
              </span>
              <span v-if="job.author" class="metadata-item">
                <strong>UP主 / 主播:</strong> {{ job.author }}
              </span>
              <span v-if="job.pubdate" class="metadata-item">
                <strong>发布时间:</strong> {{ job.pubdate }}
              </span>
            </div>
          </div>

          <template v-if="isDone">
            <p v-if="isFancyHtmlPending" class="cache-hit-note">
              <LoaderCircle :size="16" class="spin" />
              <span
                >Fancy HTML
                正在后台生成，现有总结文件已可下载，稍后会自动加入文件列表。</span
              >
            </p>
            <p
              v-else-if="
                job.auto_generate_fancy_html &&
                job.fancy_html_status === 'failed' &&
                job.fancy_html_error
              "
              class="inline-error"
            >
              <AlertCircle :size="16" />
              <span>Fancy HTML 自动生成失败：{{ job.fancy_html_error }}</span>
            </p>
            <FileList
              :items="allDownloadRows"
              :history-run-id="job.history_run_id || ''"
            />
          </template>
          <p v-else class="download-placeholder">
            任务完成后在这里展示可下载文件。
          </p>
        </div>
      </article>
    </section>

    <section class="log-layout">
      <article class="panel panel-log">
        <header class="log-header">
          <h2>执行日志</h2>
        </header>

        <div ref="logsViewport" class="log-view">
          <p
            v-if="!Array.isArray(job.logs) || job.logs.length === 0"
            class="log-empty"
          >
            任务开始后会在这里滚动显示日志。
          </p>
          <p v-for="(line, idx) in job.logs || []" :key="idx" class="log-line">
            {{ line }}
          </p>
        </div>
      </article>
    </section>
  </div>
</template>

<style scoped>
  /* ─── New-job hint row ───────────────────────────────────────── */

  .new-job-hint {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }

  .new-job-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 6px 12px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.9);
    color: var(--text-soft);
    font-size: 0.84rem;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
    transition:
      background-color 0.2s ease,
      border-color 0.2s ease;
  }

  .new-job-btn:hover {
    background: #ffffff;
    border-color: #94a3b8;
  }

  .new-job-hint-text {
    font-size: 0.82rem;
    color: var(--text-muted);
  }

  /* ─── Layouts ────────────────────────────────────────────────── */

  .layout {
    position: relative;
    z-index: 3;
    max-width: 1160px;
    margin: 0 auto;
    display: grid;
    grid-template-columns: minmax(0, 1.16fr) minmax(320px, 0.84fr);
    gap: 20px;
  }

  .download-layout,
  .log-layout {
    position: relative;
    z-index: 2;
    max-width: 1160px;
    margin: 20px auto 0;
  }

  /* ─── Panel variants ─────────────────────────────────────────── */

  .panel-main {
    position: relative;
    z-index: 2;
    padding: 24px 40px 40px;
  }

  .panel-download {
    padding: 28px;
    animation-delay: 0.12s;
  }

  .panel-log {
    padding: 28px;
    animation-delay: 0.16s;
  }

  /* ─── Header ─────────────────────────────────────────────────── */

  .header h1 {
    margin: 8px 0 10px;
    font-size: clamp(1.8rem, 3vw, 2.5rem);
    font-weight: 800;
    line-height: 1.1;
    letter-spacing: -0.04em;
  }

  .header p {
    margin: 0;
    max-width: 52ch;
    color: var(--text-soft);
    line-height: 1.65;
    font-size: 1.05rem;
  }

  /* ─── Hero pills ─────────────────────────────────────────────── */

  .hero-meta {
    margin-top: 18px;
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }

  .hero-pill {
    display: inline-flex;
    align-items: center;
    min-height: 30px;
    padding: 0 14px;
    border-radius: 999px;
    border: 1px solid rgba(153, 246, 228, 0.6);
    background: rgba(236, 254, 255, 0.7);
    backdrop-filter: blur(6px);
    color: #0f766e;
    font-size: 0.82rem;
    font-weight: 600;
  }

  .hero-pill-soft {
    border-color: rgba(203, 213, 225, 0.6);
    background: rgba(248, 250, 252, 0.7);
    color: #475569;
  }

  /* ─── Form ───────────────────────────────────────────────────── */

  .form {
    margin-top: 32px;
    display: grid;
    gap: 18px;
  }

  .form label {
    font-size: 0.9rem;
    color: var(--text-soft);
    font-weight: 700;
    margin-bottom: -4px;
  }

  .input-row {
    display: flex;
    align-items: center;
    gap: 12px;
    border: 1px solid var(--line);
    background: rgba(255, 255, 255, 0.7);
    backdrop-filter: blur(8px);
    border-radius: 16px;
    padding: 0 16px;
    min-height: 52px;
    transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    box-shadow: inset 0 2px 4px rgba(15, 23, 42, 0.02);
  }

  .input-row:focus-within {
    border-color: #38bdf8;
    box-shadow:
      0 0 0 4px rgba(56, 189, 248, 0.15),
      inset 0 2px 4px rgba(15, 23, 42, 0.01);
    background: #ffffff;
  }

  .input-row svg {
    color: #64748b;
    flex-shrink: 0;
  }

  .input-row input {
    width: 100%;
    border: none;
    outline: none;
    background: transparent;
    color: var(--text-main);
    height: 50px;
    font-size: 1rem;
  }

  .input-example {
    margin: -4px 0 4px;
    font-size: 0.84rem;
    color: var(--text-muted);
    line-height: 1.5;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .input-example a {
    color: var(--brand-strong);
    text-decoration: none;
    word-break: break-all;
  }

  .input-example a:hover {
    text-decoration: underline;
  }

  .input-mode-tabs {
    display: inline-flex;
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 6px;
    background: rgba(248, 250, 252, 0.7);
    backdrop-filter: blur(8px);
    gap: 6px;
  }

  .input-mode-button {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 38px;
    padding: 0 16px;
    border: none;
    border-radius: 10px;
    background: transparent;
    color: #475569;
    font-size: 0.9rem;
    font-weight: 700;
    cursor: pointer;
    transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  }

  .input-mode-button.active {
    background: linear-gradient(135deg, #0ea5e9, #14b8a6);
    color: #ffffff;
    box-shadow: 0 2px 8px rgba(14, 165, 233, 0.25);
  }

  .input-mode-button:disabled {
    opacity: 0.65;
    cursor: not-allowed;
  }

  .upload-row {
    display: flex;
    align-items: center;
    border: 1px solid var(--line);
    border-radius: 16px;
    min-height: 52px;
    padding: 10px 16px;
    background: rgba(255, 255, 255, 0.7);
    backdrop-filter: blur(8px);
    box-shadow: inset 0 2px 4px rgba(15, 23, 42, 0.02);
    transition: all 0.25s ease;
  }

  .upload-row input[type='file'] {
    width: 100%;
    color: var(--text-soft);
    font-size: 0.95rem;
  }

  /* ─── Toggle switch ──────────────────────────────────────────── */

  .switch {
    margin-top: 4px;
    display: inline-flex;
    align-items: center;
    gap: 12px;
    cursor: pointer;
    user-select: none;
  }

  .switch input {
    position: absolute;
    opacity: 0;
    width: 0;
    height: 0;
  }

  .switch-track {
    width: 46px;
    height: 26px;
    border-radius: 999px;
    border: 1px solid #cbd5e1;
    background: #e2e8f0;
    padding: 2px;
    transition:
      background-color 0.25s ease,
      border-color 0.25s ease;
  }

  .switch-thumb {
    display: block;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: #ffffff;
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.15);
    transform: translateX(0);
    transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
  }

  .switch input:checked + .switch-track {
    border-color: #14b8a6;
    background: linear-gradient(135deg, #14b8a6, #0ea5e9);
  }

  .switch input:checked + .switch-track .switch-thumb {
    transform: translateX(20px);
  }

  .switch input:focus-visible + .switch-track {
    box-shadow: 0 0 0 4px rgba(20, 184, 166, 0.2);
  }

  .switch-label {
    color: var(--text-soft);
    font-size: 0.95rem;
    font-weight: 600;
  }

  /* ─── Summary config ─────────────────────────────────────────── */

  .process-summary-config {
    padding: 24px;
    border: 1px solid rgba(255, 255, 255, 0.6);
    border-radius: 20px;
    background: linear-gradient(
      180deg,
      rgba(255, 255, 255, 0.7) 0%,
      rgba(248, 253, 255, 0.5) 100%
    );
    box-shadow: 0 8px 24px -8px rgba(15, 23, 42, 0.05);
    backdrop-filter: blur(12px);
    display: grid;
    gap: 20px;
  }

  .process-summary-head {
    display: grid;
    gap: 6px;
  }

  .process-summary-head h3 {
    margin: 0;
    font-size: 1.15rem;
    color: #0f172a;
  }

  .process-summary-head p {
    margin: 0;
    font-size: 0.88rem;
    line-height: 1.55;
    color: #475569;
  }

  .process-summary-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 16px;
  }

  .process-summary-field {
    display: grid;
    gap: 8px;
  }

  .process-summary-inline-field {
    grid-template-columns: max-content minmax(0, 1fr);
    column-gap: 14px;
    row-gap: 8px;
    align-items: center;
  }

  .process-summary-toggle {
    grid-column: 1 / -1;
  }

  .comments-summary-field {
    gap: 10px;
  }

  .comments-summary-toggle-row {
    display: flex;
    align-items: center;
    gap: 7px;
  }

  .comments-summary-toggle-row .switch {
    margin-top: 0;
  }

  .comments-help {
    position: relative;
    display: inline-flex;
    align-items: center;
  }

  .comments-help-trigger {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: transparent;
    color: #64748b;
    cursor: help;
  }

  .comments-help-trigger:hover,
  .comments-help-trigger:focus-visible {
    background: #f1f5f9;
    color: #0f766e;
    outline: none;
  }

  .comments-help-trigger:focus-visible {
    box-shadow: 0 0 0 3px rgba(20, 184, 166, 0.18);
  }

  .comments-help-tooltip {
    position: absolute;
    left: 50%;
    bottom: calc(100% + 8px);
    z-index: 40;
    width: min(360px, calc(100vw - 48px));
    padding: 10px 12px;
    border: 1px solid rgba(203, 213, 225, 0.9);
    border-radius: 8px;
    background: #ffffff;
    box-shadow: 0 12px 28px -14px rgba(15, 23, 42, 0.35);
    color: #334155;
    font-size: 0.82rem;
    font-weight: 500;
    line-height: 1.55;
    opacity: 0;
    pointer-events: none;
    transform: translate(-50%, 4px);
    transition:
      opacity 0.16s ease,
      transform 0.16s ease;
  }

  .comments-help:hover .comments-help-tooltip,
  .comments-help:focus-within .comments-help-tooltip {
    opacity: 1;
    transform: translate(-50%, 0);
  }

  .comments-options {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
    padding: 10px;
    border: 1px solid rgba(203, 213, 225, 0.9);
    border-radius: 8px;
    background: rgba(248, 250, 252, 0.78);
  }

  .comments-options-label {
    margin: 0 2px;
    color: #475569;
    font-size: 0.82rem;
    font-weight: 700;
  }

  .comment-range-segments {
    display: inline-grid;
    grid-template-columns: repeat(2, max-content);
    gap: 2px;
    padding: 3px;
    border: 1px solid #cbd5e1;
    border-radius: 7px;
    background: #e2e8f0;
  }

  .comment-range-segment {
    min-height: 30px;
    padding: 0 11px;
    border: 0;
    border-radius: 5px;
    background: transparent;
    color: #64748b;
    font-size: 0.82rem;
    font-weight: 700;
    cursor: pointer;
  }

  .comment-range-segment.active {
    background: #ffffff;
    color: #0f766e;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.12);
  }

  .comment-range-segment:focus-visible {
    outline: 2px solid #14b8a6;
    outline-offset: 1px;
  }

  .comment-limit-stepper {
    display: inline-flex;
    align-items: center;
    height: 38px;
    border: 1px solid #cbd5e1;
    border-radius: 7px;
    overflow: hidden;
    background: #ffffff;
  }

  .comment-limit-stepper:focus-within {
    border-color: #14b8a6;
    box-shadow: 0 0 0 3px rgba(20, 184, 166, 0.12);
  }

  .comment-limit-stepper input {
    width: 58px;
    height: 100%;
    padding: 0 4px;
    border: 0;
    outline: 0;
    background: transparent;
    color: #0f172a;
    font-size: 0.88rem;
    font-weight: 700;
    text-align: right;
    appearance: textfield;
  }

  .comment-limit-stepper input::-webkit-inner-spin-button,
  .comment-limit-stepper input::-webkit-outer-spin-button {
    margin: 0;
    appearance: none;
  }

  .comment-limit-unit {
    padding-right: 8px;
    color: #64748b;
    font-size: 0.78rem;
  }

  .comment-limit-stepper-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 34px;
    height: 100%;
    padding: 0;
    border: 0;
    background: #f8fafc;
    color: #64748b;
    cursor: pointer;
  }

  .comment-limit-stepper-button:first-child {
    border-right: 1px solid #e2e8f0;
  }

  .comment-limit-stepper-button:last-child {
    border-left: 1px solid #e2e8f0;
  }

  .comment-limit-stepper-button:hover {
    background: #ecfeff;
    color: #0f766e;
  }

  .comment-limit-stepper-button:focus-visible {
    outline: 2px solid #14b8a6;
    outline-offset: -2px;
  }

  .process-summary-field label {
    font-size: 0.88rem;
    font-weight: 700;
    color: #334155;
  }

  .process-summary-inline-field .preset-hint {
    grid-column: 2 / 3;
  }

  .summary-preset-dropdown {
    position: relative;
    min-width: 0;
  }

  .summary-profile-select-wrap {
    position: relative;
    min-width: 0;
  }

  .process-preset-select {
    min-height: 42px;
    padding-inline: 14px;
    font-size: 0.9rem;
    border-color: #cbd5e1;
    background: linear-gradient(
      145deg,
      rgba(255, 255, 255, 0.9),
      rgba(248, 250, 252, 0.8)
    );
    box-shadow:
      inset 0 1px 2px rgba(255, 255, 255, 1),
      0 2px 6px rgba(15, 23, 42, 0.04);
  }

  .summary-profile-select {
    appearance: none;
    -webkit-appearance: none;
    -moz-appearance: none;
    padding-right: 42px;
  }

  .summary-profile-select-icon {
    position: absolute;
    top: 50%;
    right: 14px;
    transform: translateY(-50%);
    color: #64748b;
    pointer-events: none;
  }

  .summary-preset-trigger {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    width: 100%;
    text-align: left;
    cursor: pointer;
  }

  .summary-preset-trigger svg {
    flex-shrink: 0;
    color: #64748b;
    transition: transform 0.2s ease;
  }

  .summary-preset-dropdown.open .summary-preset-trigger svg {
    transform: rotate(180deg);
  }

  .summary-preset-trigger-text {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .summary-preset-popover {
    position: absolute;
    left: 0;
    top: calc(100% + 10px);
    z-index: 30;
    width: min(700px, calc(100vw - 96px));
    display: grid;
    grid-template-columns: 248px 410px;
    gap: 14px;
    padding: 14px;
    border: 1px solid rgba(203, 213, 225, 0.85);
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.96);
    box-shadow:
      0 16px 40px -18px rgba(15, 23, 42, 0.28),
      0 8px 20px -12px rgba(15, 23, 42, 0.16);
    backdrop-filter: blur(18px);
  }

  .summary-preset-option-list {
    display: grid;
    gap: 8px;
    max-height: 280px;
    overflow: auto;
  }

  .summary-preset-option {
    width: 100%;
    border: 1px solid rgba(203, 213, 225, 0.7);
    border-radius: 12px;
    background: rgba(248, 250, 252, 0.9);
    color: #334155;
    padding: 10px 12px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    text-align: left;
    cursor: pointer;
    transition:
      border-color 0.18s ease,
      background-color 0.18s ease,
      transform 0.18s ease;
  }

  .summary-preset-option:hover,
  .summary-preset-option.previewing {
    border-color: #7dd3fc;
    background: #f0f9ff;
  }

  .summary-preset-option.active {
    border-color: #5eead4;
    background: #ecfeff;
    color: #0f766e;
  }

  .summary-preset-option:focus-visible {
    outline: none;
    box-shadow: 0 0 0 4px rgba(56, 189, 248, 0.16);
  }

  .summary-preset-option-label {
    min-width: 0;
    font-size: 0.86rem;
    font-weight: 700;
    line-height: 1.45;
  }

  .summary-preset-option-tag {
    flex-shrink: 0;
    padding: 3px 8px;
    border-radius: 999px;
    background: rgba(20, 184, 166, 0.14);
    color: #0f766e;
    font-size: 0.74rem;
    font-weight: 800;
  }

  .summary-preset-preview {
    width: 410px;
    height: 280px;
    min-width: 0;
    padding: 14px 16px;
    border-radius: 14px;
    border: 1px solid rgba(191, 219, 254, 0.8);
    background: linear-gradient(
      180deg,
      rgba(248, 250, 252, 0.96),
      rgba(239, 246, 255, 0.92)
    );
    display: grid;
    grid-template-rows: auto auto minmax(0, 1fr);
  }

  .summary-preset-preview-kicker {
    margin: 0;
    font-size: 0.75rem;
    font-weight: 800;
    letter-spacing: 0.06em;
    color: #0284c7;
    text-transform: uppercase;
  }

  .summary-preset-preview h4 {
    margin: 8px 0 10px;
    font-size: 0.95rem;
    color: #0f172a;
  }

  .summary-preset-preview-body {
    margin: 0;
    color: #475569;
    font-size: 0.84rem;
    line-height: 1.65;
    white-space: pre-wrap;
    word-break: break-word;
    overflow: auto;
  }

  .preset-select.process-preset-select:hover:not(:disabled) {
    border-color: #93c5fd;
    box-shadow:
      inset 0 1px 2px rgba(255, 255, 255, 1),
      0 6px 16px rgba(59, 130, 246, 0.08);
  }

  .preset-select.process-preset-select:focus {
    border-color: #38bdf8;
    box-shadow:
      0 0 0 4px rgba(56, 189, 248, 0.18),
      inset 0 1px 2px rgba(255, 255, 255, 1);
  }

  /* ─── Download card ──────────────────────────────────────────── */

  .download-card {
    margin-top: 24px;
    border-radius: 20px;
    border: 1px solid rgba(153, 246, 228, 0.6);
    background: linear-gradient(
      145deg,
      rgba(240, 253, 250, 0.8),
      rgba(236, 254, 255, 0.8)
    );
    backdrop-filter: blur(8px);
    padding: 18px;
    display: block;
  }

  .cache-hit-note {
    margin: 0 0 12px;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: #065f46;
    font-size: 0.9rem;
    font-weight: 600;
  }

  .download-placeholder {
    margin: 0;
    color: var(--text-muted);
    font-size: 0.95rem;
    line-height: 1.6;
  }

  /* ─── Log ────────────────────────────────────────────────────── */

  .log-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 14px;
  }

  .log-header h2 {
    margin: 0;
    font-size: 1.15rem;
    font-weight: 800;
  }

  .log-header p {
    margin: 0;
    color: var(--text-muted);
    font-size: 0.88rem;
  }

  .log-view {
    margin-top: 18px;
    border-radius: 16px;
    border: 1px solid rgba(100, 116, 139, 0.25);
    background: linear-gradient(
      180deg,
      rgba(248, 250, 252, 0.8),
      rgba(241, 245, 249, 0.8)
    );
    backdrop-filter: blur(8px);
    padding: 16px 18px;
    height: 280px;
    overflow: auto;
    font-family:
      'SFMono-Regular', Menlo, Monaco, Consolas, 'Liberation Mono',
      'Courier New', monospace;
    box-shadow: inset 0 2px 4px rgba(15, 23, 42, 0.04);
  }

  .log-line {
    margin: 0 0 8px;
    color: #475569;
    font-size: 0.84rem;
    line-height: 1.55;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .log-line:last-child {
    margin-bottom: 0;
  }

  .log-empty {
    margin: 0;
    color: #94a3b8;
    font-size: 0.9rem;
  }

  /* ─── Responsive ─────────────────────────────────────────────── */

  @media (max-width: 980px) {
    .layout {
      grid-template-columns: 1fr;
    }

    .panel-main,
    .panel-download,
    .panel-log {
      padding: 24px;
    }

    .log-header {
      flex-direction: column;
      align-items: flex-start;
    }

    .process-summary-grid {
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 640px) {
    .panel-main,
    .panel-download,
    .panel-log {
      padding: 20px;
    }

    .header h1 {
      font-size: 1.7rem;
    }

    .input-row,
    .upload-row {
      padding-inline: 14px;
    }

    .input-mode-tabs {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      width: 100%;
    }

    .input-mode-button {
      justify-content: center;
      padding: 0 12px;
    }

    .process-summary-config {
      padding: 18px;
    }

    .process-summary-inline-field {
      grid-template-columns: 1fr;
    }

    .summary-preset-popover {
      left: 0;
      width: 100%;
      grid-template-columns: 1fr;
    }

    .summary-preset-preview {
      width: 100%;
      height: 240px;
    }

    .process-summary-inline-field .preset-hint {
      grid-column: 1 / 2;
    }

    .comments-options {
      align-items: stretch;
    }

    .comments-options-label {
      width: 100%;
    }

    .comment-range-segments {
      flex: 1;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .log-view {
      height: 240px;
      padding: 14px;
    }
  }
</style>
