<script setup>
import { computed, onMounted, ref } from 'vue';
import {
  AlertCircle,
  ArrowLeft,
  CalendarDays,
  Clock,
  FileText,
  LoaderCircle,
  Search,
  Trash2,
  User,
} from 'lucide-vue-next';
import FileList from './FileList.vue';
import { bilibiliVideoUrl, formatTime } from '../utils/fileUtils';

const props = defineProps({
  summaryPresets: {
    type: Array,
    required: true,
  },
  summaryDefaultPreset: {
    type: String,
    required: true,
  },
  selectedSummaryPreset: {
    type: String,
    required: true,
  },
  summaryProfiles: {
    type: Array,
    required: true,
  },
  selectedSummaryProfile: {
    type: String,
    required: true,
  },
});

const historyItems = ref([]);
const historyTotal = ref(0);
const historyPage = ref(1);
const historyPageSize = ref(20);
const historyHasMore = ref(false);
const historySearch = ref('');
const historyLoading = ref(false);
const historyError = ref('');
const historyDetail = ref(null);
const historyDetailLoading = ref(false);
const showHistoryDetail = ref(false);
const deleteConfirmRunId = ref(null);
const deleteLoading = ref(false);
const regenerateLoading = ref(false);
const regenerateError = ref('');
const regenerateSuccess = ref('');
const selectedHistorySummaryPreset = ref('');
const selectedHistorySummaryProfile = ref('');

let searchTimer = null;

const historyTotalPages = computed(() =>
  Math.max(1, Math.ceil(historyTotal.value / historyPageSize.value))
);
const showHistorySkeleton = computed(
  () => historyLoading.value && historyItems.value.length === 0
);

const historyDetailDownloadRows = computed(() => {
  const detail = historyDetail.value;
  if (!detail || !Array.isArray(detail.artifacts)) {
    return [];
  }
  return detail.artifacts.map((artifact, index) => ({
    kind: artifact.kind,
    key: `${artifact.download_url}-${artifact.filename}-${index}`,
    url: artifact.download_url,
    filename: artifact.filename,
    presetName: artifact.summary_preset || '',
    summaryProfile: artifact.summary_profile || '',
  }));
});

const loadHistory = async () => {
  historyLoading.value = true;
  historyError.value = '';
  try {
    const params = new URLSearchParams({
      page: String(historyPage.value),
      page_size: String(historyPageSize.value),
    });
    const q = historySearch.value.trim();
    if (q) {
      params.set('search', q);
    }
    const resp = await fetch(`/api/history?${params}`);
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.detail || '获取历史记录失败');
    }
    historyItems.value = data.items;
    historyTotal.value = data.total;
    historyHasMore.value = data.has_more;
  } catch (err) {
    historyError.value = err instanceof Error ? err.message : '获取历史记录失败';
  } finally {
    historyLoading.value = false;
  }
};

const loadHistoryDetail = async (runId) => {
  historyDetailLoading.value = true;
  showHistoryDetail.value = true;
  historyDetail.value = null;
  regenerateError.value = '';
  regenerateSuccess.value = '';
  selectedHistorySummaryPreset.value =
    props.selectedSummaryPreset || props.summaryDefaultPreset || '';
  selectedHistorySummaryProfile.value = props.selectedSummaryProfile || '';
  try {
    const resp = await fetch(`/api/history/${encodeURIComponent(runId)}`);
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.detail || '获取详情失败');
    }
    historyDetail.value = data;
  } catch (err) {
    historyError.value = err instanceof Error ? err.message : '获取详情失败';
    showHistoryDetail.value = false;
  } finally {
    historyDetailLoading.value = false;
  }
};

