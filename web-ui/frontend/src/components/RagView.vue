<script setup>
  import { computed, onMounted, ref } from 'vue'
  import { ragApi } from '../api'
  import { usePublicCredentials } from '../composables/usePublicCredentials'
  import { useSummaryConfig } from '../composables/useSummaryConfig'
  import { renderMarkdown } from '../utils/markdown'
  import { Sparkles } from 'lucide-vue-next'
  import RagAnswerPanel from './rag/RagAnswerPanel.vue'
  import RagIndexPanel from './rag/RagIndexPanel.vue'
  import RagSearchPanel from './rag/RagSearchPanel.vue'
  import RagSources from './rag/RagSources.vue'

  const { getApiKey, getDeepseekApiKey, getCustomLlmPayload } =
    usePublicCredentials()
  const {
    summaryProfiles: llmProfiles,
    selectedSummaryProfile: selectedLlmProfile
  } = useSummaryConfig()

  // ─── Query state ──────────────────────────────────────────────────
  const question = ref('')
  const answer = ref('')
  const answerDownloadId = ref('')
  const answerFilename = ref('')
  const sources = ref([])
  const queryError = ref('')
  const isQuerying = ref(false)
  const hasQueried = ref(false)
  const queryStageMessage = ref('')

  // ─── Author filter ────────────────────────────────────────────────
  const authorList = ref([])
  const selectedAuthors = ref([])
  const authorOptions = computed(() =>
    authorList.value.map((item) => ({
      value: item.author,
      label: item.author,
      count: `${item.indexed_run_count} 个视频`
    }))
  )

  const loadAuthors = async () => {
    try {
      const data = await ragApi.getAuthors()
      authorList.value = [...(data.authors || [])].sort(
        (left, right) => right.indexed_run_count - left.indexed_run_count
      )
    } catch {}
  }

  onMounted(() => {
    void loadAuthors()
  })

  // ─── Index state ──────────────────────────────────────────────────
  const indexStatus = ref(null)
  const indexStatusError = ref('')
  const isLoadingStatus = ref(false)
  const isIndexing = ref(false)
  const indexingForce = ref(false)
  const indexMessage = ref('')
  const indexError = ref('')
  const showIndexPanel = ref(false)
  const indexPanelLoaded = ref(false)
  const showIndexedFiles = ref(false)

  // ─── Query ────────────────────────────────────────────────────────
  const handleSseEvent = (payload) => {
    if (payload.message) queryStageMessage.value = payload.message
    if (payload.sources) sources.value = payload.sources

    if (payload.stage === 'done') {
      answer.value = payload.answer || ''
      answerDownloadId.value = payload.download_id || ''
      answerFilename.value = payload.filename || 'rag_answer.md'
      isQuerying.value = false
      queryStageMessage.value = ''
    } else if (payload.stage === 'error') {
      queryError.value = payload.message || '查询失败'
      isQuerying.value = false
      queryStageMessage.value = ''
    }
  }

  const submitQuery = async () => {
    const q = question.value.trim()
    if (!q) return

    isQuerying.value = true
    queryError.value = ''
    answer.value = ''
    answerDownloadId.value = ''
    answerFilename.value = ''
    sources.value = []
    hasQueried.value = true
    queryStageMessage.value = ''

    try {
      const stream = await ragApi.queryStream({
        question: q,
        filter_authors: selectedAuthors.value,
        llm_profile: selectedLlmProfile.value || null,
        api_key: getApiKey() || null,
        deepseek_api_key: getDeepseekApiKey() || null,
        ...getCustomLlmPayload()
      })
      const reader = stream.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done })

        let eventBoundary = buffer.indexOf('\n\n')
        while (eventBoundary !== -1) {
          const rawEvent = buffer.slice(0, eventBoundary)
          buffer = buffer.slice(eventBoundary + 2)

          for (const line of rawEvent.split('\n')) {
            if (!line.startsWith('data: ')) continue
            try {
              handleSseEvent(JSON.parse(line.slice(6)))
            } catch {}
          }

          eventBoundary = buffer.indexOf('\n\n')
        }

        if (done) break
      }

      if (isQuerying.value) {
        throw new Error('连接中断，请重试')
      }
    } catch (err) {
      queryError.value =
        err instanceof Error ? err.message : '连接失败，请检查后端服务'
      isQuerying.value = false
      queryStageMessage.value = ''
    }
  }

  // ─── Index management ─────────────────────────────────────────────
  const toggleIndexPanel = async () => {
    showIndexPanel.value = !showIndexPanel.value
    if (showIndexPanel.value && !indexPanelLoaded.value) {
      await loadIndexStatus()
      indexPanelLoaded.value = true
    }
  }

  const loadIndexStatus = async () => {
    isLoadingStatus.value = true
    indexStatusError.value = ''
    try {
      const data = await ragApi.getStatus()
      indexStatus.value = data
    } catch (err) {
      indexStatus.value = null
      indexStatusError.value =
        err instanceof Error ? err.message : '获取状态失败'
    } finally {
      isLoadingStatus.value = false
    }
  }

  const runIndexAll = async (force) => {
    isIndexing.value = true
    indexingForce.value = force
    indexMessage.value = ''
    indexError.value = ''
    try {
      const data = await ragApi.indexAll(force)
      await loadIndexStatus()
      const pending = indexStatus.value?.pending_index_runs
      const pendingText = Number.isFinite(pending)
        ? `，剩余 ${pending} 条未索引`
        : ''
      indexMessage.value = `${data.succeeded} 条成功，${data.failed} 条失败，共 ${data.total_runs} 条${pendingText}`
    } catch (err) {
      indexError.value = err instanceof Error ? err.message : '索引失败'
    } finally {
      isIndexing.value = false
      indexingForce.value = false
    }
  }

  const renderedAnswer = computed(() => {
    if (!answer.value) return ''
    return renderMarkdown(answer.value)
  })
  const answerDownloadItems = computed(() =>
    answerDownloadId.value
      ? [
          {
            kind: 'rag_answer',
            key: answerDownloadId.value,
            url: `/api/download/${answerDownloadId.value}`,
            filename: answerFilename.value
          }
        ]
      : []
  )

  const onAnswerClick = (e) => {
    const badge = e.target.closest('.citation-ref')
    if (!badge) return
    const target = badge.dataset.target || ''
    const targetNumber = Number(target.replace('source-', ''))
    const el =
      document.getElementById(target) ||
      (Number.isFinite(targetNumber)
        ? document.getElementById(`source-${targetNumber - 1}`)
        : null)
    el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    el?.classList.add('source-highlight')
    setTimeout(() => el?.classList.remove('source-highlight'), 1400)
  }
