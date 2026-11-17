<script setup>
  import {
    Brain,
    CalendarDays,
    ChevronRight,
    Clock,
    FileText,
    FolderTree,
    Layers3,
    SearchX,
    Trash2,
    User
  } from 'lucide-vue-next'
  import InlineNotice from '../common/InlineNotice.vue'
  import {
    formatTime,
    resourceAuthorLabel,
    resourceDisplayLabel,
    resourceUrl
  } from '../../utils/fileUtils'

  defineProps({
    items: { type: Array, default: () => [] },
    loading: Boolean,
    refreshing: Boolean,
    filtered: Boolean,
    error: { type: String, default: '' },
    allowDelete: Boolean,
    deleteLoading: Boolean
  })

  const emit = defineEmits([
    'open',
    'delete',
    'filter-category',
    'filter-author',
    'retry',
    'clear-filters'
  ])
</script>

<template>
  <div
    v-if="loading && items.length === 0"
    class="history-list-skeleton"
    aria-hidden="true"
  >
    <div v-for="idx in 6" :key="idx" class="history-skeleton-item">
      <div><span></span><span></span><span></span></div>
      <i></i>
    </div>
  </div>
  <InlineNotice v-else-if="error">
    {{ error }}
    <template #action>
      <button
        type="button"
        class="history-inline-action"
        @click="emit('retry')"
      >
        重试
      </button>
    </template>
  </InlineNotice>
  <div v-else-if="items.length === 0 && filtered" class="history-empty">
    <SearchX :size="32" aria-hidden="true" />
    <p>没有符合当前搜索或筛选条件的记录。</p>
    <button
      type="button"
      class="history-empty-action"
      @click="emit('clear-filters')"
    >
      清除搜索和筛选
    </button>
  </div>
  <div v-else-if="items.length === 0" class="history-empty">
    <FileText :size="32" aria-hidden="true" />
    <p>暂无历史转录记录。</p>
  </div>
  <ul
    v-else
    class="history-list"
    :class="{ refreshing }"
    :aria-busy="refreshing"
  >
    <li v-for="item in items" :key="item.run_id" class="history-item">
      <div class="history-item-content">
        <div class="history-item-copy">
          <div class="history-item-primary">
            <span v-if="item.record_type === 'rag_query'" class="rag-badge">
              <Brain :size="12" />知识库查询
            </span>
            <button
              class="history-title"
              type="button"
              @click="emit('open', item.run_id)"
            >
              {{ item.title || item.bvid }}
            </button>
          </div>

          <div
            v-if="
              (item.record_type !== 'rag_query' && item.bvid) || item.author
            "
            class="history-item-source"
          >
            <a
              v-if="
                item.record_type !== 'rag_query' &&
                item.bvid &&
                resourceUrl(item.bvid, item.page)
              "
              class="history-bvid"
              :href="resourceUrl(item.bvid, item.page)"
              target="_blank"
              rel="noopener noreferrer"
              @click.stop
              >{{ resourceDisplayLabel(item.bvid, item.page) }}</a
            >
            <span
              v-else-if="item.record_type !== 'rag_query' && item.bvid"
              class="history-bvid"
            >
              {{ resourceDisplayLabel(item.bvid, item.page) }}
            </span>
            <button
              v-if="item.author"
              class="history-author history-filter-link"
              type="button"
              :title="`筛选 UP 主：${item.author}`"
              @click.stop="emit('filter-author', item.author)"
            >
              <User :size="13" />{{ resourceAuthorLabel(item.bvid) }}
              {{ item.author }}
            </button>
          </div>

          <div class="history-item-meta">
            <button
              v-if="item.parent_tname || item.tname"
              class="history-category history-filter-link"
              type="button"
              :title="`筛选分区：${item.tname || item.parent_tname}`"
              @click.stop="emit('filter-category', item.tid)"
            >
              <FolderTree :size="13" />
              <span v-if="item.parent_tname">{{ item.parent_tname }}</span>
              <i v-if="item.parent_tname && item.tname">/</i>
              <span v-if="item.tname">{{ item.tname }}</span>
            </button>
            <span v-if="item.pubdate" title="发布时间">
              <CalendarDays :size="13" />发布 {{ item.pubdate }}
            </span>
            <span
              :title="
                item.record_type === 'rag_query' ? '查询时间' : '转录时间'
              "
            >
              <Clock :size="13" />{{
                item.record_type === 'rag_query' ? '查询' : '转录'
              }}
              {{ formatTime(item.created_at) }}
            </span>
            <span title="总结版本数">
              <Layers3 :size="13" />{{ item.summary_version_count }} 个总结版本
            </span>
          </div>
        </div>
        <span class="history-item-open" aria-hidden="true">
          <ChevronRight class="history-item-chevron" :size="19" />
        </span>
      </div>
      <button
        v-if="allowDelete"
        class="history-item-delete"
        type="button"
        :disabled="deleteLoading"
        title="删除"
        :aria-label="`删除历史记录：${item.title || item.bvid}`"
        @click="emit('delete', item.run_id)"
      >
        <Trash2 :size="16" />
      </button>
    </li>
  </ul>