const regenerateSummary = async () => {
  const runId = historyDetail.value?.run_id;
  if (!runId) {
    return;
  }

  regenerateLoading.value = true;
  regenerateError.value = '';
  regenerateSuccess.value = '';
  try {
    const resp = await fetch(
      `/api/history/${encodeURIComponent(runId)}/regenerate-summary`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          summary_preset: selectedHistorySummaryPreset.value || null,
          summary_profile: selectedHistorySummaryProfile.value || null,
        }),
      }
    );
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.detail || '重新生成总结失败');
    }

    historyDetail.value = data;
    regenerateSuccess.value = '总结重新生成完成，文件已持久化到存储后端。';
    await loadHistory();
  } catch (err) {
    regenerateError.value =
      err instanceof Error ? err.message : '重新生成总结失败';
  } finally {
    regenerateLoading.value = false;
  }
};

const onSearchInput = () => {
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    historyPage.value = 1;
    loadHistory();
  }, 400);
};

const historyPrevPage = () => {
  if (historyPage.value > 1) {
    historyPage.value--;
    loadHistory();
  }
};

const historyNextPage = () => {
  if (historyHasMore.value) {
    historyPage.value++;
    loadHistory();
  }
};

const confirmDelete = (runId) => {
  deleteConfirmRunId.value = runId;
};

const cancelDelete = () => {
  deleteConfirmRunId.value = null;
};

const deleteHistory = async (runId) => {
  deleteLoading.value = true;
  try {
    const resp = await fetch(`/api/history/${encodeURIComponent(runId)}`, {
      method: 'DELETE',
    });
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.detail || '删除失败');
    }
    // Close detail view if currently viewing deleted item
    if (showHistoryDetail.value && historyDetail.value?.run_id === runId) {
      showHistoryDetail.value = false;
      historyDetail.value = null;
    }
    // Reload list
    await loadHistory();
    deleteConfirmRunId.value = null;
  } catch (err) {
    historyError.value = err instanceof Error ? err.message : '删除失败';
  } finally {
    deleteLoading.value = false;
  }
};

const onHistoryArtifactDeleted = (detail) => {
  historyDetail.value = detail;
  regenerateError.value = '';
  regenerateSuccess.value = '文件已删除。';
  loadHistory();
};

defineExpose({
  loadHistory,
});

onMounted(() => {
  loadHistory();
});
</script>

