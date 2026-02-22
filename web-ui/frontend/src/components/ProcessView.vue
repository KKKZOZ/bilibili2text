<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import {
  AlertCircle,
  CheckCircle2,
  Link2,
  LoaderCircle,
  Sparkles,
} from 'lucide-vue-next';
import ProgressPanel from './ProgressPanel.vue';
import FileList from './FileList.vue';
import { buildArtifactDisplayName, inferSummaryPresetFromFilename } from '../utils/fileUtils';

const props = defineProps({
  summaryPresets: {
    type: Array,
    required: true,
  },
  summaryDefaultPreset: {
    type: String,
    required: true,
  },
  selectedSummaryPreset: {
    type: String,
    required: true,
  },
  summaryProfiles: {
    type: Array,
    required: true,
  },
  selectedSummaryProfile: {
    type: String,
    required: true,
  },
  summaryPresetError: {
    type: String,
    default: '',
  },
  summaryProfileError: {
    type: String,
    default: '',
  },
  isLoadingSummaryPresets: {
    type: Boolean,
    default: false,
  },
  isLoadingSummaryProfiles: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits([
  'update:selectedSummaryPreset',
  'update:selectedSummaryProfile',
  'loadSummaryPresets',
  'loadSummaryProfiles',
]);

const url = ref('');
const error = ref('');
const enableSummary = ref(true);
const currentSkipSummary = ref(false);
const isStarting = ref(false);
const isPolling = ref(false);
const pollErrorCount = ref(0);
const jobId = ref('');
const logsViewport = ref(null);
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
});

let pollTimer = null;
const maxPollErrors = 3;
const ACTIVE_JOB_STORAGE_KEY = 'b2t.active-job-id';

const readPersistedJobId = () => {
  if (typeof window === 'undefined') {
    return '';
  }

  try {
    return window.localStorage.getItem(ACTIVE_JOB_STORAGE_KEY)?.trim() || '';
  } catch {
    return '';
  }
};

const persistActiveJobId = (id) => {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    if (!id) {
      window.localStorage.removeItem(ACTIVE_JOB_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(ACTIVE_JOB_STORAGE_KEY, id);
  } catch {
    // ignore storage errors (private mode / quota / permission)
  }
};

const setActiveJobId = (id) => {
  jobId.value = id;
  persistActiveJobId(id);
};

const clearActiveJobId = () => {
  setActiveJobId('');
};

const parseJsonSafely = async (resp, fallbackMessage) => {
  const raw = await resp.text();
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error(`${fallbackMessage}（服务返回了非 JSON 响应，HTTP ${resp.status}）`);
  }
};

const pickApiError = (resp, data, fallbackMessage) => {
  if (
    data &&
    typeof data === 'object' &&
    typeof data.detail === 'string' &&
    data.detail.trim()
  ) {
    return data.detail;
  }
  return `${fallbackMessage}（HTTP ${resp.status}）`;
};

const isRunning = computed(
  () => job.value.status === 'queued' || job.value.status === 'running'
);
const isDone = computed(() => job.value.status === 'succeeded');
const shouldSkipSummary = computed(() => {
  if (job.value.status === 'idle') {
    return !enableSummary.value;
  }
  return currentSkipSummary.value;
});

const allDownloadRows = computed(() => {
  const downloads = Array.isArray(job.value.all_downloads)
    ? job.value.all_downloads
    : [];
  return downloads.map((item) => ({
    kind: item.kind,
    key: `${item.url}-${item.filename}`,
    url: item.url,
    filename: item.filename,
    presetName:
      job.value.summary_preset ||
      inferSummaryPresetFromFilename(item.filename) ||
      props.selectedSummaryPreset,
    summaryProfile: job.value.summary_profile || props.selectedSummaryProfile,
  }));
});

const stopPolling = () => {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
};

const syncLogScroll = () => {
  if (logsViewport.value === null) {
    return;
  }
  logsViewport.value.scrollTop = logsViewport.value.scrollHeight;
};

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
  };
};

