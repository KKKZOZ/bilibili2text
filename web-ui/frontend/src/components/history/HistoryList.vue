<script setup>
  import {
    Brain,
    CalendarDays,
    ChevronRight,
    Clock,
    Files,
    FileText,
    FolderTree,
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
    error: { type: String, default: '' },
    allowDelete: Boolean,
    deleteLoading: Boolean
  })

  const emit = defineEmits(['open', 'delete'])
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
  <InlineNotice v-else-if="error">{{ error }}</InlineNotice>
  <div v-else-if="items.length === 0" class="history-empty">
    <FileText :size="32" />
    <p>暂无历史转录记录。</p>
  </div>
  <ul v-else class="history-list">
    <li v-for="item in items" :key="item.run_id" class="history-item">
      <button
        class="history-item-content"
        type="button"
        @click="emit('open', item.run_id)"
      >
        <div class="history-item-copy">
          <div class="history-item-primary">
            <span v-if="item.record_type === 'rag_query'" class="rag-badge">
              <Brain :size="12" />知识库查询
            </span>
            <span class="history-title">{{ item.title || item.bvid }}</span>
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
            <span v-if="item.author" class="history-author">
              <User :size="13" />{{ resourceAuthorLabel(item.bvid) }}
              {{ item.author }}
            </span>
          </div>

          <div class="history-item-meta">
            <span
              v-if="item.parent_tname || item.tname"
              class="history-category"
            >
              <FolderTree :size="13" />
              <span v-if="item.parent_tname">{{ item.parent_tname }}</span>
              <i v-if="item.parent_tname && item.tname">/</i>
              <span v-if="item.tname">{{ item.tname }}</span>
            </span>
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
            <span title="生成文件数">
              <Files :size="13" />{{ item.file_count }} 个文件
            </span>
          </div>
        </div>
        <ChevronRight class="history-item-chevron" :size="19" />
      </button>
      <button
        v-if="allowDelete"
        class="history-item-delete"
        type="button"
        :disabled="deleteLoading"
        title="删除"
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
    color: #94a3b8;
  }

  .history-empty p {
    margin: 0;
  }

  .history-list {
    display: grid;
    gap: 0;
    margin: 14px 0 0;
    padding: 0;
    border-block: 1px solid #dce3e8;
    background: rgba(255, 255, 255, 0.72);
    list-style: none;
  }

  .history-item {
    position: relative;
    display: flex;
    align-items: stretch;
    border: 0;
    border-bottom: 1px solid #e3e8ec;
    border-radius: 0;
    background: transparent;
    transition:
      background-color 160ms ease,
      box-shadow 160ms ease;
  }

  .history-item:hover {
    background: #f5f9f8;
    box-shadow: inset 3px 0 #0f8f83;
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
    cursor: pointer;
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

  .history-title {
    color: #0f172a;
    font-size: 0.96rem;
    font-weight: 700;
    line-height: 1.45;
  }

  .history-bvid {
    color: #0b8076;
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
    color: #64748b;
    font-size: 0.78rem;
  }

  .history-item-meta {
    color: #718096;
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
    color: #91a1b2;
  }

  .history-category i {
    color: #a7b3bf;
    font-style: normal;
  }

  .rag-badge {
    padding: 3px 7px;
    border-radius: 5px;
    background: #e8f8f6;
    color: #0b746b;
    font-size: 0.72rem;
    font-weight: 700;
  }

  .history-item-chevron {
    flex: 0 0 auto;
    color: #a7b3bf;
    transition:
      color 160ms ease,
      transform 160ms ease;
  }

  .history-item:hover .history-item-chevron {
    color: #0f8f83;
    transform: translateX(2px);
  }

  .history-item-delete {
    align-self: center;
    width: 36px;
    height: 36px;
    margin-right: 10px;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: #94a3b8;
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

  .history-item-delete:hover:not(:disabled) {
    background: #fef2f2;
    color: #dc2626;
  }

  .history-list-skeleton {
    display: grid;
    gap: 0;
    margin-top: 14px;
    border-block: 1px solid #dce3e8;
    background: rgba(255, 255, 255, 0.72);
  }

  .history-skeleton-item {
    display: flex;
    justify-content: space-between;
    padding: 17px 16px;
    border: 0;
    border-bottom: 1px solid #e3e8ec;
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
    border-radius: 5px;
    background: #e2e8f0;
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

    .history-item-chevron {
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
