<script setup>
  import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
  import {
    Check,
    CheckCircle2,
    ChevronsDown,
    Copy,
    LoaderCircle,
    Maximize2,
    Minimize2,
    Pause
  } from 'lucide-vue-next'
  import FileList from '../FileList.vue'
  import InlineNotice from '../common/InlineNotice.vue'

  const props = defineProps({
    job: { type: Object, required: true },
    isDone: Boolean,
    isFancyHtmlPending: Boolean,
    downloadRows: { type: Array, default: () => [] }
  })

  const AUTO_FOLLOW_THRESHOLD = 40
  const LOG_LINE_PATTERN =
    /^(?<time>(?:\d{4}-\d{2}-\d{2}\s+)?\d{2}:\d{2}:\d{2})\s+\[(?<level>[A-Z]+)\]\s+(?<source>[^:]+):\s?(?<message>.*)$/

  const logsViewport = ref(null)
  const followLogs = ref(true)
  const pendingLogCount = ref(0)
  const isLogExpanded = ref(false)
  const copyStatus = ref('idle')
  let copyStatusTimer = null

  const rawLogs = computed(() =>
    Array.isArray(props.job.logs) ? props.job.logs : []
  )
  const parsedLogs = computed(() =>
    rawLogs.value.map((raw, index) => {
      const line = String(raw || '')
      const match = line.match(LOG_LINE_PATTERN)
      const level = (match?.groups?.level || '').toLowerCase()
      return {
        key: [index, line].join(':'),
        time: match?.groups?.time || '',
        level: level || 'plain',
        levelLabel: match?.groups?.level || '',
        source: match?.groups?.source || '',
        message: match?.groups?.message || line,
        structured: Boolean(match)
      }
    })
  )

  const logsChanged = (current, previous) => {
    if (current.length !== previous.length) return true
    return current.some((line, index) => line !== previous[index])
  }

  const scrollToLatest = (behavior = 'smooth') => {
    followLogs.value = true
    pendingLogCount.value = 0
    void nextTick(() => {
      logsViewport.value?.scrollTo({
        top: logsViewport.value.scrollHeight,
        behavior
      })
    })
  }

  watch(
    rawLogs,
    (current, previous = []) => {
      if (!logsChanged(current, previous)) return
      if (followLogs.value) {
        scrollToLatest('auto')
        return
      }
      pendingLogCount.value +=
        current.length > previous.length ? current.length - previous.length : 1
    },
    { immediate: true }
  )

  const onLogsScroll = () => {
    const viewport = logsViewport.value
    if (!viewport) return
    const distanceFromBottom =
      viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight
    const isNearBottom = distanceFromBottom <= AUTO_FOLLOW_THRESHOLD
    followLogs.value = isNearBottom
    if (isNearBottom) pendingLogCount.value = 0
  }

  const fallbackCopyText = (text) => {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    const copied = document.execCommand('copy')
    textarea.remove()
    if (!copied) throw new Error('复制失败')
  }

  const copyLogs = async () => {
    const text = rawLogs.value.join('\n')
    if (!text) return
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
      } else {
        fallbackCopyText(text)
      }
      copyStatus.value = 'success'
    } catch {
      copyStatus.value = 'error'
    }
    if (copyStatusTimer !== null) window.clearTimeout(copyStatusTimer)
    copyStatusTimer = window.setTimeout(() => {
      copyStatus.value = 'idle'
      copyStatusTimer = null
    }, 1800)
  }

  onBeforeUnmount(() => {
    if (copyStatusTimer !== null) window.clearTimeout(copyStatusTimer)
  })
</script>

