<script setup>
  import { nextTick, ref, watch } from 'vue'
  import { CheckCircle2, LoaderCircle } from 'lucide-vue-next'
  import FileList from '../FileList.vue'
  import InlineNotice from '../common/InlineNotice.vue'

  const props = defineProps({
    job: { type: Object, required: true },
    isDone: Boolean,
    isFancyHtmlPending: Boolean,
    downloadRows: { type: Array, default: () => [] }
  })

  const logsViewport = ref(null)
  watch(
    () => props.job.logs?.length || 0,
    () => {
      void nextTick(() => {
        if (logsViewport.value) {
          logsViewport.value.scrollTop = logsViewport.value.scrollHeight
        }
      })
    }
  )
</script>

<template>
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
            <span v-if="job.bvid"
              ><strong>资源 ID:</strong> {{ job.bvid }}</span
            >
            <span v-if="job.author"
              ><strong>UP主 / 主播:</strong> {{ job.author }}</span
            >
            <span v-if="job.pubdate"
              ><strong>发布时间:</strong> {{ job.pubdate }}</span
            >
          </div>
        </div>
        <template v-if="isDone">
          <p v-if="isFancyHtmlPending" class="cache-hit-note">
            <LoaderCircle :size="16" class="spin" />
            <span>Fancy HTML 正在后台生成，稍后会自动加入文件列表。</span>
          </p>
          <InlineNotice
            v-else-if="
              job.auto_generate_fancy_html &&
              job.fancy_html_status === 'failed' &&
              job.fancy_html_error
            "
          >
            Fancy HTML 自动生成失败：{{ job.fancy_html_error }}
          </InlineNotice>
          <FileList
            :items="downloadRows"
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
      <header class="log-header"><h2>执行日志</h2></header>
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
</template>

<style scoped>
  .download-layout,
  .log-layout {
    max-width: 1220px;
    margin: 16px auto 0;
  }

  .panel-download,
  .panel-log {
    padding: 22px;
  }

  .download-card {
    min-height: 46px;
  }

  .cache-hit-note {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin: 0 0 12px;
    color: #065f46;
    font-size: 0.9rem;
    font-weight: 600;
  }

  .video-metadata {
    margin-bottom: 14px;
  }

  .video-metadata h3 {
    margin: 0 0 8px;
    font-size: 0.95rem;
  }

  .metadata-items {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 18px;
    color: var(--text-soft);
    font-size: 0.84rem;
  }

  .download-placeholder,
  .log-empty {
    margin: 0;
    color: var(--text-muted);
  }

  .log-header h2 {
    margin: 0;
    font-size: 1.15rem;
  }

  .log-view {
    height: 280px;
    margin-top: 18px;
    overflow: auto;
    padding: 16px 18px;
    border: 1px solid rgba(100, 116, 139, 0.25);
    border-radius: 6px;
    background: #111820;
    font-family: 'SFMono-Regular', Menlo, Monaco, Consolas, monospace;
  }

  .log-line {
    margin: 0 0 8px;
    color: #cbd5df;
    font-size: 0.84rem;
    line-height: 1.55;
    white-space: pre-wrap;
    word-break: break-word;
  }

  @media (max-width: 640px) {
    .panel-download,
    .panel-log {
      padding: 20px;
    }

    .log-view {
      height: 240px;
      padding: 14px;
    }
  }
</style>
