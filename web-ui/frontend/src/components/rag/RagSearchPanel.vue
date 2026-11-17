<script setup>
  import { LoaderCircle, Search, Users } from 'lucide-vue-next'
  import InlineNotice from '../common/InlineNotice.vue'
  import MultiSelectPopover from '../common/MultiSelectPopover.vue'
  import SummaryProfileSelect from '../common/SummaryProfileSelect.vue'

  defineProps({
    question: { type: String, default: '' },
    selectedAuthors: { type: Array, default: () => [] },
    authorOptions: { type: Array, default: () => [] },
    selectedProfile: { type: String, default: '' },
    profiles: { type: Array, default: () => [] },
    querying: Boolean,
    stageMessage: { type: String, default: '' },
    error: { type: String, default: '' }
  })

  const emit = defineEmits([
    'update:question',
    'update:selectedAuthors',
    'update:selectedProfile',
    'submit'
  ])

  const isApplePlatform =
    typeof navigator !== 'undefined' &&
    /Mac|iPhone|iPad/i.test(navigator.platform || navigator.userAgent || '')
  const submitShortcut = isApplePlatform
    ? '⌘ + Enter 提交'
    : 'Ctrl + Enter 提交'

  const onKeydown = (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey))
      emit('submit')
  }
</script>

<template>
  <article class="panel search-panel">
    <header>
      <h2>跨视频内容检索</h2>
      <p>
        基于历史转录内容，用自然语言提问，AI
        从所有视频中检索相关片段并生成回答。
      </p>
    </header>
    <div class="search-box">
      <div class="textarea-wrap">
        <textarea
          :value="question"
          aria-label="向知识库提问"
          placeholder="例如：关于中国民航信息网络，你知道多少？"
          rows="3"
          :disabled="querying"
          @input="emit('update:question', $event.target.value)"
          @keydown="onKeydown"
        ></textarea>
        <span>{{ submitShortcut }}</span>
      </div>
      <div class="filters-row">
        <MultiSelectPopover
          :model-value="selectedAuthors"
          :options="authorOptions"
          :trigger-label="
            selectedAuthors.length
              ? `已选 ${selectedAuthors.length} 位 UP 主`
              : '全部 UP 主'
          "
          empty-text="暂无已索引的 UP 主"
          compact
          @update:model-value="emit('update:selectedAuthors', $event)"
        >
          <template #icon><Users :size="13" /></template>
        </MultiSelectPopover>
        <SummaryProfileSelect
          v-if="profiles.length"
          id="rag-llm-profile"
          label="模型"
          :model-value="selectedProfile"
          :profiles="profiles"
          :disabled="querying"
          compact
          @update:model-value="emit('update:selectedProfile', $event)"
        />
      </div>
      <button
        class="submit search-submit"
        :disabled="querying || !question.trim()"
        @click="emit('submit')"
      >
        <LoaderCircle v-if="querying" :size="16" class="spin" />
        <Search v-else :size="16" />
        {{ querying ? '检索中...' : '提交问题' }}
      </button>
    </div>
    <InlineNotice v-if="error">{{ error }}</InlineNotice>
  </article>
</template>

<style scoped>
  .search-panel {
    padding: 28px;
  }

  header {
    margin-bottom: 18px;
  }

  h2 {
    margin: 0 0 6px;
    font-size: 1.15rem;
  }

  header p {
    margin: 0;
    color: var(--text-muted);
    font-size: 0.88rem;
    line-height: 1.6;
  }

  .search-box {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .textarea-wrap {
    position: relative;
    border: 1.5px solid var(--line);
    border-radius: var(--radius-lg);
    background: var(--panel-bg);
  }

  .textarea-wrap:focus-within {
    border-color: var(--brand);
    box-shadow: 0 0 0 3px var(--focus-ring);
  }

  textarea {
    display: block;
    width: 100%;
    resize: none;
    padding: 14px 16px 32px;
    border: none;
    border-radius: var(--radius-lg);
    outline: none;
    background: transparent;
    color: var(--text-main);
    font: inherit;
    font-size: 0.94rem;
    line-height: 1.6;
  }

  .textarea-wrap > span {
    position: absolute;
    right: 14px;
    bottom: 10px;
    color: var(--text-faint);
    font-size: 0.72rem;
  }

  .filters-row {
    display: flex;
    align-items: end;
    flex-wrap: wrap;
    gap: 12px;
  }

  .filters-row > :last-child {
    flex: 1 1 280px;
  }

  .search-submit {
    align-self: flex-end;
    min-width: 130px;
    margin: 0;
  }

  @media (max-width: 640px) {
    .search-panel {
      padding: 20px;
    }

    .search-submit {
      width: 100%;
    }
  }
</style>
