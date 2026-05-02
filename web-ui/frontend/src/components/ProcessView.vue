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
    FileAudio2,
    Link2,
    LoaderCircle,
    Sparkles
  } from 'lucide-vue-next'
  import ProgressPanel from './ProgressPanel.vue'
  import FileList from './FileList.vue'
  import { inferSummaryPresetFromFilename } from '../utils/fileUtils'

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
    summaryDefaultPromptTemplate: {
      type: String,
      default: ''
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
    summaryPresetError: {
      type: String,
      default: ''
    },
    summaryProfileError: {
      type: String,
      default: ''
    },
    isLoadingSummaryPresets: {
      type: Boolean,
      default: false
    },
    isLoadingSummaryProfiles: {
      type: Boolean,
      default: false
    },
    allowUpload: {
      type: Boolean,
      default: true
    },
    requiresApiKey: {
      type: Boolean,
      default: false
    },
    apiKeyConfigured: {
      type: Boolean,
      default: true
    },
    deepseekApiKeyConfigured: {
      type: Boolean,
      default: false
    }
  })

  const emit = defineEmits([
    'update:selectedSummaryPreset',
    'update:selectedSummaryProfile',
    'loadSummaryPresets',
    'loadSummaryProfiles'
  ])

  const url = ref('')
  const error = ref('')
  const inputMode = ref('url')
  const uploadedAudioFile = ref(null)
  const uploadFileInput = ref(null)
  const enableSummary = ref(true)
  const autoGenerateFancyHtml = ref(false)
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
    bvid: ''
  })

  let pollTimer = null
  const maxPollErrors = 3
  const ACTIVE_JOB_IDS_KEY = 'b2t.active-job-ids'
  const LOCAL_API_KEY_KEY = 'b2t.public-api-key'
  const LOCAL_DEEPSEEK_API_KEY_KEY = 'b2t.public-deepseek-api-key'
  const LOCAL_OPEN_PUBLIC_SUMMARY_TEMPLATE_KEY =
    'b2t.open-public-summary-template'
  const CUSTOM_SUMMARY_PRESET_VALUE = '__user_custom__'
  const uploadAccept = '.aac,.flac,.m4a,.mp3,.ogg,.opus,.wav,.webm'
  const uploadFilenamePattern =
    /^(BV[0-9A-Za-z]{10})_.+\.(aac|flac|m4a|mp3|ogg|opus|wav|webm)$/i
  const userSummaryPromptTemplate = ref('')

  // Job from route param
  const routeJobId = computed(() => String(route.params.jobId || ''))
  const isJobDetailMode = computed(() => !!routeJobId.value)
  const isOpenPublic = computed(() => props.requiresApiKey)
  const presetOptions = computed(() => {
    const base = Array.isArray(props.summaryPresets) ? props.summaryPresets : []
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
    if (props.selectedSummaryPreset !== CUSTOM_SUMMARY_PRESET_VALUE) {
      return ''
    }
    return userSummaryPromptTemplate.value.trim()
  })

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

  const parseJsonSafely = async (resp, fallbackMessage) => {
    const raw = await resp.text()
    if (!raw) {
      return null
    }
    try {
      return JSON.parse(raw)
    } catch {
      throw new Error(
        `${fallbackMessage}（服务返回了非 JSON 响应，HTTP ${resp.status}）`
      )
    }
  }

  const pickApiError = (resp, data, fallbackMessage) => {
    if (
      data &&
      typeof data === 'object' &&
      typeof data.detail === 'string' &&
      data.detail.trim()
    ) {
      return data.detail
    }
    return `${fallbackMessage}（HTTP ${resp.status}）`
  }

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

  const loadLocalSummaryPromptTemplate = () => {
    if (!isOpenPublic.value) {
      userSummaryPromptTemplate.value = ''
      return
    }
    try {
      const stored = (
        window.localStorage.getItem(LOCAL_OPEN_PUBLIC_SUMMARY_TEMPLATE_KEY) || ''
      ).trim()
      userSummaryPromptTemplate.value =
        stored || props.summaryDefaultPromptTemplate || ''
    } catch {
      userSummaryPromptTemplate.value = props.summaryDefaultPromptTemplate || ''
    }
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
    () => props.allowUpload && inputMode.value === 'upload'
  )

  watch(
    () => props.allowUpload,
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
        props.selectedSummaryPreset,
      summaryProfile: job.value.summary_profile || props.selectedSummaryProfile
    }))
  })

  const stopPolling = () => {
    if (pollTimer !== null) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  const syncLogScroll = () => {
    if (logsViewport.value === null) {
      return
    }
    logsViewport.value.scrollTop = logsViewport.value.scrollHeight
  }

  const resetJob = () => {
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
      bvid: ''
    }
  }

  const setInputMode = (mode) => {
    if (mode === 'upload' && !props.allowUpload) {
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
      return '请先选择音频文件'
    }
    const normalizedName = String(file.name || '').trim()
    if (!uploadFilenamePattern.test(normalizedName)) {
      return '上传文件名必须符合 `BV号_视频标题.xxx`，例如 `BV1R9i4BoE7H_视频标题.m4a`'
    }
    return ''
  }

  const pollStatus = async () => {
    if (!jobId.value || isPolling.value) {
      return
    }

    isPolling.value = true
    try {
      const resp = await fetch(`/api/process/${jobId.value}`)
      const data = await parseJsonSafely(resp, '获取任务进度失败')

      if (!resp.ok) {
        if (resp.status === 404) {
          clearActiveJobId()
          stopPolling()
        }
        throw new Error(pickApiError(resp, data, '获取任务进度失败'))
      }
      if (!data || typeof data !== 'object') {
        throw new Error('获取任务进度失败（服务返回空响应）')
      }

      const previousLogCount = Array.isArray(job.value.logs)
        ? job.value.logs.length
        : 0
      job.value = data
      currentSkipSummary.value = Boolean(data.skip_summary)
      if (
        isOpenPublic.value &&
        typeof data.summary_prompt_template === 'string' &&
        data.summary_prompt_template.trim()
      ) {
        userSummaryPromptTemplate.value = data.summary_prompt_template
      }
      pollErrorCount.value = 0
      error.value = ''
      const currentLogCount = Array.isArray(data.logs) ? data.logs.length : 0
      if (currentLogCount !== previousLogCount) {
        nextTick(syncLogScroll)
      }

      if (data.status === 'failed') {
        error.value = data.error || '处理失败'
        clearActiveJobId()
        stopPolling()
      } else if (data.status === 'cancelled') {
        error.value = data.error || '任务已取消'
        clearActiveJobId()
        stopPolling()
      } else if (
        data.status === 'succeeded' &&
        !(
          data.auto_generate_fancy_html &&
          ['pending', 'running'].includes(data.fancy_html_status || '')
        )
      ) {
        clearActiveJobId()
        stopPolling()
      }
    } catch (err) {
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

  const submit = async () => {
    isStarting.value = true
    error.value = ''
    stopPolling()
    clearActiveJobId()
    resetJob()

    try {
      if (props.requiresApiKey && !props.apiKeyConfigured) {
        throw new Error('请先在「API Key」页面配置阿里云 DashScope API Key')
      }
      if (
        enableSummary.value &&
        props.selectedSummaryPreset === CUSTOM_SUMMARY_PRESET_VALUE &&
        !effectiveSummaryPromptTemplate.value
      ) {
        throw new Error(
          '请先在「API Key」页面保存自定义总结模板，再选择“用户自定义”模板'
        )
      }

      const skipSummary = !enableSummary.value
      currentSkipSummary.value = skipSummary
      pollErrorCount.value = 0

      let resp
      if (isUploadMode.value) {
        if (!props.allowUpload) {
          throw new Error('当前模式不允许上传音频，请改为输入视频 URL 或 BV 号')
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
          props.selectedSummaryPreset &&
          props.selectedSummaryPreset !== CUSTOM_SUMMARY_PRESET_VALUE
        ) {
          formData.append('summary_preset', props.selectedSummaryPreset)
        }
        if (
          !skipSummary &&
          props.selectedSummaryPreset === CUSTOM_SUMMARY_PRESET_VALUE &&
          props.summaryDefaultPreset
        ) {
          formData.append('summary_preset', props.summaryDefaultPreset)
        }
        if (!skipSummary && props.selectedSummaryProfile) {
          formData.append('summary_profile', props.selectedSummaryProfile)
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
        if (props.requiresApiKey) {
          formData.append('api_key', getLocalApiKey())
          const dsKey = getLocalDeepseekApiKey()
          if (dsKey) formData.append('deepseek_api_key', dsKey)
        }
        resp = await fetch('/api/process/upload', {
          method: 'POST',
          body: formData
        })
      } else {
        if (!url.value.trim()) {
          throw new Error('请输入 bilibili 视频 URL 或 BV 号')
        }
        resp = await fetch('/api/process', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            url: url.value.trim(),
            skip_summary: skipSummary,
            summary_preset:
              skipSummary ||
              !props.selectedSummaryPreset ||
              props.selectedSummaryPreset === CUSTOM_SUMMARY_PRESET_VALUE
                ? null
                : props.selectedSummaryPreset,
            ...(skipSummary ||
            props.selectedSummaryPreset !== CUSTOM_SUMMARY_PRESET_VALUE ||
            !props.summaryDefaultPreset
              ? {}
              : { summary_preset: props.summaryDefaultPreset }),
            summary_profile:
              skipSummary || !props.selectedSummaryProfile
                ? null
                : props.selectedSummaryProfile,
            summary_prompt_template:
              skipSummary || !effectiveSummaryPromptTemplate.value
                ? null
                : effectiveSummaryPromptTemplate.value,
            auto_generate_fancy_html: skipSummary
              ? false
              : autoGenerateFancyHtml.value,
            api_key: props.requiresApiKey ? getLocalApiKey() : null,
            deepseek_api_key: props.requiresApiKey
              ? getLocalDeepseekApiKey() || null
              : null
          })
        })
      }

      const data = await parseJsonSafely(resp, '提交任务失败')
      if (!resp.ok) {
        throw new Error(pickApiError(resp, data, '提交任务失败'))
      }
      if (
        !data ||
        typeof data !== 'object' ||
        typeof data.job_id !== 'string' ||
        !data.job_id
      ) {
        throw new Error('提交任务失败（服务未返回有效 job_id）')
      }

      jobId.value = data.job_id
      addActiveJobId(data.job_id)
      // Navigate to the job detail URL
      await router.push(`/process/${data.job_id}`)
      pollTimer = setInterval(pollStatus, 1200)
      await pollStatus()
    } catch (err) {
      error.value = err instanceof Error ? err.message : '提交任务失败'
    } finally {
      isStarting.value = false
    }
  }

  onMounted(async () => {
    loadLocalSummaryPromptTemplate()
    if (!routeJobId.value) {
      return
    }

    jobId.value = routeJobId.value
    pollErrorCount.value = 0
    await pollStatus()
    if (
      jobId.value &&
      (job.value.status === 'queued' || job.value.status === 'running')
    ) {
      pollTimer = setInterval(pollStatus, 1200)
    }
  })

  onBeforeUnmount(() => {
    stopPolling()
  })

  watch(
    () => props.summaryDefaultPromptTemplate,
    () => {
      if (!isOpenPublic.value) {
        return
      }
      const hasLocalValue = userSummaryPromptTemplate.value.trim().length > 0
      if (!hasLocalValue) {
        userSummaryPromptTemplate.value = props.summaryDefaultPromptTemplate || ''
      }
    },
    { immediate: true }
  )

  watch(
    () => props.requiresApiKey,
    () => {
      loadLocalSummaryPromptTemplate()
    },
    { immediate: true }
  )