</template>

<style scoped>
  .history-empty {
    display: grid;
    justify-items: center;
    gap: 8px;
    padding: 52px 20px;
    color: var(--text-faint);
  }

  .history-empty p {
    margin: 0;
  }

  .history-empty-action,
  .history-inline-action {
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--brand-strong);
    font-size: 0.86rem;
    font-weight: 700;
    cursor: pointer;
  }

  .history-inline-action {
    margin-left: 4px;
  }

  .history-empty-action:hover,
  .history-inline-action:hover {
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .history-empty-action:focus-visible,
  .history-inline-action:focus-visible {
    border-radius: 3px;
    outline: 2px solid var(--brand);
    outline-offset: 2px;
  }

  .history-list.refreshing {
    opacity: 0.6;
    transition: opacity 160ms ease;
  }

  .history-list {
    display: grid;
    gap: 0;
    margin: 14px 0 0;
    padding: 0;
    border-block: 1px solid var(--line);
    background: var(--panel-bg);
    list-style: none;
  }

  .history-item {
    position: relative;
    display: flex;
    align-items: stretch;
    border: 0;
    border-bottom: 1px solid var(--line);
    border-radius: 0;
    background: transparent;
    transition:
      background-color 160ms ease,
      box-shadow 160ms ease;
  }

  .history-item:hover {
    background: var(--surface-subtle);
    box-shadow: inset 3px 0 var(--brand);
  }

  .history-item:last-child {
    border-bottom: 0;
  }

  .history-item-content {
    display: flex;
    align-items: center;
    flex: 1;
    gap: 16px;
    min-width: 0;
    padding: 17px 14px 17px 16px;
    border: 0;
    background: transparent;
    color: inherit;
    text-align: left;
  }

  .history-item-copy {
    display: grid;
    flex: 1;
    gap: 7px;
    min-width: 0;
  }

  .history-item-primary,
  .history-item-source,
  .history-item-meta,
  .history-item-meta span,
  .history-category,
  .history-author,
  .rag-badge {
    display: flex;
    align-items: center;
  }

  .history-item-primary,
  .history-item-source,
  .history-item-meta {
    flex-wrap: wrap;
    gap: 6px 14px;
  }

  .history-item-primary {
    gap: 8px;
  }

  /* The title is the row's single click target: its ::after covers the row,
     and the other controls sit above it. */
  .history-title::after {
    position: absolute;
    inset: 0;
    content: '';
  }

  .history-item-source a,
  .history-item .history-filter-link,
  .history-item-delete {
    position: relative;
    z-index: 1;
  }

  .history-title {
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--text-main);
    cursor: pointer;
    font-size: 0.96rem;
    font-weight: 700;
    line-height: 1.45;
    text-align: left;
  }

  .history-bvid {
    color: var(--brand-strong);
    font-size: 0.79rem;
    font-weight: 700;
    text-decoration: none;
  }

  .history-bvid:hover {
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .history-item-source,
  .history-item-meta {
    color: var(--text-muted);
    font-size: 0.78rem;
  }

  .history-item-meta {
    color: var(--text-muted);
  }

  .history-author,
  .history-item-meta span,
  .history-category,
  .rag-badge {
    gap: 5px;
  }

  .history-item-source svg,
  .history-item-meta svg {
    flex: 0 0 auto;
    color: var(--text-faint);
  }

  .history-category i {
    color: var(--text-faint);
    font-style: normal;
  }

  .history-item-meta .history-category {
    gap: 4px;
    color: var(--brand-strong);
    font-weight: 600;
  }

  .history-item-meta .history-category svg {
    color: var(--brand);
  }

  .history-filter-link {
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: inherit;
  }

  .history-filter-link:hover,
  .history-filter-link:focus-visible {
    color: var(--brand-strong);
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .history-item-meta .history-category:hover,
  .history-item-meta .history-category:focus-visible {
    color: var(--brand-strong);
  }

  .history-filter-link:hover svg,
  .history-filter-link:focus-visible svg,
  .history-item-meta .history-category:hover svg,
  .history-item-meta .history-category:focus-visible svg {
    color: var(--brand-strong);
  }

  .history-title:focus-visible,
  .history-filter-link:focus-visible {
    border-radius: 3px;
    outline: 2px solid var(--brand);
    outline-offset: 2px;
  }

  .rag-badge {
    padding: 3px 7px;
    border-radius: var(--radius-md);
    background: var(--brand-soft);
    color: var(--brand-strong);
    font-size: 0.72rem;
    font-weight: 700;
  }

  .history-item-chevron {
    flex: 0 0 auto;
    transition:
      color 160ms ease,
      transform 160ms ease;
  }

  .history-item-open {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 auto;
    width: 32px;
    height: 32px;
    color: var(--text-faint);
  }

  .history-item:hover .history-item-open {
    color: var(--brand);
  }

  .history-item:hover .history-item-chevron {
    transform: translateX(2px);
  }

  .history-item-delete {
    align-self: center;
    width: 36px;
    height: 36px;
    margin-right: 10px;
    border: 0;
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text-faint);
    cursor: pointer;
    opacity: 0;
    transition:
      background-color 160ms ease,
      color 160ms ease,
      opacity 160ms ease;
  }

  .history-item:hover .history-item-delete,
  .history-item-delete:focus-visible {
    opacity: 1;
  }

  /* Touch devices have no hover, so the action is always visible. */
  @media (hover: none) {
    .history-item-delete {
      opacity: 1;
    }
  }

  .history-item-delete:hover:not(:disabled) {
    background: var(--danger-soft);
    color: var(--danger);
  }

  .history-list-skeleton {
    display: grid;
    gap: 0;
    margin-top: 14px;
    border-block: 1px solid var(--line);
    background: var(--panel-bg);
  }

  .history-skeleton-item {
    display: flex;
    justify-content: space-between;
    padding: 17px 16px;
    border: 0;
    border-bottom: 1px solid var(--line);
    border-radius: 0;
  }

  .history-skeleton-item:last-child {
    border-bottom: 0;
  }

  .history-skeleton-item div {
    display: grid;
    gap: 8px;
    width: 70%;
  }

  .history-skeleton-item span,
  .history-skeleton-item i {
    height: 11px;
    border-radius: var(--radius-md);
    background: var(--line);
    animation: pulse 1.2s ease-in-out infinite alternate;
  }

  .history-skeleton-item span:nth-child(2) {
    width: 45%;
  }
  .history-skeleton-item span:nth-child(3) {
    width: 65%;
  }
  .history-skeleton-item i {
    width: 32px;
    height: 32px;
  }

  @keyframes pulse {
    to {
      opacity: 0.45;
    }
  }

  @media (max-width: 640px) {
    .history-item-content {
      align-items: flex-start;
      gap: 8px;
      padding: 15px 8px 15px 12px;
    }

    .history-item-copy {
      gap: 8px;
    }

    .history-item-primary {
      align-items: flex-start;
    }

    .history-title {
      display: -webkit-box;
      overflow: hidden;
      font-size: 0.91rem;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
    }

    .history-item-meta {
      gap: 6px 12px;
    }

    .history-item-open {
      margin-top: 2px;
    }

    .history-item-delete {
      width: 34px;
      height: 34px;
      margin-right: 5px;
      opacity: 1;
    }
  }
</style>
