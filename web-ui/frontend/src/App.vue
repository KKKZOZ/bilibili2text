<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  Link2,
  LoaderCircle,
  Sparkles,
} from "lucide-vue-next";

const STAGES = [
  { key: "queued", label: "任务创建" },
  { key: "downloading", label: "下载视频音频" },
  { key: "transcribing", label: "语音转录" },
  { key: "converting", label: "生成 Markdown" },
  { key: "summarizing", label: "LLM 整理总结" },
  { key: "completed", label: "处理完成" },
];

const url = ref("");
const error = ref("");
const enableSummary = ref(true);
const summaryPresets = ref([]);
const summaryProfiles = ref([]);
const selectedSummaryPreset = ref("");
const selectedSummaryProfile = ref("");
const summaryPresetError = ref("");
const summaryProfileError = ref("");
const isLoadingSummaryPresets = ref(false);
const isLoadingSummaryProfiles = ref(false);
const currentSkipSummary = ref(false);
const isStarting = ref(false);
const isPolling = ref(false);
const jobId = ref("");
const logsViewport = ref(null);
const job = ref({
  status: "idle",
  stage: "queued",
  stage_label: "等待开始",
  progress: 0,
  download_url: "",
  filename: "",
  txt_download_url: "",
  txt_filename: "",
  summary_download_url: "",
  summary_filename: "",
  summary_txt_download_url: "",
  summary_txt_filename: "",
  summary_table_pdf_download_url: "",
  summary_table_pdf_filename: "",
  summary_preset: "",
  summary_profile: "",
  error: "",
  logs: [],
  stage_durations: {},
  created_at: "",
  updated_at: "",
});

let pollTimer = null;

const isRunning = computed(
  () => job.value.status === "queued" || job.value.status === "running",
);
const isDone = computed(() => job.value.status === "succeeded");
const hasFailed = computed(() => job.value.status === "failed");
const progressText = computed(() => `${job.value.progress}%`);
const jobStatusText = computed(() => {
  if (job.value.status === "succeeded") {
    return "已完成";
  }
  if (job.value.status === "failed") {
    return "失败";
  }
  if (job.value.status === "running" || job.value.status === "queued") {
    return "进行中";
  }
  return "等待中";
});
const shouldSkipSummary = computed(() => {
  if (job.value.status === "idle") {
    return !enableSummary.value;
  }
  return currentSkipSummary.value;
});

const activeStageIndex = computed(() =>
  STAGES.findIndex((stage) => stage.key === job.value.stage),
);

const stageStatus = (stageKey) => {
  if (shouldSkipSummary.value && stageKey === "summarizing") {
    return "skipped";
  }

  const index = STAGES.findIndex((stage) => stage.key === stageKey);
  const current = activeStageIndex.value;

  if (current < 0) {
    return "pending";
  }
  if (hasFailed.value && index === current) {
    return "error";
  }
  if (index < current) {
    return "done";
  }
  if (index === current && isRunning.value) {
    return "active";
  }
  if (isDone.value && stageKey === "completed") {
    return "done";
  }
  return "pending";
};

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
    status: "idle",
    stage: "queued",
    stage_label: "等待开始",
    progress: 0,
    download_url: "",
    filename: "",
    txt_download_url: "",
    txt_filename: "",
    summary_download_url: "",
    summary_filename: "",
    summary_txt_download_url: "",
    summary_txt_filename: "",
    summary_table_pdf_download_url: "",
    summary_table_pdf_filename: "",
    summary_preset: "",
    summary_profile: "",
    error: "",
    logs: [],
    stage_durations: {},
    created_at: "",
    updated_at: "",
  };
};

const pollStatus = async () => {
  if (!jobId.value || isPolling.value) {
    return;
  }

  isPolling.value = true;
  try {
    const resp = await fetch(`/api/process/${jobId.value}`);
    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.detail || "获取任务进度失败");
    }

    const previousLogCount = Array.isArray(job.value.logs) ? job.value.logs.length : 0;
    job.value = data;
    const currentLogCount = Array.isArray(data.logs) ? data.logs.length : 0;
    if (currentLogCount !== previousLogCount) {
      nextTick(syncLogScroll);
    }

    if (data.status === "failed") {
      error.value = data.error || "处理失败";
      stopPolling();
    } else if (data.status === "succeeded") {
      stopPolling();
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : "获取任务进度失败";
    stopPolling();
  } finally {
    isPolling.value = false;
  }
};

