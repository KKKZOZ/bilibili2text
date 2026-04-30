<script setup>
  import { ref, computed, onMounted } from 'vue'
  import { useConversion } from '../composables/useConversion'
  import { renderMarkdown } from '../utils/markdown'
  import {
    AlertCircle,
    BookMarked,
    Brain,
    ChevronDown,
    Database,
    Download,
    ExternalLink,
    FileText,
    Layers,
    LoaderCircle,
    RefreshCw,
    Search,
    Sparkles,
    Type,
    Users
  } from 'lucide-vue-next'

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

  const { convertAndDownload, isConverting, download } = useConversion()

  const fancyHtmlGenerating = ref(false)
  const fancyHtmlError = ref('')

  const generateFancyHtml = async () => {
    if (!answerDownloadId.value || fancyHtmlGenerating.value) return
    fancyHtmlGenerating.value = true
    fancyHtmlError.value = ''
    try {
      const resp = await fetch('/api/summary/fancy-html', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ download_id: answerDownloadId.value })
      })
      const data = await resp.json()
      if (!resp.ok) throw new Error(data.detail || '生成 Fancy HTML 失败')
      download(data.download_url, data.filename)
    } catch (err) {
      fancyHtmlError.value =
        err instanceof Error ? err.message : '生成 Fancy HTML 失败'
    } finally {
      fancyHtmlGenerating.value = false
    }
  }

  // ─── LLM profile ──────────────────────────────────────────────────
  const llmProfiles = ref([])
  const selectedLlmProfile = ref('')

  const loadLlmProfiles = async () => {
    try {
      const resp = await fetch('/api/summarize-profiles')
      const data = await resp.json()
      llmProfiles.value = data.profiles || []
      if (!selectedLlmProfile.value && data.selected_profile) {
        selectedLlmProfile.value = data.selected_profile
      }
    } catch {}
  }

  // ─── Author filter ────────────────────────────────────────────────
  const authorList = ref([])
  const selectedAuthors = ref([])
  const showAuthorFilter = ref(false)
  const authorsLoaded = ref(false)

  const filterLabel = computed(() =>
    selectedAuthors.value.length === 0
      ? '全部 UP主'
      : `已选 ${selectedAuthors.value.length} 位 UP主`
  )

  const loadAuthors = async () => {
    if (authorsLoaded.value) return
    try {
      const resp = await fetch('/api/rag/authors')
      const data = await resp.json()
      authorList.value = data.authors || []
      authorsLoaded.value = true
    } catch {}
  }

  const toggleAuthorFilter = async () => {
    showAuthorFilter.value = !showAuthorFilter.value
    if (showAuthorFilter.value) await loadAuthors()
  }

  const toggleAuthor = (author) => {
    const idx = selectedAuthors.value.indexOf(author)
    if (idx >= 0) selectedAuthors.value.splice(idx, 1)
    else selectedAuthors.value.push(author)
  }

  const isAuthorSelected = (author) => selectedAuthors.value.includes(author)

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
  const submitQuery = () => {
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

    const params = new URLSearchParams({ question: q })
    if (selectedAuthors.value.length > 0) {
      params.set('filter_authors', selectedAuthors.value.join(','))
    }
    if (selectedLlmProfile.value) {
      params.set('llm_profile', selectedLlmProfile.value)
    }
    const url = `/api/rag/query-stream?${params}`
    const es = new EventSource(url)

    es.onmessage = (event) => {
      let data
      try {
        data = JSON.parse(event.data)
      } catch {
        return
      }

      if (data.message) queryStageMessage.value = data.message
      if (data.sources) sources.value = data.sources

      if (data.stage === 'done') {
        answer.value = data.answer || ''
        answerDownloadId.value = data.download_id || ''
        answerFilename.value = data.filename || 'rag_answer.md'
        isQuerying.value = false
        queryStageMessage.value = ''
        es.close()
      } else if (data.stage === 'error') {
        queryError.value = data.message || '查询失败'
        isQuerying.value = false
        queryStageMessage.value = ''
        es.close()
      }
    }

    es.onerror = () => {
      if (isQuerying.value) {
        queryError.value = '连接失败，请检查后端服务'
        isQuerying.value = false
        queryStageMessage.value = ''
      }
      es.close()
    }
  }

  const onKeydown = (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      submitQuery()
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
      const resp = await fetch('/api/rag/status')
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || `请求失败（HTTP ${resp.status}）`)
      }
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
      const resp = await fetch('/api/rag/index-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force })
      })
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || `请求失败（HTTP ${resp.status}）`)
      }
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

  const scorePercent = (score) => Math.round(score * 100)

  const bilibiliUrl = (bvid) =>
    bvid ? `https://www.bilibili.com/video/${bvid}` : null

  const scoreColor = (score) => {
    const pct = score * 100
    if (pct >= 70) return '#0d9488'
    if (pct >= 45) return '#0284c7'
    return '#64748b'
  }

  const indexedFileKindLabel = (kind) => {
    if (kind === 'summary') return 'LLM 总结'
    if (kind === 'markdown') return '转录原文'
    return kind || '未知类型'
  }

  onMounted(() => {
    loadLlmProfiles()
  })