const pollStatus = async () => {
  if (!jobId.value || isPolling.value) {
    return;
  }

  isPolling.value = true;
  try {
    const resp = await fetch(`/api/process/${jobId.value}`);
    const data = await parseJsonSafely(resp, '获取任务进度失败');

    if (!resp.ok) {
      if (resp.status === 404) {
        clearActiveJobId();
        stopPolling();
      }
      throw new Error(pickApiError(resp, data, '获取任务进度失败'));
    }
    if (!data || typeof data !== 'object') {
      throw new Error('获取任务进度失败（服务返回空响应）');
    }

    const previousLogCount = Array.isArray(job.value.logs) ? job.value.logs.length : 0;
    job.value = data;
    currentSkipSummary.value = Boolean(data.skip_summary);
    pollErrorCount.value = 0;
    error.value = '';
    const currentLogCount = Array.isArray(data.logs) ? data.logs.length : 0;
    if (currentLogCount !== previousLogCount) {
      nextTick(syncLogScroll);
    }

    if (data.status === 'failed') {
      error.value = data.error || '处理失败';
      clearActiveJobId();
      stopPolling();
    } else if (data.status === 'succeeded') {
      clearActiveJobId();
      stopPolling();
    }
  } catch (err) {
    pollErrorCount.value += 1;
    const message = err instanceof Error ? err.message : '获取任务进度失败';
    if (pollErrorCount.value >= maxPollErrors) {
      error.value = message;
      stopPolling();
    } else {
      error.value = `${message}，正在重试（${pollErrorCount.value}/${maxPollErrors}）`;
    }
  } finally {
    isPolling.value = false;
  }
};

const submit = async () => {
  if (!url.value.trim()) {
    error.value = '请输入 bilibili 视频 URL';
    return;
  }

  isStarting.value = true;
  error.value = '';
  stopPolling();
  clearActiveJobId();
  resetJob();

  try {
    const skipSummary = !enableSummary.value;
    currentSkipSummary.value = skipSummary;
    pollErrorCount.value = 0;

    const resp = await fetch('/api/process', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        url: url.value.trim(),
        skip_summary: skipSummary,
        summary_preset:
          skipSummary || !props.selectedSummaryPreset
            ? null
            : props.selectedSummaryPreset,
        summary_profile:
          skipSummary || !props.selectedSummaryProfile
            ? null
            : props.selectedSummaryProfile,
      }),
    });
    const data = await parseJsonSafely(resp, '提交任务失败');
    if (!resp.ok) {
      throw new Error(pickApiError(resp, data, '提交任务失败'));
    }
    if (
      !data ||
      typeof data !== 'object' ||
      typeof data.job_id !== 'string' ||
      !data.job_id
    ) {
      throw new Error('提交任务失败（服务未返回有效 job_id）');
    }

    setActiveJobId(data.job_id);
    pollTimer = setInterval(pollStatus, 1200);
    await pollStatus();
  } catch (err) {
    error.value = err instanceof Error ? err.message : '提交任务失败';
  } finally {
    isStarting.value = false;
  }
};

onMounted(async () => {
  const persistedJobId = readPersistedJobId();
  if (!persistedJobId) {
    return;
  }

  setActiveJobId(persistedJobId);
  pollErrorCount.value = 0;
  await pollStatus();
  if (jobId.value && (job.value.status === 'queued' || job.value.status === 'running')) {
    pollTimer = setInterval(pollStatus, 1200);
  }
});