<template>
  <section class="history-layout">
    <!-- Detail View -->
    <article v-if="showHistoryDetail" class="panel panel-history">
      <header class="history-detail-header">
        <button class="detail-back" @click="showHistoryDetail = false">
          <ArrowLeft :size="16" />
          <span>返回列表</span>
        </button>
      </header>

      <div v-if="historyDetailLoading" class="history-detail-skeleton">
        <div class="history-skeleton-line skeleton-title"></div>
        <div class="history-skeleton-line skeleton-meta"></div>
        <div class="history-skeleton-line skeleton-meta short"></div>
        <div class="history-skeleton-block"></div>
        <div class="history-skeleton-block compact"></div>
      </div>

      <template v-else-if="historyDetail">
        <div class="detail-info">
          <div class="detail-header-row">
            <div>
              <h2 class="detail-title">{{ historyDetail.title }}</h2>
              <div class="detail-meta">
                <a
                  class="detail-bvid"
                  :href="bilibiliVideoUrl(historyDetail.bvid)"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {{ historyDetail.bvid }}
                </a>
                <span v-if="historyDetail.author" class="detail-author-tag">
                  <User :size="12" />
                  UP主 {{ historyDetail.author }}
                </span>
                <span v-if="historyDetail.pubdate" class="detail-pubdate">
                  <CalendarDays :size="14" />
                  发布时间：{{ historyDetail.pubdate }}
                </span>
                <span class="detail-time">
                  <Clock :size="14" />
                  转录时间：{{ formatTime(historyDetail.created_at) }}
                </span>
              </div>
            </div>
            <button
              class="delete-button"
              @click="confirmDelete(historyDetail.run_id)"
              :disabled="deleteLoading"
            >
              <Trash2 :size="16" />
              <span>删除</span>
            </button>
          </div>
        </div>

        <div class="history-regenerate">
          <div class="history-regenerate-head">
            <p class="history-regenerate-kicker">重新生成配置</p>
            <h3>总结参数</h3>
            <p>可切换模型配置与 preset，对同一条历史转录重新生成总结。</p>
          </div>

          <div class="history-regenerate-grid">
            <div class="summary-preset history-summary-preset">
              <label for="history-summary-profile-select">模型配置</label>
              <select
                id="history-summary-profile-select"
                v-model="selectedHistorySummaryProfile"
                class="preset-select history-preset-select"
                :disabled="regenerateLoading || summaryProfiles.length === 0"
              >
                <option v-if="summaryProfiles.length === 0" value="">
                  未获取到模型配置（将使用后端默认）
                </option>
                <option
                  v-for="profile in summaryProfiles"
                  :key="profile.name"
                  :value="profile.name"
                >
                  {{ profile.name }} ({{ profile.model }})
                </option>
              </select>
            </div>

            <div class="summary-preset history-summary-preset">
              <label for="history-summary-preset-select">总结模板</label>
              <select
                id="history-summary-preset-select"
                v-model="selectedHistorySummaryPreset"
                class="preset-select history-preset-select"
                :disabled="regenerateLoading || summaryPresets.length === 0"
              >
                <option v-if="summaryPresets.length === 0" value="">
                  未获取到 preset（将使用后端默认）
                </option>
                <option
                  v-for="preset in summaryPresets"
                  :key="preset.name"
                  :value="preset.name"
                >
                  {{ preset.label }}
                </option>
              </select>
            </div>
          </div>

          <button
            class="submit history-regenerate-button"
            type="button"
            :disabled="regenerateLoading"
            @click="regenerateSummary"
          >
            <LoaderCircle v-if="regenerateLoading" :size="16" class="spin" />
            <span>{{ regenerateLoading ? '生成中...' : '用当前配置重新生成总结' }}</span>
          </button>
          <p v-if="regenerateError" class="inline-error">
            <AlertCircle :size="16" />
            <span>{{ regenerateError }}</span>
          </p>
          <p v-if="regenerateSuccess" class="preset-hint">{{ regenerateSuccess }}</p>
        </div>

        <FileList
          class="detail-download-list"
          :items="historyDetailDownloadRows"
          :summary-presets="summaryPresets"
          :summary-default-preset="summaryDefaultPreset"
          :selected-summary-preset="selectedHistorySummaryPreset"
          :summary-profiles="summaryProfiles"
          :selected-summary-profile="selectedHistorySummaryProfile"
          :bvid="historyDetail.bvid"
          :history-run-id="historyDetail.run_id"
          title="文件列表"
          :filter-kinds="['markdown', 'summary', 'summary_no_table', 'summary_table_md', 'text', 'json', 'audio']"
          @artifact-deleted="onHistoryArtifactDeleted"
        />
      </template>
    </article>

    <!-- List View -->
    <article v-else class="panel panel-history">
      <header class="history-list-header">
        <h2>历史记录</h2>
        <div class="history-search-row">
          <Search :size="16" />
          <input
            v-model="historySearch"
            type="text"
            placeholder="搜索标题、BV 号或 UP 主..."
            @input="onSearchInput"
          />
        </div>
      </header>

      <div v-if="showHistorySkeleton" class="history-list-skeleton" aria-hidden="true">
        <div v-for="idx in 6" :key="idx" class="history-skeleton-item">
          <div class="history-skeleton-main">
            <div class="history-skeleton-line skeleton-title"></div>
            <div class="history-skeleton-line skeleton-bvid"></div>
            <div class="history-skeleton-line skeleton-meta"></div>
          </div>
          <div class="history-skeleton-action"></div>
        </div>
      </div>
      <p v-else-if="historyError" class="inline-error">
        <AlertCircle :size="16" />
        <span>{{ historyError }}</span>
      </p>
      <div v-else-if="historyItems.length === 0" class="history-empty">
        <FileText :size="32" />
        <p>暂无历史转录记录。</p>
      </div>

      <ul v-else class="history-list">
        <li
          v-for="item in historyItems"
          :key="item.run_id"
          class="history-item"
        >
          <div class="history-item-content" @click="loadHistoryDetail(item.run_id)">
            <div class="history-item-main">
              <span class="history-title">{{ item.title || item.bvid }}</span>
              <a
                class="history-bvid"
                :href="bilibiliVideoUrl(item.bvid)"
                target="_blank"
                rel="noopener noreferrer"
                @click.stop
              >
                {{ item.bvid }}
              </a>
              <span v-if="item.author" class="history-author-tag">
                <User :size="12" />
                UP主 {{ item.author }}
              </span>
            </div>
            <div class="history-item-meta">
              <span v-if="item.pubdate" class="history-pubdate">
                <CalendarDays :size="13" />
                发布时间：{{ item.pubdate }}
              </span>
              <span class="history-time">
                <Clock :size="13" />
                转录时间：{{ formatTime(item.created_at) }}
              </span>
              <span class="history-file-count">{{ item.file_count }} 个文件</span>
            </div>
          </div>
          <button
            class="history-item-delete"
            @click.stop="confirmDelete(item.run_id)"
            :disabled="deleteLoading"
            title="删除"
          >
            <Trash2 :size="16" />
          </button>
        </li>
      </ul>

      <!-- Pagination -->
      <div v-if="historyTotal > historyPageSize" class="history-pagination">
        <button :disabled="historyPage <= 1" @click="historyPrevPage">上一页</button>
        <span>第 {{ historyPage }} 页 / 共 {{ historyTotalPages }} 页</span>
        <button :disabled="!historyHasMore" @click="historyNextPage">下一页</button>
      </div>
    </article>

    <!-- Delete Confirmation Modal -->
    <div v-if="deleteConfirmRunId" class="modal-overlay" @click="cancelDelete">
      <div class="modal-content" @click.stop>
        <h3>确认删除</h3>
        <p>确定要删除这条历史记录吗？此操作将删除所有相关文件，且无法恢复。</p>
        <div class="modal-actions">
          <button class="cancel-button" @click="cancelDelete" :disabled="deleteLoading">
            取消
          </button>
          <button
            class="confirm-delete-button"
            @click="deleteHistory(deleteConfirmRunId)"
            :disabled="deleteLoading"
          >
            <Trash2 v-if="!deleteLoading" :size="16" />
            <LoaderCircle v-else :size="16" class="spin" />
            <span>{{ deleteLoading ? '删除中...' : '确认删除' }}</span>
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* ─── Layout & Panel variant ─────────────────────────────────── */

