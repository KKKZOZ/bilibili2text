<script setup>
  import { computed } from 'vue'
  import { ExternalLink, Video } from 'lucide-vue-next'

  const props = defineProps({
    job: { type: Object, required: true },
    sourceBvid: { type: String, default: '' },
    includeComments: Boolean,
    commentLimit: { type: Number, default: 200 }
  })

  const bvid = computed(() => props.job.bvid || props.sourceBvid || '')
  const videoUrl = computed(() =>
    bvid.value.startsWith('BV')
      ? `https://www.bilibili.com/video/${bvid.value}`
      : ''
  )

  const formatDuration = (seconds) => {
    const total = Math.max(0, Number.parseInt(seconds, 10) || 0)
    if (!total) return '—'
    const hours = Math.floor(total / 3600)
    const minutes = Math.floor((total % 3600) / 60)
    const remainder = total % 60
    return hours
      ? [hours, minutes, remainder]
          .map((part) => String(part).padStart(2, '0'))
          .join(':')
      : [minutes, remainder]
          .map((part) => String(part).padStart(2, '0'))
          .join(':')
  }

  const category = computed(() => {
    const values = [props.job.parent_tname, props.job.tname]
      .map((value) => String(value || '').trim())
      .filter((value, index, items) => value && items.indexOf(value) === index)
    return values.join(' / ') || '—'
  })

  const commentState = computed(() => {
    const status = props.job.comment_status || 'disabled'
    if (props.job.status === 'idle') {
      if (!props.includeComments) return { label: '未启用', tone: 'muted' }
      return {
        label:
          props.commentLimit > 0
            ? `计划抓取 ${props.commentLimit} 条主评论`
            : '计划抓取全部主评论',
        tone: 'pending'
      }
    }
    if (status === 'pending') return { label: '等待抓取', tone: 'pending' }
    if (status === 'running') return { label: '抓取中', tone: 'running' }
    if (status === 'succeeded') {
      const replies = Number(props.job.comment_reply_count) || 0
      return {
        label: `主评论 ${Number(props.job.comment_count) || 0} 条${
          replies ? ` · 回复 ${replies} 条` : ''
        }`,
        tone: 'success'
      }
    }
    if (status === 'failed') return { label: '抓取失败', tone: 'error' }
    if (status === 'unavailable') {
      return { label: '当前来源不支持', tone: 'muted' }
    }
    return { label: '未启用', tone: 'muted' }
  })
</script>

<template>
  <article class="panel video-metadata-panel">
    <header>
      <Video :size="17" />
      <h2>视频信息</h2>
    </header>
    <dl>
      <div class="title-row">
        <dt>视频标题</dt>
        <dd>{{ job.title || '等待获取' }}</dd>
      </div>
      <div>
        <dt>BV 号</dt>
        <dd>
          <a v-if="videoUrl" :href="videoUrl" target="_blank" rel="noopener">
            {{ bvid }}<ExternalLink :size="12" />
          </a>
          <span v-else>{{ bvid || '—' }}</span>
        </dd>
      </div>
      <div>
        <dt>视频长度</dt>
        <dd>{{ formatDuration(job.duration_seconds) }}</dd>
      </div>
      <div>
        <dt>UP 主</dt>
        <dd>{{ job.author || '—' }}</dd>
      </div>
      <div>
        <dt>分区</dt>
        <dd>{{ category }}</dd>
      </div>
      <div>
        <dt>评论</dt>
        <dd class="comment-status" :class="`tone-${commentState.tone}`">
          <span></span>{{ commentState.label }}
        </dd>
      </div>
    </dl>
  </article>
</template>

<style scoped>
  .video-metadata-panel {
    padding: 20px 22px;
  }

  header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-bottom: 13px;
    border-bottom: 1px solid var(--line);
  }

  header svg {
    color: var(--brand);
  }

  h2 {
    margin: 0;
    font-size: 1rem;
  }

  dl {
    margin: 0;
  }

  dl > div {
    display: grid;
    grid-template-columns: 70px minmax(0, 1fr);
    gap: 12px;
    align-items: center;
    min-height: 39px;
    border-bottom: 1px solid #edf0f3;
  }

  dl > div:last-child {
    border-bottom: 0;
  }

  dt,
  dd {
    margin: 0;
    font-size: 0.82rem;
  }

  dt {
    color: var(--text-muted);
  }

  dd {
    min-width: 0;
    overflow: hidden;
    color: var(--text-main);
    font-weight: 650;
    text-align: right;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .title-row {
    align-items: start;
    padding: 10px 0;
  }

  .title-row dd {
    display: -webkit-box;
    overflow: hidden;
    line-height: 1.45;
    white-space: normal;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }

  a,
  .comment-status {
    display: inline-flex;
    align-items: center;
    justify-content: flex-end;
    gap: 5px;
  }

  a {
    color: #0369a1;
    text-decoration: none;
  }

  .comment-status > span {
    width: 7px;
    height: 7px;
    flex: 0 0 auto;
    border-radius: 50%;
    background: #94a3b8;
  }

  .tone-pending > span {
    background: #f59e0b;
  }

  .tone-running > span {
    background: #0891b2;
  }

  .tone-success > span {
    background: #16a34a;
  }

  .tone-error > span {
    background: #dc2626;
  }

  @media (max-width: 980px) {
    .video-metadata-panel {
      padding: 20px;
    }
  }

  @media (max-width: 640px) {
    .video-metadata-panel {
      padding: 18px;
    }
  }
</style>