onBeforeUnmount(() => {
  stopPolling();
});
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
          <p>输入 B 站视频链接，自动生成转录后的文本内容和大模型总结。</p>
          <div class="hero-meta">
            <span class="hero-pill">
              {{ isRunning ? '处理中' : '准备就绪' }}
            </span>
            <span class="hero-pill hero-pill-soft">
              总结{{ enableSummary ? '已开启' : '已关闭' }}
            </span>
          </div>
        </header>

        <form class="form" @submit.prevent="submit">
          <label for="video-url">视频 URL 或 BV 号</label>
          <div class="input-row">
            <Link2 :size="18" />
            <input
              id="video-url"
              v-model="url"
              type="text"
              placeholder="https://www.bilibili.com/video/BV..."
            />
          </div>
          <p class="input-example">
            示例 URL:
            <a
              href="https://www.bilibili.com/video/BV1R9i4BoE7H"
              target="_blank"
              rel="noopener noreferrer"
            >
              https://www.bilibili.com/video/BV1R9i4BoE7H
            </a>
          </p>

          <label class="switch" for="enable-summary">
            <input id="enable-summary" v-model="enableSummary" type="checkbox" />
            <span class="switch-track">
              <span class="switch-thumb"></span>
            </span>
            <span class="switch-label">启用 LLM 整理总结</span>
          </label>

          <div v-if="enableSummary" class="process-summary-config">
            <div class="process-summary-head">
              <p class="process-summary-kicker">Summary Config</p>
              <h3>总结参数</h3>
              <p>选择模型配置与总结模板，生成更符合用途的总结内容。</p>
            </div>

            <div class="process-summary-grid">
              <div class="summary-preset process-summary-field">
                <label for="summary-profile-select">模型配置</label>
                <select
                  id="summary-profile-select"
                  :value="selectedSummaryProfile"
                  class="preset-select process-preset-select"
                  :disabled="isLoadingSummaryProfiles || summaryProfiles.length === 0"
                  @change="emit('update:selectedSummaryProfile', $event.target.value)"
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
                <p v-if="summaryProfileError" class="preset-hint preset-hint-error">
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
                  :disabled="isLoadingSummaryPresets || summaryPresets.length === 0"
                  @change="emit('update:selectedSummaryPreset', $event.target.value)"
                >
                  <option v-if="isLoadingSummaryPresets" value="">
                    正在加载模板...
                  </option>
                  <option v-else-if="summaryPresets.length === 0" value="">
                    未获取到模板（将使用后端默认）
                  </option>
                  <option
                    v-for="preset in summaryPresets"
                    :key="preset.name"
                    :value="preset.name"
                  >
                    {{ preset.label }}
                  </option>
                </select>
                <p v-if="summaryPresetError" class="preset-hint preset-hint-error">
                  {{ summaryPresetError }}
                  <button
                    class="preset-retry"
                    type="button"
                    @click="emit('loadSummaryPresets')"
                  >
                    重试
                  </button>
                </p>
                <p v-else-if="summaryPresets.length === 0" class="preset-hint">
                  暂未连接到后端模板接口，提交时会使用服务端默认模板。
                </p>
              </div>
            </div>
          </div>

          <button class="submit" type="submit" :disabled="isStarting || isRunning">
            <LoaderCircle v-if="isStarting || isRunning" class="spin" :size="16" />
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
            <span>{{ job.notice || '该视频曾经转录过，已直接返回历史文件。' }}</span>
          </p>

          <div v-if="isDone && (job.author || job.pubdate || job.bvid)" class="video-metadata">
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
            <FileList
              :items="allDownloadRows"
              :summary-presets="summaryPresets"
              :summary-default-preset="summaryDefaultPreset"
              :selected-summary-preset="selectedSummaryPreset"
              :summary-profiles="summaryProfiles"
              :selected-summary-profile="selectedSummaryProfile"
            />
          </template>
          <p v-else class="download-placeholder">任务完成后在这里展示可下载文件。</p>
        </div>
      </article>
    </section>

    <section class="log-layout">
      <article class="panel panel-log">
        <header class="log-header">
          <h2>执行日志</h2>
        </header>

        <div ref="logsViewport" class="log-view">
          <p v-if="!Array.isArray(job.logs) || job.logs.length === 0" class="log-empty">
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
