<script setup>
  import {
    Brain,
    CalendarDays,
    Clock,
    FileText,
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
        <div class="history-item-main">
          <span v-if="item.record_type === 'rag_query'" class="rag-badge">
            <Brain :size="11" />知识库查询
          </span>
          <span class="history-title">{{ item.title || item.bvid }}</span>
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
            <User :size="12" />{{ resourceAuthorLabel(item.bvid) }}
            {{ item.author }}
          </span>
        </div>
        <div class="history-item-meta">
          <span v-if="item.parent_tname" class="category parent">{{
            item.parent_tname
          }}</span>
          <span v-if="item.tname" class="category child">{{ item.tname }}</span>
          <span v-if="item.pubdate"
            ><CalendarDays :size="13" />发布时间：{{ item.pubdate }}</span
          >
          <span
            ><Clock :size="13" />{{
              item.record_type === 'rag_query' ? '查询时间：' : '转录时间：'
            }}{{ formatTime(item.created_at) }}</span
          >
          <span>{{ item.file_count }} 个文件</span>
        </div>
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
    gap: 9px;
    margin: 18px 0 0;
    padding: 0;
    list-style: none;
  }

  .history-item {
    display: flex;
    align-items: stretch;
    overflow: hidden;
    border: 1px solid rgba(203, 213, 225, 0.7);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.72);
  }

  .history-item:hover {
    border-color: #7dd3fc;
    box-shadow: 0 4px 14px rgba(14, 165, 233, 0.08);
  }

  .history-item-content {
    display: grid;
    flex: 1;
    gap: 9px;
    min-width: 0;
    padding: 14px 16px;
    border: 0;
    background: transparent;
    color: inherit;
    cursor: pointer;
    text-align: left;
  }

  .history-item-main,
  .history-item-meta,
  .history-item-meta span,
  .history-author,
  .rag-badge {
    display: flex;
    align-items: center;
  }

  .history-item-main,
  .history-item-meta {
    flex-wrap: wrap;
    gap: 7px 10px;
  }

  .history-title {
    color: #0f172a;
    font-size: 0.94rem;
    font-weight: 700;
  }

  .history-bvid {
    color: #0284c7;
    font-size: 0.8rem;
    font-weight: 600;
    text-decoration: none;
  }

  .history-author,
  .history-item-meta {
    color: #64748b;
    font-size: 0.78rem;
  }

  .history-author,
  .history-item-meta span,
  .rag-badge {
    gap: 4px;
  }

  .rag-badge,
  .category {
    padding: 2px 6px;
    border-radius: 5px;
    font-size: 0.7rem;
    font-weight: 700;
  }

  .rag-badge,
  .category.parent {
    background: #ecfeff;
    color: #0f766e;
  }

  .category.child {
    background: #eff6ff;
    color: #1d4ed8;
  }

  .history-item-delete {
    width: 44px;
    border: 0;
    border-left: 1px solid #e2e8f0;
    background: transparent;
    color: #94a3b8;
    cursor: pointer;
  }

  .history-item-delete:hover:not(:disabled) {
    background: #fef2f2;
    color: #dc2626;
  }

  .history-list-skeleton {
    display: grid;
    gap: 9px;
    margin-top: 18px;
  }

  .history-skeleton-item {
    display: flex;
    justify-content: space-between;
    padding: 14px 16px;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
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
</style>