.history-layout {
  position: relative;
  z-index: 2;
  max-width: 1160px;
  margin: 0 auto;
}

.panel-history {
  padding: 28px;
}

/* ─── List header ────────────────────────────────────────────── */

.history-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.history-list-header h2 {
  margin: 0;
  font-size: 1.14rem;
  white-space: nowrap;
}

.history-search-row {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.9);
  border-radius: 12px;
  padding: 0 12px;
  min-height: 40px;
  min-width: 240px;
  max-width: 360px;
  flex: 1;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.history-search-row:focus-within {
  border-color: #22d3ee;
  box-shadow: 0 0 0 4px rgba(34, 211, 238, 0.16);
}

.history-search-row svg {
  color: #94a3b8;
  flex-shrink: 0;
}

.history-search-row input {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-main);
  height: 38px;
  font-size: 0.9rem;
}

/* ─── Skeleton loading ───────────────────────────────────────── */

.history-skeleton-line,
.history-skeleton-block,
.history-skeleton-action {
  position: relative;
  overflow: hidden;
  background: #e2e8f0;
}

.history-skeleton-line::after,
.history-skeleton-block::after,
.history-skeleton-action::after {
  content: '';
  position: absolute;
  inset: 0;
  transform: translateX(-100%);
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0) 0%,
    rgba(255, 255, 255, 0.68) 50%,
    rgba(255, 255, 255, 0) 100%
  );
  animation: history-skeleton-shimmer 1.1s ease-in-out infinite;
}

