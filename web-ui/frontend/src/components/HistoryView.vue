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

let searchTimer = null;

const historyTotalPages = computed(() =>
  Math.max(1, Math.ceil(historyTotal.value / historyPageSize.value))
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

      <div v-if="historyDetailLoading" class="history-status">
        <LoaderCircle :size="16" class="spin" />
        <span>加载详情...</span>
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

        <FileList
          :items="historyDetailDownloadRows"
          :summary-presets="summaryPresets"
          :summary-default-preset="summaryDefaultPreset"
          :selected-summary-preset="selectedSummaryPreset"
          :bvid="historyDetail.bvid"
          title="文件列表"
          :filter-kinds="['markdown', 'summary', 'summary_no_table', 'summary_table_md', 'summary_table_pdf', 'text', 'summary_text', 'json', 'audio']"
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
            placeholder="搜索标题或 BV 号..."
            @input="onSearchInput"
          />
        </div>
      </header>

      <div v-if="historyLoading" class="history-status">
        <LoaderCircle :size="16" class="spin" />
        <span>加载中...</span>
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