</script>

<template>
  <div class="rag-root">
    <RagSearchPanel
      :question="question"
      :selected-authors="selectedAuthors"
      :author-options="authorOptions"
      :selected-profile="selectedLlmProfile"
      :profiles="llmProfiles"
      :querying="isQuerying"
      :stage-message="queryStageMessage"
      :error="queryError"
      @update:question="question = $event"
      @update:selected-authors="selectedAuthors = $event"
      @update:selected-profile="selectedLlmProfile = $event"
      @submit="submitQuery"
    />

    <div v-if="!hasQueried" class="empty-state">
      <div><Sparkles :size="28" /></div>
      <p>输入问题，开始检索</p>
      <span>AI 会从你的历史转录视频中找到相关内容片段，并给出综合回答。</span>
    </div>

    <RagAnswerPanel
      v-if="answer"
      :answer-html="renderedAnswer"
      :download-items="answerDownloadItems"
      @answer-click="onAnswerClick"
    />

    <RagSources v-if="sources.length" :sources="sources" />

    <RagIndexPanel
      :open="showIndexPanel"
      :status="indexStatus"
      :loading="isLoadingStatus"
      :indexing="isIndexing"
      :indexing-force="indexingForce"
      :status-error="indexStatusError"
      :message="indexMessage"
      :error="indexError"
      @toggle="toggleIndexPanel"
      @refresh="loadIndexStatus"
      @index="runIndexAll"
    />
  </div>
</template>

<style scoped>
  .rag-root {
    display: flex;
    flex-direction: column;
    gap: 20px;
    max-width: 800px;
    margin: 0 auto;
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 40px 24px;
    color: var(--text-muted);
    text-align: center;
  }

  .empty-state div {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 56px;
    height: 56px;
    border-radius: 8px;
    background: var(--brand-soft);
    color: var(--brand);
  }

  .empty-state p {
    margin: 0;
    color: var(--text-soft);
    font-size: 0.96rem;
    font-weight: 700;
  }

  .empty-state span {
    max-width: 360px;
    font-size: 0.84rem;
    line-height: 1.6;
  }
</style>