</script>

<template>
  <div class="rag-root">
    <!-- ══════════════════════════════════════════════════════════
         SEARCH PANEL
    ══════════════════════════════════════════════════════════ -->
    <article class="panel search-panel">
      <header class="search-header">
        <div class="header-badge">
          <Brain :size="13" />
          <span>知识库问答</span>
        </div>
        <h1>跨视频内容检索</h1>
        <p>
          基于历史转录内容，用自然语言提问，AI
          从所有视频中检索相关片段并生成回答。
        </p>
      </header>

      <div class="search-box">
        <div class="textarea-wrap" :class="{ focused: isQuerying }">
          <textarea
            v-model="question"
            class="question-input"
            placeholder="关于中国民航信息网络,你知道多少"
            rows="3"
            :disabled="isQuerying"
            @keydown="onKeydown"
          />
          <span class="kbd-hint">Ctrl + Enter 提交</span>
        </div>
        <div class="filters-row">
          <!-- Author filter -->
          <div class="author-filter">
            <button class="author-filter-toggle" @click="toggleAuthorFilter">
              <Users :size="13" />
              <span>{{ filterLabel }}</span>
              <ChevronDown
                :size="13"
                class="toggle-chevron"
                :class="{ open: showAuthorFilter }"
              />
            </button>
            <transition name="slide-down">
              <div v-if="showAuthorFilter" class="author-list">
                <label
                  v-for="item in authorList"
                  :key="item.author"
                  class="author-item"
                  :class="{ active: isAuthorSelected(item.author) }"
                >
                  <input
                    type="checkbox"
                    :checked="isAuthorSelected(item.author)"
                    @change="toggleAuthor(item.author)"
                  />
                  <span class="author-name">{{ item.author }}</span>
                  <span class="author-count"
                    >{{ item.indexed_run_count }} 个视频</span
                  >
                </label>
                <p v-if="authorList.length === 0" class="author-empty">
                  暂无已索引的 UP主
                </p>
                <button
                  v-if="selectedAuthors.length > 0"
                  class="author-clear"
                  @click="selectedAuthors.splice(0)"
                >
                  清除筛选
                </button>
              </div>
            </transition>
          </div>

          <!-- LLM profile selector -->
          <div v-if="llmProfiles.length > 0" class="llm-profile-row">
            <label class="llm-profile-label" for="rag-llm-profile">模型</label>
            <select
              id="rag-llm-profile"
              v-model="selectedLlmProfile"
              class="llm-profile-select"
              :disabled="isQuerying"
            >
              <option v-for="p in llmProfiles" :key="p.name" :value="p.name">
                {{ p.name }} ({{ p.model }})
              </option>
            </select>
          </div>
        </div>

        <button
          class="submit search-submit"
          :disabled="isQuerying || !question.trim()"
          @click="submitQuery"
        >
          <LoaderCircle v-if="isQuerying" :size="16" class="spin" />
          <Search v-else :size="16" />
          {{ isQuerying ? queryStageMessage || '检索中…' : '提交问题' }}
        </button>
      </div>

      <p v-if="queryError" class="inline-error">
        <AlertCircle :size="15" />
        {{ queryError }}
      </p>
    </article>

    <!-- ══════════════════════════════════════════════════════════
         EMPTY STATE
    ══════════════════════════════════════════════════════════ -->
    <div v-if="!hasQueried" class="empty-state">
      <div class="empty-icon-wrap">
        <Sparkles :size="28" />
      </div>
      <p class="empty-title">输入问题，开始检索</p>
      <p class="empty-sub">
        AI 会从你的历史转录视频中找到相关内容片段，并给出综合回答。
      </p>
    </div>

    <!-- ══════════════════════════════════════════════════════════
         ANSWER
    ══════════════════════════════════════════════════════════ -->
    <transition name="fade-up">
      <article v-if="answer" class="panel answer-panel">
        <div class="answer-header-row">
          <div class="answer-label">
            <Sparkles :size="14" />
            <span>AI 回答</span>
          </div>
          <div v-if="answerDownloadId" class="answer-dl-actions">
            <button
              class="answer-dl-btn"
              :disabled="false"
              @click="
                download(`/api/download/${answerDownloadId}`, answerFilename)
              "
            >
              <FileText :size="13" />
              <span>MD</span>
            </button>
            <button
              class="answer-dl-btn"
              :disabled="isConverting(answerDownloadId, 'txt')"
              @click="
                convertAndDownload(answerDownloadId, answerFilename, 'txt')
              "
            >
              <LoaderCircle
                v-if="isConverting(answerDownloadId, 'txt')"
                :size="13"
                class="spin"
              />
              <Type v-else :size="13" />
              <span>TXT</span>
            </button>
            <button
              class="answer-dl-btn"
              :disabled="isConverting(answerDownloadId, 'pdf')"
              @click="
                convertAndDownload(answerDownloadId, answerFilename, 'pdf')
              "
            >
              <LoaderCircle
                v-if="isConverting(answerDownloadId, 'pdf')"
                :size="13"
                class="spin"
              />
              <Download v-else :size="13" />
              <span>PDF</span>
            </button>
            <button
              class="answer-dl-btn answer-dl-btn-fancy"
              :disabled="fancyHtmlGenerating"
              @click="generateFancyHtml"
            >
              <LoaderCircle
                v-if="fancyHtmlGenerating"
                :size="13"
                class="spin"
              />
              <FileText v-else :size="13" />
              <span>Fancy HTML</span>
            </button>
          </div>
          <p
            v-if="fancyHtmlError"
            class="inline-error"
            style="margin-top: 6px; font-size: 0.82rem"
          >
            <AlertCircle :size="13" />
            {{ fancyHtmlError }}
          </p>
        </div>
        <!-- eslint-disable-next-line vue/no-v-html -->
        <div
          class="answer-text"
          v-html="renderedAnswer"
          @click="onAnswerClick"
        />
      </article>
    </transition>

    <!-- ══════════════════════════════════════════════════════════
         SOURCES
    ══════════════════════════════════════════════════════════ -->
    <transition name="fade-up">
      <section v-if="sources.length" class="sources-section">
        <h3 class="sources-heading">
          <BookMarked :size="15" />
          <span>参考来源</span>
          <span class="sources-count">{{ sources.length }}</span>
        </h3>
        <div class="sources-grid">
          <a
            v-for="(src, i) in sources"
            :key="i"
            :id="`source-${i}`"
            :href="bilibiliUrl(src.bvid)"
            target="_blank"
            rel="noopener noreferrer"
            class="source-card"
            :class="{ 'no-link': !bilibiliUrl(src.bvid) }"
          >
            <div class="source-card-top">
              <span class="source-index">{{ i + 1 }}</span>
              <div class="source-meta">
                <span class="source-title">{{
                  src.title || src.bvid || '未知视频'
                }}</span>
                <span v-if="src.bvid" class="source-bvid">
                  {{ src.bvid }}
                  <ExternalLink :size="11" />
                </span>
              </div>
              <div
                class="score-pill"
                :style="{ '--score-color': scoreColor(src.score) }"
              >
                {{ scorePercent(src.score) }}%
              </div>
            </div>
            <div class="score-bar-track">
              <div
                class="score-bar-fill"
                :style="{
                  width: scorePercent(src.score) + '%',
                  background: scoreColor(src.score)
                }"
              />
            </div>
            <p class="source-excerpt">
              {{ src.text.slice(0, 220) }}{{ src.text.length > 220 ? '…' : '' }}
            </p>
          </a>
        </div>
      </section>
    </transition>

    <!-- ══════════════════════════════════════════════════════════
         INDEX MANAGEMENT
    ══════════════════════════════════════════════════════════ -->
    <section class="index-section">
      <button class="index-toggle" @click="toggleIndexPanel">
        <Database :size="14" />
        <span>索引管理</span>
        <ChevronDown
          :size="14"
          class="toggle-chevron"
          :class="{ open: showIndexPanel }"
        />
      </button>

      <transition name="slide-down">
        <div v-if="showIndexPanel" class="index-body">
          <!-- Status row -->
          <div v-if="isLoadingStatus" class="status-loading">
            <LoaderCircle :size="14" class="spin" />
            <span>加载中…</span>
          </div>
          <div v-else-if="indexStatus" class="stats-grid">
            <div class="stat-card">
              <Layers :size="18" class="stat-icon" />
              <span class="stat-value">{{
                indexStatus.total_indexed_runs
              }}</span>
              <span class="stat-label">已索引视频</span>
            </div>
            <div class="stat-card">
              <AlertCircle :size="18" class="stat-icon" />
              <span class="stat-value">{{
                indexStatus.pending_index_runs
              }}</span>
              <span class="stat-label">未索引视频</span>
            </div>
            <div class="stat-card">
              <Database :size="18" class="stat-icon" />
              <span class="stat-value">{{ indexStatus.total_chunks }}</span>
              <span class="stat-label">向量片段</span>
            </div>
            <button class="refresh-btn" title="刷新" @click="loadIndexStatus">
              <RefreshCw :size="14" :class="{ spin: isLoadingStatus }" />
            </button>
          </div>
          <p v-else-if="indexStatusError" class="inline-error">
            <AlertCircle :size="14" />{{ indexStatusError }}
          </p>

          <!-- Result message -->
          <p v-if="indexMessage" class="index-ok">✓ {{ indexMessage }}</p>
          <p v-if="indexError" class="inline-error">
            <AlertCircle :size="14" />{{ indexError }}
          </p>
          <p v-if="indexStatus" class="index-summary">
            历史视频共 {{ indexStatus.total_history_runs }} 条，当前还有
            {{ indexStatus.pending_index_runs }} 条未索引。
          </p>
          <div v-if="indexStatus?.indexed_items?.length" class="indexed-files">
            <button
              class="indexed-files-toggle"
              @click="showIndexedFiles = !showIndexedFiles"
            >
              <span>当前已索引文件</span>
              <span class="indexed-files-toggle-meta">
                {{ indexStatus.indexed_items.length }} 条
                <ChevronDown
                  :size="14"
                  class="toggle-chevron"
                  :class="{ open: showIndexedFiles }"
                />
              </span>
            </button>
            <div v-if="showIndexedFiles" class="indexed-file-list">
              <div
                v-for="item in indexStatus.indexed_items"
                :key="item.run_id"
                class="indexed-file-item"
              >
                <div class="indexed-file-main">
                  <span class="indexed-file-title">{{
                    item.title || item.bvid || item.run_id
                  }}</span>
                  <span v-if="item.author" class="indexed-file-author">{{
                    item.author
                  }}</span>
                </div>
                <div class="indexed-file-meta">
                  <span
                    class="indexed-file-kind"
                    :class="{
                      'indexed-file-kind-summary':
                        item.source_kind === 'summary',
                      'indexed-file-kind-markdown':
                        item.source_kind === 'markdown'
                    }"
                    >{{ indexedFileKindLabel(item.source_kind) }}</span
                  >
                  <span class="indexed-file-name">{{
                    item.source_filename
                  }}</span>
                  <span class="indexed-file-chunks"
                    >{{ item.chunk_count }} chunks</span
                  >
                </div>
              </div>
            </div>
          </div>

          <!-- Actions -->
          <div class="index-actions">
            <button
              class="idx-btn idx-btn-outline"
              :disabled="isIndexing"
              @click="runIndexAll(false)"
            >
              <LoaderCircle
                v-if="isIndexing && !indexingForce"
                :size="14"
                class="spin"
              />
              增量索引
            </button>
            <button
              class="idx-btn idx-btn-solid"
              :disabled="isIndexing"
              @click="runIndexAll(true)"
            >
              <LoaderCircle
                v-if="isIndexing && indexingForce"
                :size="14"
                class="spin"
              />
              重建全部
            </button>
          </div>
          <p class="index-hint">
            「增量」跳过已索引的视频；「重建全部」清空后重新索引所有历史记录。
          </p>
        </div>
      </transition>
    </section>
  </div>
