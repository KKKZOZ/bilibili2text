<script setup>
  import { Sparkles } from 'lucide-vue-next'
  import FileList from '../FileList.vue'

  defineProps({
    answerHtml: { type: String, default: '' },
    downloadItems: { type: Array, default: () => [] }
  })

  const emit = defineEmits(['answerClick'])
</script>

<template>
  <article class="panel answer-panel">
    <div class="answer-label"><Sparkles :size="14" /><span>AI 回答</span></div>
    <!-- eslint-disable-next-line vue/no-v-html -->
    <div
      class="answer-text"
      v-html="answerHtml"
      @click="emit('answerClick', $event)"
    ></div>
    <FileList
      v-if="downloadItems.length"
      :items="downloadItems"
      :filter-kinds="['rag_answer', 'summary_fancy_html']"
      title="回答文件"
    />
  </article>
</template>

<style scoped>
  .answer-panel {
    padding: clamp(18px, 3vw, 28px) clamp(18px, 3vw, 32px);
    border-left: 3px solid var(--brand);
  }

  .answer-label {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    margin-bottom: 12px;
    color: var(--brand);
    font-size: 0.74rem;
    font-weight: 700;
    text-transform: uppercase;
  }

  .answer-text {
    color: var(--text-main);
    font-size: 0.94rem;
    line-height: 1.8;
  }

  .answer-text :deep(h1),
  .answer-text :deep(h2),
  .answer-text :deep(h3) {
    margin: 0.9em 0 0.45em;
    line-height: 1.35;
  }

  .answer-text :deep(p),
  .answer-text :deep(ol),
  .answer-text :deep(ul),
  .answer-text :deep(blockquote),
  .answer-text :deep(pre) {
    margin: 0.7em 0;
  }

  .answer-text :deep(blockquote) {
    margin-left: 0;
    padding: 10px 14px;
    border-left: 3px solid rgba(13, 148, 136, 0.28);
    border-radius: 0 8px 8px 0;
    background: rgba(240, 253, 250, 0.8);
  }

  .answer-text :deep(pre) {
    overflow: auto;
    padding: 12px 14px;
    border-radius: 8px;
    background: #0f172a;
    color: #e2e8f0;
  }

  .answer-text :deep(table) {
    display: block;
    max-width: 100%;
    overflow-x: auto;
    border-collapse: collapse;
  }

  .answer-text :deep(th),
  .answer-text :deep(td) {
    padding: 10px 12px;
    border: 1px solid #e2e8f0;
    text-align: left;
  }

  :deep(.citation-ref) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 18px;
    height: 18px;
    padding: 0 4px;
    border-radius: 5px;
    background: var(--brand-soft);
    color: var(--brand-strong);
    font-size: 0.72rem;
    font-weight: 700;
    cursor: pointer;
  }
</style>
