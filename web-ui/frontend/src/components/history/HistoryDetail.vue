<script setup>
  import {
    ArrowLeft,
    BookMarked,
    CalendarDays,
    Clock,
    ExternalLink,
    FileText,
    LoaderCircle,
    Trash2,
    User
  } from 'lucide-vue-next'
  import FileList from '../FileList.vue'
  import InlineNotice from '../common/InlineNotice.vue'
  import HistorySummaryConfig from './HistorySummaryConfig.vue'
  import {
    formatTime,
    resourceAuthorLabel,
    resourceDisplayLabel,
    resourceUrl
  } from '../../utils/fileUtils'

  defineProps({
    detail: { type: Object, default: null },
    loading: Boolean,
    allowDelete: Boolean,
    deleteLoading: Boolean,
    downloadRows: { type: Array, default: () => [] },
    selectedProfile: { type: String, default: '' },
    selectedPreset: { type: String, default: '' },
    profiles: { type: Array, default: () => [] },
    presets: { type: Array, default: () => [] },
    regenerateLoading: Boolean,
    requiresApiKey: Boolean,
    regenerateError: { type: String, default: '' },
    regenerateSuccess: { type: String, default: '' },
    ragAnswerHtml: { type: String, default: '' },
    ragReferences: { type: Array, default: () => [] },
    ragAnswerLoading: Boolean,
    ragAnswerError: { type: String, default: '' },
    ragFancyGenerating: Boolean,
    ragFancyError: { type: String, default: '' },
    ragConnectionNotice: { type: String, default: '' }
  })

  const emit = defineEmits([
    'back',
    'delete',
    'update:selectedProfile',
    'update:selectedPreset',
    'regenerate',
    'generateFancy',
    'artifactDeleted',
    'artifactGenerated'
  ])
</script>

