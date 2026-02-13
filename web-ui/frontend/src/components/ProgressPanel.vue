<script setup>
import { computed } from 'vue';
import { CheckCircle2, AlertCircle, LoaderCircle } from 'lucide-vue-next';

const STAGES = [
  { key: 'queued', label: '任务创建' },
  { key: 'downloading', label: '下载视频音频' },
  { key: 'transcribing', label: '语音转录' },
  { key: 'converting', label: '生成 Markdown' },
  { key: 'summarizing', label: 'LLM 整理总结' },
  { key: 'completed', label: '处理完成' },
];

const props = defineProps({
  job: {
    type: Object,
    required: true,
  },
  skipSummary: {
    type: Boolean,
    default: false,
  },
});

const isRunning = computed(
  () => props.job.status === 'queued' || props.job.status === 'running'
);
const isDone = computed(() => props.job.status === 'succeeded');
const hasFailed = computed(() => props.job.status === 'failed');
const progressText = computed(() => `${props.job.progress}%`);

const jobStatusText = computed(() => {
  if (props.job.status === 'succeeded') {
    return '已完成';
  }
  if (props.job.status === 'failed') {
    return '失败';
  }
  if (props.job.status === 'running' || props.job.status === 'queued') {
    return '进行中';
  }
  return '等待中';
});

const activeStageIndex = computed(() =>
  STAGES.findIndex((stage) => stage.key === props.job.stage)
);

const stageStatus = (stageKey) => {
  if (props.skipSummary && stageKey === 'summarizing') {
    return 'skipped';
  }

  const index = STAGES.findIndex((stage) => stage.key === stageKey);
  const current = activeStageIndex.value;

  if (current < 0) {
    return 'pending';
  }
  if (hasFailed.value && index === current) {
    return 'error';
  }
  if (index < current) {
    return 'done';
  }
  if (index === current && isRunning.value) {
    return 'active';
  }
  if (isDone.value && stageKey === 'completed') {
    return 'done';
  }
  return 'pending';
};
</script>

<template>
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
            job.stage_durations && typeof job.stage_durations[stage.key] === 'string'
              ? job.stage_durations[stage.key]
              : '--'
          }}
        </span>
        <LoaderCircle
          v-if="stageStatus(stage.key) === 'active'"
          :size="14"
          class="spin"
        />
        <CheckCircle2 v-else-if="stageStatus(stage.key) === 'done'" :size="14" />
        <AlertCircle v-else-if="stageStatus(stage.key) === 'error'" :size="14" />
        <span v-else-if="stageStatus(stage.key) === 'skipped'" class="meta-tag">
          跳过
        </span>
      </li>
    </ul>
  </article>
</template>
