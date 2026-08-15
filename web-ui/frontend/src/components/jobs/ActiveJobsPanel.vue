<script setup>
  import { LoaderCircle, User, XCircle } from 'lucide-vue-next'
  import InlineNotice from '../common/InlineNotice.vue'

  defineProps({
    jobs: { type: Array, default: () => [] },
    connectionNotice: { type: String, default: '' }
  })

  const emit = defineEmits(['cancel', 'open'])
</script>

<template>
  <InlineNotice v-if="connectionNotice && jobs.length" kind="warning" compact>
    {{ connectionNotice }}
  </InlineNotice>
  <div v-if="jobs.length" class="active-jobs-section">
    <h3><LoaderCircle :size="14" class="spin" />进行中的任务</h3>
    <div
      v-for="job in jobs"
      :key="job.job_id"
      class="active-job-card"
      role="button"
      tabindex="0"
      @click="emit('open', job.job_id)"
      @keydown.enter="emit('open', job.job_id)"
    >
      <div class="active-job-info">
        <p class="active-job-title">
          {{ job.title || job.bvid || '转录中...' }}
        </p>
        <div class="active-job-meta">
          <span v-if="job.bvid && job.title">{{ job.bvid }}</span>
          <span v-if="job.author"><User :size="11" />{{ job.author }}</span>
        </div>
        <p class="active-job-stage">{{ job.stage_label }}</p>
        <div class="active-job-progress">
          <div :style="{ width: `${job.progress}%` }"></div>
        </div>
      </div>
      <button
        type="button"
        class="active-job-cancel"
        title="取消任务"
        aria-label="取消任务"
        @click.stop="emit('cancel', job.job_id)"
      >
        <XCircle :size="16" />
      </button>
    </div>
  </div>
</template>

<style scoped>
  .active-jobs-section {
    display: grid;
    gap: 8px;
    margin: 12px 0 18px;
  }

  h3 {
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 0 0 4px;
    color: #0284c7;
    font-size: 0.82rem;
    font-weight: 700;
    letter-spacing: 0;
    text-transform: uppercase;
  }

  .active-job-card {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 14px;
    border: 1px solid #bae6fd;
    border-radius: 8px;
    background: linear-gradient(135deg, #f0f9ff, #e0f2fe);
    cursor: pointer;
  }

  .active-job-card:hover,
  .active-job-card:focus-visible {
    border-color: #7dd3fc;
    outline: none;
    box-shadow: 0 2px 8px rgba(14, 165, 233, 0.12);
  }

  .active-job-info {
    display: grid;
    flex: 1;
    gap: 4px;
    min-width: 0;
  }

  .active-job-title,
  .active-job-stage {
    margin: 0;
  }

  .active-job-title {
    overflow: hidden;
    color: #0f172a;
    font-size: 0.92rem;
    font-weight: 700;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .active-job-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    color: #64748b;
    font-size: 0.8rem;
  }

  .active-job-meta span {
    display: inline-flex;
    align-items: center;
    gap: 3px;
  }

  .active-job-stage {
    color: #475569;
    font-size: 0.82rem;
  }

  .active-job-progress {
    height: 4px;
    overflow: hidden;
    border-radius: 999px;
    background: #bae6fd;
  }

  .active-job-progress div {
    height: 100%;
    border-radius: inherit;
    background: linear-gradient(90deg, #0ea5e9, #14b8a6);
    transition: width 0.6s ease;
  }

  .active-job-cancel {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    padding: 0;
    border: none;
    border-radius: 6px;
    background: transparent;
    color: #94a3b8;
    cursor: pointer;
  }

  .active-job-cancel:hover {
    background: #fee2e2;
    color: #dc2626;
  }
</style>