<template>
  <article class="history-detail">
    <header>
      <button type="button" @click="emit('back')">
        <ArrowLeft :size="16" />返回列表
      </button>
    </header>
    <div v-if="loading" class="detail-skeleton" aria-hidden="true">
      <span></span><span></span><span></span>
      <div></div>
    </div>
    <template v-else-if="detail">
      <div class="detail-info">
        <div>
          <h2>{{ detail.title }}</h2>
          <div class="detail-meta">
            <a
              v-if="resourceUrl(detail.bvid, detail.page)"
              :href="resourceUrl(detail.bvid, detail.page)"
              target="_blank"
              rel="noopener noreferrer"
              >{{ resourceDisplayLabel(detail.bvid, detail.page) }}</a
            >
            <span v-else>{{
              resourceDisplayLabel(detail.bvid, detail.page)
            }}</span>
            <span v-if="detail.author"
              ><User :size="12" />{{ resourceAuthorLabel(detail.bvid) }}
              {{ detail.author }}</span
            >
            <span v-if="detail.pubdate"
              ><CalendarDays :size="14" />发布时间：{{ detail.pubdate }}</span
            >
            <span
              ><Clock :size="14" />{{
                detail.record_type === 'rag_query'
                  ? '查询时间：'
                  : '转录时间：'
              }}{{ formatTime(detail.created_at) }}</span
            >
          </div>
        </div>
        <button
          v-if="allowDelete"
          class="delete-button"
          :disabled="deleteLoading"
          @click="emit('delete', detail.run_id)"
        >
          <Trash2 :size="16" />删除
        </button>
      </div>

      <HistorySummaryConfig
        v-if="detail.record_type !== 'rag_query'"
        :selected-profile="selectedProfile"
        :selected-preset="selectedPreset"
        :profiles="profiles"
        :presets="presets"
        :loading="regenerateLoading"
        :requires-api-key="requiresApiKey"
        :error="regenerateError"
        :success="regenerateSuccess"
        @update:selected-profile="emit('update:selectedProfile', $event)"
        @update:selected-preset="emit('update:selectedPreset', $event)"
        @regenerate="emit('regenerate')"
      />

      <div v-if="detail.record_type === 'rag_query'" class="rag-preview">
        <div class="rag-preview-head">
          <div>
            <p>知识库回答</p>
            <h3>渲染预览</h3>
          </div>
          <button
            type="button"
            :disabled="
              ragFancyGenerating ||
              ragAnswerLoading ||
              detail.fancy_html_status === 'running'
            "
            @click="emit('generateFancy')"
          >
            <LoaderCircle
              v-if="
                ragFancyGenerating || detail.fancy_html_status === 'running'
              "
              :size="13"
              class="spin"
            />
            <FileText v-else :size="13" />
            {{
              detail.fancy_html_status === 'running'
                ? '生成中...'
                : 'Fancy HTML'
            }}
          </button>
        </div>
        <p v-if="detail.fancy_html_status === 'running'" class="hint">
          Fancy HTML 正在后台生成，离开当前页面后稍后再回来，状态仍会保留。
        </p>
        <InlineNotice v-if="ragConnectionNotice" kind="warning" compact>{{
          ragConnectionNotice
        }}</InlineNotice>
        <InlineNotice v-if="ragFancyError" compact>{{
          ragFancyError
        }}</InlineNotice>
        <div v-if="ragAnswerLoading" class="status-loading">
          <LoaderCircle :size="14" class="spin" />加载回答中...
        </div>
        <InlineNotice v-else-if="ragAnswerError">{{
          ragAnswerError
        }}</InlineNotice>
        <article
          v-else-if="ragAnswerHtml"
          class="rag-markdown"
          v-html="ragAnswerHtml"
        ></article>

        <section v-if="ragReferences.length" class="rag-sources">
          <h3>
            <BookMarked :size="15" />参考来源 <b>{{ ragReferences.length }}</b>
          </h3>
          <div>
            <a
              v-for="item in ragReferences"
              :id="`source-${item.index}`"
              :key="`${item.index}-${item.bvid}-${item.title}`"
              :href="item.bvid ? resourceUrl(item.bvid) : undefined"
              :class="{ 'no-link': !resourceUrl(item.bvid) }"
              target="_blank"
              rel="noopener noreferrer"
            >
              <div>
                <strong>{{ item.index }}</strong
                ><span>{{ item.title || item.bvid || '未知视频' }}</span
                ><b>{{ item.score }}%</b>
              </div>
              <small v-if="item.bvid"
                >{{ resourceDisplayLabel(item.bvid) }}
                <ExternalLink v-if="resourceUrl(item.bvid)" :size="11"
              /></small>
              <p>{{ item.text }}</p>
            </a>
          </div>
        </section>
      </div>

      <FileList
        :items="downloadRows"
        :selected-summary-preset="selectedPreset"
        :selected-summary-profile="selectedProfile"
        :bvid="detail.bvid"
        :history-run-id="detail.run_id"
        title="文件列表"
        :filter-kinds="
          detail.record_type === 'rag_query'
            ? ['rag_answer', 'summary_fancy_html']
            : [
                'markdown',
                'summary',
                'summary_no_table',
                'summary_fancy_html',
                'summary_table_md',
                'summary_table_pdf',
                'summary_timeline',
                'text',
                'json',
                'audio'
              ]
        "
        @artifact-deleted="emit('artifactDeleted', $event)"
        @artifact-generated="emit('artifactGenerated', $event)"
      />
    </template>
  </article>
</template>

