<script setup>
  import { computed, onMounted, ref, watch } from 'vue'
  import { useRoute, useRouter } from 'vue-router'
  import { ArrowLeft, LoaderCircle } from 'lucide-vue-next'
  import ProgressPanel from './ProgressPanel.vue'
  import InlineNotice from './common/InlineNotice.vue'
  import ProcessJobOutput from './process/ProcessJobOutput.vue'
  import ProcessSourceInput from './process/ProcessSourceInput.vue'
  import ProcessSummaryConfig from './process/ProcessSummaryConfig.vue'
  import ProcessVideoMetadata from './process/ProcessVideoMetadata.vue'
  import { processApi } from '../api'
  import { useJobStore } from '../composables/useJobStore'
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
    untrackJob
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
  const preferBilibiliSubtitle = ref(true)
  const autoGenerateFancyHtml = ref(false)
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
  const inputBvid = computed(() => {
    const currentBvid = String(job.value.bvid || '').trim()
    if (currentBvid) return currentBvid
    return String(url.value || '').match(/BV[0-9A-Za-z]{10}/i)?.[0] || ''
  })

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
      summaryProfile: job.value.summary_profile || selectedSummaryProfile.value
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
      return false
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
    isStarting.value = true
    error.value = ''
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
      trackJob(data.job_id)
      // Navigate to the job detail URL
      await router.push(`/process/${data.job_id}`)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '提交任务失败'
    } finally {
      isStarting.value = false
    }
  }

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
      if (!nextJobId) {
        jobId.value = ''
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
    <section class="layout">
      <article class="panel panel-main">
        <div v-if="job.is_ephemeral_upload" class="hero-meta">
          <span class="hero-pill">临时结果 2 小时后删除</span>
        </div>

        <form class="form" @submit.prevent="submit">
          <ProcessSourceInput
            v-model:input-mode="inputMode"
            v-model:url="url"
            v-model:prefer-bilibili-subtitle="preferBilibiliSubtitle"
            v-model:include-comments="includeComments"
            v-model:download-all-comments="downloadAllComments"
            v-model:comment-limit="commentLimit"
            :allow-upload="allowUpload"
            :is-open-public="isOpenPublic"
            :disabled="isStarting || isRunning"
            :upload-accept="uploadAccept"
            @file-change="onUploadFileChange"
          />

          <ProcessSummaryConfig
            :enabled="enableSummary"
            :auto-generate-fancy-html="autoGenerateFancyHtml"
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
            @update:auto-generate-fancy-html="autoGenerateFancyHtml = $event"
            @update:selected-profile="selectedSummaryProfile = $event"
            @update:selected-preset="selectedSummaryPreset = $event"
            @retry-profiles="loadSummaryProfiles"
            @retry-presets="loadSummaryPresets"
          />

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

        <InlineNotice v-if="error">{{ error }}</InlineNotice>
        <InlineNotice v-if="connectionNotice" kind="warning">
          {{ connectionNotice }}
        </InlineNotice>
      </article>

      <aside class="process-sidebar">
        <ProgressPanel :job="job" :skip-summary="shouldSkipSummary" />
        <ProcessVideoMetadata
          v-if="!isUploadMode"
          :job="job"
          :source-bvid="inputBvid"
          :include-comments="includeComments"
          :comment-limit="downloadAllComments ? 0 : normalizedCommentLimit"
        />
      </aside>
    </section>

    <ProcessJobOutput
      :job="job"
      :is-done="isDone"
      :is-fancy-html-pending="isFancyHtmlPending"
      :download-rows="allDownloadRows"
    />
  </div>
</template>

<style scoped>
  .layout {
    display: grid;
    grid-template-columns: minmax(0, 1.35fr) minmax(300px, 0.65fr);
    gap: 16px;
    max-width: 1220px;
    margin: 0 auto;
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
  }

  .hero-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 18px;
  }

  .hero-pill {
    display: inline-flex;
    align-items: center;
    min-height: 28px;
    padding: 0 10px;
    border: 1px solid #fcd34d;
    border-radius: 5px;
    background: #fffbeb;
    color: #92400e;
    font-size: 0.76rem;
    font-weight: 700;
  }

  .form {
    display: grid;
    gap: 18px;
    margin-top: 0;
  }

  .new-job-hint {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
  }

  .new-job-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 6px 12px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.9);
    color: var(--text-soft);
    font-size: 0.84rem;
    font-weight: 600;
    cursor: pointer;
  }

  .new-job-hint-text {
    color: var(--text-muted);
    font-size: 0.82rem;
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
  }

  @media (max-width: 640px) {
    .panel-main {
      padding: 20px;
    }

    .layout {
      gap: 12px;
    }
  }
</style>