<template>
  <section class="download-layout">
    <article class="panel panel-download">
      <div class="download-card">
        <template v-if="isDone">
          <p v-if="job.already_transcribed" class="cache-hit-note">
            <CheckCircle2 :size="16" />
            <span>{{
              job.notice || '该视频曾经转录过，已直接返回历史文件。'
            }}</span>
          </p>
          <div
            v-if="job.author || job.pubdate || job.bvid"
            class="video-metadata"
          >
            <h3>视频信息</h3>
            <div class="metadata-items">
              <span v-if="job.bvid">
                <strong>资源 ID:</strong> {{ job.bvid }}
              </span>
              <span v-if="job.author">
                <strong>UP主 / 主播:</strong> {{ job.author }}
              </span>
              <span v-if="job.pubdate">
                <strong>发布时间:</strong> {{ job.pubdate }}
              </span>
            </div>
          </div>
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
      <header class="log-header">
        <div class="log-heading">
          <h2>执行日志</h2>
          <span class="log-count">{{ rawLogs.length }} 条</span>
        </div>
        <div class="log-toolbar" role="toolbar" aria-label="日志工具">
          <span class="follow-state" :class="{ paused: !followLogs }">
            <span v-if="followLogs" class="live-dot" aria-hidden="true"></span>
            <Pause v-else :size="13" aria-hidden="true" />
            {{ followLogs ? '自动跟随' : '已暂停跟随' }}
          </span>
          <button
            v-if="!followLogs"
            type="button"
            class="log-tool-button log-latest-button"
            :title="
              pendingLogCount > 0
                ? '跳到最新（' + pendingLogCount + ' 条新日志）'
                : '跳到最新'
            "
            :aria-label="
              pendingLogCount > 0
                ? '跳到最新，' + pendingLogCount + ' 条新日志'
                : '跳到最新'
            "
            @click="scrollToLatest()"
          >
            <ChevronsDown :size="16" aria-hidden="true" />
            <span>查看最新</span>
            <span v-if="pendingLogCount > 0" class="new-log-count">
              {{ pendingLogCount > 99 ? '99+' : pendingLogCount }}
            </span>
          </button>
          <button
            type="button"
            class="log-tool-button"
            :class="{
              success: copyStatus === 'success',
              error: copyStatus === 'error'
            }"
            :disabled="rawLogs.length === 0"
            :title="copyStatus === 'success' ? '已复制' : '复制全部日志'"
            :aria-label="
              copyStatus === 'success' ? '日志已复制' : '复制全部日志'
            "
            @click="copyLogs"
          >
            <Check
              v-if="copyStatus === 'success'"
              :size="16"
              aria-hidden="true"
            />
            <Copy v-else :size="16" aria-hidden="true" />
          </button>
          <button
            type="button"
            class="log-tool-button"
            :title="isLogExpanded ? '收起日志' : '展开日志'"
            :aria-label="isLogExpanded ? '收起日志' : '展开日志'"
            :aria-pressed="isLogExpanded"
            @click="isLogExpanded = !isLogExpanded"
          >
            <Minimize2 v-if="isLogExpanded" :size="16" aria-hidden="true" />
            <Maximize2 v-else :size="16" aria-hidden="true" />
          </button>
        </div>
      </header>
      <div
        ref="logsViewport"
        class="log-view"
        :class="{ expanded: isLogExpanded }"
        role="log"
        :aria-live="followLogs ? 'polite' : 'off'"
        aria-label="任务执行日志"
        aria-relevant="additions text"
        aria-atomic="false"
        tabindex="0"
        @scroll.passive="onLogsScroll"
      >
        <p v-if="rawLogs.length === 0" class="log-empty">
          任务开始后会在这里显示日志。
        </p>
        <p
          v-for="entry in parsedLogs"
          :key="entry.key"
          class="log-line"
          :class="['level-' + entry.level, { structured: entry.structured }]"
        >
          <template v-if="entry.structured">
            <time class="log-time">{{ entry.time }}</time>
            <span class="log-level">{{ entry.levelLabel }}</span>
            <span class="log-source" :title="entry.source">
              {{ entry.source }}
            </span>
            <span class="log-message">{{ entry.message }}</span>
          </template>
          <span v-else class="log-message">{{ entry.message }}</span>
        </p>
      </div>
      <p class="sr-only" aria-live="polite">
        {{
          copyStatus === 'success'
            ? '日志已复制'
            : copyStatus === 'error'
              ? '日志复制失败'
              : ''
        }}
      </p>
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

  .log-empty {
    color: #82909f;
  }

  .log-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
  }

  .log-heading,
  .log-toolbar,
  .follow-state {
    display: flex;
    align-items: center;
  }

  .log-heading {
    gap: 9px;
  }

  .log-header h2 {
    margin: 0;
    font-size: 1.15rem;
  }

  .log-count {
    color: var(--text-muted);
    font-size: 0.78rem;
    font-variant-numeric: tabular-nums;
  }

  .log-toolbar {
    gap: 6px;
  }

  .follow-state {
    gap: 6px;
    margin-right: 2px;
    color: #397069;
    font-size: 0.76rem;
    font-weight: 650;
  }

  .live-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #22c55e;
  }

  .follow-state.paused {
    color: var(--warning);
  }

  .follow-state.paused svg {
    flex: 0 0 auto;
  }

  .log-tool-button {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    padding: 0;
    border: 1px solid var(--line);
    border-radius: 6px;
    background: #fff;
    color: var(--text-soft);
    cursor: pointer;
  }

  .log-tool-button:hover:not(:disabled),
  .log-tool-button:focus-visible {
    border-color: var(--brand);
    outline: none;
    color: var(--brand-strong);
    box-shadow: 0 0 0 3px rgba(15, 143, 131, 0.12);
  }

  .log-tool-button:disabled {
    cursor: not-allowed;
    opacity: 0.45;
  }

  .log-tool-button.success {
    border-color: #86efac;
    color: var(--success);
  }

  .log-tool-button.error {
    border-color: #fecaca;
    color: var(--danger);
  }

  .log-tool-button.log-latest-button {
    width: auto;
    min-width: 32px;
    gap: 5px;
    padding: 0 9px;
    border-color: #fcd34d;
    background: #fffbeb;
    color: #92400e;
    font-size: 0.76rem;
    font-weight: 700;
    white-space: nowrap;
  }

  .new-log-count {
    min-width: 1.4em;
    color: #b45309;
    font-size: 0.7rem;
    font-variant-numeric: tabular-nums;
    text-align: center;
  }

  .log-view {
    height: clamp(240px, 40vh, 480px);
    min-height: 220px;
    max-height: 72vh;
    margin-top: 18px;
    overflow: auto;
    resize: vertical;
    padding: 12px;
    border: 1px solid rgba(100, 116, 139, 0.25);
    border-radius: 6px;
    background: #111820;
    font-family: 'SFMono-Regular', Menlo, Monaco, Consolas, monospace;
    scrollbar-color: #52606d #111820;
  }

  .log-view.expanded {
    height: min(68vh, 720px);
  }

  .log-view:focus-visible {
    outline: 3px solid rgba(15, 143, 131, 0.3);
    outline-offset: 2px;
  }

  .log-line {
    margin: 0;
    padding: 5px 8px;
    border-left: 2px solid transparent;
    color: #d7e0e7;
    font-size: 0.8rem;
    line-height: 1.5;
  }

  .log-line.structured {
    display: grid;
    grid-template-columns: max-content 4.5rem minmax(7rem, 13rem) minmax(0, 1fr);
    gap: 10px;
    align-items: baseline;
  }

  .log-line:hover {
    background: rgba(255, 255, 255, 0.035);
  }

  .log-time,
  .log-level {
    font-variant-numeric: tabular-nums;
  }

  .log-time {
    color: #82909f;
  }

  .log-level {
    color: #8fa3b5;
    font-size: 0.7rem;
    font-weight: 750;
  }

  .log-source {
    overflow: hidden;
    color: #91a4b5;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .log-message {
    min-width: 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .log-line.level-warning {
    border-left-color: #f59e0b;
    background: rgba(245, 158, 11, 0.06);
  }

  .log-line.level-warning .log-level {
    color: #fbbf24;
  }

  .log-line.level-error,
  .log-line.level-critical {
    border-left-color: #fb7185;
    background: rgba(244, 63, 94, 0.07);
  }

  .log-line.level-error .log-level,
  .log-line.level-critical .log-level {
    color: #fda4af;
  }

  .log-line.level-debug {
    opacity: 0.76;
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }

  @media (max-width: 640px) {
    .panel-download,
    .panel-log {
      padding: 20px;
    }

    .log-view {
      height: clamp(240px, 45vh, 420px);
      padding: 10px 8px;
    }

    .log-header {
      align-items: flex-start;
    }

    .log-toolbar {
      width: 100%;
    }

    .follow-state {
      margin-right: auto;
    }

    .log-line.structured {
      grid-template-columns: max-content 4.5rem minmax(0, 1fr);
      gap: 4px 9px;
    }

    .log-source {
      text-align: right;
    }

    .log-line.structured .log-message {
      grid-column: 1 / -1;
      padding-bottom: 3px;
    }
  }
</style>