<style scoped>
  .history-detail {
    padding: 28px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: #fff;
    box-shadow: var(--panel-shadow);
  }
  header {
    margin-bottom: 16px;
  }
  header button {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--brand-strong);
    font-size: 0.88rem;
    font-weight: 600;
    cursor: pointer;
  }
  .detail-info {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 20px;
  }
  .detail-info > div {
    min-width: 0;
  }
  h2 {
    margin: 0 0 10px;
    font-size: 1.24rem;
    line-height: 1.3;
    overflow-wrap: anywhere;
  }
  .detail-meta {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px 12px;
    color: var(--text-muted);
    font-size: 0.84rem;
  }
  .detail-meta span,
  .detail-meta a {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .detail-meta a {
    color: var(--brand-strong);
    font-weight: 600;
    text-decoration: none;
  }
  .delete-button {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-height: 36px;
    padding: 0 14px;
    border: 1px solid #fecaca;
    border-radius: 8px;
    background: #fef2f2;
    color: #dc2626;
    font-weight: 600;
    cursor: pointer;
  }
  .rag-preview {
    display: grid;
    gap: 14px;
    margin-bottom: 22px;
    padding: 18px 20px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.72);
  }
  .rag-preview-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }
  .rag-preview-head p,
  .rag-preview-head h3 {
    margin: 0;
  }
  .rag-preview-head p {
    color: #0284c7;
    font-size: 0.72rem;
    font-weight: 800;
  }
  .rag-preview-head h3 {
    margin-top: 3px;
    font-size: 1rem;
  }
  .rag-preview-head button {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 6px 11px;
    border: 1px solid #fdba74;
    border-radius: 7px;
    background: #fff;
    color: #c2410c;
    font-weight: 700;
    cursor: pointer;
  }
  .hint {
    margin: 0;
    color: var(--text-muted);
    font-size: 0.8rem;
  }
  .status-loading {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--text-muted);
    font-size: 0.84rem;
  }
  .rag-markdown {
    color: var(--text-main);
    font-size: 0.94rem;
    line-height: 1.8;
  }
  .rag-markdown :deep(h1),
  .rag-markdown :deep(h2),
  .rag-markdown :deep(h3) {
    margin: 0.9em 0 0.45em;
  }
  .rag-markdown :deep(blockquote) {
    margin-left: 0;
    padding: 10px 14px;
    border-left: 3px solid rgba(13, 148, 136, 0.28);
    background: var(--brand-soft);
  }
  .rag-markdown :deep(pre) {
    overflow: auto;
    padding: 12px 14px;
    border-radius: 8px;
    background: #0f172a;
    color: #e2e8f0;
  }
  .rag-markdown :deep(table) {
    display: block;
    max-width: 100%;
    overflow: auto;
    border-collapse: collapse;
  }
  .rag-markdown :deep(th),
  .rag-markdown :deep(td) {
    padding: 9px;
    border: 1px solid #e2e8f0;
  }
  .rag-sources {
    display: grid;
    gap: 10px;
  }
  .rag-sources h3 {
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 0;
    font-size: 0.86rem;
  }
  .rag-sources h3 b {
    padding: 2px 6px;
    border-radius: 99px;
    background: var(--brand-soft);
    color: var(--brand-strong);
    font-size: 0.72rem;
  }
  .rag-sources > div {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 10px;
  }
  .rag-sources a {
    display: grid;
    gap: 6px;
    padding: 12px;
    border: 1px solid var(--line);
    border-radius: 8px;
    color: inherit;
    text-decoration: none;
  }
  .rag-sources a > div {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .rag-sources a strong {
    display: grid;
    place-items: center;
    width: 23px;
    height: 23px;
    border-radius: 5px;
    background: #0f172a;
    color: #fff;
    font-size: 0.72rem;
  }
  .rag-sources a span {
    flex: 1;
    font-size: 0.84rem;
    font-weight: 700;
  }
  .rag-sources a b {
    color: var(--brand-strong);
    font-size: 0.74rem;
  }
  .rag-sources small {
    display: flex;
    align-items: center;
    gap: 3px;
    color: var(--brand-strong);
  }
  .rag-sources p {
    margin: 0;
    color: var(--text-soft);
    font-size: 0.8rem;
    line-height: 1.6;
  }
  .detail-skeleton {
    display: grid;
    gap: 10px;
  }
  .detail-skeleton span,
  .detail-skeleton div {
    height: 14px;
    border-radius: 6px;
    background: #e2e8f0;
    animation: pulse 1s ease-in-out infinite alternate;
  }
  .detail-skeleton span:nth-child(2) {
    width: 55%;
  }
  .detail-skeleton span:nth-child(3) {
    width: 35%;
  }
  .detail-skeleton div {
    height: 180px;
    margin-top: 8px;
  }
  @keyframes pulse {
    to {
      opacity: 0.45;
    }
  }
  @media (max-width: 640px) {
    .history-detail {
      padding: 20px;
    }
    .detail-info {
      flex-direction: column;
    }
    .delete-button {
      width: 100%;
      justify-content: center;
    }
    .rag-sources > div {
      grid-template-columns: 1fr;
    }
  }
</style>