const loadSummaryPresets = async () => {
  isLoadingSummaryPresets.value = true;
  summaryPresetError.value = "";
  try {
    const resp = await fetch("/api/summary-presets");
    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.detail || "获取总结 presets 失败");
    }

    const presets = Array.isArray(data.presets) ? data.presets : [];
    summaryPresets.value = presets;
    if (presets.length === 0) {
      selectedSummaryPreset.value = "";
      return;
    }

    const fallback = presets[0].name;
    selectedSummaryPreset.value =
      data.selected_preset || data.default_preset || fallback;
  } catch (err) {
    console.error(err);
    summaryPresets.value = [];
    selectedSummaryPreset.value = "";
    summaryPresetError.value =
      err instanceof Error
        ? `preset 加载失败：${err.message}`
        : "preset 加载失败，请检查后端服务是否已启动";
  } finally {
    isLoadingSummaryPresets.value = false;
  }
};

const loadSummaryProfiles = async () => {
  isLoadingSummaryProfiles.value = true;
  summaryProfileError.value = "";
  try {
    const resp = await fetch("/api/summarize-profiles");
    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.detail || "获取总结模型配置失败");
    }

    const profiles = Array.isArray(data.profiles) ? data.profiles : [];
    summaryProfiles.value = profiles;
    if (profiles.length === 0) {
      selectedSummaryProfile.value = "";
      return;
    }

    const fallback = profiles[0].name;
    selectedSummaryProfile.value =
      data.selected_profile || data.default_profile || fallback;
  } catch (err) {
    console.error(err);
    summaryProfiles.value = [];
    selectedSummaryProfile.value = "";
    summaryProfileError.value =
      err instanceof Error
        ? `模型配置加载失败：${err.message}`
        : "模型配置加载失败，请检查后端服务是否已启动";
  } finally {
    isLoadingSummaryProfiles.value = false;
  }
};

const submit = async () => {
  if (!url.value.trim()) {
    error.value = "请输入 bilibili 视频 URL";
    return;
  }

  isStarting.value = true;
  error.value = "";
  stopPolling();
  resetJob();

  try {
    const skipSummary = !enableSummary.value;
    currentSkipSummary.value = skipSummary;

    const resp = await fetch("/api/process", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
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
      }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.detail || "提交任务失败");
    }

    jobId.value = data.job_id;
    pollTimer = setInterval(pollStatus, 1200);
    await pollStatus();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "提交任务失败";
  } finally {
    isStarting.value = false;
  }
};

const download = (url, filename) => {
  if (!url) {
    return;
  }

  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename || "output.md";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
};

onBeforeUnmount(() => {
  stopPolling();
});

onMounted(() => {
  void Promise.all([loadSummaryProfiles(), loadSummaryPresets()]);
});
</script>

