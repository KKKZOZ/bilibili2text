<script setup>
  import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
  import { useRoute, useRouter } from 'vue-router'
  import {
    ArrowLeft,
    Ban,
    BellRing,
    LoaderCircle,
    XCircle
  } from 'lucide-vue-next'
  import ProgressPanel from './ProgressPanel.vue'
  import ConfirmDialog from './common/ConfirmDialog.vue'
  import InlineNotice from './common/InlineNotice.vue'
  import ProcessJobOutput from './process/ProcessJobOutput.vue'
  import ProcessSourceInput from './process/ProcessSourceInput.vue'
  import ProcessSummaryConfig from './process/ProcessSummaryConfig.vue'
  import ProcessReportConfig from './process/ProcessReportConfig.vue'
  import ProcessVideoMetadata from './process/ProcessVideoMetadata.vue'
  import { processApi } from '../api'
  import { useJobStore } from '../composables/useJobStore'
  import { setPageTitleDetail } from '../composables/usePageTitle'
  import { usePublicCredentials } from '../composables/usePublicCredentials'
  import { useRuntimeFeatures } from '../composables/useRuntimeFeatures'
  import { requestJobNotificationPermission } from '../composables/useJobNotifications'
  import {
    CUSTOM_SUMMARY_PRESET_VALUE,
    useSummaryConfig,
    withCustomSummaryPreset
  } from '../composables/useSummaryConfig'
  import { inferSummaryPresetFromFilename } from '../utils/fileUtils'

  const route = useRoute()
  const router = useRouter()
  const {
    connectionNotice,
    getJob: getStoredJob,
    loadJob,
    trackJob,
    untrackJob,
    cancelJob
  } = useJobStore()
  const { runtimeFeatures } = useRuntimeFeatures()
  const allowUpload = computed(() => runtimeFeatures.value.allow_upload_audio)
  const requiresApiKey = computed(
    () => runtimeFeatures.value.requires_user_api_key
  )
  const {
    summaryPresets,
    summaryDefaultPromptTemplate,
    summaryProfiles,
    defaultReportProfile,
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
  const inputMode = ref('url')
  const uploadedAudioFile = ref(null)
  const enableSummary = ref(true)
  const autoGenerateFancyHtml = ref(false)
  const reportOptions = ref({
    mode: 'standard',
    profile: ''
  })
  const effectiveReportOptions = computed(() => ({
    ...reportOptions.value,
    profile: reportOptions.value.profile || defaultReportProfile.value || ''
  }))
  const includeComments = ref(true)
  const commentLimit = ref(200)
  const downloadAllComments = ref(false)
  const currentSkipSummary = ref(false)
  const isStarting = ref(false)
  const jobId = ref('')
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
    subtitle_source: '',
    subtitle_language: '',
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
    title: '',
    duration_seconds: 0,
    tname: '',
    parent_tname: '',
    comment_status: 'disabled',
    comment_limit: 200,
    comment_count: 0,
    comment_reply_count: 0,
    history_run_id: '',
    is_ephemeral_upload: false,
    expires_at: ''
  })

  let lastRenderedJobSignature = ''
  const uploadAccept =
    '.aac,.flac,.m4a,.mp3,.ogg,.opus,.wav,.webm,.avi,.m4v,.mkv,.mov,.mp4'
  const uploadFilenamePattern =
    /^(BV[0-9A-Za-z]{10})_.+\.(aac|flac|m4a|mp3|ogg|opus|wav|webm)$/i
  const openPublicUploadPattern =
    /\.(aac|flac|m4a|mp3|ogg|opus|wav|webm|avi|m4v|mkv|mov|mp4)$/i
  const userSummaryPromptTemplate = ref('')

  // Job from route param
  const routeJobId = computed(() => String(route.params.jobId || ''))
  const isJobDetailMode = computed(() => !!routeJobId.value)
  const isOpenPublic = requiresApiKey
  const presetOptions = computed(() => {
    return withCustomSummaryPreset(summaryPresets.value, isOpenPublic.value)
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

  const normalizedCommentLimit = computed(() => {
    if (downloadAllComments.value) {
      return null
    }
    const parsed = Number(commentLimit.value)
    if (!Number.isFinite(parsed)) {
      return 200
    }
    return Math.min(1000, Math.max(1, Math.floor(parsed)))
  })

  const clearActiveJobId = () => {
    if (jobId.value) untrackJob(jobId.value)
    jobId.value = ''
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
      summaryProfile:
        item.kind === 'summary_fancy_html'
          ? item.summary_profile || ''
          : item.summary_profile ||
            job.value.summary_profile ||
            selectedSummaryProfile.value
    }))
  })

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
      payload.subtitle_source || '',
      payload.subtitle_language || '',
      payload.already_transcribed ? '1' : '0',
      payload.notice || '',
      payload.error || '',
      getDownloadSignature(payload.all_downloads),
      getLogSignature(payload.logs),
      payload.author || '',
      payload.pubdate || '',
      payload.bvid || '',
      payload.title || '',
      payload.duration_seconds || 0,
      payload.tname || '',
      payload.parent_tname || '',
      payload.comment_status || '',
      payload.comment_limit ?? '',
      payload.comment_count || 0,
      payload.comment_reply_count || 0,
      payload.history_run_id || '',
      payload.is_ephemeral_upload ? '1' : '0',
      payload.expires_at || ''
    ].join('\u001f')

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
      subtitle_source: '',
      subtitle_language: '',
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
      title: '',
      duration_seconds: 0,
      tname: '',
      parent_tname: '',
      comment_status: 'disabled',
      comment_limit: 200,
      comment_count: 0,
      comment_reply_count: 0,
      history_run_id: '',
      is_ephemeral_upload: false,
      expires_at: ''
    }
  }

  const onUploadFileChange = (file) => {
    uploadedAudioFile.value = file || null
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
    error.value = ''
    const currentLogCount = Array.isArray(data.logs) ? data.logs.length : 0
    if (shouldRenderJob && currentLogCount !== previousLogCount) {
    }

    if (data.status === 'failed') {
      error.value = data.error || '处理失败'
      return (
        Boolean(data.auto_generate_fancy_html) &&
        ['pending', 'running'].includes(data.fancy_html_status || '')
      )
    } else if (data.status === 'cancelled') {
      error.value = data.error || '任务已取消'
      return false
    } else if (
      data.status === 'succeeded' &&
      !(
        data.auto_generate_fancy_html &&
        ['pending', 'running'].includes(data.fancy_html_status || '')
      )
    ) {
      return false
    }
    return true
  }

  const submit = async () => {
    if (!enableSummary.value && !autoGenerateFancyHtml.value) {
      error.value = '总结和阅读报告至少需要开启一项'
      return
    }
    isStarting.value = true
    error.value = ''
    clearActiveJobId()
    resetJob()

    try {
      if (
        requiresApiKey.value &&
        isUploadMode.value &&
        !apiKeyConfigured.value
      ) {
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
      if (isUploadMode.value) {
        if (!allowUpload.value) {
          throw new Error('当前模式不允许上传音频，请改为输入播客/视频链接')
        }
        const validationMessage = validateUploadedAudio(uploadedAudioFile.value)
        if (validationMessage) {
          throw new Error(validationMessage)
        }
      } else if (!url.value.trim()) {
        throw new Error('请输入播客链接或视频 URL')
      }

      const skipSummary = !enableSummary.value
      currentSkipSummary.value = skipSummary
      requestJobNotificationPermission()

      let data
      if (isUploadMode.value) {
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
        formData.append(
          'auto_generate_fancy_html',
          String(autoGenerateFancyHtml.value)
        )
        formData.append(
          'report_options',
          JSON.stringify(effectiveReportOptions.value)
        )
        if (requiresApiKey.value) {
          formData.append('api_key', getApiKey())
          const dsKey = getDeepseekApiKey()
          if (dsKey) formData.append('deepseek_api_key', dsKey)
          appendCustomLlmFormData(formData, true)
        }
        data = await processApi.startFromUpload(formData)
      } else {
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
          auto_generate_fancy_html: autoGenerateFancyHtml.value,
          report_options: effectiveReportOptions.value,
          prefer_subtitles: true,
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
      trackJob(data.job_id)
      // Navigate to the job detail URL
      await router.push(`/process/${data.job_id}`)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '提交任务失败'
    } finally {
      isStarting.value = false
    }
  }

  // ─── Job detail header ────────────────────────────────────────────
  const jobHeading = computed(
    () => job.value.title || job.value.bvid || job.value.filename || '转录任务'
  )
  const jobConfigChips = computed(() => {
    if (job.value.status === 'idle') return []
    const chips = []
    if (currentSkipSummary.value) {
      chips.push('不生成总结')
    } else {
      const preset = summaryPresets.value.find(
        (item) => item.name === job.value.summary_preset
      )
      chips.push(
        `总结：${preset?.label || job.value.summary_preset || '默认模板'}`
      )
      if (job.value.summary_profile) {
        chips.push(`模型：${job.value.summary_profile}`)
      }
    }
    if (job.value.auto_generate_fancy_html) chips.push('阅读报告')
    return chips
  })

  const cancelConfirmOpen = ref(false)
  const cancelLoading = ref(false)
  const cancelError = ref('')

  const confirmCancelJob = async () => {
    if (!jobId.value || cancelLoading.value) return
    cancelLoading.value = true
    cancelError.value = ''
    try {
      await cancelJob(jobId.value)
      const latest = getStoredJob(jobId.value)
      if (latest) applyJobUpdate(latest)
      cancelConfirmOpen.value = false
    } catch (err) {
      cancelError.value = err instanceof Error ? err.message : '取消任务失败'
    } finally {
      cancelLoading.value = false
    }
  }

  watch(
    () => [
      isJobDetailMode.value,
      isRunning.value,
      job.value.progress,
      jobHeading.value
    ],
    ([detailMode, running, progress, heading]) => {
      if (!detailMode) {
        setPageTitleDetail('')
        return
      }
      setPageTitleDetail(running ? `${progress || 0}% ${heading}` : heading)
    },
    { immediate: true }
  )

  onBeforeUnmount(() => setPageTitleDetail(''))

  onMounted(() => {
    loadLocalSummaryPromptTemplate()
  })

  watch(
    () => getStoredJob(jobId.value),
    (data) => {
      if (data) applyJobUpdate(data)
    }
  )

  watch(
    routeJobId,
    async (nextJobId) => {
      cancelConfirmOpen.value = false
      cancelError.value = ''
      if (!nextJobId) {
        jobId.value = ''
        error.value = ''
        resetJob()
        return
      }
      jobId.value = nextJobId
      const cached = getStoredJob(nextJobId)
      if (cached) applyJobUpdate(cached)
      try {
        const data = await loadJob(nextJobId)
        if (routeJobId.value === nextJobId) applyJobUpdate(data)
      } catch (err) {
        if (routeJobId.value === nextJobId) {
          error.value = err instanceof Error ? err.message : '获取任务进度失败'
        }
      }
    },
    { immediate: true }
  )

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
</script>

<template>
  <div class="process-page">
    <!-- New transcription -->
    <section v-if="!isJobDetailMode" class="layout">
      <article class="panel panel-main">
        <form class="form" @submit.prevent="submit">
          <ProcessSourceInput
            v-model:input-mode="inputMode"
            v-model:url="url"
            :allow-upload="allowUpload"
            :is-open-public="isOpenPublic"
            :disabled="isStarting || isRunning"
            :upload-accept="uploadAccept"
            @file-change="onUploadFileChange"
          />

          <ProcessSummaryConfig
            v-model:include-comments="includeComments"
            v-model:download-all-comments="downloadAllComments"
            v-model:comment-limit="commentLimit"
            :allow-comments="!isUploadMode"
            :disabled="isStarting || isRunning"
            :enabled="enableSummary"
            :is-open-public="isOpenPublic"
            :selected-profile="selectedSummaryProfile"
            :selected-preset="selectedSummaryPreset"
            :profiles="summaryProfiles"
            :presets="presetOptions"
            :profiles-loading="isLoadingSummaryProfiles"
            :presets-loading="isLoadingSummaryPresets"
            :profile-error="summaryProfileError"
            :preset-error="summaryPresetError"
            :custom-prompt-template="userSummaryPromptTemplate"
            :fallback-prompt-template="summaryDefaultPromptTemplate"
            :custom-preset-value="CUSTOM_SUMMARY_PRESET_VALUE"
            @update:enabled="enableSummary = $event"
            @update:selected-profile="selectedSummaryProfile = $event"
            @update:selected-preset="selectedSummaryPreset = $event"
            @retry-profiles="loadSummaryProfiles"
            @retry-presets="loadSummaryPresets"
          />

          <ProcessReportConfig
            v-model:enabled="autoGenerateFancyHtml"
            v-model:options="reportOptions"
            :profiles="summaryProfiles"
            :default-profile="defaultReportProfile"
            :loading="isLoadingSummaryProfiles"
            :error="summaryProfileError"
            @retry="loadSummaryProfiles"
          />

          <InlineNotice
            v-if="!enableSummary && !autoGenerateFancyHtml"
            kind="warning"
          >
            总结和阅读报告至少需要开启一项
          </InlineNotice>

          <button
            class="submit"
            type="submit"
            :disabled="
              isStarting ||
              isRunning ||
              (!enableSummary && !autoGenerateFancyHtml)
            "
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

        <InlineNotice v-if="error">{{ error }}</InlineNotice>
      </article>

      <aside class="process-sidebar">
        <article class="panel guide-panel">
          <h2>处理流程</h2>
          <ol>
            <li>
              <strong>获取内容</strong>
              <span>优先读取平台字幕，没有字幕时下载音频。</span>
            </li>
            <li>
              <strong>转录文本</strong>
              <span>音频转成带时间戳的原文，并整理为 Markdown。</span>
            </li>
            <li>
              <strong>生成总结 / 阅读报告</strong>
              <span>按所选模板和模型整理内容。</span>
            </li>
            <li>
              <strong>导出文件</strong>
              <span>结果可下载为 Markdown、TXT、PDF 或 PNG。</span>
            </li>
          </ol>
          <p class="guide-note">
            <BellRing :size="14" aria-hidden="true" />
            <span>
              提交后可以离开本页，任务会在后台继续；进度可在「历史记录」查看，完成时会发送浏览器通知。
            </span>
          </p>
        </article>
      </aside>
    </section>

    <!-- Job detail -->
    <template v-else>
      <header class="panel job-header">
        <button type="button" class="job-back" @click="router.push('/process')">
          <ArrowLeft :size="15" aria-hidden="true" />
          <span>新建转录</span>
        </button>
        <div class="job-heading">
          <h2>{{ jobHeading }}</h2>
          <div
            v-if="jobConfigChips.length || job.is_ephemeral_upload"
            class="job-chips"
          >
            <span v-for="chip in jobConfigChips" :key="chip">{{ chip }}</span>
            <span v-if="job.is_ephemeral_upload" class="chip-warning">
              临时结果 2 小时后删除
            </span>
          </div>
        </div>
        <button
          v-if="isRunning"
          type="button"
          class="job-cancel"
          @click="cancelConfirmOpen = true"
        >
          <XCircle :size="15" aria-hidden="true" />
          <span>取消任务</span>
        </button>
      </header>

      <InlineNotice v-if="job.status === 'cancelled'" kind="warning">
        {{ error || '任务已取消' }}
      </InlineNotice>
      <InlineNotice v-else-if="error">{{ error }}</InlineNotice>
      <InlineNotice v-if="connectionNotice" kind="warning">
        {{ connectionNotice }}
      </InlineNotice>
      <InlineNotice v-if="isRunning" kind="info">
        任务在后台进行，离开本页不会中断，可在「历史记录」中随时回到这里。
      </InlineNotice>

      <section class="layout layout-job">
        <div class="job-main">
          <ProcessJobOutput
            :job="job"
            :is-done="isDone"
            :is-fancy-html-pending="isFancyHtmlPending"
            :download-rows="allDownloadRows"
          />
        </div>
        <aside class="process-sidebar">
          <ProgressPanel :job="job" :skip-summary="shouldSkipSummary" />
          <ProcessVideoMetadata
            v-if="!job.is_ephemeral_upload"
            :job="job"
            :source-bvid="job.bvid || ''"
            :include-comments="includeComments"
            :comment-limit="downloadAllComments ? 0 : normalizedCommentLimit"
          />
        </aside>
      </section>

      <ConfirmDialog
        :open="cancelConfirmOpen"
        title="确认取消任务"
        confirm-label="取消任务"
        cancel-label="继续处理"
        busy-label="取消中..."
        :busy="cancelLoading"
        @cancel="cancelConfirmOpen = false"
        @confirm="confirmCancelJob"
      >
        <p>确定要取消这个任务吗？取消后需要重新提交才能再次处理。</p>
        <InlineNotice v-if="cancelError" compact>{{
          cancelError
        }}</InlineNotice>
        <template #confirm-icon><Ban :size="16" /></template>
      </ConfirmDialog>
    </template>
  </div>
</template>

<style scoped>
  .process-page {
    display: grid;
    gap: 14px;
  }

  .process-page > :deep(.inline-notice) {
    margin: 0;
  }

  .layout {
    display: grid;
    grid-template-columns: minmax(0, 1.35fr) minmax(300px, 0.65fr);
    gap: 16px;
    min-width: 0;
  }

  .panel-main {
    padding: 28px;
  }

  .process-sidebar {
    position: sticky;
    top: 92px;
    align-self: start;
    display: grid;
    gap: 16px;
    min-width: 0;
  }

  .form {
    display: grid;
    gap: 18px;
    margin-top: 0;
  }

  /* ─── Guide panel (new transcription) ────────────────────────── */

  .guide-panel {
    padding: 22px;
  }

  .guide-panel h2 {
    margin: 0 0 14px;
    font-size: 1.07rem;
  }

  .guide-panel ol {
    display: grid;
    gap: 14px;
    margin: 0;
    padding: 0;
    list-style: none;
    counter-reset: guide;
  }

  .guide-panel li {
    position: relative;
    display: grid;
    gap: 2px;
    padding-left: 34px;
    counter-increment: guide;
  }

  .guide-panel li::before {
    position: absolute;
    top: 1px;
    left: 0;
    display: grid;
    width: 22px;
    height: 22px;
    place-items: center;
    border-radius: 50%;
    background: var(--brand-soft);
    color: var(--brand-strong);
    font-size: 0.74rem;
    font-weight: 700;
    content: counter(guide);
  }

  .guide-panel li strong {
    font-size: 0.89rem;
  }

  .guide-panel li span {
    color: var(--text-muted);
    font-size: 0.82rem;
    line-height: 1.5;
  }

  .guide-note {
    display: flex;
    gap: 8px;
    margin: 18px 0 0;
    padding-top: 14px;
    border-top: 1px solid var(--line-soft);
    color: var(--text-muted);
    font-size: 0.82rem;
    line-height: 1.55;
  }

  .guide-note svg {
    flex: 0 0 auto;
    margin-top: 3px;
    color: var(--brand);
  }

  /* ─── Job detail ─────────────────────────────────────────────── */

  .job-header {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 16px 22px;
  }

  .job-heading {
    display: grid;
    flex: 1;
    gap: 8px;
    min-width: 0;
  }

  .job-heading h2 {
    margin: 0;
    overflow: hidden;
    font-size: 1.12rem;
    line-height: 1.35;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .job-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .job-chips span {
    display: inline-flex;
    align-items: center;
    min-height: 24px;
    padding: 0 8px;
    border: 1px solid var(--line);
    border-radius: var(--radius-md);
    background: var(--surface-subtle);
    color: var(--text-soft);
    font-size: 0.76rem;
    font-weight: 600;
  }

  .job-chips .chip-warning {
    border-color: var(--warning-line);
    background: var(--warning-soft);
    color: var(--warning-strong);
  }

  .job-back,
  .job-cancel {
    display: inline-flex;
    flex: 0 0 auto;
    align-items: center;
    gap: 6px;
    min-height: 36px;
    padding: 0 12px;
    border: 1px solid var(--line);
    border-radius: var(--radius-md);
    background: var(--panel-bg);
    color: var(--text-soft);
    font-size: 0.84rem;
    font-weight: 600;
    cursor: pointer;
  }

  .job-back:hover {
    border-color: var(--brand);
    color: var(--brand-strong);
  }

  .job-cancel {
    border-color: var(--danger-line);
    color: var(--danger);
  }

  .job-cancel:hover {
    background: var(--danger-soft);
  }

  .job-back:focus-visible,
  .job-cancel:focus-visible {
    outline: 3px solid var(--focus-ring);
    outline-offset: 2px;
  }

  .job-main {
    display: grid;
    align-content: start;
    gap: 16px;
    min-width: 0;
  }

  @media (max-width: 980px) {
    .layout {
      grid-template-columns: 1fr;
    }

    .panel-main {
      padding: 24px;
    }

    .process-sidebar {
      position: static;
    }

    /* Progress comes before files and logs on narrow screens. */
    .layout-job .process-sidebar {
      order: -1;
    }
  }

  @media (max-width: 640px) {
    .panel-main {
      padding: 20px;
    }

    .layout {
      gap: 12px;
    }

    .job-header {
      flex-wrap: wrap;
      padding: 16px 18px;
    }

    .job-heading {
      flex-basis: 100%;
      order: 3;
    }

    .job-heading h2 {
      white-space: normal;
    }

    .job-cancel {
      margin-left: auto;
    }
  }
</style>