.history-list-skeleton {
  margin-top: 18px;
  display: grid;
  gap: 8px;
}

.history-skeleton-item {
  display: flex;
  align-items: stretch;
  gap: 10px;
  padding: 14px 16px;
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(255, 255, 255, 0.78);
}

.history-skeleton-main {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 8px;
}

.history-skeleton-line {
  border-radius: 10px;
}

.history-skeleton-line.skeleton-title {
  width: min(56%, 420px);
  height: 18px;
}

.history-skeleton-line.skeleton-bvid {
  width: 140px;
  height: 14px;
}

.history-skeleton-line.skeleton-meta {
  width: min(62%, 480px);
  height: 13px;
}

.history-skeleton-line.skeleton-meta.short {
  width: min(42%, 320px);
}

.history-skeleton-action {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  align-self: center;
  flex-shrink: 0;
}

.history-detail-skeleton {
  display: grid;
  gap: 10px;
}

.history-skeleton-block {
  width: 100%;
  height: 118px;
  border-radius: 14px;
}

.history-skeleton-block.compact {
  height: 92px;
}

/* ─── Empty state ────────────────────────────────────────────── */

.history-empty {
  margin-top: 32px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: #94a3b8;
  padding: 40px 0;
}

.history-empty svg {
  opacity: 0.5;
}

.history-empty p {
  margin: 0;
  font-size: 0.92rem;
}

/* ─── History list ───────────────────────────────────────────── */

.history-list {
  margin: 18px 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 8px;
}

.history-item {
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 14px;
  padding: 14px 16px;
  background: rgba(255, 255, 255, 0.84);
  display: flex;
  align-items: center;
  gap: 12px;
  transition: border-color 0.2s ease, background-color 0.2s ease, box-shadow 0.2s ease;
}

.history-item:hover {
  border-color: #99f6e4;
  background: rgba(240, 253, 250, 0.7);
  box-shadow: 0 4px 16px rgba(13, 148, 136, 0.08);
}

.history-item-content {
  flex: 1;
  cursor: pointer;
  min-width: 0;
}

.history-item-delete {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 8px;
  background: rgba(254, 242, 242, 0.6);
  color: #dc2626;
  cursor: pointer;
  transition: all 0.2s ease;
  padding: 0;
}

.history-item-delete:hover:not(:disabled) {
  border-color: #fca5a5;
  background: #fef2f2;
  transform: scale(1.05);
}

.history-item-delete:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.history-item-main {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}

.history-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-main);
  word-break: break-word;
}

.history-bvid {
  font-size: 0.8rem;
  color: var(--brand-strong);
  font-weight: 600;
  font-family: "SFMono-Regular", Menlo, Monaco, Consolas, monospace;
  flex-shrink: 0;
  text-decoration: none;
}

.history-bvid:hover {
  text-decoration: underline;
}

.history-item-meta {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.history-time,
.history-pubdate {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.8rem;
  color: var(--text-muted);
}

.history-author-tag {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  gap: 4px;
  border: 1px solid #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 0.72rem;
  font-weight: 700;
}

.history-file-count {
  font-size: 0.8rem;
  color: var(--text-muted);
}

/* ─── Pagination ─────────────────────────────────────────────── */

.history-pagination {
  margin-top: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
}

.history-pagination button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 34px;
  padding: 0 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.9);
  color: var(--text-soft);
  font-size: 0.84rem;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.2s ease, background-color 0.2s ease;
}

.history-pagination button:hover:not(:disabled) {
  border-color: #99f6e4;
  background: #f0fdfa;
}

.history-pagination button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.history-pagination span {
  font-size: 0.82rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

/* ─── Detail header ──────────────────────────────────────────── */

.history-detail-header {
  margin-bottom: 16px;
}

.detail-back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: transparent;
  color: var(--brand-strong);
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  padding: 0;
  transition: opacity 0.2s ease;
}