<template>
  <main class="shell">
    <div class="ambient ambient-left"></div>
    <div class="ambient ambient-right"></div>

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
              {{ isRunning ? "处理中" : "准备就绪" }}
            </span>
            <span class="hero-pill hero-pill-soft">
              总结{{ enableSummary ? "已开启" : "已关闭" }}
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

          <div v-if="enableSummary" class="summary-preset">
            <label for="summary-profile-select">总结模型配置</label>
            <select
              id="summary-profile-select"
              v-model="selectedSummaryProfile"
              class="preset-select"
              :disabled="isLoadingSummaryProfiles || summaryProfiles.length === 0"
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
                @click="loadSummaryProfiles"
              >
                重试
              </button>
            </p>
            <p
              v-else-if="summaryProfiles.length === 0"
              class="preset-hint"
            >
              暂未连接到后端模型配置接口，提交时会使用服务端默认模型。
            </p>
          </div>

          <div v-if="enableSummary" class="summary-preset">
            <label for="summary-preset-select">总结 preset</label>
            <select
              id="summary-preset-select"
              v-model="selectedSummaryPreset"
              class="preset-select"
              :disabled="isLoadingSummaryPresets || summaryPresets.length === 0"
            >
              <option v-if="isLoadingSummaryPresets" value="">
                正在加载 preset...
              </option>
              <option v-else-if="summaryPresets.length === 0" value="">
                未获取到 preset（将使用后端默认）
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
                @click="loadSummaryPresets"
              >
                重试
              </button>
            </p>
            <p
              v-else-if="summaryPresets.length === 0"
              class="preset-hint"
            >
              暂未连接到后端 preset 接口，提交时会使用服务端默认 preset。
            </p>
          </div>

          <button class="submit" type="submit" :disabled="isStarting || isRunning">
            <LoaderCircle v-if="isStarting || isRunning" class="spin" :size="16" />
            <span>
              {{ isStarting || isRunning ? "处理中..." : "开始处理" }}
            </span>
          </button>
        </form>

        <p v-if="error" class="inline-error">
          <AlertCircle :size="16" />
          <span>{{ error }}</span>
        </p>

        <div v-if="isDone" class="download-card">
          <div class="download-actions">
            <button
              class="download"
              type="button"
              @click="download(job.download_url, job.filename)"
            >
              <Download :size="16" />
              <span>下载原文 Markdown</span>
            </button>
            <button
              v-if="job.txt_download_url"
              class="download"
              type="button"
              @click="download(job.txt_download_url, job.txt_filename || 'output.txt')"
            >
              <Download :size="16" />
              <span>下载原文 TXT</span>
            </button>
            <button
              v-if="job.summary_download_url"
              class="download download-secondary"
              type="button"
              @click="
                download(job.summary_download_url, job.summary_filename || 'summary.md')
              "
            >
              <Download :size="16" />
              <span>下载总结 Markdown</span>
            </button>
            <button
              v-if="job.summary_txt_download_url"
              class="download download-secondary"
              type="button"
              @click="
                download(
                  job.summary_txt_download_url,
                  job.summary_txt_filename || 'summary.txt',
                )
              "
            >
              <Download :size="16" />
              <span>下载总结 TXT</span>
            </button>
            <button
              v-if="job.summary_table_pdf_download_url"
              class="download download-secondary"
              type="button"
              @click="
                download(
                  job.summary_table_pdf_download_url,
                  job.summary_table_pdf_filename || 'summary_table.pdf',
                )
              "
            >
              <Download :size="16" />
              <span>下载总结表格 PDF</span>
            </button>
          </div>
        </div>
      </article>

      <article class="panel panel-progress">
        <header class="progress-header">
          <div>
            <h2>任务进度</h2>
            <p>{{ job.stage_label }}</p>
          </div>
          <span class="progress-state" :class="`state-${job.status}`">
            {{ jobStatusText }}
          </span>
        </header>

        <div class="progress-wrap">
          <div class="progress-bar">
            <span :style="{ width: progressText }"></span>
          </div>
          <strong>{{ progressText }}</strong>
        </div>

        <ul class="stage-list">
          <li
            v-for="stage in STAGES"
            :key="stage.key"
            :class="`stage-${stageStatus(stage.key)}`"
          >
            <span class="dot"></span>
            <span class="stage-name">{{ stage.label }}</span>
            <span class="stage-duration">
              {{
                job.stage_durations &&
                typeof job.stage_durations[stage.key] === "string"
                  ? job.stage_durations[stage.key]
                  : "--"
              }}
            </span>
            <LoaderCircle
              v-if="stageStatus(stage.key) === 'active'"
              :size="14"
              class="spin"
            />
            <CheckCircle2
              v-else-if="stageStatus(stage.key) === 'done'"
              :size="14"
            />
            <AlertCircle
              v-else-if="stageStatus(stage.key) === 'error'"
              :size="14"
            />
            <span v-else-if="stageStatus(stage.key) === 'skipped'" class="meta-tag">
              跳过
            </span>
          </li>
        </ul>
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
  </main>
</template>
