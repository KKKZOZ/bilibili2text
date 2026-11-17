<script setup>
  import { computed, onBeforeUnmount, ref, watch } from 'vue'
  import { AlertCircle, Ban, CheckCircle2, LoaderCircle } from 'lucide-vue-next'

  const STAGES = [
    { key: 'queued', label: '任务创建' },
    { key: 'downloading', label: '获取字幕/音频' },
    { key: 'transcribing', label: '转录/整理文本' },
    { key: 'converting', label: '生成 Markdown' },
    { key: 'summarizing', label: 'LLM 整理总结' },
    { key: 'postprocessing', label: '后处理及文件导出' },
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
  const isCancelled = computed(() => props.job.status === 'cancelled')
  const progressText = computed(() => `${props.job.progress}%`)
  const activeStageElapsedTick = ref(0)
  let activeStageTimer = null

  const jobStatusText = computed(() => {
    if (props.job.status === 'succeeded') {
      return '已完成'
    }
    if (props.job.status === 'failed') {
      return '失败'
    }
    if (props.job.status === 'cancelled') {
      return '已取消'
    }
    if (props.job.status === 'running' || props.job.status === 'queued') {
      return '进行中'
    }
    return '等待中'
  })

  const activeStageIndex = computed(() =>
    STAGES.findIndex((stage) => stage.key === props.job.stage)
  )

  const activeStageDurationLabel = computed(() => {
    if (!props.job.stage_durations || !props.job.stage) {
      return ''
    }
    const label = props.job.stage_durations[props.job.stage]
    return typeof label === 'string' ? label : ''
  })

  const parseDurationLabel = (label) => {
    if (typeof label !== 'string') {
      return null
    }
    const parts = label.split(':').map((part) => Number.parseInt(part, 10))
    if (
      parts.length < 2 ||
      parts.length > 3 ||
      parts.some((part) => Number.isNaN(part))
    ) {
      return null
    }

    const [hours, minutes, seconds] =
      parts.length === 3 ? parts : [0, parts[0], parts[1]]
    return hours * 3600 + minutes * 60 + seconds
  }

  const formatElapsed = (seconds) => {
    const normalizedSeconds = Math.max(0, Number.parseInt(seconds, 10) || 0)
    const hours = Math.floor(normalizedSeconds / 3600)
    const minutes = Math.floor((normalizedSeconds % 3600) / 60)
    const secs = normalizedSeconds % 60
    if (hours > 0) {
      return [hours, minutes, secs]
        .map((part) => String(part).padStart(2, '0'))
        .join(':')
    }
    return [minutes, secs]
      .map((part) => String(part).padStart(2, '0'))
      .join(':')
  }

  const shouldTickActiveStage = computed(
    () =>
      isRunning.value &&
      props.job.stage &&
      !(props.skipSummary && props.job.stage === 'summarizing') &&
      parseDurationLabel(activeStageDurationLabel.value) !== null
  )

  const stopActiveStageTimer = () => {
    if (activeStageTimer !== null) {
      clearInterval(activeStageTimer)
      activeStageTimer = null
    }
  }

  const syncActiveStageTimer = () => {
    stopActiveStageTimer()
    activeStageElapsedTick.value = 0
    if (!shouldTickActiveStage.value) {
      return
    }
    activeStageTimer = setInterval(() => {
      activeStageElapsedTick.value += 1
    }, 1000)
  }

  watch(
    () => [
      props.job.stage,
      props.job.status,
      activeStageDurationLabel.value,
      props.skipSummary
    ],
    syncActiveStageTimer,
    { immediate: true }
  )

  onBeforeUnmount(stopActiveStageTimer)

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
    if (isCancelled.value && index === current) {
      return 'cancelled'
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

  const stageLabel = (stage) => {
    if (stage.key === 'downloading' && props.job.subtitle_source) {
      const labels = {
        bilibili_subtitle: '已使用 B 站字幕',
        youtube_subtitle: '已使用 YouTube 人工字幕',
        youtube_auto_subtitle: '已使用 YouTube 自动字幕'
      }
      const label = labels[props.job.subtitle_source] || '已使用平台字幕'
      return props.job.subtitle_language
        ? `${label} · ${props.job.subtitle_language}`
        : label
    }
    if (stage.key === 'downloading' && props.job.used_bilibili_subtitle) {
      return '已使用 B 站字幕'
    }
    return stage.label
  }

  const stageDurationLabel = (stageKey) => {
    const label =
      props.job.stage_durations &&
      typeof props.job.stage_durations[stageKey] === 'string'
        ? props.job.stage_durations[stageKey]
        : '--'

    if (stageKey !== props.job.stage || !shouldTickActiveStage.value) {
      return label
    }

    const baseSeconds = parseDurationLabel(label)
    if (baseSeconds === null) {
      return label
    }
    return formatElapsed(baseSeconds + activeStageElapsedTick.value)
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
      <div
        class="progress-bar"
        :class="{ halted: hasFailed || isCancelled }"
        role="progressbar"
        aria-label="任务进度"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-valuenow="Number(job.progress) || 0"
      >
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
        <span class="stage-name">{{ stageLabel(stage) }}</span>
        <span class="stage-duration">{{ stageDurationLabel(stage.key) }}</span>
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
        <template v-else-if="stageStatus(stage.key) === 'cancelled'">
          <Ban :size="14" aria-hidden="true" />
          <span class="sr-only">已取消</span>
        </template>
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
    align-self: start;
    padding: 22px;
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
    border-radius: var(--radius-pill);
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.02em;
    border: 1px solid var(--line-strong);
    color: var(--text-soft);
    background: var(--surface-subtle);
  }

  .progress-state.state-running,
  .progress-state.state-queued {
    border-color: var(--info-line);
    color: var(--info-strong);
    background: var(--info-soft);
  }

  .progress-state.state-succeeded {
    border-color: var(--success-line);
    color: var(--success-strong);
    background: var(--success-soft);
  }

  .progress-state.state-cancelled {
    border-color: var(--warning-line);
    color: var(--warning-strong);
    background: var(--warning-soft);
  }

  .progress-state.state-failed {
    border-color: var(--danger-line);
    color: var(--danger-strong);
    background: var(--danger-soft);
  }

  /* ─── Progress bar ───────────────────────────────────────────── */

  .progress-wrap {
    margin-top: 16px;
    display: grid;
    gap: 8px;
  }

  .progress-bar {
    height: 7px;
    width: 100%;
    border-radius: var(--radius-pill);
    background: var(--line);
    overflow: hidden;
  }

  .progress-bar span {
    display: block;
    height: 100%;
    width: 0;
    border-radius: var(--radius-pill);
    background: var(--brand);
    transition: width 0.35s ease;
  }

  .progress-bar.halted span {
    background: var(--text-faint);
  }

  .progress-wrap strong {
    color: var(--brand-strong);
    font-size: 0.92rem;
  }

  /* ─── Stage list ─────────────────────────────────────────────── */

  .stage-list {
    margin: 16px 0 0;
    padding: 0;
    list-style: none;
    display: grid;
    gap: 0;
  }

  .stage-list li {
    min-height: 44px;
    padding: 9px 4px;
    border: 0;
    border-bottom: 1px solid var(--line-soft);
    border-radius: 0;
    display: grid;
    grid-template-columns: auto 1fr auto auto;
    gap: 10px;
    align-items: center;
    color: var(--text-soft);
    background: transparent;
    transition:
      border-color 0.2s ease,
      background-color 0.2s ease;
  }

  .dot {
    width: 8px;
    height: 8px;
    border-radius: var(--radius-pill);
    background: var(--line-strong);
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
    color: var(--text-faint);
  }

  .stage-list .stage-done {
    color: var(--success-strong);
    background: transparent;
  }

  .stage-list .stage-done .dot {
    background: var(--success-dot);
  }

  .stage-list .stage-done svg {
    color: var(--success-dot);
  }

  .stage-list .stage-active {
    color: var(--brand-strong);
    background: var(--brand-soft);
  }

  .stage-list .stage-active .dot {
    background: var(--brand);
  }

  .stage-list .stage-active svg {
    color: var(--brand);
  }

  .stage-list .stage-error {
    color: var(--danger-strong);
    background: var(--danger-soft);
  }

  .stage-list .stage-error .dot {
    background: var(--danger);
  }

  .stage-list .stage-error svg {
    color: var(--danger);
  }

  .stage-list .stage-cancelled {
    color: var(--warning-strong);
    background: var(--warning-soft);
  }

  .stage-list .stage-cancelled .dot {
    background: var(--warning-dot);
  }

  .stage-list .stage-cancelled svg {
    color: var(--warning);
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
    .panel-progress {
      padding: 18px;
    }

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