</template>

<style scoped>
  /* ─── Root layout ───────────────────────────────────────────────── */
  .rag-root {
    max-width: 800px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  /* ─── Search panel ──────────────────────────────────────────────── */
  .search-panel {
    padding: clamp(20px, 4vw, 36px) clamp(20px, 4vw, 40px);
  }

  .search-header {
    margin-bottom: 22px;
  }

  .header-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 10px;
    border-radius: 99px;
    background: var(--brand-soft, #e6fffb);
    color: var(--brand-strong, #0f766e);
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.02em;
    margin-bottom: 10px;
  }

  .search-header h1 {
    margin: 0 0 6px;
    font-size: clamp(1.2rem, 2.5vw, 1.5rem);
    font-weight: 800;
    color: var(--text-main, #0f172a);
    line-height: 1.25;
  }

  .search-header p {
    margin: 0;
    font-size: 0.88rem;
    color: var(--text-muted, #64748b);
    line-height: 1.6;
  }

  /* ─── Textarea ──────────────────────────────────────────────────── */
  .search-box {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .textarea-wrap {
    position: relative;
    border: 1.5px solid var(--panel-border, rgba(148, 163, 184, 0.28));
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.9);
    transition:
      border-color 0.2s,
      box-shadow 0.2s;
  }

  .textarea-wrap:focus-within {
    border-color: var(--brand, #0d9488);
    box-shadow: 0 0 0 4px rgba(13, 148, 136, 0.1);
  }

  .question-input {
    display: block;
    width: 100%;
    resize: none;
    padding: 14px 16px 32px;
    border: none;
    border-radius: 14px;
    background: transparent;
    font-size: 0.94rem;
    font-family: inherit;
    color: var(--text-main, #0f172a);
    line-height: 1.6;
    box-sizing: border-box;
    outline: none;
  }

  .question-input::placeholder {
    color: var(--text-muted, #94a3b8);
  }

  .question-input:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .kbd-hint {
    position: absolute;
    bottom: 10px;
    right: 14px;
    font-size: 0.72rem;
    color: var(--text-muted, #94a3b8);
    pointer-events: none;
  }

  .search-submit {
    margin-top: 0;
    align-self: flex-end;
    min-width: 130px;
  }

  /* ─── Empty state ───────────────────────────────────────────────── */
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 40px 24px;
    text-align: center;
  }

  .empty-icon-wrap {
    width: 56px;
    height: 56px;
    border-radius: 16px;
    background: var(--brand-soft, #e6fffb);
    color: var(--brand, #0d9488);
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 4px;
  }

  .empty-title {
    margin: 0;
    font-size: 0.96rem;
    font-weight: 700;
    color: var(--text-soft, #334155);
  }

  .empty-sub {
    margin: 0;
    font-size: 0.84rem;
    color: var(--text-muted, #64748b);
    max-width: 360px;
    line-height: 1.6;
  }

  /* ─── Answer panel ──────────────────────────────────────────────── */
  .answer-panel {
    padding: clamp(18px, 3vw, 28px) clamp(18px, 3vw, 32px);
    border-left: 3px solid var(--brand, #0d9488);
  }

  .answer-header-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 12px;
  }

  .answer-label {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 0.74rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--brand, #0d9488);
  }

  .answer-dl-actions {
    display: flex;
    gap: 6px;
  }

  .answer-dl-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 10px;
    border: 1.5px solid var(--panel-border, rgba(148, 163, 184, 0.28));
    border-radius: 7px;
    background: rgba(255, 255, 255, 0.8);
    color: var(--text-soft, #334155);
    font-size: 0.78rem;
    font-weight: 700;
    cursor: pointer;
    transition:
      border-color 0.15s,
      background 0.15s,
      color 0.15s;
  }

  .answer-dl-btn:hover:not(:disabled) {
    border-color: var(--brand, #0d9488);
    color: var(--brand-strong, #0f766e);
    background: var(--brand-soft, #e6fffb);
  }

  .answer-dl-btn:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .answer-dl-btn-fancy {
    border-color: rgba(249, 115, 22, 0.35);
    color: #c2410c;
  }

  .answer-dl-btn-fancy:hover:not(:disabled) {
    border-color: #f97316;
    color: #c2410c;
    background: rgba(249, 115, 22, 0.08);
  }

  .answer-text {
    margin: 0;
    font-size: 0.94rem;
    line-height: 1.8;
    color: var(--text-main, #0f172a);
  }

  .answer-text :deep(h1),
  .answer-text :deep(h2),
  .answer-text :deep(h3),
  .answer-text :deep(h4) {
    margin: 0.9em 0 0.45em;
    line-height: 1.35;
    color: var(--text-main, #0f172a);
  }

  .answer-text :deep(h1) {
    font-size: 1.28rem;
  }

  .answer-text :deep(h2) {
    font-size: 1.06rem;
  }

  .answer-text :deep(h3) {
    font-size: 0.98rem;
  }

  .answer-text :deep(p),
  .answer-text :deep(ol),
  .answer-text :deep(ul),
  .answer-text :deep(blockquote),
  .answer-text :deep(pre) {
    margin: 0.7em 0;
  }

  .answer-text :deep(ol),
  .answer-text :deep(ul) {
    padding-left: 1.4em;
  }

  .answer-text :deep(li + li) {
    margin-top: 0.3em;
  }

  .answer-text :deep(blockquote) {
    margin-left: 0;
    padding: 10px 14px;
    border-left: 3px solid rgba(13, 148, 136, 0.28);
    background: rgba(240, 253, 250, 0.8);
    border-radius: 0 12px 12px 0;
    color: var(--text-soft, #334155);
  }

  .answer-text :deep(code) {
    padding: 0.15em 0.4em;
    border-radius: 6px;
    background: rgba(148, 163, 184, 0.16);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.88em;
  }

  .answer-text :deep(pre) {
    overflow: auto;
    padding: 12px 14px;
    border-radius: 14px;
    background: #0f172a;
    color: #e2e8f0;
  }

  .answer-text :deep(pre code) {
    padding: 0;
    background: transparent;
    color: inherit;
  }

  .answer-text :deep(a) {
    color: var(--brand-strong, #0f766e);
    text-decoration: none;
  }

  .answer-text :deep(a:hover) {
    text-decoration: underline;
  }

  .answer-text :deep(table) {
    display: block;
    width: 100%;
    max-width: 100%;
    border-collapse: collapse;
    margin: 0.9em 0;
    overflow-x: auto;
    border-radius: 12px;
    border: 1px solid rgba(148, 163, 184, 0.24);
  }

  .answer-text :deep(th),
  .answer-text :deep(td) {
    padding: 10px 12px;
    border-bottom: 1px solid rgba(148, 163, 184, 0.18);
    text-align: left;
    vertical-align: top;
  }

  .answer-text :deep(th) {
    background: rgba(241, 245, 249, 0.9);
    font-size: 0.8rem;
    font-weight: 700;
    color: var(--text-soft, #334155);
  }

  .answer-text :deep(td) {
    font-size: 0.85rem;
  }

  :deep(.citation-ref) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 18px;
    height: 18px;
    padding: 0 4px;
    margin: 0 1px;
    border-radius: 5px;
    background: var(--brand-soft, #e6fffb);
    color: var(--brand-strong, #0f766e);
    font-size: 0.72rem;
    font-weight: 700;
    cursor: pointer;
    vertical-align: middle;
    transition:
      background 0.15s,
      color 0.15s;
    user-select: none;
  }

  :deep(.citation-ref:hover) {
    background: var(--brand, #0d9488);
    color: #fff;
  }

  .source-card {
    transition:
      transform 0.18s ease,
      box-shadow 0.18s ease,
      border-color 0.18s ease,
      background 0.3s ease;
  }

  .source-highlight {
    border-color: var(--brand, #0d9488) !important;
    background: var(--brand-soft, #e6fffb) !important;
    box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.18) !important;
  }

  /* ─── Sources ───────────────────────────────────────────────────── */
  .sources-section {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .sources-heading {
    display: flex;
    align-items: center;
    gap: 7px;
    margin: 0;
    font-size: 0.86rem;
    font-weight: 700;
    color: var(--text-soft, #334155);
  }

  .sources-count {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 20px;
    height: 20px;
    padding: 0 6px;
    border-radius: 99px;
    background: var(--brand-soft, #e6fffb);
    color: var(--brand-strong, #0f766e);
    font-size: 0.74rem;
    font-weight: 700;
  }

  .sources-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 12px;
  }

  .source-card {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 14px 16px;
    background: rgba(255, 255, 255, 0.82);
    border: 1px solid var(--panel-border, rgba(148, 163, 184, 0.28));
    border-radius: 16px;
    text-decoration: none;
    transition:
      transform 0.18s ease,
      box-shadow 0.18s ease,
      border-color 0.18s ease;
    cursor: pointer;
  }

  .source-card:hover:not(.no-link) {
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.1);
    border-color: var(--brand, #0d9488);
  }

  .source-card.no-link {
    cursor: default;
  }

  .source-card-top {
    display: flex;
    align-items: flex-start;
    gap: 10px;
  }

  .source-index {
    flex-shrink: 0;
    width: 22px;
    height: 22px;
    border-radius: 7px;
    background: var(--brand-soft, #e6fffb);
    color: var(--brand-strong, #0f766e);
    font-size: 0.74rem;
    font-weight: 800;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-top: 1px;
  }

  .source-meta {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .source-title {
    font-size: 0.86rem;
    font-weight: 700;
    color: var(--text-main, #0f172a);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .source-bvid {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-size: 0.76rem;
    color: var(--brand, #0d9488);
  }

  .score-pill {
    flex-shrink: 0;
    padding: 2px 8px;
    border-radius: 99px;
    font-size: 0.74rem;
    font-weight: 700;
    background: color-mix(in srgb, var(--score-color) 12%, transparent);
    color: var(--score-color);
  }

  .score-bar-track {
    height: 3px;
    border-radius: 99px;
    background: rgba(148, 163, 184, 0.18);
    overflow: hidden;
  }

  .score-bar-fill {
    height: 100%;
    border-radius: 99px;
    transition: width 0.6s cubic-bezier(0.22, 1, 0.36, 1);
  }

  .source-excerpt {
    margin: 0;
    font-size: 0.82rem;
    color: var(--text-muted, #64748b);
    line-height: 1.6;
  }

  /* ─── LLM profile selector ──────────────────────────────────────── */
  .filters-row {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }

  .llm-profile-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: 1 1 320px;
    min-width: 260px;
  }

  .llm-profile-label {
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--text-muted, #64748b);
    white-space: nowrap;
  }

  .llm-profile-select {
    flex: 1;
    min-width: 0;
    padding: 6px 10px;
    border: 1.5px solid var(--panel-border, rgba(148, 163, 184, 0.28));
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.9);
    color: var(--text-soft, #334155);
    font-size: 0.83rem;
    font-family: inherit;
    cursor: pointer;
    transition: border-color 0.18s;
  }

  .llm-profile-select:focus {
    outline: none;
    border-color: var(--brand, #0d9488);
    box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.1);
  }

  .llm-profile-select:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  /* ─── Author filter ─────────────────────────────────────────────── */
  .author-filter {
    position: relative;
    flex: 0 1 auto;
  }

  .author-filter-toggle {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    border: 1.5px solid var(--panel-border, rgba(148, 163, 184, 0.28));
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.8);
    color: var(--text-soft, #334155);
    font-size: 0.82rem;
    font-weight: 600;
    cursor: pointer;
    transition:
      border-color 0.18s,
      background 0.18s;
  }

  .author-filter-toggle:hover {
    border-color: var(--brand, #0d9488);
    color: var(--brand-strong, #0f766e);
    background: var(--brand-soft, #e6fffb);
  }

  .author-list {
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    z-index: 20;
    min-width: 240px;
    max-height: 260px;
    overflow-y: auto;
    background: #fff;
    border: 1.5px solid var(--panel-border, rgba(148, 163, 184, 0.28));
    border-radius: 12px;
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.1);
    padding: 6px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .author-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 10px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 0.84rem;
    color: var(--text-soft, #334155);
    transition: background 0.15s;
  }

  .author-item:hover {
    background: var(--brand-soft, #e6fffb);
  }

  .author-item.active {
    background: var(--brand-soft, #e6fffb);
    color: var(--brand-strong, #0f766e);
    font-weight: 600;
  }

  .author-item input[type='checkbox'] {
    accent-color: var(--brand, #0d9488);
    flex-shrink: 0;
  }

  .author-name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .author-count {
    font-size: 0.74rem;
    color: var(--text-muted, #94a3b8);
    flex-shrink: 0;
  }

  .author-empty {
    margin: 0;
    padding: 8px 10px;
    font-size: 0.82rem;
    color: var(--text-muted, #94a3b8);
    text-align: center;
  }

  .author-clear {
    margin-top: 4px;
    padding: 6px 10px;
    border: none;
    border-top: 1px solid var(--panel-border, rgba(148, 163, 184, 0.18));
    background: transparent;
    color: var(--text-muted, #94a3b8);
    font-size: 0.78rem;
    cursor: pointer;
    text-align: center;
    border-radius: 0 0 8px 8px;
    transition: color 0.15s;
  }

  .author-clear:hover {
    color: var(--brand-strong, #0f766e);
  }

  /* ─── Index section ─────────────────────────────────────────────── */
  .index-section {
    border: 1px solid var(--panel-border, rgba(148, 163, 184, 0.28));
    border-radius: 16px;
    overflow: hidden;
    background: rgba(255, 255, 255, 0.6);
    backdrop-filter: blur(8px);
  }

  .index-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 13px 18px;
    border: none;
    background: transparent;
    cursor: pointer;
    font-size: 0.86rem;
    font-weight: 700;
    color: var(--text-soft, #334155);
    text-align: left;
    transition: background 0.18s;
  }

  .index-toggle:hover {
    background: rgba(13, 148, 136, 0.04);
  }

  .toggle-chevron {
    margin-left: auto;
    transition: transform 0.25s cubic-bezier(0.22, 1, 0.36, 1);
    color: var(--text-muted, #94a3b8);
  }

  .toggle-chevron.open {
    transform: rotate(180deg);
  }

  .index-body {
    padding: 16px 18px 18px;
    border-top: 1px solid var(--panel-border, rgba(148, 163, 184, 0.28));
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  /* Stats */
  .status-loading {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.84rem;
    color: var(--text-muted, #64748b);
  }

  .stats-grid {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }

  .stat-card {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    background: var(--brand-soft, #e6fffb);
    border-radius: 12px;
    flex: 1;
    min-width: 120px;
  }

  .stat-icon {
    color: var(--brand, #0d9488);
    flex-shrink: 0;
  }

  .stat-value {
    font-size: 1.1rem;
    font-weight: 800;
    color: var(--text-main, #0f172a);
  }

  .stat-label {
    font-size: 0.76rem;
    color: var(--text-muted, #64748b);
  }

  .refresh-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 8px;
    border: 1px solid var(--panel-border, rgba(148, 163, 184, 0.28));
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.8);
    color: var(--text-muted, #64748b);
    cursor: pointer;
    transition: all 0.18s;
    flex-shrink: 0;
  }

  .refresh-btn:hover {
    border-color: var(--brand, #0d9488);
    color: var(--brand, #0d9488);
    background: var(--brand-soft, #e6fffb);
  }

  /* Actions */
  .index-actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }

  .idx-btn {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 0 18px;
    min-height: 38px;
    border-radius: 10px;
    font-size: 0.86rem;
    font-weight: 700;
    cursor: pointer;
    transition: all 0.18s ease;
    border: none;
  }

  .idx-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    transform: none !important;
  }

  .idx-btn-outline {
    border: 1.5px solid var(--brand, #0d9488);
    background: transparent;
    color: var(--brand-strong, #0f766e);
  }

  .idx-btn-outline:hover:not(:disabled) {
    background: var(--brand-soft, #e6fffb);
  }

  .idx-btn-solid {
    background: linear-gradient(135deg, #0d9488, #0284c7);
    color: #fff;
  }

  .idx-btn-solid:hover:not(:disabled) {
    transform: translateY(-1px);
    box-shadow: 0 8px 20px rgba(2, 132, 199, 0.28);
  }

  .index-ok {
    margin: 0;
    font-size: 0.84rem;
    color: var(--success, #16a34a);
    font-weight: 600;
  }

  .index-summary {
    margin: 0;
    font-size: 0.83rem;
    color: var(--text-soft, #475569);
    line-height: 1.5;
  }

  .indexed-files {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .indexed-files-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    font-size: 0.8rem;
    font-weight: 700;
    color: var(--text-soft, #334155);
  }

  .indexed-files-toggle {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    width: 100%;
    padding: 0;
    border: none;
    background: transparent;
    font-size: 0.8rem;
    font-weight: 700;
    color: var(--text-soft, #334155);
    cursor: pointer;
    text-align: left;
  }

  .indexed-files-toggle-meta {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--text-muted, #64748b);
  }

  .indexed-file-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-height: 280px;
    overflow: auto;
  }

  .indexed-file-item {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 10px 12px;
    border: 1px solid var(--panel-border, rgba(148, 163, 184, 0.24));
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.7);
  }

  .indexed-file-main {
    display: flex;
    align-items: baseline;
    gap: 8px;
    flex-wrap: wrap;
  }

  .indexed-file-title {
    font-size: 0.86rem;
    font-weight: 700;
    color: var(--text-main, #0f172a);
  }

  .indexed-file-author {
    font-size: 0.76rem;
    color: var(--text-muted, #64748b);
  }

  .indexed-file-meta {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
    font-size: 0.75rem;
    color: var(--text-muted, #64748b);
  }

  .indexed-file-kind {
    padding: 3px 8px;
    border-radius: 999px;
    font-weight: 700;
  }

  .indexed-file-kind-summary {
    background: var(--brand-soft, #e6fffb);
    color: var(--brand-strong, #0f766e);
  }

  .indexed-file-kind-markdown {
    background: rgba(245, 158, 11, 0.14);
    color: #b45309;
  }

  .indexed-file-name {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    color: var(--text-soft, #475569);
  }

  .indexed-file-chunks {
    white-space: nowrap;
  }

  .index-hint {
    margin: 0;
    font-size: 0.78rem;
    color: var(--text-muted, #64748b);
    line-height: 1.5;
  }

  /* ─── Transitions ───────────────────────────────────────────────── */
  .fade-up-enter-active {
    animation: fade-up-in 0.38s cubic-bezier(0.22, 1, 0.36, 1) both;
  }

  .fade-up-leave-active {
    animation: fade-up-in 0.22s cubic-bezier(0.22, 1, 0.36, 1) reverse both;
  }

  @keyframes fade-up-in {
    from {
      opacity: 0;
      transform: translateY(10px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .slide-down-enter-active {
    animation: slide-down-in 0.3s cubic-bezier(0.22, 1, 0.36, 1) both;
  }

  .slide-down-leave-active {
    animation: slide-down-in 0.2s cubic-bezier(0.22, 1, 0.36, 1) reverse both;
  }

  @keyframes slide-down-in {
    from {
      opacity: 0;
      transform: translateY(-6px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  /* ─── Responsive ────────────────────────────────────────────────── */
  @media (max-width: 640px) {
    .search-panel,
    .answer-panel {
      padding: 20px;
    }

    .filters-row,
    .llm-profile-row {
      align-items: stretch;
      flex-direction: column;
    }

    .llm-profile-row {
      flex-basis: auto;
      min-width: 0;
      width: 100%;
    }

    .author-filter,
    .author-filter-toggle,
    .author-list {
      width: 100%;
    }

    .author-list {
      min-width: 0;
    }

    .answer-header-row,
    .answer-dl-actions {
      align-items: stretch;
      flex-direction: column;
    }

    .answer-dl-btn {
      justify-content: center;
      width: 100%;
    }

    .sources-grid {
      grid-template-columns: 1fr;
    }

    .source-title {
      white-space: normal;
      overflow-wrap: anywhere;
    }

    .source-card-top {
      align-items: flex-start;
    }

    .search-submit {
      align-self: stretch;
    }
    .stats-grid {
      flex-direction: column;
    }
    .stat-card {
      width: 100%;
    }
    .index-actions {
      flex-direction: column;
    }
    .idx-btn {
      width: 100%;
      justify-content: center;
    }
  }
</style>
