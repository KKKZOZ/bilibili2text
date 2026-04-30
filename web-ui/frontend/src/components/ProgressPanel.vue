<script setup>
  import { computed } from 'vue'
  import { CheckCircle2, AlertCircle, LoaderCircle } from 'lucide-vue-next'

  const STAGES = [
    { key: 'queued', label: '任务创建' },
    { key: 'downloading', label: '下载视频音频' },
    { key: 'transcribing', label: '语音转录' },
    { key: 'converting', label: '生成 Markdown' },
    { key: 'summarizing', label: 'LLM 整理总结' },
    { key: 'completed', label: '处理完成' }
  ]

  const props = defineProps({
    job: {
      type: Object,
      required: true
    },
    skipSummary: {
      type: Boolean,
      default: false
    }
  })

  const isRunning = computed(
    () => props.job.status === 'queued' || props.job.status === 'running'
  )
  const isDone = computed(() => props.job.status === 'succeeded')
  const hasFailed = computed(() => props.job.status === 'failed')
  const progressText = computed(() => `${props.job.progress}%`)

  const jobStatusText = computed(() => {
    if (props.job.status === 'succeeded') {
      return '已完成'
    }
    if (props.job.status === 'failed') {
      return '失败'
    }
    if (props.job.status === 'running' || props.job.status === 'queued') {
      return '进行中'
    }
    return '等待中'
  })

  const activeStageIndex = computed(() =>
    STAGES.findIndex((stage) => stage.key === props.job.stage)
  )

  const stageStatus = (stageKey) => {
    if (props.skipSummary && stageKey === 'summarizing') {
      return 'skipped'
    }

    const index = STAGES.findIndex((stage) => stage.key === stageKey)
    const current = activeStageIndex.value

    if (current < 0) {
      return 'pending'
    }
    if (hasFailed.value && index === current) {
      return 'error'
    }
    if (index < current) {
      return 'done'
    }
    if (index === current && isRunning.value) {
      return 'active'
    }
    if (isDone.value && stageKey === 'completed') {
      return 'done'
    }
    return 'pending'
  }
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
            job.stage_durations &&
            typeof job.stage_durations[stage.key] === 'string'
              ? job.stage_durations[stage.key]
              : '--'
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
</template>

<style scoped>
  /* ─── Panel variant ──────────────────────────────────────────── */

  .panel-progress {
    padding: 24px;
    animation-delay: 0.08s;
  }

  /* ─── Progress header ────────────────────────────────────────── */

  .progress-header {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    align-items: flex-start;
  }

  .progress-header h2 {
    margin: 0;
    font-size: 1.07rem;
  }

  .progress-header p {
    margin: 6px 0 0;
    color: var(--text-soft);
    min-height: 1.4em;
  }

  /* ─── State badge ────────────────────────────────────────────── */

  .progress-state {
    margin-top: 1px;
    display: inline-flex;
    align-items: center;
    min-height: 25px;
    padding: 0 10px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.02em;
    border: 1px solid #cbd5e1;
    color: #334155;
    background: #f8fafc;
  }

  .progress-state.state-running,
  .progress-state.state-queued {
    border-color: #67e8f9;
    color: #155e75;
    background: #ecfeff;
  }

  .progress-state.state-succeeded {
    border-color: #86efac;
    color: #166534;
    background: #f0fdf4;
  }

  .progress-state.state-failed {
    border-color: #fecaca;
    color: #991b1b;
    background: #fef2f2;
  }

  /* ─── Progress bar ───────────────────────────────────────────── */

  .progress-wrap {
    margin-top: 16px;
    display: grid;
    gap: 8px;
  }

  .progress-bar {
    height: 12px;
    width: 100%;
    border-radius: 999px;
    background: #dbe4ef;
    overflow: hidden;
  }

  .progress-bar span {
    display: block;
    height: 100%;
    width: 0;
    border-radius: 999px;
    background: linear-gradient(90deg, #0d9488, #06b6d4);
    transition: width 0.35s ease;
  }

  .progress-wrap strong {
    color: #0f766e;
    font-size: 0.92rem;
  }

  /* ─── Stage list ─────────────────────────────────────────────── */

  .stage-list {
    margin: 18px 0 0;
    padding: 0;
    list-style: none;
    display: grid;
    gap: 9px;
  }

  .stage-list li {
    border: 1px solid rgba(148, 163, 184, 0.34);
    border-radius: 12px;
    padding: 10px 12px;
    display: grid;
    grid-template-columns: auto 1fr auto auto;
    gap: 10px;
    align-items: center;
    color: var(--text-soft);
    background: rgba(255, 255, 255, 0.84);
    transition:
      border-color 0.2s ease,
      background-color 0.2s ease;
  }

  .dot {
    width: 8px;
    height: 8px;
    border-radius: 999px;
    background: #cbd5e1;
  }

  .stage-name {
    font-size: 0.89rem;
  }

  .stage-duration {
    font-size: 0.8rem;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }

  .stage-list li svg {
    color: #94a3b8;
  }

  .stage-list .stage-done {
    border-color: #bbf7d0;
    color: #166534;
    background: #f0fdf4;
  }

  .stage-list .stage-done .dot {
    background: #22c55e;
  }

  .stage-list .stage-done svg {
    color: #22c55e;
  }

  .stage-list .stage-active {
    border-color: #7dd3fc;
    color: #0c4a6e;
    background: #ecfeff;
  }

  .stage-list .stage-active .dot {
    background: #0ea5e9;
  }

  .stage-list .stage-active svg {
    color: #0ea5e9;
  }

  .stage-list .stage-error {
    border-color: #fecaca;
    color: #991b1b;
    background: #fef2f2;
  }

  .stage-list .stage-error .dot {
    background: #ef4444;
  }

  .stage-list .stage-error svg {
    color: #ef4444;
  }

  .stage-list .stage-skipped {
    opacity: 0.62;
  }

  .meta-tag {
    color: var(--text-muted);
    font-size: 0.78rem;
  }

  /* ─── Responsive ─────────────────────────────────────────────── */

  @media (max-width: 980px) {
    .panel-progress {
      padding: 20px;
    }
  }

  @media (max-width: 640px) {
    .progress-header {
      flex-direction: column;
    }

    .stage-list li {
      grid-template-columns: auto 1fr auto;
    }

    .stage-duration {
      grid-column: 2 / 3;
    }
  }
</style>