.detail-back:hover {
  opacity: 0.7;
}

/* ─── Detail info ────────────────────────────────────────────── */

.detail-info {
  margin-bottom: 20px;
}

.detail-header-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.detail-header-row > :first-child {
  flex: 1;
  min-width: 0;
}

.detail-title {
  margin: 0 0 10px;
  font-size: 1.24rem;
  line-height: 1.3;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.detail-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.detail-bvid {
  font-size: 0.86rem;
  color: var(--brand-strong);
  font-weight: 600;
  font-family: "SFMono-Regular", Menlo, Monaco, Consolas, monospace;
  text-decoration: none;
}

.detail-bvid:hover {
  text-decoration: underline;
}

.detail-time,
.detail-pubdate {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.84rem;
  color: var(--text-muted);
}

.detail-author-tag {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  gap: 4px;
  border: 1px solid #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 0.72rem;
  font-weight: 700;
}

/* ─── Delete button ──────────────────────────────────────────── */

.delete-button {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 36px;
  padding: 0 14px;
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 10px;
  background: rgba(254, 242, 242, 0.8);
  color: #dc2626;
  font-size: 0.86rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.delete-button:hover:not(:disabled) {
  border-color: #fca5a5;
  background: #fef2f2;
  box-shadow: 0 2px 8px rgba(239, 68, 68, 0.15);
}

.delete-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ─── Regenerate section ─────────────────────────────────────── */

.history-regenerate {
  margin-bottom: 20px;
  padding: 14px;
  border: 1px solid rgba(14, 165, 233, 0.18);
  border-radius: 14px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fdff 100%);
  display: grid;
  gap: 12px;
}

.history-regenerate-head {
  display: grid;
  gap: 4px;
}

.history-regenerate-kicker {
  margin: 0;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: #0284c7;
}

.history-regenerate-head h3 {
  margin: 0;
  font-size: 1.06rem;
  color: #0f172a;
}

.history-regenerate-head p {
  margin: 0;
  font-size: 0.84rem;
  line-height: 1.5;
  color: #475569;
  overflow-wrap: anywhere;
}

.history-regenerate-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  min-width: 0;
}

.history-summary-preset {
  gap: 6px;
  min-width: 0;
}

.history-summary-preset label {
  font-size: 0.84rem;
  font-weight: 700;
  color: #334155;
}

.history-preset-select {
  min-height: 46px;
  border-radius: 12px;
  border-color: #cbd5e1;
  background: linear-gradient(145deg, #ffffff, #f8fafc);
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.04);
}

.history-preset-select:hover:not(:disabled) {
  border-color: #93c5fd;
  box-shadow: 0 6px 16px rgba(59, 130, 246, 0.08);
}

.history-preset-select:focus {
  border-color: #38bdf8;
  box-shadow: 0 0 0 4px rgba(56, 189, 248, 0.18);
}

.history-regenerate-button {
  margin-top: 2px;
}

.detail-download-list {
  margin-top: 0;
}

/* ─── Responsive ─────────────────────────────────────────────── */

@media (max-width: 980px) {
  .history-regenerate-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .history-list-header {
    flex-direction: column;
    align-items: stretch;
  }

  .history-search-row {
    max-width: none;
    min-width: 0;
  }

  .panel-history {
    padding: 20px;
  }

  .history-skeleton-line.skeleton-title,
  .history-skeleton-line.skeleton-meta,
  .history-skeleton-line.skeleton-meta.short {
    width: 100%;
  }

  .history-skeleton-item {
    padding: 12px;
  }

  .history-skeleton-action {
    width: 30px;
    height: 30px;
  }

  .history-item-main {
    flex-direction: column;
    gap: 4px;
  }

  .detail-header-row {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }

  .delete-button {
    align-self: flex-end;
  }
}
</style>