</script>

<template>
  <div>
    <section class="layout">
      <article class="panel panel-main">
        <header class="header">
          <div class="badge">
            <Sparkles :size="14" />
            <span>AI Workflow</span>
          </div>
          <h1>bilibili-to-text</h1>
          <p>
            {{
              allowUpload
                ? '输入 B 站视频链接，或上传符合命名规范的音频文件，自动生成转录内容和大模型总结。'
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
              <FileAudio2 :size="15" />
              <span>上传音频</span>
            </button>
          </div>

          <template v-if="!isUploadMode">
            <label for="video-url">视频 URL 或 BV 号</label>
            <div class="input-row">
              <Link2 :size="18" />
              <input
                id="video-url"
                v-model="url"
                type="text"
                placeholder="https://www.bilibili.com/video/BV... 或 b23.tv/..."
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
                href="https://b23.tv/2cvz6sn"
                target="_blank"
                rel="noopener noreferrer"
              >
                https://b23.tv/2cvz6sn
              </a>
              <span
                >【第1173日投资记录：稍微回血，伊利业绩大放异彩，基本确定把蒙牛卖飞了……-哔哩哔哩】
                https://b23.tv/2cvz6sn</span
              >
            </div>
          </template>

          <template v-else>
            <label for="audio-file">音频文件（必需包含 BV 号）</label>
            <div class="upload-row">
              <input
                id="audio-file"
                ref="uploadFileInput"
                type="file"
                :accept="uploadAccept"
                @change="onUploadFileChange"
              />
            </div>
            <p class="input-example">
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
              <p class="process-summary-kicker">Summary Config</p>
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
                  不阻塞总结文件展示；总结可下载后，Fancy HTML
                  会在后台补生成并自动出现在文件列表中。
                </p>
              </div>

              <div class="summary-preset process-summary-field">
                <label for="summary-profile-select">模型配置</label>
                <select
                  id="summary-profile-select"
                  :value="selectedSummaryProfile"
                  class="preset-select process-preset-select"
                  :disabled="
                    isLoadingSummaryProfiles || summaryProfiles.length === 0
                  "
                  @change="
                    emit('update:selectedSummaryProfile', $event.target.value)
                  "
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
                    {{ profile.name }} ({{ profile.model }})
                  </option>
                </select>
                <p
                  v-if="summaryProfileError"
                  class="preset-hint preset-hint-error"
                >
                  {{ summaryProfileError }}
                  <button
                    class="preset-retry"
                    type="button"
                    @click="emit('loadSummaryProfiles')"
                  >
                    重试
                  </button>
                </p>
                <p v-else-if="summaryProfiles.length === 0" class="preset-hint">
                  暂未连接到后端模型配置接口，提交时会使用服务端默认模型。
                </p>
              </div>

              <div class="summary-preset process-summary-field">
                <label for="summary-preset-select">总结模板</label>
                <select
                  id="summary-preset-select"
                  :value="selectedSummaryPreset"
                  class="preset-select process-preset-select"
                  :disabled="
                    isLoadingSummaryPresets || presetOptions.length === 0
                  "
                  @change="
                    emit('update:selectedSummaryPreset', $event.target.value)
                  "
                >
                  <option v-if="isLoadingSummaryPresets" value="">
                    正在加载模板...
                  </option>
                  <option v-else-if="presetOptions.length === 0" value="">
                    未获取到模板（将使用后端默认）
                  </option>
                  <option
                    v-for="preset in presetOptions"
                    :key="preset.name"
                    :value="preset.name"
                  >
                    {{ preset.label }}
                  </option>
                </select>
                <p
                  v-if="summaryPresetError"
                  class="preset-hint preset-hint-error"
                >
                  {{ summaryPresetError }}
                  <button
                    class="preset-retry"
                    type="button"
                    @click="emit('loadSummaryPresets')"
                  >
                    重试
                  </button>
                </p>
                <p v-else-if="presetOptions.length === 0" class="preset-hint">
                  暂未连接到后端模板接口，提交时会使用服务端默认模板。
                </p>
                <p
                  v-else-if="
                    isOpenPublic &&
                    selectedSummaryPreset === CUSTOM_SUMMARY_PRESET_VALUE
                  "
                  class="preset-hint"
                >
                  当前将使用你在 API Key 页面保存的自定义模板。
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
                <strong>BV 号:</strong> {{ job.bvid }}
              </span>
              <span v-if="job.author" class="metadata-item">
                <strong>UP主:</strong> {{ job.author }}
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
              :summary-presets="summaryPresets"
              :summary-default-preset="summaryDefaultPreset"
              :selected-summary-preset="selectedSummaryPreset"
              :summary-profiles="summaryProfiles"
              :selected-summary-profile="selectedSummaryProfile"
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
    z-index: 2;
    max-width: 1160px;
    margin: 0 auto;
    display: grid;
    grid-template-columns: minmax(0, 1.12fr) minmax(0, 0.88fr);
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
    padding: 40px;
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
    margin: 18px 0 10px;
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

  /* ─── Badge ──────────────────────────────────────────────────── */

  .badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    border-radius: 999px;
    border: 1px solid rgba(167, 243, 208, 0.6);
    background: linear-gradient(
      140deg,
      rgba(240, 253, 250, 0.8),
      rgba(236, 254, 255, 0.8)
    );
    backdrop-filter: blur(8px);
    color: #0f766e;
    font-size: 0.76rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.12em;
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

  .process-summary-kicker {
    margin: 0;
    font-size: 0.78rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    color: #0284c7;
    text-transform: uppercase;
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

  .process-summary-toggle {
    grid-column: 1 / -1;
  }

  .process-summary-field label {
    font-size: 0.88rem;
    font-weight: 700;
    color: #334155;
  }

  .process-preset-select {
    min-height: 50px;
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

    .log-view {
      height: 240px;
      padding: 14px;
    }
  }
</style>
