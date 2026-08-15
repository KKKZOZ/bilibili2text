<script setup>
  import {
    AlertCircle,
    ChevronDown,
    Database,
    Layers,
    LoaderCircle,
    RefreshCw
  } from 'lucide-vue-next'
  import { ref } from 'vue'
  import InlineNotice from '../common/InlineNotice.vue'

  defineProps({
    open: Boolean,
    status: { type: Object, default: null },
    loading: Boolean,
    indexing: Boolean,
    indexingForce: Boolean,
    statusError: { type: String, default: '' },
    message: { type: String, default: '' },
    error: { type: String, default: '' }
  })

  const emit = defineEmits(['toggle', 'refresh', 'index'])
  const showFiles = ref(false)
  const kindLabel = (kind) =>
    ({ summary: 'LLM 总结', markdown: '转录原文' })[kind] || kind
</script>

<template>
  <section class="index-section">
    <button class="index-toggle" type="button" @click="emit('toggle')">
      <Database :size="14" /><span>索引管理</span>
      <ChevronDown :size="14" :class="{ open }" />
    </button>
    <div v-if="open" class="index-body">
      <div v-if="loading" class="status-loading">
        <LoaderCircle :size="14" class="spin" />加载中...
      </div>
      <div v-else-if="status" class="stats-grid">
        <div>
          <Layers :size="18" /><b>{{ status.total_indexed_runs }}</b
          ><span>已索引视频</span>
        </div>
        <div>
          <AlertCircle :size="18" /><b>{{ status.pending_index_runs }}</b
          ><span>未索引视频</span>
        </div>
        <div>
          <Database :size="18" /><b>{{ status.total_chunks }}</b
          ><span>向量片段</span>
        </div>
        <button type="button" title="刷新" @click="emit('refresh')">
          <RefreshCw :size="14" />
        </button>
      </div>
      <InlineNotice v-else-if="statusError">{{ statusError }}</InlineNotice>
      <InlineNotice v-if="message" kind="success">{{ message }}</InlineNotice>
      <InlineNotice v-if="error">{{ error }}</InlineNotice>
      <p v-if="status" class="index-summary">
        历史视频共 {{ status.total_history_runs }} 条，当前还有
        {{ status.pending_index_runs }} 条未索引。
      </p>
      <div v-if="status?.indexed_items?.length" class="indexed-files">
        <button
          type="button"
          class="files-toggle"
          @click="showFiles = !showFiles"
        >
          <span>当前已索引文件</span
          ><span
            >{{ status.indexed_items.length }} 条 <ChevronDown :size="14"
          /></span>
        </button>
        <div v-if="showFiles" class="file-list">
          <div
            v-for="item in status.indexed_items"
            :key="item.run_id"
            class="file-item"
          >
            <div>
              <b>{{ item.title || item.bvid || item.run_id }}</b
              ><span v-if="item.author">{{ item.author }}</span>
            </div>
            <div>
              <span>{{ kindLabel(item.source_kind) }}</span
              ><span>{{ item.source_filename }}</span
              ><span>{{ item.chunk_count }} chunks</span>
            </div>
          </div>
        </div>
      </div>
      <div class="index-actions">
        <button
          type="button"
          :disabled="indexing"
          @click="emit('index', false)"
        >
          <LoaderCircle
            v-if="indexing && !indexingForce"
            :size="14"
            class="spin"
          />增量索引
        </button>
        <button
          type="button"
          class="primary"
          :disabled="indexing"
          @click="emit('index', true)"
        >
          <LoaderCircle
            v-if="indexing && indexingForce"
            :size="14"
            class="spin"
          />重建全部
        </button>
      </div>
      <p class="index-hint">
        “增量”跳过已索引的视频；“重建全部”清空后重新索引所有历史记录。
      </p>
    </div>
  </section>
</template>

<style scoped>
  .index-section {
    overflow: hidden;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.6);
  }

  button {
    font: inherit;
  }

  .index-toggle,
  .files-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 13px 18px;
    border: none;
    background: transparent;
    color: var(--text-soft);
    font-size: 0.86rem;
    font-weight: 700;
    cursor: pointer;
    text-align: left;
  }

  .index-toggle svg:last-child,
  .files-toggle span:last-child {
    margin-left: auto;
  }
  .index-toggle svg.open {
    transform: rotate(180deg);
  }

  .index-body {
    display: grid;
    gap: 14px;
    padding: 16px 18px 18px;
    border-top: 1px solid var(--line);
  }

  .status-loading {
    display: flex;
    gap: 6px;
    color: var(--text-muted);
    font-size: 0.84rem;
  }
  .stats-grid {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }
  .stats-grid > div {
    display: flex;
    align-items: center;
    flex: 1;
    gap: 8px;
    min-width: 120px;
    padding: 10px 14px;
    border-radius: 8px;
    background: var(--brand-soft);
  }
  .stats-grid > div svg {
    color: var(--brand);
  }
  .stats-grid > div span {
    color: var(--text-muted);
    font-size: 0.76rem;
  }
  .stats-grid > button {
    padding: 8px;
    border: 1px solid var(--line);
    border-radius: 7px;
    background: #fff;
    cursor: pointer;
  }

  .index-summary,
  .index-hint {
    margin: 0;
    color: var(--text-muted);
    font-size: 0.8rem;
  }
  .indexed-files {
    overflow: hidden;
    border: 1px solid var(--line);
    border-radius: 8px;
  }
  .files-toggle {
    padding: 10px 12px;
    font-size: 0.8rem;
  }
  .files-toggle span {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .file-list {
    max-height: 280px;
    overflow: auto;
    border-top: 1px solid var(--line);
  }
  .file-item {
    display: grid;
    gap: 6px;
    padding: 10px 12px;
    border-bottom: 1px solid #e2e8f0;
  }
  .file-item > div {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 12px;
    color: var(--text-muted);
    font-size: 0.74rem;
  }
  .file-item b {
    color: var(--text-soft);
    font-size: 0.8rem;
  }
  .index-actions {
    display: flex;
    gap: 8px;
  }
  .index-actions button {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 8px 13px;
    border: 1px solid var(--brand);
    border-radius: 7px;
    background: #fff;
    color: var(--brand-strong);
    cursor: pointer;
  }
  .index-actions .primary {
    background: var(--brand);
    color: #fff;
  }
</style>
